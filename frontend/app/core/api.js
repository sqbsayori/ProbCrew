/**
 * API 客户端 —— 前端唯一允许直接 fetch 的地方。
 *
 * 契约来源：`contracts/events.schema.json`。
 * 所有 feature 都通过本模块访问后端，好处是：
 *   1. 接口路径/事件格式变化时只改一个文件；
 *   2. 可整体替换为 mock（见 mockRun），前端开发不必等后端；
 *   3. 便于加统一错误处理与日志。
 */
import { bus, EV } from './bus.js';

/** 统一 JSON 请求 */
async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* 忽略 */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}

export const getJSON = (path) => request(path);
export const postJSON = (path, body) =>
  request(path, { method: 'POST', body: JSON.stringify(body ?? {}) });

/* ------------------------------------------------------------------ *
 * SSE 流
 * ------------------------------------------------------------------ */

/**
 * 读取一个 SSE 响应流，逐条回调事件对象。
 * 协议：每条事件是 `data: <json>\n\n`；末尾有 `event: end` 帧。
 *
 * @param {Response} res
 * @param {(event:object)=>void} onEvent
 * @param {AbortSignal} [signal]
 */
async function consumeSSE(res, onEvent, signal) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  try {
    for (;;) {
      if (signal?.aborted) break;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let idx;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        for (const line of frame.split('\n')) {
          if (!line.startsWith('data:')) continue;
          const raw = line.slice(5).trim();
          if (!raw || raw === '{}') continue;
          try {
            onEvent(JSON.parse(raw));
          } catch (err) {
            console.warn('[api] 事件解析失败', raw, err);
          }
        }
      }
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      /* 忽略 */
    }
  }
}

async function openSSE(path, body, onEvent, signal) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* 忽略 */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  await consumeSSE(res, onEvent, signal);
}

/* ------------------------------------------------------------------ *
 * 业务接口
 * ------------------------------------------------------------------ */

/**
 * 发起一次多 Agent 协作。
 * @param {{query:string, sessionId:string, chapter?:string}} params
 * @param {(event:object)=>void} onEvent 每个事件都会回调（含 run.end / error）
 * @param {AbortSignal} [signal]
 */
export function streamChat({ query, sessionId, chapter }, onEvent, signal) {
  return openSSE(
    '/api/chat/stream',
    { query, session_id: sessionId, chapter: chapter || null },
    (e) => {
      bus.emit(EV.RUN_EVENT, e);
      onEvent(e);
    },
    signal
  );
}

/**
 * 处理人机协同（HITL）：确认 / 修正 / 补充后继续执行。
 * @param {string} runId
 * @param {{action:'confirm'|'correct'|'supplement', text?:string}} decision
 */
export function resolveHitl(runId, decision, onEvent, signal) {
  return openSSE(
    `/api/hitl/${encodeURIComponent(runId)}/resolve`,
    { action: decision.action, text: decision.text || '' },
    (e) => {
      bus.emit(EV.RUN_EVENT, e);
      onEvent(e);
    },
    signal
  );
}

/** 取回一次运行的完整事件轨迹（用于复盘/评估） */
export const getRun = (runId) => getJSON(`/api/runs/${encodeURIComponent(runId)}`);

/* ---- 目录类接口 ---- */

export const health = () => getJSON('/api/health');
export const listAgents = () => getJSON('/api/agents');
export const listTools = () => getJSON('/api/tools');
export const listDistributions = () => getJSON('/api/distributions');

export const listAnimations = (category) =>
  getJSON(`/api/animations${category && category !== '全部' ? `?category=${encodeURIComponent(category)}` : ''}`);

export const recommendAnimations = (query, topK = 3) =>
  postJSON('/api/animations/recommend', { query, top_k: topK });

/**
 * 分布绘图数据（可视化页直接调用，不经过 Agent，响应更快）。
 * @param {string} dist
 * @param {Record<string, number>} params
 * @param {'pdf'|'cdf'} mode
 */
export function distributionSeries(dist, params, mode = 'pdf') {
  const qs = new URLSearchParams({ mode });
  for (const [k, v] of Object.entries(params || {})) {
    qs.set(k === 'lambda' ? 'lambda' : k, String(v));
  }
  return getJSON(`/api/distributions/${encodeURIComponent(dist)}/series?${qs}`);
}

export const learningStats = (sessionId, limit = 20) =>
  getJSON(`/api/stats/${encodeURIComponent(sessionId)}?limit=${limit}`);

/* ---- 内容类接口（让页面"有东西可看"）---- */

/** 课程章节目录（含知识点与建议问法） */
export const knowledgeChapters = () => getJSON('/api/knowledge/chapters');

/**
 * 典型例题库。
 * @param {{chapter?:string, level?:string, tag?:string, limit?:number}} [filters]
 */
export function problemExamples(filters = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  }
  const q = qs.toString();
  return getJSON(`/api/problems/examples${q ? `?${q}` : ''}`);
}

/* ---- 运行轨迹（后端已留档，前端用来做回放）---- */

/** 最近的运行列表 */
export const listRuns = (limit = 30) => getJSON(`/api/runs?limit=${limit}`);

/** 单次运行的结构化轨迹（阶段 + 条目 + 原始事件） */
export const runTimeline = (runId) =>
  getJSON(`/api/runs/${encodeURIComponent(runId)}/timeline`);

/* ---- 原始动画文件夹（大创/动画）---- */

/** `/raw-live/` 下可注入悬浮窗的页面清单 */
export const rawLiveList = () => getJSON('/api/raw-live/list');

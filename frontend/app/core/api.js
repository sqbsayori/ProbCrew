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
import { authHeaders, handleUnauthorized } from './auth.js';
import { consumeSSE as sharedConsumeSSE } from '../../shared/sse.js';

/** 统一 JSON 请求
 *
 *  ★ 这里有两个容易踩的坑：
 *  1. **请求头必须显式合并**。原写法是 `{ headers: {...}, ...options }` ——
 *     `...options` 在后面，调用方一旦传了 `options.headers`，`Content-Type`
 *     就被整体顶掉了。现在改成先解构再合并。
 *  2. **认证头在这里统一注入**，页面一行认证代码都不用写。
 *     收到 401 说明令牌被撤销/过期 → 清会话并跳登录（由 bootstrap 注入动作）。
 */
async function request(path, options = {}) {
  const { headers, ...rest } = options;
  const res = await fetch(path, {
    ...rest,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* 忽略 */
    }
    if (res.status === 401) handleUnauthorized(typeof detail === 'string' ? detail : '');
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}

export const getJSON = (path) => request(path);
export const postJSON = (path, body) =>
  request(path, { method: 'POST', body: JSON.stringify(body ?? {}) });
export const deleteJSON = (path) => request(path, { method: 'DELETE' });

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
/**
 * 消费 SSE 流 —— **转发共享内核**（`shared/sse.js`）。
 *
 * 协议解析以前在这里有一份、widget 里又有一份，且已经漂移（一个 async-for、
 * 一个 promise-pump）。现在两边共用同一份实现（见 `docs/23` §1）。
 */
function consumeSSE(res, onEvent, signal) {
  return sharedConsumeSSE(res, onEvent, { signal });
}

async function openSSE(path, body, onEvent, signal) {
  const res = await fetch(path, {
    method: 'POST',
    // SSE 也要带认证头：接口一律要求登录（防别人刷你的模型额度）。
    // 用 fetch 而不是 EventSource 的好处就在这里 —— EventSource 不能自定义请求头。
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
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
    if (res.status === 401) handleUnauthorized(typeof detail === 'string' ? detail : '');
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

/* ------------------------------------------------------------------ *
 * 我的数据（需登录；身份取自令牌，**页面不用传 session_id**）
 * ------------------------------------------------------------------ */

/** 我的学习统计（主页四张卡 + 薄弱知识点） */
export const meStats = () => getJSON('/api/me/stats');

/** 我的错题本（字段与旧 /api/wrong/{session_id} 逐字一致） */
export const meWrong = (limit = 200) => getJSON(`/api/me/wrong?limit=${limit}`);

/** 我的知识点掌握度 */
export const meMastery = () => getJSON('/api/me/mastery');

/* ------------------------------------------------------------------ *
 * 刷题（服务端判定，前端不做比对）
 * ------------------------------------------------------------------ */

/**
 * 题目列表。**响应里不含答案**（红线：final/steps 永不下发）。
 * @param {{chapter?:string, level?:string, kc?:string, limit?:number}} [filters]
 */
export function practiceQuestions(filters = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  }
  const q = qs.toString();
  return getJSON(`/api/practice/questions${q ? `?${q}` : ''}`);
}

/** 单题题干 + 第 N 层提示（hint: 0 无提示 / 1 方向 / 2 步骤名，都不含答案） */
export const practiceQuestion = (itemId, hint = 0) =>
  getJSON(`/api/practice/questions/${encodeURIComponent(itemId)}?hint=${hint}`);

/**
 * 提交作答 → 服务端判定。
 *
 * 响应三态（页面必须分别处理，**不要把 graded=null 当答错**）：
 *   graded=true  → 对（含 final/steps）
 *   graded=false → 错（含 message 错在第几步 + basis 判定依据 + diagnosis）
 *   graded=null  → 没解析出答案（"我不会"这类），不记 attempt
 *
 * @param {{item_id:string, student_answer:string, hint_used?:number,
 *          duration_ms?:number, reveal?:boolean}} payload
 */
export const gradeAnswer = (payload) => postJSON('/api/practice/grade', payload);

/* ------------------------------------------------------------------ *
 * 管理端（仅管理员；服务端二次校验角色，菜单隐藏不算权限）
 * ------------------------------------------------------------------ */

export const adminOverview = () => getJSON('/api/admin/overview');

/** 学生列表（分页 + 搜索 + 排序） */
export function adminStudents({ page = 1, page_size = 20, q = '', sort = '', order = '' } = {}) {
  const qs = new URLSearchParams({ page: String(page), page_size: String(page_size) });
  if (q) qs.set('q', q);
  if (sort) qs.set('sort', sort);
  if (order) qs.set('order', order);
  return getJSON(`/api/admin/students?${qs}`);
}

/** 学生详情 + 逐题明细（服务端会记一条 view_detail 审计） */
export const adminStudent = (userId) =>
  getJSON(`/api/admin/students/${encodeURIComponent(userId)}`);

export const adminCreateStudent = (payload) => postJSON('/api/admin/students', payload);

/** CSV 批量建号。用 JSON 传文本而不是 multipart —— 少一个 python-multipart 依赖。 */
export const adminImportStudents = (csvText) =>
  postJSON('/api/admin/students/import', { csv_text: csvText });

export const adminResetPassword = (userId) =>
  postJSON(`/api/admin/students/${encodeURIComponent(userId)}/reset-password`, {});

export const adminSetStatus = (userId, status) =>
  postJSON(`/api/admin/students/${encodeURIComponent(userId)}/status`, { status });

/** 删除某学生的全部数据（不可逆；服务端记 data_delete 审计） */
export const adminDeleteData = (userId) =>
  deleteJSON(`/api/admin/students/${encodeURIComponent(userId)}/data`);

export const adminAudit = ({ page = 1, page_size = 50, action = '', actor_id = '' } = {}) => {
  const qs = new URLSearchParams({ page: String(page), page_size: String(page_size) });
  if (action) qs.set('action', action);
  if (actor_id) qs.set('actor_id', actor_id);
  return getJSON(`/api/admin/audit?${qs}`);
};

/**
 * 下载学生统计 CSV。
 *
 * ⚠️ 不能直接 `location.href = '/api/admin/export/students.csv'` —— 那样浏览器不会
 * 带上 Authorization 头，服务端只会回 401。所以要自己 fetch 成 blob，再触发下载。
 */
export async function adminDownloadCsv() {
  const res = await fetch('/api/admin/export/students.csv', { headers: authHeaders() });
  if (!res.ok) {
    if (res.status === 401) handleUnauthorized('导出需要重新登录');
    throw new Error(`导出失败：HTTP ${res.status}`);
  }
  return res.blob();
}

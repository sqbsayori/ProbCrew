/**
 * 极简响应式状态容器。
 *
 * 为什么自己写而不上框架：本项目要求"免构建、离线可跑"。
 * 这个 store 只有几十行，但已经够用：状态变化 → 订阅者重渲染。
 *
 * @example
 *   import { store } from '../core/store.js';
 *   store.set('sessionId', 'abc');
 *   const off = store.subscribe('sessionId', v => console.log(v));
 */
import { bus } from './bus.js';

const state = {
  /** 会话 id（由浏览器生成并持久化，替代登录系统） */
  sessionId: '',
  /** 后端 /api/health 的结果 */
  health: null,
  /** Agent / 工具 / 动画 目录 */
  agents: [],
  tools: [],
  animations: [],
  animationCategories: ['全部'],
  distributions: [],
  /** 当前运行：事件轨迹 + 状态 */
  run: {
    runId: null,
    status: 'idle', // idle | running | awaiting_hitl | done | error
    events: [],
    answer: '',
    plan: [],
    agentStates: {}, // agentId -> { status, durationMs, summary }
    toolCalls: [], // { tool, agent, args, ok, durationMs, data }
    artifacts: [], // { kind, payload }
    error: null,
  },
};

const subscribers = new Map();

function keyOf(path) {
  return String(path);
}

export const store = {
  /** 读取（浅层路径，如 'run.status'） */
  get(path) {
    if (path === undefined) return state;
    return keyOf(path)
      .split('.')
      .reduce((acc, k) => (acc == null ? acc : acc[k]), state);
  },

  /** 写入并通知订阅者 */
  set(path, value) {
    const keys = keyOf(path).split('.');
    const last = keys.pop();
    let target = state;
    for (const k of keys) {
      if (target[k] == null) target[k] = {};
      target = target[k];
    }
    target[last] = value;
    subscribers.get(path)?.forEach((fn) => fn(value));
    bus.emit(`store:${path}`, value);
    return value;
  },

  /** 局部更新对象（不覆盖其他字段） */
  patch(path, partial) {
    const current = store.get(path) || {};
    return store.set(path, { ...current, ...partial });
  },

  /** 数组追加（用于事件流、产物流） */
  push(path, item) {
    const arr = store.get(path) || [];
    arr.push(item);
    subscribers.get(path)?.forEach((fn) => fn(arr));
    bus.emit(`store:${path}`, arr);
    return arr;
  },

  /** 订阅某个路径。返回取消订阅函数。 */
  subscribe(path, fn) {
    if (!subscribers.has(path)) subscribers.set(path, new Set());
    subscribers.get(path).add(fn);
    return () => subscribers.get(path)?.delete(fn);
  },

  /** 重置一次运行的轨迹（每次发起新提问时调用） */
  resetRun() {
    store.set('run', {
      runId: null,
      status: 'idle',
      events: [],
      answer: '',
      plan: [],
      agentStates: {},
      toolCalls: [],
      artifacts: [],
      error: null,
    });
  },
};

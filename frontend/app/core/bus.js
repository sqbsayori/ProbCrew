/**
 * 事件总线 —— feature 之间唯一的通信方式。
 *
 * 为什么不用互相 import：5 个人各写一个 feature，如果 A 直接 import B 的函数，
 * 就会产生耦合和循环依赖。约定事件名之后，各自只认事件，不认实现。
 *
 * @example
 *   import { bus } from '../core/bus.js';
 *   bus.on('run:event', e => console.log(e));
 *   bus.emit('navigate', { route: 'animations' });
 */

const listeners = new Map();

export const bus = {
  /**
   * 订阅事件。
   * @param {string} type 事件名（约定：'域:动作'，如 'run:event'、'artifact:animation'）
   * @param {(payload:any)=>void} fn
   * @returns {() => void} 取消订阅函数
   */
  on(type, fn) {
    if (!listeners.has(type)) listeners.set(type, new Set());
    listeners.get(type).add(fn);
    return () => bus.off(type, fn);
  },

  /** 只触发一次 */
  once(type, fn) {
    const off = bus.on(type, (payload) => {
      off();
      fn(payload);
    });
    return off;
  },

  off(type, fn) {
    listeners.get(type)?.delete(fn);
  },

  /**
   * 广播事件。单个监听器抛错不影响其他监听器 ——
   * 这是"一个人写崩了不拖垮整个应用"的保险。
   */
  emit(type, payload) {
    const set = listeners.get(type);
    if (!set) return;
    for (const fn of [...set]) {
      try {
        fn(payload);
      } catch (err) {
        console.error(`[bus] 监听器出错 type=${type}`, err);
      }
    }
  },
};

/** 约定的事件名常量。新增事件请在此登记，避免拼写错误。 */
export const EV = {
  NAVIGATE: 'navigate',
  RUN_EVENT: 'run:event', // 一条 Agent 事件（见 contracts/events.schema.json）
  RUN_START: 'run:start',
  RUN_END: 'run:end',
  HITL_REQUEST: 'hitl:request',
  ARTIFACT: 'artifact', // 结构化产物
  TOAST: 'toast',
  HEALTH: 'health:loaded',
  CATALOG: 'catalog:loaded',
};

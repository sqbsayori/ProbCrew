/**
 * 事件类型常量 —— **本文件由 `scripts/gen_events_js.py` 自动生成，请勿手工编辑。**
 *
 * 唯一来源：`contracts/events.schema.json`（契约层）。
 * 主站与悬浮窗都必须用这里的常量，不许再手写事件名 —— 否则契约新增一种事件时，
 * 两处分发会各自漏掉（这正是生成它的原因，见 `docs/23` §六）。
 *
 * 重新生成：`python scripts/gen_events_js.py`
 */

/** 契约里的全部事件类型（14 种） */
export const EVENT_TYPES = [
  'run.start',
  'context.received',
  'plan',
  'agent.start',
  'agent.delta',
  'agent.end',
  'tool.call',
  'tool.result',
  'artifact',
  'verification.report',
  'hitl.request',
  'hitl.resolved',
  'run.end',
  'error',
];

/** 事件类型 → 常量名（`EVENT.AGENT_DELTA` 这种写法靠它） */
export const EVENT = Object.freeze(
  Object.fromEntries(EVENT_TYPES.map((t) => [t.toUpperCase().replace(/\./g, '_'), t]))
);

/** 判断某事件类型是否在契约里（分发处用它兜住「未处理类型」） */
export const isKnownEventType = (t) => EVENT_TYPES.includes(t);

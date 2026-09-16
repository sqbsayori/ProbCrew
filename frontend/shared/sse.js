/**
 * SSE 帧解析 —— **跨形态共享内核**。
 *
 * 为什么必须共享：这是"协议层"。在它被共享之前，主站（`app/core/api.js`）与
 * 悬浮窗（`widget/api.js`）各写了一份，而且**形状已经不同**（一个 `async for`，
 * 一个 promise 递归 pump）。协议解析出 bug 只会修一处，另一处静默不一致 ——
 * 这是最危险的一类重复（见 `docs/23` §1 的证据表）。
 *
 * 协议（与 `backend/app/api/chat.py` 的 `_sse()` 对应）：
 *   data: <json>\n\n        —— 一条事件
 *   event: end\ndata: {}\n\n —— 收尾帧（`{}` 会被忽略）
 *
 * 约束（`docs/23` §三 R2）：不碰 `document`/`window`/`fetch`；
 * 它只接收**已经拿到的 Response**，因此主站与悬浮窗共用同一份。
 */

/** 把一段缓冲按 `\n\n` 切帧，返回 `[完整帧数组, 剩余缓冲]` */
export function splitFrames(buffer) {
  const frames = [];
  let rest = buffer;
  let idx;
  while ((idx = rest.indexOf('\n\n')) >= 0) {
    frames.push(rest.slice(0, idx));
    rest = rest.slice(idx + 2);
  }
  return [frames, rest];
}

/**
 * 从一帧里取出事件对象。非 `data:` 行、空 payload、`{}` 一律忽略。
 * @returns {object|null}
 */
export function parseFrame(frame) {
  let payload = null;
  for (const line of frame.split('\n')) {
    const trimmed = line.trimStart();
    if (!trimmed.startsWith('data:')) continue;
    const raw = trimmed.slice(5).trim();
    if (!raw || raw === '{}') continue;
    payload = raw;
  }
  if (payload === null) return null;
  try {
    return JSON.parse(payload);
  } catch (err) {
    console.warn('[sse] 事件解析失败', payload, err);
    return null;
  }
}

/**
 * 消费一个 SSE 响应流。
 *
 * 用 `reader.read()` 而不是 `EventSource`：我们需要**自定义请求头**（`Authorization`），
 * 而 EventSource 不支持 —— 这正是账号体系上线后 SSE 仍能带令牌的原因。
 *
 * @param {Response} res fetch 的响应（已确认 ok 且 body 存在）
 * @param {(event: object) => void} onEvent 每个事件回调
 * @param {{signal?: AbortSignal, onError?: (err: unknown) => void}} [opts]
 */
export async function consumeSSE(res, onEvent, opts = {}) {
  const { signal, onError } = opts;
  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  try {
    for (;;) {
      if (signal?.aborted) break;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const [frames, rest] = splitFrames(buffer);
      buffer = rest;
      for (const frame of frames) {
        const event = parseFrame(frame);
        if (event) onEvent(event);
      }
    }
    // 收尾：最后一段可能没有以 \n\n 结尾（连接被中途关闭）
    const tail = parseFrame(buffer);
    if (tail) onEvent(tail);
  } catch (err) {
    if (onError) onError(err);
    else throw err;
  } finally {
    try {
      await reader.cancel();
    } catch {
      /* 已经关闭，忽略 */
    }
  }
}

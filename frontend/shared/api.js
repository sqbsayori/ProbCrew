/**
 * HTTP 客户端内核 —— **跨形态共享内核**。
 *
 * 共享的是**语义**，不是 `fetch` 本身：`docs/23` §三 R2 规定 `shared/` 不许直接调 `fetch`，
 * 所以这里用工厂函数接收注入的实现。两条投递路径各自注入自己的 `fetch`
 * （主站是浏览器原生 fetch；悬浮窗将来可能换成油猴的 `GM_xmlhttpRequest`）。
 *
 * 统一掉的三件事（这三件事两边以前各写了一遍，而错误文案是学生直接看到的）：
 *   1. `{"detail": "..."}` 的提取规则；
 *   2. 认证头的注入点；
 *   3. 401 的统一处理（清会话 + 跳登录）。
 */

/** 把对象拼成查询串（跳过 undefined/null/''，值统一按字符串） */
export function buildQuery(params = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
}

/**
 * 从错误响应里取"给人看的那句话"。
 * 后端统一返回 `{"detail": "中文人话"}`（见 `contracts/api.md`），
 * 但 500/网关错误可能不是 JSON —— 所以要有兜底。
 */
export function errorDetailFrom(status, statusText, bodyText) {
  let detail = statusText || `HTTP ${status}`;
  if (bodyText) {
    try {
      const parsed = JSON.parse(bodyText);
      if (parsed && typeof parsed.detail === 'string') detail = parsed.detail;
      else if (parsed && parsed.detail) detail = JSON.stringify(parsed.detail);
    } catch {
      /* 不是 JSON：保留 statusText */
    }
  }
  return `${status} ${detail}`;
}

export class HttpError extends Error {
  constructor(status, detailText) {
    super(detailText);
    this.name = 'HttpError';
    this.status = status;
  }
}

/**
 * 建一个请求器。
 * @param {object} deps
 * @param {typeof fetch} deps.fetchImpl 注入的 fetch
 * @param {string} [deps.baseUrl] 前缀（悬浮窗注入到第三方页面时需要）
 * @param {() => Record<string,string>} [deps.authHeaders] 认证头提供者
 * @param {(err: HttpError) => void} [deps.onUnauthorized] 收到 401 时调用
 * @param {string} [deps.timeoutMs] 毫秒；0 = 不超时
 */
export function createRequester({ fetchImpl, baseUrl = '', authHeaders, onUnauthorized, timeoutMs = 0 }) {
  const full = (path) => (/^https?:\/\//i.test(path) ? path : baseUrl + path);

  async function request(path, { method = 'GET', body, headers } = {}) {
    let signal;
    let timer;
    if (timeoutMs > 0 && typeof AbortController !== 'undefined') {
      const ctrl = new AbortController();
      signal = ctrl.signal;
      timer = setTimeout(() => ctrl.abort(), timeoutMs);
    }
    try {
      const res = await fetchImpl(full(path), {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...(authHeaders ? authHeaders() : {}),
          ...(headers || {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
      });
      if (!res.ok) {
        let text = '';
        try {
          text = await res.text();
        } catch {
          /* 忽略 */
        }
        const err = new HttpError(res.status, errorDetailFrom(res.status, res.statusText, text));
        if (res.status === 401 && onUnauthorized) onUnauthorized(err);
        throw err;
      }
      return res.json();
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  return {
    request,
    getJSON: (path, headers) => request(path, { headers }),
    postJSON: (path, body, headers) => request(path, { method: 'POST', body: body ?? {}, headers }),
    deleteJSON: (path, headers) => request(path, { method: 'DELETE', headers }),
    full,
  };
}

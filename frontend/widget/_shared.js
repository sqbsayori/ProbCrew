/**
 * 共享内核（经典脚本产物）—— **本文件由 `scripts/build_widget.py` 自动生成，请勿手工编辑。**
 *
 * 源码：`frontend/shared/*.js`（ESM，主站直接 import 那一份）。
 * 为什么有这份产物：油猴 `@require` 只吃经典脚本，而它安装期抓取、运行时不受目标站点
 * CSP 限制 —— 那是悬浮窗能在第三方课程平台上工作的前提（见 docs/23 §1.1）。
 *
 * 模块顺序（依赖优先）：api.js → events.js → text.js → markdown.js → math.js → sse.js
 */
(function (global) {
  'use strict';
  var shared = {};

  /* ===== shared/api.js ===== */
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
  function buildQuery(params = {}) {
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
  function errorDetailFrom(status, statusText, bodyText) {
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

  class HttpError extends Error {
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
  function createRequester({ fetchImpl, baseUrl = '', authHeaders, onUnauthorized, timeoutMs = 0 }) {
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
  shared.buildQuery = buildQuery;
  shared.errorDetailFrom = errorDetailFrom;
  shared.HttpError = HttpError;
  shared.createRequester = createRequester;

  /* ===== shared/events.js ===== */
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
  const EVENT_TYPES = [
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
  const EVENT = Object.freeze(
    Object.fromEntries(EVENT_TYPES.map((t) => [t.toUpperCase().replace(/\./g, '_'), t]))
  );

  /** 判断某事件类型是否在契约里（分发处用它兜住「未处理类型」） */
  const isKnownEventType = (t) => EVENT_TYPES.includes(t);
  shared.EVENT_TYPES = EVENT_TYPES;
  shared.EVENT = EVENT;
  shared.isKnownEventType = isKnownEventType;

  /* ===== shared/text.js ===== */
  /**
   * 文本转义 —— 跨形态共享（主站与悬浮窗共用这一份）。
   *
   * 为什么单独一个文件：它是**安全边界**。渲染器把模型输出当 HTML 插入 DOM，
   * 转义漏一个字符就是 XSS。这份实现必须只有一处，两边都不许再写第二份。
   *
   * 约束（见 `docs/23` §三 R2）：本文件**不许**触碰 `document`/`window`/`fetch` —— 纯函数。
   */

  /** HTML 文本转义：`& < > " '` 五个字符全部处理（引号也要，因为会进属性值）。 */
  function escapeHtml(text) {
    return String(text ?? '').replace(
      /[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );
  }

  /** 属性值转义：与 escapeHtml 同实现，单独一个名字是为了让调用点意图清楚。 */
  const escapeAttr = escapeHtml;
  shared.escapeHtml = escapeHtml;
  shared.escapeAttr = escapeAttr;

  /* ===== shared/markdown.js ===== */
  /**
   * 极简 Markdown 渲染器（含 LaTeX 公式占位）—— **跨形态共享内核**。
   *
   * 唯一真相来源。主站通过 `app/components/markdown.js` 转出它，
   * 悬浮窗通过生成的 `widget/_shared.js` 消费它（见 `docs/23`）。
   * **不许再写第二份** —— 在它被共享之前，这里和 `widget/render.js` 各有一份，
   * 而且已经漂移（同一段 `normalizeMath` 写成两种形态）。
   *
   * 为什么自己写：免构建 + 零依赖 + 可离线。只实现我们真正用到的语法
   * （后端 Prompt 也按这个子集约束输出）：
   *   标题 # ## ###、分隔线 ---、引用 >、无序/有序列表、表格、粗体、斜体、
   *   行内代码、链接、公式 $...$ 与 $$...$$。
   *
   * 公式不立刻渲染，而是留成**占位 span**（`<span class="math-inline|math-block" data-tex="...">`），
   * 由 `shared/math.js` 的 `renderMathIn()` 填充。这样"流式输出过程中反复重渲染"不会闪断。
   *
   * 约束（`docs/23` §三 R2）：纯函数，不碰 `document`/`window`/`fetch`。
   */

  /** 占位符用的私有区字符：不可能出现在正常文本里 */
  const PLACEHOLDER = '\u0000';

  /** 公式占位 span 的类名（`shared/math.js` 按同一对类名查找，改这里要一起改） */
  const MATH_INLINE_CLASS = 'math-inline';
  const MATH_BLOCK_CLASS = 'math-block';

  /**
   * 归一化 LaTeX 定界符。
   *
   * 不同模型习惯不同：DeepSeek / GPT 常输出 `\(...\)` 与 `\[...\]`，
   * 而本渲染器只认 `$...$` 与 `$$...$$`。不归一化就会在界面上显示原始代码。
   * 放在渲染器而不是 Prompt 里，是为了防御任何模型的任何习惯（Prompt 里也会要求，双保险）。
   */
  function normalizeMath(text) {
    return String(text ?? '')
      .replace(/\\\[([\s\S]+?)\\\]/g, (_m, body) => `$$${body}$$`)
      .replace(/\\\(([\s\S]+?)\\\)/g, (_m, body) => `$${body}$`);
  }

  /** 行内解析：公式、代码、链接、粗斜体 */
  function inline(raw) {
    const tokens = [];

    // 1) 先把公式抽出来保护起来（否则 * _ \ 会被后续规则破坏）
    let s = normalizeMath(raw).replace(
      /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g,
      (_m, block, inl) => {
        tokens.push({ display: Boolean(block), tex: (block ?? inl).trim() });
        return `${PLACEHOLDER}${tokens.length - 1}${PLACEHOLDER}`;
      }
    );

    // 2) 转义，防止 XSS
    s = escapeHtml(s);

    // 3) 行内代码
    s = s.replace(/`([^`]+)`/g, (_m, c) => `<code class="mono">${c}</code>`);

    // 4) 链接（只允许 http/https/相对路径）
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, text, url) => {
      if (!/^(https?:|\/|#|\.)/i.test(url)) return m;
      const ext = /^https?:/i.test(url) ? ' target="_blank" rel="noopener"' : '';
      return `<a href="${url}"${ext}>${text}</a>`;
    });

    // 5) 粗体 / 斜体
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*\w])\*([^*\n]+)\*/g, '$1<em>$2</em>');

    // 6) 还原公式为占位 span
    s = s.replace(new RegExp(`${PLACEHOLDER}(\\d+)${PLACEHOLDER}`, 'g'), (_m, i) => {
      const t = tokens[Number(i)];
      if (!t) return '';
      const cls = t.display ? MATH_BLOCK_CLASS : MATH_INLINE_CLASS;
      return `<span class="${cls}" data-tex="${escapeHtml(t.tex)}"></span>`;
    });

    return s;
  }

  /** 判断表格分隔行，如 |---|---| */
  const isTableSep = (line) => /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line) && line.includes('-');

  /** 把 Markdown 文本转成 HTML 字符串 */
  function markdownToHtml(text) {
    const lines = normalizeMath(text).replace(/\r\n?/g, '\n').split('\n');
    const out = [];
    let i = 0;

    const flushParagraph = (buf) => {
      if (buf.length) out.push(`<p>${inline(buf.join(' '))}</p>`);
      buf.length = 0;
    };
    const para = [];

    while (i < lines.length) {
      const line = lines[i];

      // 空行
      if (!line.trim()) {
        flushParagraph(para);
        i += 1;
        continue;
      }

      // 独立公式块（整行 $$...$$）
      const blockMath = /^\s*\$\$(.+?)\$\$\s*$/.exec(line);
      if (blockMath) {
        flushParagraph(para);
        out.push(
          `<span class="${MATH_BLOCK_CLASS}" data-tex="${escapeHtml(blockMath[1].trim())}"></span>`
        );
        i += 1;
        continue;
      }

      // 分隔线
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        flushParagraph(para);
        out.push('<hr>');
        i += 1;
        continue;
      }

      // 标题
      const heading = /^(#{1,4})\s+(.*)$/.exec(line);
      if (heading) {
        flushParagraph(para);
        const level = heading[1].length;
        out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
        i += 1;
        continue;
      }

      // 表格
      if (line.includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        flushParagraph(para);
        const cells = (row) =>
          row.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim());
        const head = cells(line);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
          rows.push(cells(lines[i]));
          i += 1;
        }
        out.push(
          `<table class="data"><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead>` +
            `<tbody>${rows
              .map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`)
              .join('')}</tbody></table>`
        );
        continue;
      }

      // 引用
      if (/^\s*>\s?/.test(line)) {
        flushParagraph(para);
        const buf = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
          buf.push(lines[i].replace(/^\s*>\s?/, ''));
          i += 1;
        }
        out.push(`<blockquote>${inline(buf.join(' '))}</blockquote>`);
        continue;
      }

      // 有序列表
      if (/^\s*\d+[.)]\s+/.test(line)) {
        flushParagraph(para);
        const items = [];
        while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
          items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ''));
          i += 1;
        }
        out.push(`<ol>${items.map((t) => `<li>${inline(t)}</li>`).join('')}</ol>`);
        continue;
      }

      // 无序列表
      if (/^\s*[-*+]\s+/.test(line)) {
        flushParagraph(para);
        const items = [];
        while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
          items.push(lines[i].replace(/^\s*[-*+]\s+/, ''));
          i += 1;
        }
        out.push(`<ul>${items.map((t) => `<li>${inline(t)}</li>`).join('')}</ul>`);
        continue;
      }

      para.push(line.trim());
      i += 1;
    }

    flushParagraph(para);
    return out.join('\n');
  }
  shared.MATH_INLINE_CLASS = MATH_INLINE_CLASS;
  shared.MATH_BLOCK_CLASS = MATH_BLOCK_CLASS;
  shared.normalizeMath = normalizeMath;
  shared.inline = inline;
  shared.markdownToHtml = markdownToHtml;

  /* ===== shared/math.js ===== */
  /**
   * 公式渲染 —— **跨形态共享内核**（占位符 → KaTeX）。
   *
   * 为什么共享：主站与悬浮窗各写过一份"把 `.math-*` 占位 span 渲染成真公式"的逻辑，
   * 且两边的**类名都不一样**（`math-block` vs `psa-math-block`）——
   * 这正是"同一件事写了两遍"的典型症状。现在类名与实现都收敛到 `shared/markdown.js`
   * 导出的常量与本文件。
   *
   * ## KaTeX 从哪来：**由调用方注入**（`docs/23` §三 R2）
   * 本文件**不加载**任何脚本、不碰 `document.head`：
   *   - 主站：`app/components/katex.js` 负责 `loadKatex()`（vendor 本地文件）
   *   - 悬浮窗：`widget/render.js` 负责 `load()`（宿主页面注入 / 油猴 @require）
   * 渲染函数只接受一个 `katex` 对象。这样"怎么拿到渲染器"与"怎么用渲染器"解耦 ——
   * 悬浮窗将来换成 @require 注入（不再动宿主 `<head>`）时，这里一行都不用改。
   */


  /** 公式占位 span 的选择器（与 markdown.js 生成的类名保持一致） */
  const MATH_SELECTOR = `.${MATH_INLINE_CLASS}, .${MATH_BLOCK_CLASS}`;

  /** KaTeX 渲染参数：三处调用点必须一致，否则同一个公式会渲染出不同结果 */
  const KATEX_OPTIONS = {
    throwOnError: false,
    errorColor: '#ef4444',
    strict: 'ignore',
    trust: false,
    macros: { '\\RR': '\\mathbb{R}' },
  };

  /**
   * 单个公式 → HTML 字符串。
   * KaTeX 未就绪时**降级为转义后的源码**（可读、可复制），而不是抛错或空白。
   */
  function texToHtml(tex, displayMode = false, katex = null) {
    const engine = katex || (typeof globalThis !== 'undefined' ? globalThis.katex : null);
    if (!engine) {
      return `<code class="mono">${escapeHtml(tex)}</code>`;
    }
    try {
      return engine.renderToString(tex, { ...KATEX_OPTIONS, displayMode });
    } catch (err) {
      console.warn('[math] 公式渲染失败', tex, err);
      return `<code class="mono" style="color:var(--danger,#ef4444)">${escapeHtml(tex)}</code>`;
    }
  }

  /**
   * 把容器里所有占位 span 渲染成真公式。
   * @param {ParentNode} root 容器（元素或 ShadowRoot）
   * @param {{katex?: object, selector?: string}} [opts]
   */
  function renderMathIn(root, opts = {}) {
    if (!root || typeof root.querySelectorAll !== 'function') return 0;
    const selector = opts.selector || MATH_SELECTOR;
    const nodes = root.querySelectorAll(selector);
    let done = 0;
    for (const el of nodes) {
      const tex = el.dataset?.tex ?? el.getAttribute?.('data-tex') ?? '';
      const display =
        el.classList?.contains(MATH_BLOCK_CLASS) ?? false;
      el.innerHTML = texToHtml(tex, display, opts.katex || null);
      el.classList?.add('math-rendered');
      done += 1;
    }
    return done;
  }

  /** 一步到位：把 Markdown 写进元素并渲染公式（两种形态的公共动作） */
  function intoElement(el, html, opts = {}) {
    if (!el) return;
    el.innerHTML = html;
    renderMathIn(el, opts);
  }
  shared.MATH_SELECTOR = MATH_SELECTOR;
  shared.KATEX_OPTIONS = KATEX_OPTIONS;
  shared.texToHtml = texToHtml;
  shared.renderMathIn = renderMathIn;
  shared.intoElement = intoElement;

  /* ===== shared/sse.js ===== */
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
  function splitFrames(buffer) {
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
  function parseFrame(frame) {
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
  async function consumeSSE(res, onEvent, opts = {}) {
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
  shared.splitFrames = splitFrames;
  shared.parseFrame = parseFrame;
  shared.consumeSSE = consumeSSE;

  global.__PSA = global.__PSA || {};
  global.__PSA.shared = shared;
})(typeof window !== 'undefined' ? window : globalThis);

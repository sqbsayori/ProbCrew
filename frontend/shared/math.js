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
import { MATH_BLOCK_CLASS, MATH_INLINE_CLASS } from './markdown.js';
import { escapeHtml } from './text.js';

/** 公式占位 span 的选择器（与 markdown.js 生成的类名保持一致） */
export const MATH_SELECTOR = `.${MATH_INLINE_CLASS}, .${MATH_BLOCK_CLASS}`;

/** KaTeX 渲染参数：三处调用点必须一致，否则同一个公式会渲染出不同结果 */
export const KATEX_OPTIONS = {
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
export function texToHtml(tex, displayMode = false, katex = null) {
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
export function renderMathIn(root, opts = {}) {
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
export function intoElement(el, html, opts = {}) {
  if (!el) return;
  el.innerHTML = html;
  renderMathIn(el, opts);
}

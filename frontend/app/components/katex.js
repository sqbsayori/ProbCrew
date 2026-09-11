/**
 * KaTeX 封装（本地 vendor，离线可用）。
 *
 * 为什么不用 CDN：动画资源本身是自包含的，如果公式渲染依赖 CDN，
 * 断网/内网演示时整页公式就会变成源码。所以 KaTeX 直接放进
 * `frontend/vendor/katex/`（1.6MB，含字体）。
 *
 * 用法：先 `await loadKatex()`，插入 HTML 后再 `renderMathIn(container)`。
 */
import { getJSON } from '../core/api.js';

let readyPromise = null;

/** 懒加载 KaTeX（CSS + JS）。重复调用返回同一个 Promise。 */
export function loadKatex() {
  if (readyPromise) return readyPromise;

  readyPromise = new Promise((resolve) => {
    if (window.katex) return resolve(window.katex);

    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/vendor/katex/katex.min.css';
    document.head.append(link);

    const script = document.createElement('script');
    script.src = '/vendor/katex/katex.min.js';
    script.onload = () => resolve(window.katex);
    script.onerror = () => {
      console.warn('[katex] 本地 KaTeX 加载失败，公式将退化为源码显示');
      resolve(null);
    };
    document.head.append(script);
  });

  return readyPromise;
}

/** 同步渲染单个公式为 HTML 字符串。KaTeX 未就绪时退化为转义后的源码。 */
export function texToHtml(tex, displayMode = false) {
  const katex = window.katex;
  if (!katex) {
    return `<code class="mono">${String(tex).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]))}</code>`;
  }
  try {
    return katex.renderToString(tex, {
      displayMode,
      throwOnError: false,
      errorColor: '#ef4444',
      strict: 'ignore',
      trust: false,
      macros: { '\\RR': '\\mathbb{R}' },
    });
  } catch (err) {
    console.warn('[katex] 渲染失败', tex, err);
    return `<code class="mono" style="color:var(--danger)">${tex}</code>`;
  }
}

/**
 * 把容器里所有占位符（由 markdown.js 生成）渲染成真公式。
 * 占位符：<span class="math-inline|math-block" data-tex="...">
 */
export function renderMathIn(root) {
  if (!root) return;
  root.querySelectorAll('.math-inline, .math-block').forEach((el) => {
    const tex = el.dataset.tex || '';
    const display = el.classList.contains('math-block');
    el.innerHTML = texToHtml(tex, display);
    el.classList.add('math-rendered');
  });
}

/**
 * 检查后端健康状态（供侧栏显示"真模型 / mock / 动画数"）。
 * 放在这里是因为它和渲染无关，但对演示前的自检很重要。
 */
export const fetchHealth = () => getJSON('/api/health');

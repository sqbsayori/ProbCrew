/**
 * DOM 工具。刻意做得极简 —— 不引入框架，保持免构建。
 */

/** 查询单个元素 */
export const $ = (sel, root = document) => root.querySelector(sel);
/** 查询多个元素（返回真数组） */
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
/** 按 id 查询 */
export const byId = (id) => document.getElementById(id);

/**
 * 创建元素。
 * @example h('div', { class: 'card' }, h('h3', {}, '标题'), '正文')
 */
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class' || k === 'className') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') {
      el.addEventListener(k.slice(2).toLowerCase(), v);
    } else el.setAttribute(k, v);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

/** 清空元素 */
export function clear(el) {
  while (el?.firstChild) el.removeChild(el.firstChild);
  return el;
}

/** 安全 HTML 转义 */
export function esc(text) {
  return String(text ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );
}

/**
 * 轻量 Toast 提示（避免每个 feature 各写一套）。
 */
export function toast(message, kind = 'info', ms = 2600) {
  let host = byId('toast-host');
  if (!host) {
    host = h('div', { id: 'toast-host' });
    document.body.append(host);
  }
  const colors = {
    info: 'var(--info)',
    success: 'var(--success)',
    warning: 'var(--warning)',
    error: 'var(--danger)',
  };
  const node = h(
    'div',
    {
      style: {
        background: '#fff',
        borderLeft: `3px solid ${colors[kind] || colors.info}`,
        boxShadow: 'var(--shadow-lg)',
        borderRadius: '10px',
        padding: '10px 14px',
        fontSize: '13.5px',
        marginTop: '8px',
        maxWidth: '360px',
        color: 'var(--text)',
      },
    },
    message
  );
  host.append(node);
  setTimeout(() => {
    node.style.transition = 'opacity .3s';
    node.style.opacity = '0';
    setTimeout(() => node.remove(), 320);
  }, ms);
}

/** 防抖 */
export function debounce(fn, ms = 240) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

/**
 * 注入一个 feature 自己的样式表（幂等）。
 *
 * 让每个 feature 自带 styles.css 的意义：一个人负责一个页面时，
 * 他的样式只在自己目录里，不会和别人的选择器打架。
 */
const injectedStyles = new Set();
export function injectStyles(href) {
  if (injectedStyles.has(href)) return;
  injectedStyles.add(href);
  document.head.append(h('link', { rel: 'stylesheet', href }));
}

/** 数值格式化（图表/统计共用） */
export function fmtNum(v, digits = 4) {
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  if (n !== 0 && (Math.abs(n) >= 100000 || Math.abs(n) < 0.001)) return n.toExponential(2);
  return String(Number(n.toFixed(digits)));
}

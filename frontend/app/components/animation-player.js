/**
 * 交互动画播放器 —— 把既有 8 个自包含 HTML 动画接入 SPA 的桥梁。
 *
 * 实测事实（见 docs/notes/动画接入勘测.md）
 * -----------------------------------------
 * - 8/8 个动画都暴露了稳定的 `#playBtn/#pauseBtn/#resetBtn/#stepBtn`（markov-chain 的
 *   播放键叫 `#startBtn`），因此**不需要改动任何动画文件**就能远程驱动。
 * - 驱动方式：同源 iframe → `iframe.contentDocument.querySelector(sel).click()`。
 *   ⚠️ 必须由 http(s) 提供；`file://` 下是 opaque origin，contentDocument 会被拒绝。
 *   这正是后端把 `/animations` 挂成静态目录、而不是让用户双击 html 的原因。
 * - 8/8 加载后都不自动播放。
 *
 * 两个必须处理的坑
 * ---------------
 * 1. **markov-chain 有停不掉的 requestAnimationFrame 循环**（在 IIFE 闭包内，外部无法干预）。
 *    因此离开页面时必须**销毁 iframe 节点**，只 `display:none` 会一直烧 CPU。
 * 2. **零尺寸 iframe 首帧会画成 0×0 空白**。必须先给非零尺寸 → append → 再设 src → 再补派发 resize。
 */
import { h, toast } from '../core/dom.js';

/** 建立对 iframe 内文档的操作句柄 */
function bindControls(iframe) {
  const doc = () => {
    try {
      return iframe.contentDocument || iframe.contentWindow?.document || null;
    } catch {
      return null; // 跨域（不应该发生，因为是同源）
    }
  };

  const click = (selector) => {
    if (!selector) return false;
    const d = doc();
    const btn = d?.querySelector(selector);
    if (!btn) return false;
    btn.click();
    return true;
  };

  return { doc, click };
}

/**
 * 创建一个动画播放器。
 * @param {{
 *   url: string, title: string, controls?: Record<string,string>,
 *   description?: string, accent?: string, height?: number, compact?: boolean
 * }} spec
 * @returns {{ el: HTMLElement, destroy: () => void }}
 */
export function createAnimationPlayer(spec) {
  const {
    url,
    title,
    controls = {},
    description = '',
    accent = '#4f46e5',
    height = 620,
  } = spec;

  let iframe = null;
  let handle = null;
  let destroyed = false;

  const stage = h('div', {
    class: 'anim-stage',
    style: { minHeight: `${height}px`, background: '#fff' },
  });

  const status = h('span', { class: 'anim-status muted small' }, '未加载');

  /** 只在 stage 已有非零尺寸时才装配 iframe */
  function mountIframe() {
    if (destroyed || iframe) return;
    const w = stage.clientWidth;
    if (w < 40) {
      // 布局还没完成，等一帧再试（避免 0×0 空白首帧）
      requestAnimationFrame(mountIframe);
      return;
    }
    iframe = h('iframe', {
      src: url,
      title,
      class: 'anim-frame',
      style: { width: '100%', height: `${height}px`, border: '0', display: 'block' },
      // 动画需要脚本与同源访问
      allow: 'autoplay',
      loading: 'eager',
    });
    handle = bindControls(iframe);
    iframe.addEventListener('load', () => {
      // 补派发 resize：部分动画只在 window.resize 时才重算 canvas 位图
      try {
        iframe.contentWindow?.dispatchEvent(new Event('resize'));
      } catch {
        /* 忽略 */
      }
      status.textContent = '已就绪';
      status.classList.remove('muted');
    });
    stage.append(iframe);
    status.textContent = '加载中…';
  }

  const btn = (key, label, cls = '') => {
    const sel = controls[key];
    return h(
      'button',
      {
        class: `btn btn-sm ${cls}`,
        disabled: !sel,
        title: sel ? `驱动 ${sel}` : '该动画未暴露此控制',
        onclick: () => {
          if (!handle?.click(sel)) {
            toast(`该动画未暴露「${label}」控制`, 'warning');
          }
        },
      },
      label
    );
  };

  const toolbar = h(
    'div',
    { class: 'anim-toolbar row wrap' },
    btn('play', '▶ 播放', 'btn-primary'),
    btn('pause', '⏸ 暂停'),
    btn('step', '⏭ 单步'),
    btn('reset', '⟲ 重置'),
    h('span', { class: 'spacer' }),
    status,
    h(
      'button',
      {
        class: 'btn btn-sm',
        onclick: () => {
          // 销毁式关闭：先移除 iframe 再关弹窗，确保 markov-chain 的 rAF 循环停下
          const modal = openModal();
          modal.querySelector('[data-close]')?.addEventListener('click', () => {
            const f = modal.querySelector('iframe');
            if (f) f.remove();
          });
        },
      },
      '⛶ 全屏'
    )
  );

  /** 全屏（近全宽）打开 —— 动画本身是 PC 宽布局（≥1120px 才不掉成单列） */
  function openModal() {
    const inner = h('div', { class: 'anim-modal-inner' });
    const frame = h('iframe', {
      src: url,
      class: 'anim-frame',
      style: { width: '100%', height: 'calc(100vh - 150px)', border: '0', display: 'block' },
    });
    frame.addEventListener('load', () => {
      try {
        frame.contentWindow?.dispatchEvent(new Event('resize'));
      } catch {
        /* 忽略 */
      }
    });
    const modal = h(
      'div',
      { class: 'anim-modal' },
      h(
        'div',
        { class: 'anim-modal-head row-between' },
        h('strong', {}, title),
        h('button', { class: 'btn btn-sm', dataset: { close: '1' }, onclick: () => modal.remove() }, '✕ 关闭')
      ),
      inner
    );
    inner.append(frame);
    document.body.append(modal);
    return modal;
  }

  const el = h(
    'div',
    { class: 'anim-player' },
    h(
      'div',
      { class: 'row-between wrap mb-8' },
      h('div', { class: 'row' }, h('strong', {}, title)),
      toolbar
    ),
    description ? h('p', { class: 'small muted mb-8' }, description) : null,
    stage
  );
  el.style.setProperty('--accent', accent);

  // 进入 DOM 后装配 iframe（此时才能量到尺寸）
  requestAnimationFrame(mountIframe);

  // 容器尺寸变化时补派发 resize，让动画自适应
  const ro = 'ResizeObserver' in window ? new ResizeObserver(() => {
    try {
      iframe?.contentWindow?.dispatchEvent(new Event('resize'));
    } catch {
      /* 忽略 */
    }
  }) : null;
  ro?.observe(stage);

  return {
    el,
    destroy() {
      destroyed = true;
      ro?.disconnect();
      // 关键：彻底销毁 iframe，而不是隐藏
      if (iframe) {
        iframe.src = 'about:blank';
        iframe.remove();
        iframe = null;
      }
      document.querySelectorAll('.anim-modal').forEach((m) => {
        m.querySelector('iframe')?.remove();
        m.remove();
      });
    },
  };
}

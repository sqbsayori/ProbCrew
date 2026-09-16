/**
 * 概率论伴学助手 · 渲染（悬浮窗侧）—— **薄适配层**
 * ================================================
 *
 * ## 这个文件以前有 348 行，现在只剩适配
 * 它以前自带一整套 Markdown 渲染 + 公式归一化 + 占位符替换，理由是
 * "油猴 @require 不支持 ESM、平台 CSP 可能禁掉动态 import"。
 * 那两条理由**至今成立** —— 但它们只说明"widget 必须是经典脚本"，
 * 并不说明"逻辑必须再写一遍"：现在逻辑来自共享内核，经典脚本形态由
 * `scripts/build_widget.py` 生成的 `_shared.js` 提供（见 `docs/23` §四）。
 *
 * 之前那份实现与主站那份已经漂移（ES5 写法 vs ES6、类名 `psa-math-*` vs `math-*`），
 * 同一段协议/排版逻辑修一处漏一处 —— 这正是本轮要消灭的重复。
 *
 * 本文件只保留**悬浮窗独有**的两件事：
 *   1. `load()`        —— 把 KaTeX 的 JS 拿进来（注入宿主页面；油猴路径将来可换 @require）
 *   2. `injectStyles()`—— 把样式表注入 **Shadow Root**（绝不注入宿主 `<head>`）
 *
 * ## 依赖顺序
 * `_shared.js` **必须在本文件之前加载**（`_modules.json` 已保证，loader 按它加载）。
 */
(function (global) {
  'use strict';

  var PSA = (global.__PSA = global.__PSA || {});

  /** 取共享内核。缺了就直接报错，不要静默退化成"没有公式渲染"。 */
  function shared() {
    if (!PSA.shared) {
      throw new Error('[PSA] 共享内核未加载：/widget/_shared.js 必须在 render.js 之前加载');
    }
    return PSA.shared;
  }

  var katexState = { loading: null, ok: false };

  /* ------------------------------------------------------------------ *
   * KaTeX 加载（悬浮窗独有）
   * ------------------------------------------------------------------ */

  /**
   * 加载 KaTeX 的 JS。
   *
   * ⚠️ 这是全widget**唯一**往宿主页面写东西的地方：`<script>` 必须进宿主文档，
   * Shadow DOM 承载不了它的作用域。
   * 油猴那条路径将来改成 `@require` 之后就不需要写宿主了（记在 `docs/23` §五）。
   */
  function load(base) {
    if (katexState.loading) return katexState.loading;
    if (global.katex) {
      katexState.ok = true;
      return Promise.resolve(true);
    }
    var prefix = (base || '').replace(/\/+$/, '');
    katexState.loading = new Promise(function (resolve) {
      var s = global.document.createElement('script');
      s.src = prefix + '/vendor/katex/katex.min.js';
      s.async = true;
      s.onload = function () {
        katexState.ok = !!global.katex;
        resolve(katexState.ok);
      };
      s.onerror = function () {
        console.warn('[PSA] KaTeX 加载失败，公式将以源码形式显示');
        katexState.ok = false;
        resolve(false);
      };
      global.document.head.appendChild(s);
    });
    return katexState.loading;
  }

  /**
   * 把样式注入 Shadow Root。
   *
   * ⚠️ 这一步不能省：Shadow DOM 的样式隔离是**双向**的，
   * 宿主文档 `<head>` 里的样式表**不会**作用到 Shadow 内部。
   * 漏掉它会导致"JS 加载成功、公式渲染成裸 HTML"。
   */
  function injectStyles(shadowRoot, base) {
    var prefix = (base || '').replace(/\/+$/, '');
    ['/vendor/katex/katex.min.css', '/widget/widget.css'].forEach(function (p) {
      var link = global.document.createElement('link');
      link.rel = 'stylesheet';
      link.href = prefix + p;
      shadowRoot.appendChild(link);
    });
  }

  /* ------------------------------------------------------------------ *
   * 渲染：全部转发给共享内核
   * ------------------------------------------------------------------ */

  function esc(s) {
    return shared().escapeHtml(s);
  }

  /** Markdown → HTML（含公式占位 span，类名与主站完全一致） */
  function md(text) {
    return shared().markdownToHtml(text);
  }

  /** 把 root 内的公式占位 span 渲染成真公式（KaTeX 未就绪时降级为源码） */
  function mathIn(root) {
    if (!root || !root.querySelectorAll) return;
    shared().renderMathIn(root, { katex: global.katex || null });
  }

  /** 一步到位：把 Markdown 写进元素并渲染公式 */
  function into(el, text) {
    if (!el) return;
    el.innerHTML = md(text);
    mathIn(el);
  }

  PSA.render = {
    esc: esc,
    md: md,
    into: into,
    mathIn: mathIn,
    load: load,
    injectStyles: injectStyles,
    isKatexReady: function () {
      return !!global.katex;
    },
  };
})(window);

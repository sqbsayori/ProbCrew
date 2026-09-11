/**
 * 概率论伴学助手 · 一行代码嵌入
 * ==============================
 *
 * 在**你自己能改源码**的课程页面上，只要加一行：
 *
 *     <script src="https://your-host/widget/loader.js"
 *             data-api="https://your-host"
 *             data-auto-open="false"
 *             data-skin="pet"></script>
 *
 * 就完成了嵌入。loader 会按依赖顺序加载 5 个模块，然后挂上悬浮球 / 页宠。
 *
 * 属性说明
 * -------
 *   data-api        后端地址。留空或省略 = 与脚本同源（推荐）
 *   data-auto-open  "true" 时进入页面就展开面板（默认 false）
 *   data-skin       "pet"（虚拟页宠，默认）或 "ball"（极简悬浮球）
 *
 * 第三方平台（超星/智慧树等，改不了源码）请改用 `probstat-assistant.user.js`
 * 油猴脚本 —— 那条路径用 `@require` 加载同一批模块，能绕开平台的 CSP 限制。
 */
(function () {
  'use strict';

  if (window.__PSA_ASSISTANT__) return; // 防重复挂载

  var script =
    document.currentScript ||
    (function () {
      var all = document.getElementsByTagName('script');
      return all[all.length - 1];
    })();

  /** 后端地址：优先 data-api，其次与 loader.js 同源 */
  function resolveBase() {
    var explicit = script && script.getAttribute('data-api');
    if (explicit) return explicit.replace(/\/+$/, '');
    try {
      if (script && script.src) return new URL(script.src).origin;
    } catch (e) {
      /* 忽略 */
    }
    return '';
  }

  var BASE = resolveBase();
  var AUTO_OPEN = script && script.getAttribute('data-auto-open') === 'true';
  var SKIN = (script && script.getAttribute('data-skin')) || 'pet';

  /**
   * 必须按依赖顺序加载。
   *
   * 子框架里**不加载 assistant.js** —— 助手 UI 只在顶层渲染一份，
   * 否则每个 iframe 里都会冒出一个悬浮球（超星一页能有十几个 frame）。
   * 子框架的职责只有一个：装好上下文应答器，把自己的内容上报给顶层。
   */
  var MODULES_UI = [
    '/widget/api.js',
    '/widget/pet.js',
    '/widget/render.js',
    '/widget/anim-bridge.js',
    '/widget/extractor.js',
    '/widget/frames.js',
    '/widget/assistant.js',
  ];
  var MODULES_FRAME = [
    '/widget/render.js',
    '/widget/anim-bridge.js',
    '/widget/extractor.js',
    '/widget/frames.js',
  ];

  function isTopFrame() {
    try {
      return window.top === window.self;
    } catch (e) {
      return false;
    }
  }

  function loadOne(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = BASE + src;
      s.async = false; // 保持顺序
      s.onload = resolve;
      s.onerror = function () {
        reject(new Error('加载失败：' + src));
      };
      (document.head || document.documentElement).appendChild(s);
    });
  }

  function bootFramesOnly() {
    if (window.__PSA && window.__PSA.frames) {
      window.__PSA.frames.installResponder();
    }
  }

  function boot() {
    if (!window.__PSA || !window.__PSA.createAssistant) {
      console.error('[伴学助手] 模块未就绪，无法启动。请检查 loader.js 的 data-api 是否正确。');
      return;
    }

    var assistant = window.__PSA.createAssistant({
      base: BASE,
      autoOpen: AUTO_OPEN,
      skin: SKIN,
    });
    assistant.mount();

    // 暴露到全局，便于调试与控制台驱动
    window.__PSA_ASSISTANT__ = assistant;

    // 页面内容变化（SPA 平台常见：切章节不刷新页面）→ 稍后重算上下文
    if (window.MutationObserver) {
      var timer = null;
      var mo = new MutationObserver(function () {
        if (timer) clearTimeout(timer);
        timer = setTimeout(function () {
          try {
            assistant.debugContext();
          } catch (e) {
            /* 忽略 */
          }
        }, 1200);
      });
      try {
        mo.observe(document.body, { childList: true, subtree: true });
      } catch (e) {
        /* 忽略 */
      }
    }
  }

  var modules = isTopFrame() ? MODULES_UI : MODULES_FRAME;

  modules
    .reduce(function (chain, src) {
      return chain.then(function () {
        return loadOne(src);
      });
    }, Promise.resolve())
    .then(function () {
      if (isTopFrame()) boot();
      else bootFramesOnly();
    })
    .catch(function (err) {
      console.error('[伴学助手] 启动失败：', err && err.message ? err.message : err);
    });
})();

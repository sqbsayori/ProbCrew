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
 * 第三方平台（智慧树等，改不了源码）请改用 `probstat-assistant.user.js`
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

  /** 后端地址（部署无关化：不写死任何地址）
   *
   *  顺序：① `data-api` 属性 → ② `window.__PSA_API__` 配置块 → ③ 与 loader.js 同源
   *       → ④ **本页同源**（`location.origin`，最后兜底）
   *
   *  为什么 ③ 是主路径：loader.js 本身就由后端托管，所以"脚本从哪来"= 后端在哪，
   *  换机器/换域名/换端口都不用改任何一行代码。
   *  为什么保留 ④：万一页面把脚本内联进来（此时拿不到 script.src），
   *  同源仍然是最合理的猜测；猜错的表现是请求打到自己而不是后端（见 `_test_deploy.mjs`）。
   */
  function resolveBase() {
    var explicit = script && script.getAttribute('data-api');
    if (explicit) return explicit.replace(/\/+$/, '');

    var fromConfig = window.__PSA_API__;
    if (typeof fromConfig === 'string' && fromConfig) return fromConfig.replace(/\/+$/, '');

    try {
      if (script && script.src) return new URL(script.src).origin;
    } catch (e) {
      /* 忽略：继续兜底 */
    }
    try {
      if (location.protocol === 'http:' || location.protocol === 'https:') {
        return location.origin;
      }
    } catch (e) {
      /* 忽略 */
    }
    return '';
  }

  var BASE = resolveBase();
  var AUTO_OPEN = script && script.getAttribute('data-auto-open') === 'true';
  var SKIN = (script && script.getAttribute('data-skin')) || 'pet';

  if (!BASE) {
    // 失败必须显式：宁可报错，也不要用一个"看起来能用"的空地址去猜后端
    console.error(
      '[伴学助手] 无法确定后端地址，未启动。请给 loader.js 加上 data-api：\n' +
        '  <script src="http://<后端>/widget/loader.js" data-api="http://<后端>"></script>'
    );
    return;
  }

  /**
   * 必须按依赖顺序加载。
   *
   * 子框架里**不加载 assistant.js** —— 助手 UI 只在顶层渲染一份，
   * 否则每个 iframe 里都会冒出一个悬浮球（智慧树一页能有十几个 frame）。
   * 子框架的职责只有一个：装好上下文应答器，把自己的内容上报给顶层。
   */
  // 模块清单**不再手写**：由 `scripts/build_widget.py` 生成 frontend/widget/_modules.json，
  // 运行期读它。以前这里是一份手写数组、油猴脚本里还有一份 @require 列表，
  // 改个文件名就会漏改一处（见 docs/23 §四）。
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

  function loadManifest() {
    var manUrl = BASE + '/widget/_modules.json';
    if (typeof fetch !== 'function') {
      return Promise.reject(new Error('环境不支持 fetch，无法读模块清单'));
    }
    return fetch(manUrl, { cache: 'no-cache' }).then(function (r) {
      if (!r.ok) throw new Error('模块清单加载失败 HTTP ' + r.status);
      return r.json();
    });
  }

  loadManifest()
    .then(function (man) {
      // 顶层页面要全部模块；iframe 只要最小集合（省内存）
      var modules = isTopFrame() ? man.ui : man.frame;
      return modules.reduce(function (chain, src) {
        return chain.then(function () {
          return loadOne(src);
        });
      }, Promise.resolve());
    })
    .then(function () {
      if (isTopFrame()) boot();
      else bootFramesOnly();
    })
    .catch(function (err) {
      console.error('[伴学助手] 启动失败：', err && err.message ? err.message : err);
    });
})();

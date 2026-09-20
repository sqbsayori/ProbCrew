// ==UserScript==
// @name         概率论伴学助手（多 Agent）
// @namespace    https://github.com/sqbsayori/ProbCrew
// @version      1.1.0
// @description  在任意在线课程页面上挂一个"能读懂当前页面"的 AI 伴学助手：悬浮球 / 虚拟页宠，支持划词解释、页内答疑、视频进度感知、跨 iframe 内容读取。
// @author       大创项目组
// @run-at       document-idle
// @grant        none
//
// ---------------------------------------------------------------------------
// 部署无关化（docs/13 §2.2）：这个脚本里**没有写死任何后端地址**
// ---------------------------------------------------------------------------
// 地址解析顺序（见下方 resolveApiBase，测试见 frontend/widget/_test_deploy.mjs）：
//   ① data-api              本页 <html data-api="https://..."> 上声明
//   ② 配置块 API_BASE_PIN   源码里留空 → 跳过（★★ 不要手改源码，见下）
//   ③ 页面自身 origin       http(s) 页面同源访问（后端同时托管前端时必然正确）
//   ④ 安装来源 origin       GM_info 给出的安装 URL / 绝对 @require（Tampermonkey 专用）
//   ⑤ 全部失败              **控制台显式报错并给出人话提示**，绝不静默降级
//
// 所以：**装脚本时从哪个地址装，就自动连哪个后端** ——
// 本地开发从 http://127.0.0.1:<端口>/widget/probstat-assistant.user.js 安装，
// 部署后从 https://<你们的域名>/widget/probstat-assistant.user.js 安装，
// 学生和服务器都不需要改这份源码。
//
// 分域部署（前端在 A 域、后端在 B 域）或目标是 file:// 页面时，
// 用 scripts/build_userscript.py --base <后端地址> 生成一份发布物，
// **仍然不需要手改这份源码**。
//
// ---------------------------------------------------------------------------
// 适用范围（按需增删 @match）
// ---------------------------------------------------------------------------
// 下面两行**刻意不写主机名**：本项目的 /raw/（原始动画）与 /course/（演示课程页）
// 无论后端监听哪个地址、哪个端口都能命中 —— 这正是"换台机器演示就不用改脚本"。
//
// @match        *://*/raw/*
// @match        *://*/course/*
//
// 下面这行放开全部站点，方便在任意课程页面上试用。
// 正式使用时**强烈建议收窄**，只在需要的平台上运行（省内存、避免打扰）：
//
//   @match  *://*.edu.cn/*
//   @match  *://*.icourse163.org/*
//   @match  *://*.zhihuishu.com/*
//
// @match        *://*/*
//
// 直接用 file:// 打开动画文件也可以，但需要在 Tampermonkey 的设置里
// 打开「允许访问文件网址」，并且后端必须允许 null origin。
// 更推荐用 /raw/ 的 http 方式 —— file:// 下浏览器把页面视为 opaque origin，
// 跨域请求与 iframe 读取都会被拒，而且脚本**无法推断后端地址**（会显式报错）。
//
// @match        file:///*动画*
//
// ---------------------------------------------------------------------------
// 模块加载方式（两种，二选一）
// ---------------------------------------------------------------------------
// 【方式 A · @require】（默认，最可靠）
//   Tampermonkey 在**安装时**把模块抓下来缓存，运行时不受目标站点 CSP 限制。
//   相对路径由 Tampermonkey 按"脚本安装来源"解析 —— 所以换服务器不用改源码，
//   只要学生是从新服务器的 /widget/probstat-assistant.user.js 安装的。
//   代价：改了 widget 代码后，需要到 Tampermonkey 里"检查更新"或重装脚本。
//   注意：安装时后端必须可达，否则 @require 抓不到模块、安装会失败。
//
// @require      /widget/_shared.js
//   ↑ 共享内核（由 scripts/build_widget.py 生成，勿手工编辑）：SSE 协议 / Markdown /
//     公式渲染 / 事件常量。**必须排第一**，后面的模块都从 __PSA.shared 取实现。
//     清单以 frontend/widget/_modules.json 为准（CI 会校验两者一致）。
// @require      /widget/api.js
// @require      /widget/pet.js
// @require      /widget/render.js
// @require      /widget/anim-bridge.js
// @require      /widget/extractor.js
// @require      /widget/frames.js
// @require      /widget/assistant.js
//
// 【方式 B · 动态注入】（改代码即时生效，适合开发期）
//   把上面 7 行 @require 注释掉，并把下面 USE_INJECT 改成 true。
//   代价：如果目标站点有严格 CSP（script-src），注入会被浏览器拦掉。
//
// ==/UserScript==

/* eslint-disable no-undef */
(function () {
  'use strict';

  /* ======================= 配置 ======================= */

  /** true = 用动态注入（开发期热更新）；false = 用 @require（默认） */
  var USE_INJECT = false;

  /** 只有"必须手改源码"时才填这里，正常留空。
   *  填了会**优先于**自动推断（例如前后端分域部署：
   *  'https://probstat.example.edu'）。留空 = 完全自动。 */
  var API_BASE_PIN = '';

  /** 是否进入页面就展开面板 */
  var AUTO_OPEN = false;

  /** 'pet' = 虚拟页宠，'ball' = 极简悬浮球（用户也能在面板里随时切换） */
  var DEFAULT_SKIN = 'pet';

  /** 只在顶层框架渲染 UI；子框架只上报内容（避免每个 iframe 一个悬浮球）。
   *  这是产品决定，**不是开关**（子框架挂 UI 会造成一页十几个悬浮球）。 */
  var ONLY_TOP_FRAME_UI = true;

  /* ============== 地址解析（部署无关化的核心） ============== */
  /** 纯函数，不依赖 DOM 之外的任何东西，便于单测（_test_deploy.mjs 直接抽这段跑）。 */
  function resolveApiBase(env) {
    var env = env || {};

    // ① 本页显式声明：<html data-api="..."> 或挂脚本的那个 <script data-api="...">
    var docEl = env.documentElement || null;
    if (docEl && typeof docEl.getAttribute === 'function') {
      var fromDoc = docEl.getAttribute('data-api');
      if (fromDoc) return String(fromDoc).replace(/\/+$/, '');
    }

    // ② 配置块（留空则跳过；**这是唯一需要手改源码的地方**）
    if (API_BASE_PIN) return String(API_BASE_PIN).replace(/\/+$/, '');

    // ③ 页面自身 origin：后端同时托管前端时，同源就是对的地址
    var loc = env.location || null;
    if (loc && /^https?:$/i.test(String(loc.protocol || ''))) {
      var origin = String(loc.origin || '');
      if (!origin && loc.href) {
        try {
          origin = new URL(String(loc.href)).origin;
        } catch (e) {
          origin = '';
        }
      }
      if (origin) return origin.replace(/\/+$/, '');
    }

    // ④ 模块所在地址：@require 方式下从 GM_info 的脚本元数据里解析。
    //    这是"从哪个服务器装就连哪个服务器"的关键一步。
    var fromRequires = originFromGmInfo(env.GM_info);
    if (fromRequires) return fromRequires;

    // ⑤ 失败的表达留给调用方（必须显式报错，不静默降级）
    return '';
  }

  /**
   * 从油猴的运行环境里推断"这份脚本是从哪个地址装的"。
   *
   * 两条路，按可靠性排序：
   *   ① `GM_info.script.source` / `scriptURI` —— 安装来源 URL，直接取 origin；
   *   ② 脚本元数据里若写了**绝对** @require，用它的 origin。
   *
   * 若 @require 写的是相对路径（本项目就是这样，见脚本头），
   * 而运行环境又没给出安装 URL，就拿不到主机 —— 返回空串，
   * 由调用方按"无法推断"**显式报错**（这正是 file:// 页面的情形）。
   */
  function originFromGmInfo(gmInfo) {
    try {
      if (!gmInfo) return '';
      var script = gmInfo.script || gmInfo;

      // ① 安装来源（Tampermonkey 提供 script.source / scriptURI）
      var src = script.source || gmInfo.scriptSource || gmInfo.scriptURI || '';
      if (src) {
        var srcUrl = new URL(String(src), 'https://placeholder.invalid');
        if (/^https?:$/i.test(srcUrl.protocol) && srcUrl.host !== 'placeholder.invalid') {
          return srcUrl.origin;
        }
      }

      // ② 绝对 @require
      var meta = script.scriptMetaStr || gmInfo.scriptMetaStr || '';
      var m = /^\s*\/\/\s*@require\s+(\S+)\s*$/m.exec(meta);
      if (!m || !/^https?:\/\//i.test(m[1])) return '';
      var url = new URL(m[1]);
      return /^https?:$/i.test(url.protocol) && url.host ? url.origin : '';
    } catch (e) {
      return '';
    }
  }

  /** @require 里若写了绝对地址，那才是"脚本来源"；拿它跟解析结果对一下，值得提醒。 */
  function scriptSourceOrigin() {
    return originFromGmInfo(typeof GM_info !== 'undefined' ? GM_info : null);
  }

  /** 解析并处理失败：返回 '' 时**明确报错**，绝不继续用一个空地址去请求。 */
  function resolveOrReport() {
    var base = resolveApiBase({
      documentElement: document.documentElement,
      location: window.location,
      GM_info: typeof GM_info !== 'undefined' ? GM_info : null,
    });
    if (base) {
      // 猜错的代价是"请求打到了另一个服务"，静默失败最难排查 —— 这里留一条线索
      var src = scriptSourceOrigin();
      if (src && src !== base) {
        console.warn(
          '[伴学助手] 后端地址取的是本页同源 ' +
            base +
            '，但脚本是从 ' +
            src +
            ' 安装的。\n' +
            '  若本页并不是后端自己托管的页面，请在本页 <html data-api="..."> 上声明后端地址；\n' +
            '  若页面上确实没有声明，才需要改脚本配置块 API_BASE_PIN。'
        );
      }
      return base;
    }

    console.error(
      '[伴学助手] 无法确定后端地址，脚本未启动。\n' +
        '当前页面是 ' +
        window.location.href +
        '，脚本推断不出后端在哪里。请按下面任一种方式指定：\n' +
        '  1) 在页面的 <html data-api="https://你的后端"> 上声明；或\n' +
        '  2) 从后端自己的地址安装本脚本\n' +
        '     （即打开 http://<后端>/widget/probstat-assistant.user.js 安装），这样会自动同源；或\n' +
        '  3) 改本脚本配置块的 API_BASE_PIN（仅前后端分域时需要）。'
    );
    return '';
  }

  /* ======================= 实现 ======================= */

  function isTopFrame() {
    try {
      return window.top === window.self;
    } catch (e) {
      return false;
    }
  }

  /** 子框架：只装上下文应答器，把自己的正文/选中文字上报给顶层 */
  function bootChildFrame() {
    var tries = 0;
    (function wait() {
      if (window.__PSA && window.__PSA.frames) {
        window.__PSA.frames.installResponder();
        return;
      }
      if (tries++ < 100) setTimeout(wait, 100);
    })();
  }

  /** 顶层：挂载助手 UI */
  function bootTopFrame() {
    var apiBase = resolveOrReport();
    if (!apiBase) return;
    var tries = 0;
    (function wait() {
      if (window.__PSA && window.__PSA.createAssistant) {
        if (window.__PSA_ASSISTANT__) return; // 已挂载
        var assistant = window.__PSA.createAssistant({
          base: apiBase,
          autoOpen: AUTO_OPEN,
          skin: DEFAULT_SKIN,
        });
        assistant.mount();
        window.__PSA_ASSISTANT__ = assistant;
        console.log(
          '%c[伴学助手] 已启动',
          'color:#4f46e5;font-weight:600',
          '\n后端：' + apiBase,
          '\n调试：__PSA_ASSISTANT__.debugContext() 可查看抽取到的页面内容'
        );
        return;
      }
      if (tries++ < 100) {
        setTimeout(wait, 100);
        return;
      }
      console.error(
        '[伴学助手] 模块加载失败。可能原因：\n' +
          '1) 后端未启动（' + apiBase + '）；\n' +
          '2) 若使用 @require 方式，改了代码后需要到 Tampermonkey 里"检查更新"；\n' +
          '3) 若使用注入方式，目标站点的 CSP 可能拦截了外部脚本 —— 改用 @require。'
      );
    })();
  }

  function injectLoader() {
    var apiBase = resolveOrReport();
    if (!apiBase) return;
    var s = document.createElement('script');
    s.src = apiBase + '/widget/loader.js';
    s.setAttribute('data-api', apiBase);
    s.setAttribute('data-auto-open', AUTO_OPEN ? 'true' : 'false');
    s.setAttribute('data-skin', DEFAULT_SKIN);
    s.onerror = function () {
      console.error('[伴学助手] loader.js 注入失败（可能是 CSP 限制），请改用 @require 方式。');
    };
    (document.head || document.documentElement).appendChild(s);
  }

  /* ======================= 启动 ======================= */

  /** 顶层框架：挂 UI（注入方式下由 loader.js 自行分派，这里不重复挂） */
  function bootTop() {
    if (USE_INJECT) injectLoader();
    else bootTopFrame();
  }

  // 子框架**一律**装应答器 —— 这是读到课件 iframe 正文的唯一途径。
  // 注意：即使顶层不渲染 UI，子框架也必须装，否则那种"正文在跨域 iframe 里"
  // 的页面就完全读不到了。
  if (isTopFrame()) {
    bootTop(); // ONLY_TOP_FRAME_UI 的语义：只有顶层渲染 UI（子框架走 else 分支）
  } else {
    bootChildFrame();
  }
})();

// ==UserScript==
// @name         概率论伴学助手（多 Agent）
// @namespace    https://github.com/sqbsayori/ProbCrew
// @version      1.0.0
// @description  在任意在线课程页面上挂一个"能读懂当前页面"的 AI 伴学助手：悬浮球 / 虚拟页宠，支持划词解释、页内答疑、视频进度感知、跨 iframe 内容读取。
// @author       大创项目组
// @run-at       document-idle
// @grant        none
//
// ---------------------------------------------------------------------------
// 适用范围（按需增删 @match）
// ---------------------------------------------------------------------------
// 下面这几条是**本项目自己的页面**，默认开启，装好就能用：
//   - /raw/     ：团队原始动画文件夹（`大创/动画`），由后端用 http 挂出来
//   - /course/  ：演示课程页
//
// @match        http://127.0.0.1:8000/raw/*
// @match        http://127.0.0.1:8000/course/*
// @match        http://localhost:8000/raw/*
// @match        http://localhost:8000/course/*
//
// 下面这行放开全部站点，方便在任意课程页面上试用。
// 正式使用时**强烈建议收窄**，只在需要的平台上运行（省内存、避免打扰）：
//
//   @match  *://*.chaoxing.com/*
//   @match  *://*.edu.cn/*
//   @match  *://*.icourse163.org/*
//   @match  *://*.zhihuishu.com/*
//
// @match  *://*/*
//
// 直接用 file:// 打开动画文件也可以，但需要在 Tampermonkey 的设置里
// 打开「允许访问文件网址」，并且后端必须允许 null origin（本项目已放开 CORS）。
// 更推荐用 /raw/ 的 http 方式 —— file:// 下浏览器把页面视为 opaque origin，
// 跨域请求与 iframe 读取都会被拒。
//
// @match        file:///*动画*
//
// ---------------------------------------------------------------------------
// 模块加载方式（两种，二选一）
// ---------------------------------------------------------------------------
// 【方式 A · @require】（默认，最可靠）
//   Tampermonkey 在**安装时**把模块抓下来缓存，运行时不受目标站点 CSP 限制。
//   代价：改了 widget 代码后，需要到 Tampermonkey 里"检查更新"或重装脚本。
//   注意：必须先启动后端（或把下面的地址改成你的服务器地址），否则安装会失败。
//
// @require      http://127.0.0.1:8000/widget/api.js
// @require      http://127.0.0.1:8000/widget/pet.js
// @require      http://127.0.0.1:8000/widget/render.js
// @require      http://127.0.0.1:8000/widget/anim-bridge.js
// @require      http://127.0.0.1:8000/widget/extractor.js
// @require      http://127.0.0.1:8000/widget/frames.js
// @require      http://127.0.0.1:8000/widget/assistant.js
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

  /** 后端地址。改成你部署的地址，例如 https://probstat.example.edu */
  var API_BASE = 'http://127.0.0.1:8000';

  /** true = 用动态注入（开发期热更新）；false = 用 @require（默认） */
  var USE_INJECT = false;

  /** 是否进入页面就展开面板 */
  var AUTO_OPEN = false;

  /** 'pet' = 虚拟页宠，'ball' = 极简悬浮球（用户也能在面板里随时切换） */
  var DEFAULT_SKIN = 'pet';

  /** 只在顶层框架渲染 UI；子框架只上报内容（避免每个 iframe 一个悬浮球） */
  var ONLY_TOP_FRAME_UI = true;

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
    var tries = 0;
    (function wait() {
      if (window.__PSA && window.__PSA.createAssistant) {
        if (window.__PSA_ASSISTANT__) return; // 已挂载
        var assistant = window.__PSA.createAssistant({
          base: API_BASE,
          autoOpen: AUTO_OPEN,
          skin: DEFAULT_SKIN,
        });
        assistant.mount();
        window.__PSA_ASSISTANT__ = assistant;
        console.log(
          '%c[伴学助手] 已启动',
          'color:#4f46e5;font-weight:600',
          '\n后端：' + API_BASE,
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
          '1) 后端未启动（' + API_BASE + '）；\n' +
          '2) 若使用 @require 方式，改了代码后需要到 Tampermonkey 里"检查更新"；\n' +
          '3) 若使用注入方式，目标站点的 CSP 可能拦截了外部脚本 —— 改用 @require。'
      );
    })();
  }

  function injectLoader() {
    var s = document.createElement('script');
    s.src = API_BASE.replace(/\/+$/, '') + '/widget/loader.js';
    s.setAttribute('data-api', API_BASE);
    s.setAttribute('data-auto-open', AUTO_OPEN ? 'true' : 'false');
    s.setAttribute('data-skin', DEFAULT_SKIN);
    s.onerror = function () {
      console.error('[伴学助手] loader.js 注入失败（可能是 CSP 限制），请改用 @require 方式。');
    };
    (document.head || document.documentElement).appendChild(s);
  }

  /* ======================= 启动 ======================= */

  var top = isTopFrame();

  if (USE_INJECT) {
    // 注入方式：loader.js 会自行判断顶层/子框架并做正确的分派
    injectLoader();
  } else {
    // @require 方式：模块已经在当前 frame 的作用域里准备好了
    // 1) 顶层渲染 UI（若允许，子框架也可以渲染）
    if (top || !ONLY_TOP_FRAME_UI) bootTopFrame();
    // 2) 子框架**一律**装应答器 —— 这是读到课件 iframe 正文的唯一途径。
    //    注意：即使顶层不渲染 UI，子框架也必须装，否则超星那种"正文在
    //    跨域 iframe 里"的页面就完全读不到了。
    if (!top) bootChildFrame();
  }
})();

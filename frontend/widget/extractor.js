/**
 * 概率论伴学助手 · 页面内容抽取
 * ==============================
 *
 * 目标：在**任意第三方课程平台**上，稳定地把"学生正在看的内容"抽出来。
 *
 * 现实约束（决定了本文件的所有设计）
 * --------------------------------
 * 1. 我们改不了目标站点的源码 → 只能靠通用启发式，不能靠特定 class。
 * 2. 平台结构千奇百怪 → 必须**永不抛异常**，抽不到就返回空，让助手优雅降级。
 * 3. 正文常常在 iframe 里（智慧树尤其如此）→ 每个 frame 各自抽取，
 *    由 assistant.js 汇总（见 PSA.frames）。
 * 4. 抽取结果要送到后端，URL 长度有限、模型上下文也有限 → 硬截断。
 *
 * 抽取策略（按可靠性排序）
 * ----------------------
 * 1. 显式提示：`#lesson-content`、`article`、`main`、`[role=main]`、常见课件类名
 * 2. 若提示命中且正文足够长 → 直接采用
 * 3. 否则跑一遍"阅读密度"打分，挑出正文容器（仿 readability 的轻量版）
 * 4. 兜底：document.body
 *
 * 对每个候选容器都会：剥离导航/脚本/侧栏 → 按块级元素还原段落 → 收集标题与公式。
 */
(function (global) {
  'use strict';

  var PSA = (global.__PSA = global.__PSA || {});

  var MAX_TEXT = 12000;
  var MAX_SELECTION = 3000;
  var MAX_FORMULAS = 40;

  /** 明确表示"这里就是正文"的选择器（命中即优先） */
  var CONTENT_HINTS = [
    '#lesson-content',
    '[data-lesson-content]',
    '.lesson-content',
    '.course-content',
    '.chapter-content',
    '.content-body',
    '.markdown-body',
    '.rich_media_content',
    '.article-content',
    '.ppt-content',
    'article',
    'main',
    '[role="main"]',
    '#content',
    '.content',
  ];

  /** 一定不是正文的节点 */
  var NOISE_TAGS = [
    'script', 'style', 'noscript', 'template', 'svg', 'canvas', 'iframe',
    'header', 'footer', 'nav', 'aside', 'form', 'button', 'select', 'option',
  ];

  var NOISE_SELECTORS = [
    '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    '[aria-hidden="true"]', '[hidden]',
    '.nav', '.navbar', '.menu', '.sidebar', '.breadcrumb', '.crumbs',
    '.toolbar', '.comment', '.comments', '.advertisement', '.ad', '.ads',
    '.footer', '.header', '.catalog', '.toc',
  ].join(',');

  /** 块级元素：用于在纯文本里还原段落结构 */
  var BLOCK_TAGS = {
    P: 1, DIV: 1, LI: 1, TR: 1, BR: 1, SECTION: 1, ARTICLE: 1, BLOCKQUOTE: 1,
    PRE: 1, TABLE: 1, UL: 1, OL: 1, DL: 1, DT: 1, DD: 1, FIGURE: 1, HR: 1,
    H1: 1, H2: 1, H3: 1, H4: 1, H5: 1, H6: 1,
  };

  /* ------------------------------------------------------------------ *
   * 基础工具
   * ------------------------------------------------------------------ */

  function collapse(s) {
    return String(s || '').replace(/\s+/g, ' ').trim();
  }

  function safe(fn, fallback) {
    try {
      var v = fn();
      return v === undefined || v === null ? fallback : v;
    } catch (e) {
      return fallback;
    }
  }

  /** 深拷贝一份 DOM，剥掉噪音节点，避免污染原页面 */
  function cleanClone(el) {
    var clone = el.cloneNode(true);
    var i;
    for (i = 0; i < NOISE_TAGS.length; i++) {
      var nodes = clone.querySelectorAll(NOISE_TAGS[i]);
      for (var j = nodes.length - 1; j >= 0; j--) {
        if (nodes[j].parentNode) nodes[j].parentNode.removeChild(nodes[j]);
      }
    }
    if (NOISE_SELECTORS) {
      var noise = clone.querySelectorAll(NOISE_SELECTORS);
      for (i = noise.length - 1; i >= 0; i--) {
        if (noise[i].parentNode) noise[i].parentNode.removeChild(noise[i]);
      }
    }
    return clone;
  }

  /**
   * 按块级元素还原文本。
   * 不用 innerText：分离出去的 clone 上没有布局，拿不到换行。
   */
  function blockText(node) {
    var out = [];
    (function walk(n) {
      if (n.nodeType === 3) {
        var t = n.nodeValue;
        if (t && t.trim()) out.push(t);
        return;
      }
      if (n.nodeType !== 1) return;
      var isBlock = BLOCK_TAGS[n.tagName];
      if (isBlock) out.push('\n');
      for (var i = 0; i < n.childNodes.length; i++) walk(n.childNodes[i]);
      if (isBlock) out.push('\n');
    })(node);

    return out
      .join('')
      .replace(/[ \t\u00a0]+/g, ' ')
      .replace(/\s*\n\s*/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  /* ------------------------------------------------------------------ *
   * 正文容器识别
   * ------------------------------------------------------------------ */

  function textLength(el) {
    return safe(function () {
      return (el.textContent || '').length;
    }, 0);
  }

  function linkDensity(el) {
    var total = textLength(el);
    if (!total) return 0;
    var linkLen = 0;
    var links = safe(function () {
      return el.querySelectorAll('a');
    }, []);
    for (var i = 0; i < links.length; i++) linkLen += textLength(links[i]);
    return linkLen / total;
  }

  /** 阅读密度打分：段落越多越长越好，链接越密越差 */
  function densityScore(el) {
    var paragraphs = safe(function () {
      return el.querySelectorAll('p, li, pre, blockquote, td');
    }, []);
    var score = 0;
    for (var i = 0; i < paragraphs.length; i++) {
      var len = textLength(paragraphs[i]);
      if (len < 20) continue;
      score += Math.min(len, 900) / 25 + 1;
    }
    if (score <= 0) return 0;
    score *= 1 - Math.min(linkDensity(el), 0.9);
    return score;
  }

  function pickContentRoot(doc) {
    // 1) 显式提示优先，但要求它真的有内容（有些站点的 .content 只是个空壳）
    for (var i = 0; i < CONTENT_HINTS.length; i++) {
      var hit = safe(function () {
        return doc.querySelector(CONTENT_HINTS[i]);
      }, null);
      if (hit && textLength(hit) >= 300) return { el: hit, how: 'hint:' + CONTENT_HINTS[i] };
    }

    // 2) 密度打分
    var candidates = safe(function () {
      return doc.querySelectorAll('div, section, article, main, td');
    }, []);
    var best = null;
    var bestScore = 0;
    for (var k = 0; k < candidates.length; k++) {
      var el = candidates[k];
      var len = textLength(el);
      if (len < 200 || len > 200000) continue;
      var s = densityScore(el);
      if (s > bestScore) {
        bestScore = s;
        best = el;
      }
    }
    if (best) return { el: best, how: 'density', score: bestScore };

    // 3) 兜底
    return { el: doc.body, how: 'body' };
  }

  /* ------------------------------------------------------------------ *
   * 结构化信息
   * ------------------------------------------------------------------ */

  function extractHeadings(root) {
    var nodes = safe(function () {
      return root.querySelectorAll('h1, h2, h3, h4');
    }, []);
    var out = [];
    for (var i = 0; i < nodes.length && out.length < 40; i++) {
      var t = collapse(nodes[i].textContent).slice(0, 90);
      if (t) {
        out.push({ level: parseInt(nodes[i].tagName.slice(1), 10) || 2, text: t });
      }
    }
    return out;
  }

  function extractFormulas(root, text) {
    var out = [];
    var seen = {};

    function push(f) {
      f = collapse(f);
      if (!f || f.length > 400 || seen[f]) return;
      seen[f] = 1;
      if (out.length < MAX_FORMULAS) out.push(f);
    }

    /** 判断一个行内公式是否"值得上报"。
     *
     * 课件里到处是 `$A$`、`$B$`、`$i$` 这种单符号，全部收进来会把有用信息淹掉
     * （`to_prompt()` 只展示前 12 条）。所以只保留"像公式的"：
     * 含反斜杠命令、含等号/不等号、含上下标、或本身够长。
     */
    function worthReporting(f) {
      if (f.length < 6) return false;
      return /\\[a-zA-Z]|[=<>^_]|\d\s*[+\-*/]|[+\-*/]\s*\d/.test(f);
    }

    // KaTeX 渲染过的公式：读它保留的 TeX 源码
    safe(function () {
      var ann = root.querySelectorAll('.katex annotation[encoding="application/x-tex"]');
      for (var i = 0; i < ann.length; i++) push(ann[i].textContent);
    });

    // MathJax 经典写法
    safe(function () {
      var s = root.querySelectorAll('script[type^="math/tex"]');
      for (var i = 0; i < s.length; i++) push(s[i].textContent);
    });

    // 独立公式块：优先，全部收
    var m;
    var blockRe = /\$\$([\s\S]{1,400}?)\$\$/g;
    while ((m = blockRe.exec(text)) && out.length < MAX_FORMULAS) push(m[1]);

    // 行内公式：只收"像公式的"
    var inlineRe = /\$([^$\n]{2,200}?)\$/g;
    while ((m = inlineRe.exec(text)) && out.length < MAX_FORMULAS) {
      if (worthReporting(m[1])) push(m[1]);
    }

    return out;
  }

  function extractMedia(doc) {
    var v = safe(function () {
      return doc.querySelector('video, audio');
    }, null);
    if (!v) return null;
    var dur = safe(function () {
      return v.duration;
    }, NaN);
    var cur = safe(function () {
      return v.currentTime;
    }, NaN);
    var kind = String(v.tagName || '').toLowerCase();
    if (!isFinite(cur) && !isFinite(dur)) {
      // 元素存在但还没元数据；仍然上报，让助手知道"这是视频页"
      return { kind: kind, currentTime: null, duration: null, title: mediaTitle(v, doc) };
    }
    return {
      kind: kind,
      currentTime: isFinite(cur) ? Math.round(cur * 10) / 10 : null,
      duration: isFinite(dur) ? Math.round(dur * 10) / 10 : null,
      title: mediaTitle(v, doc),
    };
  }

  function mediaTitle(el, doc) {
    var t = el.getAttribute && (el.getAttribute('data-title') || el.getAttribute('title'));
    if (t) return collapse(t).slice(0, 80);
    // 找最近的标题
    var sec = safe(function () {
      var p = el;
      while (p && p !== doc.body) {
        var h = p.querySelector && p.querySelector('h1, h2, h3');
        if (h) return collapse(h.textContent).slice(0, 80);
        p = p.parentNode;
      }
      return '';
    }, '');
    return sec || '';
  }

  /** 当前 frame 是不是我们自己的交互动画 */
  function extractAnimation() {
    // 1) 助手直接注入到动画页面里 —— anim-bridge 提供最完整的信息
    //    （动画 id、标题、当前步数、是否在播放）
    var bridge = safe(function () {
      return PSA.animBridge && PSA.animBridge.state ? PSA.animBridge.state() : null;
    }, null);
    if (bridge && (bridge.id || bridge.title)) return bridge;

    // 2) 助手在 adapter.html 外层 —— adapter 会挂这个全局对象
    var info = safe(function () {
      return global.__ANIM_INFO__;
    }, null);
    if (info && (info.id || info.title)) {
      return {
        id: info.id || '',
        title: info.title || '',
        state: info.state || '',
        steps: null,
        playing: null,
      };
    }

    // 3) 兜底：用按钮 id 判断（8 个动画都有这几个按钮）
    var play = safe(function () {
      return document.querySelector('#playBtn, #startBtn');
    }, null);
    var reset = safe(function () {
      return document.querySelector('#resetBtn');
    }, null);
    if (play && reset) {
      return { id: '', title: document.title || '交互动画', state: '', steps: null, playing: null };
    }
    return null;
  }

  function currentSelection() {
    return safe(function () {
      var s = global.getSelection();
      if (!s || !s.rangeCount || s.isCollapsed) return '';
      var t = String(s).replace(/\s+/g, ' ').trim();
      return t.slice(0, MAX_SELECTION);
    }, '');
  }

  function scrollPct() {
    return safe(function () {
      var doc = document.documentElement;
      var max = (doc.scrollHeight || 0) - (global.innerHeight || 0);
      if (max <= 20) return null;
      return Math.round((global.scrollY / max) * 1000) / 1000;
    }, null);
  }

  /* ------------------------------------------------------------------ *
   * 主入口
   * ------------------------------------------------------------------ */

  /**
   * 抽取当前 frame 的上下文。
   * @param {{maxText?:number, includeSelection?:boolean}} [opts]
   * @returns {object} FrameContext 形状的对象（见 backend/app/kernel/page_context.py）
   */
  function extractContext(opts) {
    opts = opts || {};
    var maxText = opts.maxText || MAX_TEXT;

    var result = {
      url: safe(function () {
        return location.href;
      }, ''),
      title: collapse(document.title).slice(0, 120),
      headings: [],
      text: '',
      selection: opts.includeSelection === false ? '' : currentSelection(),
      formulas: [],
      media: null,
      animation: null,
      scroll_pct: scrollPct(),
      score: 0,
    };

    var picked = safe(function () {
      return pickContentRoot(document);
    }, null);
    if (!picked || !picked.el) return result;

    var cleaned = safe(function () {
      return cleanClone(picked.el);
    }, null);
    if (!cleaned) return result;

    result.text = blockText(cleaned).slice(0, maxText);
    result.headings = extractHeadings(picked.el);
    result.formulas = extractFormulas(picked.el, result.text);
    result.media = extractMedia(document);
    result.animation = extractAnimation();

    // 内容丰富度评分（与后端 _frame_score 口径保持一致，用于多 frame 仲裁）
    result.score =
      result.text.length +
      40 * result.formulas.length +
      20 * result.headings.length +
      (result.selection ? 600 : 0) +
      (result.media ? 200 : 0);

    result._how = picked.how;
    return result;
  }

  /**
   * 监听划词变化。用于在悬浮球旁弹出"解释选中"快捷按钮。
   * @returns {() => void} 取消监听
   */
  function watchSelection(callback) {
    var timer = null;
    function handler() {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        safe(function () {
          callback(currentSelection());
        });
      }, 220);
    }
    document.addEventListener('mouseup', handler, true);
    document.addEventListener('keyup', handler, true);
    return function () {
      if (timer) clearTimeout(timer);
      document.removeEventListener('mouseup', handler, true);
      document.removeEventListener('keyup', handler, true);
    };
  }

  PSA.extractor = {
    extractContext: extractContext,
    watchSelection: watchSelection,
    currentSelection: currentSelection,
    /** 供测试与调试使用 */
    _internals: {
      blockText: blockText,
      cleanClone: cleanClone,
      pickContentRoot: pickContentRoot,
      densityScore: densityScore,
      extractFormulas: extractFormulas,
    },
  };
})(window);

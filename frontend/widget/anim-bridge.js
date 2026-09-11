/**
 * 概率论伴学助手 · 动画桥（Animation Bridge）
 * ===========================================
 *
 * 作用：当悬浮窗被注入到**动画页面自身**（不是 iframe 里）时，
 * 让它能识别"这是哪个动画"、跟踪"现在演到哪一步"，并且**能驱动它**。
 *
 * 为什么这是最好的场景
 * ------------------
 * 前面给 `adapter.html` 做动画播放器时，我们得隔着 iframe 用
 * `contentDocument.querySelector('#playBtn').click()` 去点按钮 —— 那是因为
 * 助手在父页面、动画在子框架。
 *
 * 但如果助手直接注入到动画页面里，一切都在同一个文档：
 *   - 读内容：直接读，没有跨域问题；
 *   - 驱动：直接 `document.querySelector('#stepBtn').click()`；
 *   - 而且能监听用户自己点的按钮，知道"学生已经单步到第 5 步了"。
 *
 * 于是可以做到：**助手一边讲解，一边把动画走到对应的那一步**。
 * 这是本项目演示时最有说服力的一个交互。
 *
 * 实测结论（8 个动画全部核对过）
 * ----------------------------
 *   7 个用 #playBtn，马尔科夫链用 #startBtn；其余 #pauseBtn / #stepBtn / #resetBtn 一致。
 *   全部用 addEventListener 或 onclick 绑定，直接 .click() 都能触发。
 *   8 个都不自动播放。
 */
(function (global) {
  'use strict';

  var PSA = (global.__PSA = global.__PSA || {});

  /** 动作 → 候选选择器（按顺序取第一个存在的） */
  var CONTROL_SELECTORS = {
    play: ['#playBtn', '#startBtn'],
    pause: ['#pauseBtn'],
    step: ['#stepBtn'],
    reset: ['#resetBtn'],
    apply: ['#applyBtn', '#applyMatrixBtn'],
  };

  var state = {
    detected: false,
    id: '',
    title: '',
    file: '',
    concepts: [],
    playing: false,
    steps: 0,
    lastAction: '',
    /** 首次交互前为 true，用于在上下文里区分"还没开始看" */
    untouched: true,
  };

  var installed = false;

  /* ------------------------------------------------------------------ *
   * 识别
   * ------------------------------------------------------------------ */

  function currentFileName() {
    try {
      var path = global.location.pathname || '';
      var base = path.split('/').pop() || '';
      return normalize(decodeURIComponent(base));
    } catch (e) {
      return '';
    }
  }

  /** 归一化文件名：去空白、统一 Unicode 形式（中文文件名在不同来源下可能不同） */
  function normalize(s) {
    return String(s || '')
      .replace(/\s+/g, ' ')
      .trim()
      .normalize('NFC');
  }

  function findButton(action) {
    var list = CONTROL_SELECTORS[action] || [];
    for (var i = 0; i < list.length; i++) {
      var el = document.querySelector(list[i]);
      if (el) return el;
    }
    return null;
  }

  /** 这个文档看起来是不是一个动画页？ */
  function looksLikeAnimation() {
    var found = 0;
    ['play', 'pause', 'step', 'reset'].forEach(function (a) {
      if (findButton(a)) found += 1;
    });
    if (found >= 3) return true;
    // 有些动画可能只暴露部分控制；再看有没有 canvas + 阶梯式 UI
    return !!document.querySelector('canvas') && found >= 1;
  }

  /** 用文件名在动画清单里找出对应的条目 */
  function matchManifest(items) {
    var file = currentFileName();
    if (!file) return null;
    for (var i = 0; i < (items || []).length; i++) {
      var f = normalize(items[i].file);
      if (f === file) return items[i];
      // 容错：忽略 "(g)" 后缀与空格差异
      var strip = function (s) {
        return s.replace(/\s*\(g\)\s*/i, '').replace(/\.html?$/i, '').replace(/\s+/g, '');
      };
      if (strip(f) && strip(f) === strip(file)) return items[i];
    }
    return null;
  }

  /**
   * 初始化。会拉一次动画清单（很小），匹配当前页面。
   * @param {{manifest?: Array}} [opts] 已有清单时直接传，省一次请求
   */
  function detect(opts) {
    opts = opts || {};
    if (!looksLikeAnimation()) return null;

    state.detected = true;
    state.title = normalize(document.title);

    function apply(item) {
      if (item) {
        state.id = item.id || '';
        state.title = item.title || state.title;
        state.file = item.file || currentFileName();
        state.concepts = item.concepts || [];
      } else {
        state.file = currentFileName();
      }
      install();
      return stateInfo();
    }

    if (opts.manifest && opts.manifest.length) {
      return apply(matchManifest(opts.manifest));
    }

    // 异步补全（拿不到也不影响：标题已经够用）
    if (PSA.api && PSA.api.url) {
      fetch(PSA.api.url('/api/animations'))
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          var item = matchManifest((data && data.items) || []);
          if (item) {
            state.id = item.id || '';
            state.title = item.title || state.title;
            state.file = item.file || state.file;
            state.concepts = item.concepts || [];
          }
        })
        .catch(function () {
          /* 后端不可达时静默，动画本身照常可用 */
        });
    }

    install();
    return stateInfo();
  }

  /* ------------------------------------------------------------------ *
   * 状态跟踪
   * ------------------------------------------------------------------ */

  function install() {
    if (installed) return;
    installed = true;

    // 旁听控制按钮的点击（捕获阶段，不影响动画自身的处理）
    document.addEventListener(
      'click',
      function (ev) {
        var t = ev.target;
        if (!t || t.nodeType !== 1) return;
        var btn = t.closest ? t.closest('button, input[type=button], a') : null;
        if (!btn) return;

        if (matches(btn, 'step')) {
          state.steps += 1;
          state.playing = false;
          state.lastAction = '单步';
          state.untouched = false;
        } else if (matches(btn, 'play')) {
          state.playing = true;
          state.lastAction = '播放';
          state.untouched = false;
        } else if (matches(btn, 'pause')) {
          state.playing = false;
          state.lastAction = '暂停';
          state.untouched = false;
        } else if (matches(btn, 'reset')) {
          state.playing = false;
          state.steps = 0;
          state.lastAction = '重置';
          state.untouched = false;
        }
      },
      true
    );
  }

  function matches(btn, action) {
    var list = CONTROL_SELECTORS[action] || [];
    for (var i = 0; i < list.length; i++) {
      if (btn.matches && btn.matches(list[i])) return true;
      if (btn.id && list[i] === '#' + btn.id) return true;
    }
    return false;
  }

  /** 人类可读的当前状态，会随提问一起上报给后端 */
  function stateText() {
    if (!state.detected) return '';
    if (state.untouched) return '已打开，尚未开始播放';
    var extra = state.steps > 0 ? '（已单步 ' + state.steps + ' 次）' : '';
    if (state.playing) return '正在播放' + extra;
    return '已暂停' + extra;
  }

  function stateInfo() {
    if (!state.detected) return null;
    return {
      id: state.id,
      title: state.title,
      file: state.file,
      concepts: state.concepts,
      state: stateText(),
      steps: state.steps,
      playing: state.playing,
    };
  }

  function available() {
    var out = {};
    ['play', 'pause', 'step', 'reset'].forEach(function (a) {
      out[a] = !!findButton(a);
    });
    return out;
  }

  /**
   * 驱动动画。
   * @param {'play'|'pause'|'step'|'reset'} action
   * @returns {boolean} 是否成功
   */
  function control(action) {
    var btn = findButton(action);
    if (!btn) return false;
    try {
      btn.click();
    } catch (e) {
      return false;
    }
    // 保险：如果捕获阶段的监听没跑（比如动画用了别的绑定方式），这里补一次状态
    if (action === 'step') {
      state.steps += 1;
      state.playing = false;
    } else if (action === 'play') {
      state.playing = true;
    } else if (action === 'pause') {
      state.playing = false;
    } else if (action === 'reset') {
      state.steps = 0;
      state.playing = false;
    }
    state.untouched = false;
    state.lastAction = action;
    return true;
  }

  PSA.animBridge = {
    detect: detect,
    state: stateInfo,
    stateText: stateText,
    available: available,
    control: control,
    isAnimationPage: function () {
      return state.detected;
    },
    _internals: { looksLikeAnimation: looksLikeAnimation, normalize: normalize, matchManifest: matchManifest },
  };
})(window);

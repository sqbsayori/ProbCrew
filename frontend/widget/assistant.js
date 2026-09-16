/**
 * 概率论伴学助手 · 主组件
 * ========================
 *
 * 这是被注入到在线课程页面上的那个"悬浮球 / 虚拟页宠"。
 *
 * 它做的事情，按重要性排序：
 *   1. **读懂当前页面**：抽取正文/标题/公式/选中文字/视频进度/动画状态，
 *      跨 iframe 汇总后随提问一起发给后端（这是本产品与通用聊天机器人的根本差别）；
 *   2. **让用户看见它读到了什么**：面板顶部有上下文条，可展开看页面大纲；
 *   3. **陪在旁边**：页宠的表情跟着 Agent 状态走（思考/讲解/待确认/出错）；
 *   4. 完整的多 Agent 协作对话，含 HITL 人机协同与结构化产物。
 *
 * 样式全部关在 Shadow DOM 里，不污染宿主课程平台。
 */
(function (global) {
  'use strict';

  var PSA = (global.__PSA = global.__PSA || {});

  var LS = {
    skin: 'psa.skin',
    pos: 'psa.launcher.pos',
    open: 'psa.panel.open',
    readPage: 'psa.readPage',
    session: 'psa.session_id',
  };

  function store(key, value) {
    try {
      if (value === undefined) return global.localStorage.getItem(key);
      global.localStorage.setItem(key, value);
      return value;
    } catch (e) {
      return null; // 某些平台禁用了 localStorage
    }
  }

  function sessionId() {
    var id = store(LS.session);
    if (!id) {
      id = 'web_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
      store(LS.session, id);
    }
    return id;
  }

  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') n.className = v;
        else if (k === 'text') n.textContent = v;
        else if (k === 'html') n.innerHTML = v;
        else if (k.indexOf('on') === 0 && typeof v === 'function') {
          n.addEventListener(k.slice(2).toLowerCase(), v);
        } else n.setAttribute(k, v);
      });
    }
    (children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return n;
  }

  /* ================================================================== *
   * 产物渲染（widget 内的精简版）
   * ================================================================== */

  /** 迷你折线/柱状图：392px 宽的面板里够用 */
  function miniChart(spec) {
    var canvas = el('canvas', { class: 'psa-chart', style: 'width:100%;height:130px;display:block' });
    requestAnimationFrame(function () {
      var rect = canvas.getBoundingClientRect();
      var dpr = global.devicePixelRatio || 1;
      var w = Math.max(rect.width, 160);
      var h = Math.max(rect.height, 90);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      var ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      var series = spec.series || [];
      if (!series.length || !series[0].x || !series[0].x.length) return;

      var pad = { l: 30, r: 8, t: 8, b: 16 };
      var pw = w - pad.l - pad.r;
      var ph = h - pad.t - pad.b;
      var xs = series[0].x;
      var ys = series[0].y;
      var xMin = Math.min.apply(null, xs);
      var xMax = Math.max.apply(null, xs);
      var yMax = Math.max.apply(null, ys) * 1.1 || 1;
      var bar = spec.type === 'bar';

      ctx.strokeStyle = '#eef2f7';
      ctx.lineWidth = 1;
      for (var g = 0; g <= 3; g++) {
        var gy = pad.t + (ph / 3) * g;
        ctx.beginPath();
        ctx.moveTo(pad.l, gy);
        ctx.lineTo(pad.l + pw, gy);
        ctx.stroke();
      }

      ctx.strokeStyle = spec.color || '#4f46e5';
      ctx.fillStyle = spec.color || '#4f46e5';
      ctx.lineWidth = 1.8;

      if (bar) {
        var bw = Math.max(2, Math.min(10, pw / Math.max(xs.length, 1) - 1.5));
        ctx.globalAlpha = 0.85;
        for (var i = 0; i < xs.length; i++) {
          var bx = pad.l + ((xs[i] - xMin) / (xMax - xMin || 1)) * pw;
          var by = pad.t + ph - (ys[i] / yMax) * ph;
          ctx.fillRect(bx - bw / 2, by, bw, pad.t + ph - by);
        }
        ctx.globalAlpha = 1;
      } else {
        ctx.beginPath();
        for (var k = 0; k < xs.length; k++) {
          var px = pad.l + ((xs[k] - xMin) / (xMax - xMin || 1)) * pw;
          var py = pad.t + ph - (ys[k] / yMax) * ph;
          if (k === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.stroke();
      }

      ctx.fillStyle = '#94a3b8';
      ctx.font = '10px system-ui, sans-serif';
      ctx.fillText(String(Math.round(yMax * 100) / 100), 2, pad.t + 8);
      ctx.fillText('0', 2, pad.t + ph);
    });
    return canvas;
  }

  function formulaCard(payload) {
    var wrap = el('div', { class: 'psa-artifact' }, [
      el('div', { class: 'psa-artifact-title', text: '📐 ' + (payload.title || '关键公式') }),
    ]);
    (payload.items || []).forEach(function (tex) {
      var box = el('div', {
        style:
          'padding:6px 8px;background:#fff;border:1px solid #e2e8f0;border-radius:7px;margin-top:5px;overflow-x:auto',
      });
      box.innerHTML = '<span class="math-block" data-tex="' + PSA.render.esc(tex) + '"></span>';
      wrap.appendChild(box);
    });
    PSA.render.mathIn(wrap);
    return wrap;
  }

  function tableCard(payload) {
    var cols = payload.columns || [];
    var rows = payload.rows || [];
    var html =
      '<table class="psa-table"><thead><tr>' +
      cols
        .map(function (c) {
          return '<th>' + PSA.render.esc(c) + '</th>';
        })
        .join('') +
      '</tr></thead><tbody>' +
      rows
        .map(function (r) {
          return (
            '<tr>' +
            r
              .map(function (c) {
                return '<td>' + PSA.render.esc(c == null ? '' : c) + '</td>';
              })
              .join('') +
            '</tr>'
          );
        })
        .join('') +
      '</tbody></table>';
    return el('div', { class: 'psa-artifact' }, [
      el('div', { class: 'psa-artifact-title', text: '📋 ' + (payload.title || '数据') }),
      el('div', { html: html, style: 'overflow-x:auto' }),
    ]);
  }

  function stepsCard(payload) {
    var wrap = el('div', { class: 'psa-artifact' }, [
      el('div', {
        class: 'psa-artifact-title',
        text: '🪜 ' + (payload.title || '解题步骤') + '（' + (payload.steps || []).length + ' 步）',
      }),
    ]);
    (payload.steps || []).forEach(function (s) {
      var body = el('div', { style: 'margin-top:4px' });
      PSA.render.into(body, s.body || '');
      wrap.appendChild(
        el('div', {
          style:
            'border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;margin-top:6px;background:#fff',
        }, [
          el('div', { style: 'display:flex;gap:6px;align-items:center;margin-bottom:4px' }, [
            el('span', {
              text: 'Step ' + s.index,
              style:
                'background:#4f46e5;color:#fff;font-size:10.5px;padding:1px 6px;border-radius:4px;font-weight:600',
            }),
            el('b', { text: s.title || '', style: 'font-size:12.5px' }),
          ]),
          body,
        ])
      );
    });
    return wrap;
  }

  function chartCard(payload) {
    return el('div', { class: 'psa-artifact' }, [
      el('div', { class: 'psa-artifact-title', text: '📊 ' + (payload.title || '分布') }),
      miniChart({
        series: [{ x: (payload.pdf || {}).x || [], y: (payload.pdf || {}).y || [] }],
        type: payload.kind === 'discrete' ? 'bar' : 'line',
      }),
      el('div', {
        style: 'font-size:11px;color:#64748b;margin-top:4px',
        text: 'E[X]=' + fmt(payload.mean) + '  Var(X)=' + fmt(payload.var) + (payload.note ? ' · ' + payload.note : ''),
      }),
    ]);
  }

  function fmt(v) {
    var n = Number(v);
    if (!isFinite(n)) return '—';
    if (Math.abs(n) >= 10000 || (n !== 0 && Math.abs(n) < 0.001)) return n.toExponential(2);
    return String(Math.round(n * 10000) / 10000);
  }

  /* ================================================================== *
   * 主组件
   * ================================================================== */

  /**
   * @param {{
   *   base?: string, skin?: 'pet'|'ball', autoOpen?: boolean,
   *   readPage?: boolean, title?: string, quickActions?: string[]
   * }} [opts]
   */
  function createAssistant(opts) {
    opts = opts || {};
    var base = (opts.base || '').replace(/\/+$/, '');
    var skin = opts.skin || store(LS.skin) || 'pet';
    var readPage = opts.readPage !== undefined ? opts.readPage : store(LS.readPage) !== '0';
    var destroyed = false;

    PSA.api.configure({ base: base });

    /* ---- Shadow DOM 宿主 ---- */
    var host = document.createElement('div');
    host.setAttribute('data-psa-host', '1');
    host.style.cssText = 'all:initial;position:static';
    var root = host.attachShadow({ mode: 'open' });
    PSA.render.injectStyles(root, base);
    PSA.render.load(base);

    /* ---- 结构 ---- */
    var launcherCanvas = el('canvas');
    var badge = el('span', { class: 'psa-badge' });
    var launcher = el('button', {
      class: 'psa-launcher',
      title: '概率论伴学助手（可拖动）',
      'aria-label': '打开伴学助手',
    }, [launcherCanvas, badge]);

    var headCanvas = el('canvas', { class: 'psa-head-avatar' });
    var statusText = el('span', { text: '在线，随时问我' });
    var skinBtn = el('button', {
      class: 'psa-icon-btn',
      title: '切换形象（页宠 / 悬浮球）',
      text: '🎭',
      onclick: function () {
        setSkin(skin === 'pet' ? 'ball' : 'pet');
      },
    });
    var readBtn = el('button', {
      class: 'psa-icon-btn',
      title: '是否读取当前页面内容',
      text: '📖',
      onclick: function () {
        readPage = !readPage;
        store(LS.readPage, readPage ? '1' : '0');
        updateReadBtn();
        refreshContextBar();
      },
    });
    var minBtn = el('button', {
      class: 'psa-icon-btn',
      title: '收起',
      text: '—',
      onclick: function () {
        close();
      },
    });

    var head = el('div', { class: 'psa-head' }, [
      headCanvas,
      el('div', { class: 'psa-head-text' }, [
        el('b', { text: opts.title || '概率论伴学助手' }),
        statusText,
      ]),
      readBtn,
      skinBtn,
      minBtn,
    ]);

    /* ---- 上下文条 ---- */
    var ctxText = el('div', { class: 'psa-ctx-body' });
    var ctxBar = el('div', { class: 'psa-context' }, [
      el('span', { class: 'psa-ctx-ico', text: '📄' }),
      ctxText,
    ]);

    /* ---- 动画控制条（只在动画页面上出现）----
       把动画自己的按钮"搬"进面板，好处有两层：
         1. 学生不用在页面和面板之间来回找按钮；
         2. 助手可以**主动驱动动画**再讲解 —— "我帮你走到第 3 步，你看这里"。
    ---- */
    var animTitle = el('span', { class: 'psa-anim-title', text: '' });
    var animStateText = el('span', { class: 'psa-anim-state', text: '' });
    var animCtrlBox = el('div', { class: 'psa-anim-ctrls' });
    var animBar = el('div', { class: 'psa-animbar', style: 'display:none' }, [
      animTitle,
      animCtrlBox,
      animStateText,
    ]);

    function refreshAnimBar() {
      if (!PSA.animBridge || !PSA.animBridge.isAnimationPage()) return;
      var info = PSA.animBridge.state();
      if (!info) return;
      animTitle.textContent = '🎬 ' + (info.title || '交互动画');
      animStateText.textContent = PSA.animBridge.stateText();

      var avail = PSA.animBridge.available();
      animCtrlBox.textContent = '';
      [
        ['play', '▶', '播放'],
        ['pause', '⏸', '暂停'],
        ['step', '⏭', '单步'],
        ['reset', '⟲', '重置'],
      ].forEach(function (row) {
        var action = row[0];
        animCtrlBox.appendChild(
          el('button', {
            class: 'psa-anim-btn',
            text: row[1],
            title: row[2] + (avail[action] ? '' : '（本动画未提供）'),
            disabled: !avail[action],
            onclick: function () {
              if (PSA.animBridge.control(action)) refreshAnimBar();
            },
          })
        );
      });
    }

    /* ---- 消息区 ---- */
    var body = el('div', { class: 'psa-body' });
    var empty = el('div', { class: 'psa-empty' }, [
      el('div', { text: '👋 我是你的概率论伴学助手' }),
      el('div', {
        text: readPage ? '我能看到你正在看的这一页，可以直接问我"这段什么意思"' : '页面读取已关闭，我会用教材知识库回答',
      }),
    ]);
    body.appendChild(empty);

    /* ---- 快捷动作 ---- */
    var quick = el('div', { class: 'psa-quick' });

    /* ---- 输入区 ---- */
    var input = el('textarea', {
      class: 'psa-input',
      rows: 1,
      placeholder: '问我这一页的任何问题…（Enter 发送，Shift+Enter 换行）',
    });
    var sendBtn = el('button', { class: 'psa-send', text: '↑', title: '发送' });
    var hint = el('div', { class: 'psa-hint' }, [
      el('span', { text: 'Enter 发送 · Shift+Enter 换行' }),
      el('span', { text: '' }),
    ]);
    var composer = el('div', { class: 'psa-composer' }, [
      el('div', { class: 'psa-input-row' }, [input, sendBtn]),
      hint,
    ]);

    var panel = el('div', { class: 'psa-panel' }, [head, ctxBar, animBar, body, quick, composer]);

    /* ---- 划词快捷入口 ---- */
    var selChip = el('button', {
      class: 'psa-sel-chip',
      text: '💡 解释这段',
      onclick: function () {
        var sel = PSA.extractor.currentSelection();
        open();
        setInput(sel ? '这段是什么意思？' : '');
        if (sel) send();
      },
    });

    var wrapEl = el('div', { class: 'psa-root' }, [panel, launcher, selChip]);
    root.appendChild(wrapEl);

    /* ---- 动画覆盖层（打开交互动画用，关闭时必须销毁 iframe）---- */
    var overlay = null;
    function openAnimation(payload) {
      closeAnimation();
      var frame = el('iframe', {
        src: payload.url,
        style: 'width:100%;height:calc(100vh - 140px);border:0;display:block;background:#fff',
      });
      frame.addEventListener('load', function () {
        try {
          frame.contentWindow.dispatchEvent(new Event('resize'));
        } catch (e) {
          /* 忽略 */
        }
      });
      overlay = el('div', {
        style:
          'position:fixed;inset:0;z-index:5;background:rgba(15,23,42,.7);padding:16px;display:flex;flex-direction:column;gap:10px;pointer-events:auto',
      }, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:center;color:#fff' }, [
          el('b', { text: '🎬 ' + (payload.title || '交互动画'), style: 'font-size:13.5px' }),
          el('button', { class: 'psa-btn', text: '✕ 关闭', onclick: closeAnimation }),
        ]),
        el('div', { style: 'flex:1;background:#fff;border-radius:12px;overflow:hidden' }, [frame]),
      ]);
      wrapEl.appendChild(overlay);
    }
    function closeAnimation() {
      if (!overlay) return;
      var f = overlay.querySelector('iframe');
      if (f) {
        f.src = 'about:blank'; // 关键：部分动画的 rAF 循环停不掉，必须销毁节点
        f.remove();
      }
      overlay.remove();
      overlay = null;
    }

    /* ---- 头像 ---- */
    var avatarLauncher = PSA.pet.createAvatar(launcherCanvas, { skin: skin });
    var avatarHead = PSA.pet.createAvatar(headCanvas, { skin: skin });

    function setState(name) {
      avatarLauncher.setState(name);
      avatarHead.setState(name);
      statusText.textContent = avatarLauncher.getLabel();
    }
    function setSkin(next) {
      skin = next === 'ball' ? 'ball' : 'pet';
      store(LS.skin, skin);
      avatarLauncher.setSkin(skin);
      avatarHead.setSkin(skin);
      launcher.title = skin === 'pet' ? '概率论伴学宠物（可拖动）' : '概率论伴学助手（可拖动）';
    }
    function updateReadBtn() {
      readBtn.style.background = readPage ? 'rgba(255,255,255,.32)' : 'rgba(255,255,255,.12)';
      readBtn.title = readPage ? '正在读取当前页面内容（点击关闭）' : '已关闭页面读取（点击开启）';
    }

    /* ---- 拖动 ---- */
    var drag = { active: false, moved: false, sx: 0, sy: 0, ox: 0, oy: 0 };
    var pos = (function () {
      try {
        return JSON.parse(store(LS.pos) || 'null');
      } catch (e) {
        return null;
      }
    })();

    function applyPos() {
      if (pos && typeof pos.left === 'number') {
        launcher.style.left = Math.max(4, Math.min(pos.left, global.innerWidth - 76)) + 'px';
        launcher.style.top = Math.max(4, Math.min(pos.top, global.innerHeight - 76)) + 'px';
        launcher.style.right = 'auto';
        launcher.style.bottom = 'auto';
      } else {
        launcher.style.right = '20px';
        launcher.style.bottom = '22px';
        launcher.style.left = 'auto';
        launcher.style.top = 'auto';
      }
    }

    launcher.addEventListener('pointerdown', function (e) {
      drag.active = true;
      drag.moved = false;
      var r = launcher.getBoundingClientRect();
      drag.sx = e.clientX;
      drag.sy = e.clientY;
      drag.ox = r.left;
      drag.oy = r.top;
      launcher.classList.add('psa-dragging');
      try {
        launcher.setPointerCapture(e.pointerId);
      } catch (err) {
        /* 忽略 */
      }
    });
    launcher.addEventListener('pointermove', function (e) {
      if (!drag.active) return;
      var dx = e.clientX - drag.sx;
      var dy = e.clientY - drag.sy;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true;
      var left = Math.max(4, Math.min(drag.ox + dx, global.innerWidth - 76));
      var top = Math.max(4, Math.min(drag.oy + dy, global.innerHeight - 76));
      launcher.style.left = left + 'px';
      launcher.style.top = top + 'px';
      launcher.style.right = 'auto';
      launcher.style.bottom = 'auto';
    });
    launcher.addEventListener('pointerup', function (e) {
      if (!drag.active) return;
      drag.active = false;
      launcher.classList.remove('psa-dragging');
      if (drag.moved) {
        var r = launcher.getBoundingClientRect();
        pos = { left: r.left, top: r.top };
        store(LS.pos, JSON.stringify(pos));
        positionSelChip();
      } else {
        toggle();
      }
    });

    /* ---- 面板开关 ---- */
    function open() {
      panel.classList.add('psa-open');
      store(LS.open, '1');
      setState('idle');
      setTimeout(function () {
        input.focus();
      }, 60);
      positionSelChip();
    }
    function close() {
      panel.classList.remove('psa-open');
      store(LS.open, '0');
      clearBadge();
    }
    function toggle() {
      if (panel.classList.contains('psa-open')) close();
      else open();
    }
    function setBadge(n) {
      if (n > 0) {
        badge.textContent = String(n);
        badge.classList.add('psa-show');
      } else clearBadge();
    }
    function clearBadge() {
      badge.classList.remove('psa-show');
    }

    /* ---- 划词快捷入口定位 ---- */
    function positionSelChip() {
      var r = launcher.getBoundingClientRect();
      selChip.style.left = Math.max(8, r.left - 96) + 'px';
      selChip.style.top = Math.max(8, r.top - 4) + 'px';
    }

    var unwatchSelection = PSA.extractor.watchSelection(function (sel) {
      if (sel && readPage && !panel.classList.contains('psa-open')) {
        selChip.classList.add('psa-show');
        positionSelChip();
      } else {
        selChip.classList.remove('psa-show');
      }
    });

    /* ---- 消息渲染 ---- */
    var currentAi = null; // 正在流式输出的气泡
    var currentText = '';
    var rafPending = 0;

    function clearEmpty() {
      if (empty && empty.parentNode) empty.parentNode.removeChild(empty);
    }

    function addUser(text) {
      clearEmpty();
      body.appendChild(el('div', { class: 'psa-msg psa-msg-user', text: text }));
      scrollDown();
    }

    function addAi(initial) {
      clearEmpty();
      var content = el('div', { class: 'psa-msg-ai-content' });
      var box = el('div', { class: 'psa-msg psa-msg-ai' }, [content]);
      body.appendChild(box);
      currentAi = content;
      currentText = initial || '';
      if (currentText) PSA.render.into(content, currentText);
      scrollDown();
      return content;
    }

    function flushAi() {
      if (!currentAi) return;
      rafPending = 0;
      PSA.render.into(currentAi, currentText);
      currentAi.classList.add('psa-caret');
      scrollDown();
    }
    function scheduleAi() {
      if (rafPending) return;
      rafPending = global.requestAnimationFrame(flushAi);
    }
    function finishAi() {
      if (!currentAi) return;
      PSA.render.into(currentAi, currentText);
      currentAi.classList.remove('psa-caret');
      currentAi = null;
      currentText = '';
    }

    function addArtifact(kind, payload) {
      var node = null;
      if (kind === 'formula') node = formulaCard(payload);
      else if (kind === 'table') node = tableCard(payload);
      else if (kind === 'steps') node = stepsCard(payload);
      else if (kind === 'chart') node = chartCard(payload);
      else if (kind === 'animation') {
        node = el('div', { class: 'psa-artifact' }, [
          el('div', { class: 'psa-artifact-title', text: '🎬 ' + (payload.title || '交互动画') }),
          el('div', {
            style: 'font-size:11.5px;color:#64748b;margin-bottom:6px',
            text: payload.description || payload.reason || '',
          }),
          el('button', {
            class: 'psa-btn psa-btn-primary',
            text: '▶ 打开动画演示',
            onclick: function () {
              openAnimation(payload);
            },
          }),
        ]);
      }
      if (node) {
        node.style.marginTop = '8px';
        body.appendChild(node);
        scrollDown();
      }
    }

    function addHitl(e) {
      var ta = el('textarea', {
        class: 'psa-input',
        rows: 2,
        placeholder: '若选择「修正」或「补充」，请写在这里…',
      });
      var card = el('div', { class: 'psa-hitl' }, [
        el('b', { text: '⏸ 关键结论待你确认' }),
        el('p', { text: e.draft || '（无说明）' }),
        ta,
        el('div', { class: 'psa-hitl-actions' }, [
          el('button', {
            class: 'psa-btn psa-btn-success',
            text: '✅ 确认采纳',
            onclick: function () {
              resolveHitl('confirm', '');
            },
          }),
          el('button', {
            class: 'psa-btn',
            text: '✏️ 按我的修正重写',
            onclick: function () {
              if (!ta.value.trim()) return;
              resolveHitl('correct', ta.value.trim());
            },
          }),
          el('button', {
            class: 'psa-btn',
            text: '➕ 补充说明',
            onclick: function () {
              if (!ta.value.trim()) return;
              resolveHitl('supplement', ta.value.trim());
            },
          }),
        ]),
      ]);
      body.appendChild(card);
      scrollDown();
      if (!panel.classList.contains('psa-open')) setBadge(1);
    }

    function scrollDown() {
      body.scrollTop = body.scrollHeight;
    }

    /* ---- 上下文条刷新 ---- */
    var lastContext = null;

    function refreshContextBar() {
      ctxText.textContent = '';
      if (!readPage) {
        ctxBar.classList.add('psa-ctx-warn');
        ctxText.appendChild(el('div', { text: '📖 页面读取已关闭 —— 点标题栏的 📖 开启' }));
        return;
      }
      PSA.frames.collectAll().then(function (frames) {
        if (destroyed) return;
        var usable = frames.filter(function (f) {
          return f && (f.text || f.selection);
        });
        // 选中文字可能来自任意 frame，合并到主上下文里
        var sel = PSA.extractor.currentSelection();
        var totalChars = usable.reduce(function (a, f) {
          return a + (f.text ? f.text.length : 0);
        }, 0);
        var formulas = usable.reduce(function (a, f) {
          return a + ((f.formulas && f.formulas.length) || 0);
        }, 0);
        var media = null;
        for (var i = 0; i < usable.length; i++) {
          if (usable[i].media && usable[i].media.currentTime != null) {
            media = usable[i].media;
            break;
          }
        }
        var title = '';
        for (var j = 0; j < usable.length; j++) {
          if (usable[j].title && usable[j].text && usable[j].text.length > 200) {
            title = usable[j].title;
            break;
          }
        }
        if (!title && usable.length) title = usable[0].title || '';

        if (!usable.length) {
          ctxBar.classList.add('psa-ctx-warn');
          ctxText.appendChild(
            el('div', { text: '⚠️ 这个页面读不到正文（可能是空页或内容在跨域框架里）' })
          );
          return;
        }

        ctxBar.classList.remove('psa-ctx-warn');
        var bits = [];
        if (title) bits.push('《' + title + '》');
        bits.push(totalChars.toLocaleString() + ' 字');
        if (formulas) bits.push(formulas + ' 个公式');
        if (sel) bits.push('已选中 ' + sel.length + ' 字');
        if (usable.length > 1) bits.push(usable.length + ' 个框架');
        if (media) {
          bits.push('视频 ' + Math.floor(media.currentTime / 60) + ':' + pad2(Math.floor(media.currentTime % 60)));
        }
        ctxText.appendChild(el('div', { text: '已读取 ' + bits.join('、') }));

        // 可展开的大纲
        var headingFrame = usable[0];
        for (var k = 0; k < usable.length; k++) {
          if (usable[k].headings && usable[k].headings.length > (headingFrame.headings || []).length) {
            headingFrame = usable[k];
          }
        }
        if (headingFrame.headings && headingFrame.headings.length) {
          var outlineText = headingFrame.headings
            .slice(0, 14)
            .map(function (h) {
              return new Array(Math.max((h.level || 2) - 1, 0) + 1).join('  ') + '- ' + h.text;
            })
            .join('\n');
          var det = el('details', {}, [
            el('summary', { text: '展开页面结构 ▾' }),
            el('div', { class: 'psa-ctx-outline', text: outlineText }),
          ]);
          ctxText.appendChild(det);
        }
      });
    }

    function pad2(n) {
      return (n < 10 ? '0' : '') + n;
    }

    /* ---- 快捷动作（随页面能力变化）---- */
    function refreshQuick() {
      quick.textContent = '';
      var actions = [];

      // 动画页面：给一组"边看边讲"的动作
      if (PSA.animBridge && PSA.animBridge.isAnimationPage()) {
        actions.push({
          label: '🐾 这个动画在演示什么',
          q: '这个动画在演示什么原理？请结合动画里能看到的现象讲。',
        });
        actions.push({
          label: '⏭ 单步并讲解',
          q: '', // 由 stepAndExplain 处理（先驱动动画，再提问）
          special: 'step',
        });
        actions.push({
          label: '🎯 对应哪个考点',
          q: '这个动画对应《概率论与数理统计》里的哪个知识点和考点？考试会怎么考？',
        });
        actions.push({
          label: '🔧 参数怎么调',
          q: '这个动画里哪些参数值得调？调了之后现象会怎么变？',
        });
        actions.forEach(function (a) {
          quick.appendChild(
            el('button', {
              class: 'psa-btn',
              text: a.label,
              onclick: function () {
                if (a.special === 'step') stepAndExplain();
                else {
                  setInput(a.q);
                  send();
                }
              },
            })
          );
        });
        return;
      }

      var sel = PSA.extractor.currentSelection();
      if (sel && readPage) {
        actions.push({
          label: '💡 解释选中的这段',
          q: '这段是什么意思？',
        });
      }
      if (readPage) {
        actions.push({ label: '📄 这一页讲了什么', q: '这一页讲了什么？请帮我梳理结构' });
        actions.push({ label: '🧭 我学到哪了', q: '我现在学到哪了？' });
        actions.push({ label: '❓ 这一页的重点是什么', q: '这一页的考试重点是什么？' });
      } else {
        actions.push({ label: '什么是贝叶斯公式', q: '什么是贝叶斯公式？' });
        actions.push({ label: '全概率公式和贝叶斯的关系', q: '全概率公式和贝叶斯公式是什么关系？' });
      }
      actions.slice(0, 4).forEach(function (a) {
        quick.appendChild(
          el('button', {
            class: 'psa-btn',
            text: a.label,
            onclick: function () {
              setInput(a.q);
              send();
            },
          })
        );
      });
    }

    /**
     * 「单步并讲解」—— 本项目最有说服力的交互之一。
     *
     * 助手**先替学生把动画往前走一步**，然后针对"刚发生的变化"提问。
     * 这样模型的回答是针对具体现象的，而不是泛泛介绍这个知识点。
     * 全流程在同一文档内，所以可以直接点动画自己的按钮。
     */
    function stepAndExplain() {
      if (!PSA.animBridge || !PSA.animBridge.isAnimationPage()) return;
      var ok = PSA.animBridge.control('step');
      refreshAnimBar();
      var info = PSA.animBridge.state() || {};
      var n = info.steps || 0;
      if (!ok) {
        setInput('这个动画在演示什么？');
      } else {
        setInput(
          '我刚才把动画单步推进到了第 ' + n + ' 步。请告诉我：这一步在演示什么？' +
            '和上一步相比发生了什么变化？为什么这个变化在概率论上是重要的？'
        );
      }
      open();
      setTimeout(send, 120); // 等状态更新完再发
    }

    /* ---- 发送 ---- */
    var controller = null;
    var running = false;
    /** 当前运行的 run_id —— HITL 断点恢复必须用它 */
    var lastRunId = null;

    function setInput(v) {
      input.value = v;
      input.style.height = 'auto';
    }

    function setRunning(v) {
      running = v;
      sendBtn.disabled = v;
      input.disabled = v;
      hint.lastChild.textContent = v ? '正在协作…' : '';
    }

    function gatherContext() {
      if (!readPage) return Promise.resolve(null);
      return PSA.frames.collectAll().then(function (frames) {
        var usable = (frames || []).filter(function (f) {
          return f && (f.text || f.selection);
        });
        if (!usable.length) return null;
        // 带上顶层页面的选中文字（它可能不在最丰富的那一帧里）
        var sel = PSA.extractor.currentSelection();
        return {
          source: 'userscript',
          frames: usable,
          selection: sel || '',
        };
      });
    }

    function handleEvent(e) {
      if (e.run_id) lastRunId = e.run_id;
      switch (e.type) {
        case 'run.start':
          setState('thinking');
          break;

        case 'context.received':
          lastContext = e;
          if (e.data && e.data.chars) {
            setState('thinking');
          }
          break;

        case 'plan':
          setState('thinking');
          break;

        case 'agent.start':
          setState('thinking');
          break;

        case 'agent.delta':
          setState('talking');
          if (!currentAi) addAi('');
          currentText += e.text || '';
          scheduleAi();
          break;

        case 'agent.end':
          break;

        case 'artifact':
          setState('happy');
          addArtifact(e.kind, e.payload || {});
          break;

        case 'hitl.request':
          setState('alert');
          addHitl(e);
          break;

        case 'hitl.resolved':
          setState('thinking');
          break;

        case 'run.end':
          // 用后端聚合后的最终答案收尾（含校验说明与 HITL 修正）。
          // 无论之前有没有流式气泡，都保证最后呈现的是"定稿"。
          if (e.final_answer) {
            if (!currentAi) addAi('');
            currentText = e.final_answer;
            flushAi();
          }
          finishAi();
          setState('happy');
          setRunning(false);
          setTimeout(function () {
            if (!running && !panel.classList.contains('psa-open')) setBadge(1);
          }, 400);
          break;

        case 'error':
          setState('sad');
          finishAi();
          clearEmpty();
          body.appendChild(
            el('div', { class: 'psa-msg psa-msg-ai', style: 'color:#b91c1c', text: '⚠️ ' + (e.message || '出错了') })
          );
          setRunning(false);
          scrollDown();
          break;

        default:
          break;
      }
    }

    function send() {
      var q = (input.value || '').trim();
      if (!q || running) return;

      addUser(q);
      setInput('');
      setRunning(true);
      setState('thinking');
      controller = new AbortController();

      gatherContext()
        .catch(function () {
          return null;
        })
        .then(function (pageContext) {
          return PSA.api.chatStream(
            { query: q, sessionId: sessionId(), pageContext: pageContext },
            handleEvent,
            controller.signal
          );
        })
        .catch(function (err) {
          if (err && err.name === 'AbortError') return;
          setState('sad');
          finishAi();
          body.appendChild(
            el('div', {
              class: 'psa-msg psa-msg-ai',
              style: 'color:#b91c1c',
              text: '⚠️ 请求失败：' + (err && err.message ? err.message : err),
            })
          );
          scrollDown();
        })
        .finally(function () {
          setRunning(false);
          refreshContextBar();
        });
    }

    function resolveHitl(action, text) {
      if (!lastRunId) return;
      var cards = body.querySelectorAll('.psa-hitl');
      if (cards.length) cards[cards.length - 1].remove();
      setRunning(true);
      setState('thinking');
      PSA.api
        .resolveHitl(lastRunId, { action: action, text: text }, handleEvent)
        .catch(function (err) {
          setState('sad');
          body.appendChild(
            el('div', { class: 'psa-msg psa-msg-ai', style: 'color:#b91c1c', text: '⚠️ ' + err.message })
          );
        })
        .finally(function () {
          setRunning(false);
        });
    }

    /* ---- 输入事件 ---- */
    sendBtn.addEventListener('click', send);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    });
    input.addEventListener('input', function () {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });
    document.addEventListener('mouseup', function () {
      setTimeout(refreshQuick, 260);
    });

    /* ---- 空闲 → 睡觉 ---- */
    var idleTimer = null;
    function resetIdle() {
      if (idleTimer) clearTimeout(idleTimer);
      if (running) return;
      idleTimer = setTimeout(function () {
        if (!running) setState('sleeping');
      }, 90000);
    }
    ['pointerdown', 'keydown', 'mousemove'].forEach(function (ev) {
      document.addEventListener(ev, function () {
        if (avatarLauncher.getState() === 'sleeping') setState('idle');
        resetIdle();
      }, true);
    });

    /* ---- 尺寸变化 ---- */
    var onResize = function () {
      applyPos();
      positionSelChip();
      avatarLauncher.redraw();
      avatarHead.redraw();
    };
    global.addEventListener('resize', onResize);

    /* ---- 装配 ---- */
    function mount(target) {
      var parent = target || document.body || document.documentElement;
      parent.appendChild(host);
      applyPos();
      updateReadBtn();

      // 识别"当前是不是一个交互动画页面"（本文件直接注入在动画文档里）
      var animInfo = null;
      try {
        animInfo = PSA.animBridge ? PSA.animBridge.detect({ manifest: PSA.__manifest }) : null;
      } catch (e) {
        animInfo = null;
      }
      if (animInfo) {
        animBar.style.display = '';
        refreshAnimBar();
        // 动画页面上，标题直接换成动画名 —— 学生一眼知道助手认出来了
        head.querySelector('.psa-head-text b').textContent =
          '伴学 · ' + (animInfo.title || '交互动画');
        // 学生自己点动画按钮时，同步面板里的状态
        document.addEventListener('click', function () {
          setTimeout(refreshAnimBar, 0);
        }, true);
      }

      refreshQuick();
      setState('idle');
      resetIdle();

      // 后端可达性探测：不可达时直接告诉用户，而不是等他问完才发现
      PSA.api
        .health()
        .then(function (h) {
          if (destroyed) return;
          setState('idle');
          var mode = h.provider && h.provider.resolved === 'mock' ? '演示模式' : '已连接模型';
          statusText.textContent = mode + ' · ' + (h.animations ? h.animations.total + ' 个动画' : '');
        })
        .catch(function () {
          if (destroyed) return;
          setState('offline');
          statusText.textContent = '后端未连接（请确认服务已启动）';
        });

      refreshContextBar();
      if (opts.autoOpen || store(LS.open) === '1') open();
      return api;
    }

    var api = {
      mount: mount,
      open: open,
      close: close,
      toggle: toggle,
      destroy: function () {
        destroyed = true;
        try {
          controller && controller.abort();
        } catch (e) {
          /* 忽略 */
        }
        if (rafPending) global.cancelAnimationFrame(rafPending);
        if (idleTimer) clearTimeout(idleTimer);
        unwatchSelection();
        global.removeEventListener('resize', onResize);
        avatarLauncher.destroy();
        avatarHead.destroy();
        closeAnimation();
        if (host.parentNode) host.parentNode.removeChild(host);
      },
      ask: function (text) {
        open();
        setInput(text);
        send();
      },
      setState: setState,
      setSkin: setSkin,
      getSkin: function () {
        return skin;
      },
      /** 供调试：立刻看一次抽取结果 */
      debugContext: function () {
        return PSA.frames.collectAll();
      },
      get shadowRoot() {
        return root;
      },
    };

    return api;
  }

  PSA.createAssistant = createAssistant;
})(window);

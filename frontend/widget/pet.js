/**
 * 概率论伴学助手 · 形象系统（虚拟页宠 / 极简悬浮球）
 * ================================================
 *
 * 两套皮肤，同一套状态机：
 *   skin = 'pet'   有性格的虚拟页宠，会眨眼、会随 Agent 状态变表情
 *   skin = 'ball'  极简悬浮球，只有呼吸感与状态色
 *
 * 状态由**真实的 Agent 事件**驱动，不是随机动画：
 *   idle      等待中          （无任务）
 *   thinking  某个 Agent 开始工作    ← agent.start
 *   talking   正在流式输出          ← agent.delta
 *   happy     产出了结构化产物       ← artifact
 *   alert     需要你确认（HITL）     ← hitl.request
 *   sad       出错了                ← error
 *   sleeping  长时间无操作            （超过 90 秒）
 *   offline   后端不可达            （健康检查失败）
 *
 * 这层"情绪映射"是本项目演示时最直观的部分：
 * 学生不用看日志，看宠物的表情就知道系统在干什么、是不是需要自己出面。
 *
 * 实现注意（踩过的坑）
 * ------------------
 * - **rAF 循环必须可停**。参考本项目里 markov-chain 动画的教训：
 *   闭包里跑着停不掉的 rAF，页面切走后会一直烧 CPU。这里的 destroy() 会真的取消。
 * - 页面不可见时自动暂停（document.hidden），回来再恢复。
 * - 高分屏用 devicePixelRatio 缩放，否则边缘发虚。
 */
(function (global) {
  'use strict';

  var PSA = (global.__PSA = global.__PSA || {});

  /** 状态 → 主色 + 说明（说明会显示在面板头部） */
  var STATES = {
    idle: { color: '#6366f1', label: '在线，随时问我', scale: 1.0 },
    thinking: { color: '#f59e0b', label: '正在思考…', scale: 1.03 },
    talking: { color: '#4f46e5', label: '正在讲解…', scale: 1.02 },
    happy: { color: '#10b981', label: '已生成结果', scale: 1.05 },
    alert: { color: '#f59e0b', label: '需要你确认一下', scale: 1.06 },
    sad: { color: '#ef4444', label: '出了点问题', scale: 0.97 },
    sleeping: { color: '#94a3b8', label: '睡着了…', scale: 0.96 },
    offline: { color: '#94a3b8', label: '后端未连接', scale: 0.95 },
  };

  function stateOf(name) {
    return STATES[name] || STATES.idle;
  }

  /* ------------------------------------------------------------------ *
   * 绘制基元
   * ------------------------------------------------------------------ */

  /** 圆角矩形路径（兼容没有 roundRect 的浏览器） */
  function roundRect(ctx, x, y, w, h, r) {
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, r);
      return;
    }
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function ellipse(ctx, cx, cy, rx, ry, fill) {
    ctx.beginPath();
    ctx.ellipse(cx, cy, Math.max(rx, 0.1), Math.max(ry, 0.1), 0, 0, Math.PI * 2);
    if (fill) {
      ctx.fillStyle = fill;
      ctx.fill();
    }
  }

  /* ------------------------------------------------------------------ *
   * 页宠绘制（在 100×100 的归一化坐标里画，再整体缩放）
   * ------------------------------------------------------------------ */

  function drawPet(ctx, t, s) {
    var color = s.color;
    var bob = Math.sin(t / 620) * 2.2; // 上下浮动
    var blink = s.blink; // 0..1，1 = 完全闭眼
    var talk = s.talking; // 0..1，嘴巴开合
    var lookUp = s.name === 'thinking';

    // ---- 触角 + 发光点 ----
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.4;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(50, 24 + bob);
    ctx.quadraticCurveTo(52, 12 + bob, 58, 9 + bob);
    ctx.stroke();
    var glowR = 3.4 + Math.sin(t / 300) * 0.9 + (s.name === 'thinking' ? 1.6 : 0);
    ellipse(ctx, 59, 8 + bob, glowR + 3, glowR + 3, hexA(color, 0.22));
    ellipse(ctx, 59, 8 + bob, glowR, glowR, color);

    // ---- 耳朵 ----
    ctx.fillStyle = color;
    ellipse(ctx, 33, 27 + bob, 8, 9);
    ellipse(ctx, 67, 27 + bob, 8, 9);

    // ---- 身体 ----
    var grd = ctx.createLinearGradient(0, 20, 0, 88);
    grd.addColorStop(0, lighten(color, 0.28));
    grd.addColorStop(1, color);
    roundRect(ctx, 18, 26 + bob, 64, 62, 26);
    ctx.fillStyle = grd;
    ctx.fill();

    // 高光
    ellipse(ctx, 38, 40 + bob, 12, 8, hexA('#ffffff', 0.3));

    // ---- 眼睛 ----
    var eyeY = 52 + bob + (lookUp ? -2.5 : 0);
    var eyeOpen = 1 - blink;
    var eyeRx = 5.2;
    var eyeRy = 6 * eyeOpen + 0.6;

    if (s.name === 'happy') eyeRy *= 0.55;
    if (s.name === 'alert') {
      eyeRx *= 1.15;
      eyeRy *= 1.35;
    }
    if (s.name === 'sleeping') {
      // 闭眼画弧
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2.2;
      [-11, 11].forEach(function (dx) {
        ctx.beginPath();
        ctx.arc(50 + dx, eyeY, 5.4, Math.PI * 0.15, Math.PI * 0.85);
        ctx.stroke();
      });
    } else {
      ellipse(ctx, 39, eyeY, eyeRx, eyeRy, '#ffffff');
      ellipse(ctx, 61, eyeY, eyeRx, eyeRy, '#ffffff');
      if (eyeOpen > 0.25) {
        var pupilY = eyeY + (lookUp ? -1.2 : 0.4);
        ellipse(ctx, 39 + (lookUp ? 0.8 : 0), pupilY, 2.5, 2.9 * eyeOpen, '#1e293b');
        ellipse(ctx, 61 + (lookUp ? 0.8 : 0), pupilY, 2.5, 2.9 * eyeOpen, '#1e293b');
        // 眼神光
        ellipse(ctx, 40.2, pupilY - 1.2, 0.9, 0.9, 'rgba(255,255,255,.85)');
        ellipse(ctx, 62.2, pupilY - 1.2, 0.9, 0.9, 'rgba(255,255,255,.85)');
      }
    }

    // ---- 腮红 ----
    if (s.name === 'happy' || s.name === 'talking') {
      ellipse(ctx, 28, 62 + bob, 5.5, 3.4, hexA('#fb7185', 0.35));
      ellipse(ctx, 72, 62 + bob, 5.5, 3.4, hexA('#fb7185', 0.35));
    }

    // ---- 嘴巴 ----
    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 2.1;
    ctx.lineCap = 'round';
    var my = 66 + bob;
    if (s.name === 'happy') {
      ctx.beginPath();
      ctx.arc(50, my - 3, 8, Math.PI * 0.15, Math.PI * 0.85);
      ctx.stroke();
    } else if (s.name === 'talking' || s.name === 'thinking') {
      var open = s.name === 'talking' ? 1.2 + talk * 4.2 : 1.0 + Math.sin(t / 420) * 0.7;
      ellipse(ctx, 50, my + 1, 4.2, open, '#1e293b');
    } else if (s.name === 'sad') {
      ctx.beginPath();
      ctx.arc(50, my + 7, 7, Math.PI * 1.15, Math.PI * 1.85);
      ctx.stroke();
    } else if (s.name === 'alert') {
      ellipse(ctx, 50, my + 1, 3.4, 2.8, '#1e293b');
    } else {
      ctx.beginPath();
      ctx.arc(50, my - 2, 6, Math.PI * 0.2, Math.PI * 0.8);
      ctx.stroke();
    }

    // ---- 状态装饰 ----
    if (s.name === 'thinking') {
      // 头顶飘动的思考点
      for (var i = 0; i < 3; i++) {
        var ph = (t / 380 + i * 0.6) % 3;
        var a = ph < 2 ? 0.85 - Math.abs(ph - 1) * 0.6 : 0;
        ellipse(ctx, 76 + i * 7, 30 + bob - ph * 5, 2.4, 2.4, hexA(color, Math.max(a, 0)));
      }
    } else if (s.name === 'alert') {
      // 感叹号
      ctx.fillStyle = '#f59e0b';
      roundRect(ctx, 82, 26 + bob, 3.6, 11, 1.8);
      ctx.fill();
      ellipse(ctx, 83.8, 41 + bob, 2.1, 2.1, '#f59e0b');
    } else if (s.name === 'happy') {
      // 闪光
      var sp = (Math.sin(t / 260) + 1) / 2;
      star(ctx, 83, 32 + bob, 4 + sp * 1.6, hexA('#fbbf24', 0.9));
    } else if (s.name === 'sleeping') {
      // Z z z
      ctx.fillStyle = hexA('#94a3b8', 0.85);
      ctx.font = 'bold 11px system-ui, sans-serif';
      var z = ((t / 900) % 1);
      ctx.fillText('z', 78, 30 + bob - z * 10);
      ctx.font = 'bold 8px system-ui, sans-serif';
      ctx.fillText('z', 86, 22 + bob - z * 8);
    }
  }

  function star(ctx, cx, cy, r, fill) {
    ctx.beginPath();
    for (var i = 0; i < 8; i++) {
      var ang = (Math.PI / 4) * i - Math.PI / 2;
      var rr = i % 2 === 0 ? r : r * 0.4;
      var fn = i === 0 ? 'moveTo' : 'lineTo';
      ctx[fn](cx + Math.cos(ang) * rr, cy + Math.sin(ang) * rr);
    }
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
  }

  /* ------------------------------------------------------------------ *
   * 极简悬浮球
   * ------------------------------------------------------------------ */

  function drawBall(ctx, t, s) {
    var breathe = 1 + Math.sin(t / 900) * 0.035;
    var r = 34 * breathe;

    // 外圈脉冲（运行中更明显）
    if (s.name === 'thinking' || s.name === 'talking' || s.name === 'alert') {
      var p = (t / 1100) % 1;
      ctx.beginPath();
      ctx.arc(50, 50, r + p * 16, 0, Math.PI * 2);
      ctx.strokeStyle = hexA(s.color, 0.32 * (1 - p));
      ctx.lineWidth = 2.4;
      ctx.stroke();
    }

    var grd = ctx.createLinearGradient(20, 18, 80, 84);
    grd.addColorStop(0, lighten(s.color, 0.34));
    grd.addColorStop(1, darken(s.color, 0.1));
    ctx.beginPath();
    ctx.arc(50, 50, r, 0, Math.PI * 2);
    ctx.fillStyle = grd;
    ctx.fill();

    // 玻璃高光
    ctx.beginPath();
    ctx.ellipse(38, 36, 13, 9, -0.5, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255,255,255,.34)';
    ctx.fill();

    // 中央字符
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 30px "Times New Roman", Georgia, serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('π', 50, 52);

    if (s.name === 'alert') {
      ellipse(ctx, 76, 24, 5.2, 5.2, '#f59e0b');
      ctx.fillStyle = '#fff';
      ctx.font = 'bold 9px system-ui, sans-serif';
      ctx.fillText('!', 76, 25);
    }
  }

  /* ------------------------------------------------------------------ *
   * 颜色工具
   * ------------------------------------------------------------------ */

  function parseHex(c) {
    var m = /^#?([0-9a-f]{6})$/i.exec(String(c));
    if (!m) return { r: 99, g: 102, b: 241 };
    var n = parseInt(m[1], 16);
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
  }

  function toHex(o) {
    function h(v) {
      var s = Math.max(0, Math.min(255, Math.round(v))).toString(16);
      return s.length === 1 ? '0' + s : s;
    }
    return '#' + h(o.r) + h(o.g) + h(o.b);
  }

  function lighten(c, amt) {
    var o = parseHex(c);
    return toHex({
      r: o.r + (255 - o.r) * amt,
      g: o.g + (255 - o.g) * amt,
      b: o.b + (255 - o.b) * amt,
    });
  }

  function darken(c, amt) {
    var o = parseHex(c);
    return toHex({ r: o.r * (1 - amt), g: o.g * (1 - amt), b: o.b * (1 - amt) });
  }

  function hexA(c, a) {
    var o = parseHex(c);
    return 'rgba(' + o.r + ',' + o.g + ',' + o.b + ',' + a + ')';
  }

  /* ------------------------------------------------------------------ *
   * 头像实例
   * ------------------------------------------------------------------ */

  /**
   * 创建一个头像（页宠或悬浮球），绑定到给定 canvas。
   * @param {HTMLCanvasElement} canvas
   * @param {{skin?:'pet'|'ball'}} [opts]
   */
  function createAvatar(canvas, opts) {
    opts = opts || {};
    var skin = opts.skin === 'ball' ? 'ball' : 'pet';
    var stateName = 'idle';
    var raf = 0;
    var destroyed = false;
    var start = (global.performance || Date).now();
    var nextBlink = start + 2600 + Math.random() * 2600;
    var blinkUntil = 0;

    function now() {
      return (global.performance || Date).now();
    }

    function frame() {
      if (destroyed) return;
      var t = now() - start;

      // 眨眼调度
      if (t > nextBlink && t > blinkUntil) {
        blinkUntil = t + 150;
        nextBlink = t + 2400 + Math.random() * 3200;
      }
      var blink = t < blinkUntil ? 1 : 0;

      var st = stateOf(stateName);
      var ctx = canvas.getContext('2d');
      if (!ctx) return;

      var rect = canvas.getBoundingClientRect();
      var cssW = Math.max(rect.width || canvas.clientWidth || 64, 24);
      var cssH = Math.max(rect.height || canvas.clientHeight || 64, 24);
      var dpr = global.devicePixelRatio || 1;

      if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
        canvas.width = Math.round(cssW * dpr);
        canvas.height = Math.round(cssH * dpr);
      }

      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // 缩放到统一的 100×100 设计坐标
      var side = Math.min(cssW, cssH);
      var scale = (side / 100) * (st.scale || 1) * dpr;
      ctx.setTransform(
        scale,
        0,
        0,
        scale,
        (canvas.width - 100 * scale) / 2,
        (canvas.height - 100 * scale) / 2
      );
      ctx.lineJoin = 'round';

      var s = {
        name: stateName,
        color: st.color,
        blink: blink,
        talking: (Math.sin(t / 95) + 1) / 2,
      };

      if (skin === 'ball') drawBall(ctx, t, s);
      else drawPet(ctx, t, s);

      raf = global.requestAnimationFrame(frame);
    }

    function startLoop() {
      if (destroyed || raf) return;
      raf = global.requestAnimationFrame(frame);
    }

    function stopLoop() {
      if (raf) {
        global.cancelAnimationFrame(raf);
        raf = 0;
      }
    }

    // 页面不可见时暂停，避免后台空烧 CPU
    function onVisibility() {
      if (document.hidden) stopLoop();
      else startLoop();
    }
    document.addEventListener('visibilitychange', onVisibility);
    startLoop();

    return {
      setState: function (name) {
        if (STATES[name]) stateName = name;
        return stateName;
      },
      getState: function () {
        return stateName;
      },
      getLabel: function () {
        return stateOf(stateName).label;
      },
      setSkin: function (next) {
        skin = next === 'ball' ? 'ball' : 'pet';
      },
      getSkin: function () {
        return skin;
      },
      /** 立刻重绘一帧（例如尺寸变化后） */
      redraw: function () {
        if (!destroyed) {
          stopLoop();
          frame();
        }
      },
      destroy: function () {
        destroyed = true;
        stopLoop();
        document.removeEventListener('visibilitychange', onVisibility);
      },
    };
  }

  PSA.pet = {
    createAvatar: createAvatar,
    STATES: STATES,
    _internals: { drawPet: drawPet, drawBall: drawBall, lighten: lighten },
  };
})(window);

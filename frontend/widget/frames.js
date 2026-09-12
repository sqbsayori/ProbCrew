/**
 * 概率论伴学助手 · 跨 frame 上下文汇总
 * =====================================
 *
 * 为什么必须有这一层
 * ----------------
 * 智慧树这类平台的课件**大量嵌套在 iframe 里**，而且正文通常不在顶层页面：
 * 顶层只是一个导航壳，真正的课件在 `iframe.courseware` 里。
 * 浏览器安全策略不允许顶层脚本读取跨域 iframe 的 DOM —— 读不到正文，
 * 助手就会退化成"只会查教材的聊天框"，整个产品价值就没了。
 *
 * 解决办法
 * -------
 * 油猴脚本默认会在**所有 frame**里各注入一份助手（`@match` + "在所有框架中运行"）。
 * 于是：
 *   - 每个 frame 自己抽取自己的内容（同源，随便读）；
 *   - 用 `postMessage` 把结果**上报**给父框架（跨域也能用）；
 *   - 顶层把所有 frame 的内容汇总、去重、按内容丰富度排序。
 *
 * 递归：如果某个 iframe 自己还嵌了 iframe（平台常见），
 * 它被请求时会先向自己的子框架收集一轮，再一并回复 —— 整棵树都覆盖到。
 *
 * 安全性
 * -----
 * 因为跨域，`targetOrigin` 只能用 `'*'`，所以靠一个私有 magic key 做识别，
 * 并且**只回传给发消息的那一方**（`event.source`），不做广播。
 * 这个通道只传输页面公开可见的文本，不涉及 cookie / 凭证。
 */
(function (global) {
  'use strict';

  var PSA = (global.__PSA = global.__PSA || {});

  var REQ = '__psa_context_request__';
  var REP = '__psa_context_reply__';

  /** 单个提示词的等待时限（毫秒）。太短会漏掉慢的 frame。 */
  var REPLY_TIMEOUT = 420;

  function isTop() {
    try {
      return global.top === global.self;
    } catch (e) {
      return false; // 跨域访问 top 抛异常 → 说明自己在 iframe 里
    }
  }

  /** 拿到所有直接子 iframe 的 window（跨域也能拿到引用） */
  function childWindows() {
    var out = [];
    var frames = document.querySelectorAll('iframe, frame');
    for (var i = 0; i < frames.length; i++) {
      try {
        if (frames[i].contentWindow) out.push(frames[i].contentWindow);
      } catch (e) {
        /* 忽略 */
      }
    }
    return out;
  }

  /** 向所有子 frame 要内容，收集 timeout 毫秒 */
  function askChildren(token) {
    var targets = childWindows();
    if (!targets.length) return Promise.resolve([]);

    return new Promise(function (resolve) {
      var collected = [];

      function onReply(ev) {
        var d = ev.data;
        if (!d || d[REP] !== token) return;
        if (Array.isArray(d.frames)) {
          collected = collected.concat(d.frames);
        } else if (d.frame) {
          collected.push(d.frame);
        }
      }

      global.addEventListener('message', onReply);
      for (var i = 0; i < targets.length; i++) {
        try {
          targets[i].postMessage({ __psa: REQ, [REQ]: token }, '*');
        } catch (e) {
          /* 某些沙箱 iframe 会拒绝 postMessage，跳过 */
        }
      }
      setTimeout(function () {
        global.removeEventListener('message', onReply);
        resolve(collected);
      }, REPLY_TIMEOUT);
    });
  }

  /**
   * 在**非顶层** frame 里安装应答器。
   * 顶层不需要它（顶层直接自己抽取）。
   */
  function installResponder() {
    if (isTop()) return;

    global.addEventListener('message', function (ev) {
      var d = ev.data;
      if (!d || typeof d !== 'object') return;
      var token = d[REQ];
      if (!token) return;

      var payloads = [];

      // 先递归问自己的孩子（如果有）
      askChildren(token).then(function (childrenFrames) {
        // 自己这一份
        try {
          if (PSA.extractor) payloads.push(PSA.extractor.extractContext({ includeSelection: true }));
        } catch (e) {
          /* 忽略 */
        }
        payloads = payloads.concat(childrenFrames);

        try {
          ev.source.postMessage({ __psa: REP, [REP]: token, frames: payloads }, '*');
        } catch (e) {
          /* 忽略 */
        }
      });
    });
  }

  /**
   * 顶层调用：拿到"本 frame + 所有后代 frame"的上下文集合。
   * @returns {Promise<object[]>}
   */
  function collectAll() {
    var own = [];
    try {
      if (PSA.extractor) own.push(PSA.extractor.extractContext({ includeSelection: true }));
    } catch (e) {
      /* 忽略 */
    }
    var token = 'tk_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    return askChildren(token).then(function (childrenFrames) {
      return own.concat(childrenFrames);
    });
  }

  PSA.frames = {
    isTop: isTop,
    installResponder: installResponder,
    collectAll: collectAll,
    _internals: { childWindows: childWindows, REQ: REQ, REP: REP },
  };
})(window);

/**
 * 概率论伴学助手 · API 客户端
 * ============================
 *
 * 这是 widget 命名空间（`window.__PSA`）的一个子模块。
 * 写成"经典脚本 + 全局命名空间"而不是 ESM，是因为它需要能被
 * **油猴脚本的 `@require`** 直接加载（`@require` 不支持 ESM）。
 *
 * 全站唯一的网络出口。所有 URL 都经过 `base` 前缀，
 * 因为助手可能被注入到任意第三方课程平台上（跨域访问我们的后端）。
 */
(function (global) {
  'use strict';

  var PSA = (global.__PSA = global.__PSA || {});

  var config = {
    /** 后端根地址，例如 "http://127.0.0.1:8000"。空串 = 同源。 */
    base: '',
    /** 请求超时（毫秒） */
    timeout: 30000,
  };

  function configure(opts) {
    opts = opts || {};
    if (typeof opts.base === 'string') {
      config.base = opts.base.replace(/\/+$/, '');
    }
    if (opts.timeout) config.timeout = opts.timeout;
    return config;
  }

  function url(path) {
    if (/^https?:\/\//i.test(path)) return path;
    return config.base + path;
  }

  /** 普通 JSON 请求 */
  function json(path, options) {
    options = options || {};
    var ctrl = new AbortController();
    var timer = setTimeout(function () {
      ctrl.abort();
    }, config.timeout);
    return fetch(url(path), {
      method: options.method || 'GET',
      headers: { 'Content-Type': 'application/json' },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: options.signal || ctrl.signal,
    })
      .then(function (res) {
        if (!res.ok) {
          return res
            .json()
            .catch(function () {
              return {};
            })
            .then(function (data) {
              throw new Error(data.detail || res.status + ' ' + res.statusText);
            });
        }
        return res.json();
      })
      .finally(function () {
        clearTimeout(timer);
      });
  }

  /**
   * 读取 SSE 流。
   * 协议：每条事件是 `data: <json>`，以空行分隔（见 contracts/events.schema.json）。
   */
  function consumeSSE(res, onEvent, signal) {
    var reader = res.body.getReader();
    var decoder = new TextDecoder('utf-8');
    var buffer = '';

    function pump() {
      return reader.read().then(function (r) {
        if (r.done) return undefined;
        buffer += decoder.decode(r.value, { stream: true });
        var idx;
        while ((idx = buffer.indexOf('\n\n')) >= 0) {
          var frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          var lines = frame.split('\n');
          for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            if (line.indexOf('data:') !== 0) continue;
            var raw = line.slice(5).trim();
            if (!raw || raw === '{}') continue;
            try {
              onEvent(JSON.parse(raw));
            } catch (e) {
              console.warn('[PSA] 事件解析失败', raw, e);
            }
          }
        }
        if (signal && signal.aborted) return undefined;
        return pump();
      });
    }

    return pump().finally(function () {
      try {
        reader.cancel();
      } catch (e) {
        /* 忽略 */
      }
    });
  }

  function openSSE(path, body, onEvent, signal) {
    return fetch(url(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: signal,
    }).then(function (res) {
      if (!res.ok || !res.body) {
        return res
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            throw new Error(data.detail || res.status + ' ' + res.statusText);
          });
      }
      return consumeSSE(res, onEvent, signal);
    });
  }

  PSA.api = {
    configure: configure,
    getConfig: function () {
      return { base: config.base, timeout: config.timeout };
    },
    url: url,

    /** 后端是否可达（用于在悬浮球上显示离线状态） */
    health: function () {
      return json('/api/health');
    },

    /**
     * 发起一次带页面上下文的提问。
     * @param {{query:string, sessionId:string, pageContext?:object}} params
     * @param {(e:object)=>void} onEvent
     * @param {AbortSignal} [signal]
     */
    chatStream: function (params, onEvent, signal) {
      return openSSE(
        '/api/chat/stream',
        {
          query: params.query,
          session_id: params.sessionId || 'anonymous',
          page_context: params.pageContext || null,
        },
        onEvent,
        signal
      );
    },

    /** 人机协同：确认 / 修正 / 补充后从断点继续 */
    resolveHitl: function (runId, decision, onEvent, signal) {
      return openSSE(
        '/api/hitl/' + encodeURIComponent(runId) + '/resolve',
        { action: decision.action, text: decision.text || '' },
        onEvent,
        signal
      );
    },

    /** 按知识点推荐交互动画 */
    recommendAnimations: function (query, topK) {
      return json('/api/animations/recommend', {
        method: 'POST',
        body: { query: query, top_k: topK || 2 },
      });
    },
  };
})(window);

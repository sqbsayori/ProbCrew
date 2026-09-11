/**
 * 概率论伴学助手 · 渲染（Markdown + 公式）
 * ========================================
 *
 * 为什么 widget 自带一份渲染器，而不复用 SPA 的 ESM 组件：
 * 1. 油猴脚本的 `@require` **不支持 ESM**，widget 必须是经典脚本；
 * 2. 目标课程平台的 CSP 可能禁止动态 `import()`，靠 import 会直接失效；
 * 3. 体积可控：这里只需要一个 Markdown 子集 + 把公式交给 KaTeX。
 *
 * KaTeX 的处理是本文件的关键点：
 * - KaTeX 的 JS 注入宿主页面 `<head>`（全局只注入一次）；
 * - 但 **CSS 必须注入 Shadow Root 内部** —— 文档里的样式表不会穿透
 *   Shadow 边界，这是最容易踩的坑：JS 加载成功、公式却是裸 HTML。
 */
(function (global) {
  'use strict';

  var PSA = (global.__PSA = global.__PSA || {});

  var katexState = { loading: null, ok: false };

  /* ------------------------------------------------------------------ *
   * 转义
   * ------------------------------------------------------------------ */

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* ------------------------------------------------------------------ *
   * Markdown 子集
   * ------------------------------------------------------------------ */

  var PLACEHOLDER = '\u0000';

  /**
   * 归一化 LaTeX 定界符。
   *
   * 不同的模型习惯不同：DeepSeek / GPT 常输出 `\(...\)` 与 `\[...\]`，
   * 而我们的渲染器（以及绝大多数 Markdown 数学语法）只认 `$...$` 与 `$$...$$`。
   * 不归一化的话，界面上会直接显示 `\(A_i\)` 这样的原始代码 —— 非常难看。
   *
   * 这一步放在**渲染器**而不是 Prompt 里，是为了防御任何模型的任何习惯。
   * Prompt 里同时也会明确要求 `$` 定界符（双保险）。
   */
  function normalizeMath(text) {
    return String(text == null ? '' : text)
      .replace(/\\\[([\s\S]+?)\\\]/g, function (_m, body) {
        return '$$' + body + '$$';
      })
      .replace(/\\\(([\s\S]+?)\\\)/g, function (_m, body) {
        return '$' + body + '$';
      });
  }

  function inline(raw) {
    var tokens = [];
    var s = normalizeMath(raw);

    // 1) 先把公式摘出来，避免被后续的 * _ 等规则破坏
    s = s.replace(/\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g, function (_m, block, inl) {
      tokens.push({ display: !!block, tex: String(block != null ? block : inl).trim() });
      return PLACEHOLDER + (tokens.length - 1) + PLACEHOLDER;
    });

    // 2) 转义，防 XSS（内容来自模型，不可信）
    s = esc(s);

    // 3) 行内代码
    s = s.replace(/`([^`]+)`/g, function (_m, c) {
      return '<code class="psa-code">' + c + '</code>';
    });

    // 4) 链接（只放行 http/https/相对路径）
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (m, text, href) {
      if (!/^(https?:|\/|#|\.)/i.test(href)) return m;
      var ext = /^https?:/i.test(href) ? ' target="_blank" rel="noopener noreferrer"' : '';
      return '<a href="' + href + '"' + ext + '>' + text + '</a>';
    });

    // 5) 粗体 / 斜体
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*\w])\*([^*\n]+)\*/g, '$1<em>$2</em>');

    // 6) 还原公式占位符
    var re = new RegExp(PLACEHOLDER + '(\\d+)' + PLACEHOLDER, 'g');
    s = s.replace(re, function (_m, i) {
      var t = tokens[Number(i)];
      if (!t) return '';
      var cls = t.display ? 'psa-math-block' : 'psa-math-inline';
      return '<span class="' + cls + '" data-tex="' + esc(t.tex) + '"></span>';
    });

    return s;
  }

  function isTableSep(line) {
    return /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line) && line.indexOf('-') >= 0;
  }

  /** Markdown → HTML 字符串 */
  function md(text) {
    var lines = normalizeMath(text).replace(/\r\n?/g, '\n').split('\n');
    var out = [];
    var para = [];
    var i = 0;

    function flush() {
      if (para.length) out.push('<p>' + inline(para.join(' ')) + '</p>');
      para = [];
    }

    while (i < lines.length) {
      var line = lines[i];

      if (!line.trim()) {
        flush();
        i++;
        continue;
      }

      // 独立公式
      var bm = /^\s*\$\$(.+?)\$\$\s*$/.exec(line);
      if (bm) {
        flush();
        out.push('<span class="psa-math-block" data-tex="' + esc(bm[1].trim()) + '"></span>');
        i++;
        continue;
      }

      // 分隔线
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        flush();
        out.push('<hr>');
        i++;
        continue;
      }

      // 标题
      var hd = /^(#{1,4})\s+(.*)$/.exec(line);
      if (hd) {
        flush();
        var lv = hd[1].length;
        out.push('<h' + lv + '>' + inline(hd[2]) + '</h' + lv + '>');
        i++;
        continue;
      }

      // 表格
      if (line.indexOf('|') >= 0 && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        flush();
        var cells = function (row) {
          return row
            .replace(/^\s*\|/, '')
            .replace(/\|\s*$/, '')
            .split('|')
            .map(function (c) {
              return c.trim();
            });
        };
        var head = cells(line);
        i += 2;
        var rows = [];
        while (i < lines.length && lines[i].indexOf('|') >= 0 && lines[i].trim()) {
          rows.push(cells(lines[i]));
          i++;
        }
        out.push(
          '<table class="psa-table"><thead><tr>' +
            head
              .map(function (c) {
                return '<th>' + inline(c) + '</th>';
              })
              .join('') +
            '</tr></thead><tbody>' +
            rows
              .map(function (r) {
                return (
                  '<tr>' +
                  r
                    .map(function (c) {
                      return '<td>' + inline(c) + '</td>';
                    })
                    .join('') +
                  '</tr>'
                );
              })
              .join('') +
            '</tbody></table>'
        );
        continue;
      }

      // 引用
      if (/^\s*>\s?/.test(line)) {
        flush();
        var quote = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
          quote.push(lines[i].replace(/^\s*>\s?/, ''));
          i++;
        }
        out.push('<blockquote>' + inline(quote.join(' ')) + '</blockquote>');
        continue;
      }

      // 有序列表
      if (/^\s*\d+[.)]\s+/.test(line)) {
        flush();
        var oitems = [];
        while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
          oitems.push(lines[i].replace(/^\s*\d+[.)]\s+/, ''));
          i++;
        }
        out.push(
          '<ol>' +
            oitems
              .map(function (t) {
                return '<li>' + inline(t) + '</li>';
              })
              .join('') +
            '</ol>'
        );
        continue;
      }

      // 无序列表
      if (/^\s*[-*+]\s+/.test(line)) {
        flush();
        var uitems = [];
        while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
          uitems.push(lines[i].replace(/^\s*[-*+]\s+/, ''));
          i++;
        }
        out.push(
          '<ul>' +
            uitems
              .map(function (t) {
                return '<li>' + inline(t) + '</li>';
              })
              .join('') +
            '</ul>'
        );
        continue;
      }

      para.push(line.trim());
      i++;
    }

    flush();
    return out.join('\n');
  }

  /* ------------------------------------------------------------------ *
   * KaTeX
   * ------------------------------------------------------------------ */

  /** 把 KaTeX 的 JS 注入宿主页面（全局一次）。CSS 见 injectStyles()。 */
  function load(base) {
    if (katexState.loading) return katexState.loading;
    if (global.katex) {
      katexState.ok = true;
      return Promise.resolve(true);
    }
    var prefix = (base || '').replace(/\/+$/, '');
    katexState.loading = new Promise(function (resolve) {
      var s = document.createElement('script');
      s.src = prefix + '/vendor/katex/katex.min.js';
      s.async = true;
      s.onload = function () {
        katexState.ok = !!global.katex;
        resolve(katexState.ok);
      };
      s.onerror = function () {
        console.warn('[PSA] KaTeX 加载失败，公式将以源码形式显示');
        katexState.ok = false;
        resolve(false);
      };
      document.head.appendChild(s);
    });
    return katexState.loading;
  }

  /**
   * 把 KaTeX 的 CSS 注入 Shadow Root。
   *
   * ⚠️ 这一步不能省：Shadow DOM 的样式隔离是双向的，
   * 宿主文档 <head> 里的样式表**不会**作用到 Shadow 内部。
   * 漏掉它会导致"JS 加载成功、公式渲染成裸 HTML"。
   */
  function injectStyles(shadowRoot, base) {
    var prefix = (base || '').replace(/\/+$/, '');
    ['/vendor/katex/katex.min.css', '/widget/widget.css'].forEach(function (p) {
      var link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = prefix + p;
      shadowRoot.appendChild(link);
    });
  }

  /** 把 root 内的公式占位符渲染成真公式 */
  function mathIn(root) {
    if (!root || !root.querySelectorAll) return;
    var nodes = root.querySelectorAll('.psa-math-inline, .psa-math-block');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var tex = el.getAttribute('data-tex') || '';
      if (global.katex) {
        try {
          el.innerHTML = global.katex.renderToString(tex, {
            displayMode: el.classList.contains('psa-math-block'),
            throwOnError: false,
            errorColor: '#ef4444',
            strict: 'ignore',
            trust: false,
          });
          continue;
        } catch (e) {
          /* 落到下面的降级分支 */
        }
      }
      // 降级：显示源码（仍然可读、可复制）
      el.innerHTML =
        '<code class="psa-tex-fallback" title="公式渲染器不可用">' + esc(tex) + '</code>';
    }
  }

  /** 一步到位：把 Markdown 写进元素并渲染公式 */
  function into(el, text) {
    if (!el) return;
    el.innerHTML = md(text);
    mathIn(el);
  }

  PSA.render = {
    esc: esc,
    md: md,
    into: into,
    mathIn: mathIn,
    load: load,
    injectStyles: injectStyles,
    isKatexReady: function () {
      return !!global.katex;
    },
  };
})(window);

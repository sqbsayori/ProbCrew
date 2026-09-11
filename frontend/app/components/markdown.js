/**
 * 极简 Markdown 渲染器（含 LaTeX 公式占位）。
 *
 * 为什么自己写：为了免构建 + 零依赖 + 可离线。
 * 只实现我们真正用到的语法（后端 Prompt 也按这个子集约束输出）：
 *   标题 # ## ###、分隔线 ---、引用 >、无序/有序列表、表格、粗体、斜体、
 *   行内代码、链接、公式 $...$ 与 $$...$$。
 *
 * 公式不会被立刻渲染，而是留成占位符，由 katex.js 的 renderMathIn() 填充。
 * 这样"流式输出过程中反复重渲染"也不会闪断。
 */
import { esc } from '../core/dom.js';

const PLACEHOLDER = '\u0000';

/**
 * 归一化 LaTeX 定界符。
 *
 * 不同模型习惯不同：DeepSeek / GPT 常输出 `\(...\)` 与 `\[...\]`，
 * 而本渲染器只认 `$...$` 与 `$$...$$`。不归一化就会在界面上显示原始代码。
 * 放在渲染器而不是 Prompt 里，是为了防御任何模型的任何习惯（Prompt 里也会要求，双保险）。
 */
export function normalizeMath(text) {
  return String(text ?? '')
    .replace(/\\\[([\s\S]+?)\\\]/g, (_m, body) => `$$${body}$$`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_m, body) => `$${body}$`);
}

/** 行内解析：公式、代码、链接、粗斜体 */
export function inline(raw) {
  const tokens = [];

  // 1) 先把公式抽出来保护起来（否则 * _ \ 会被后续规则破坏）
  let s = normalizeMath(raw).replace(
    /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g,
    (_m, block, inl) => {
      tokens.push({ display: Boolean(block), tex: (block ?? inl).trim() });
      return `${PLACEHOLDER}${tokens.length - 1}${PLACEHOLDER}`;
    }
  );

  // 2) 转义，防止 XSS
  s = esc(s);

  // 3) 行内代码
  s = s.replace(/`([^`]+)`/g, (_m, c) => `<code class="mono">${c}</code>`);

  // 4) 链接（只允许 http/https/相对路径）
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, text, url) => {
    if (!/^(https?:|\/|#|\.)/i.test(url)) return m;
    const ext = /^https?:/i.test(url) ? ' target="_blank" rel="noopener"' : '';
    return `<a href="${url}"${ext}>${text}</a>`;
  });

  // 5) 粗体 / 斜体
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*\w])\*([^*\n]+)\*/g, '$1<em>$2</em>');

  // 6) 还原公式为占位 span
  s = s.replace(new RegExp(`${PLACEHOLDER}(\\d+)${PLACEHOLDER}`, 'g'), (_m, i) => {
    const t = tokens[Number(i)];
    if (!t) return '';
    const cls = t.display ? 'math-block' : 'math-inline';
    return `<span class="${cls}" data-tex="${esc(t.tex)}"></span>`;
  });

  return s;
}

/** 判断表格分隔行，如 |---|---| */
const isTableSep = (line) => /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line) && line.includes('-');

/** 把 Markdown 文本转成 HTML 字符串 */
export function markdownToHtml(text) {
  const lines = normalizeMath(text).replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let i = 0;

  const flushParagraph = (buf) => {
    if (buf.length) out.push(`<p>${inline(buf.join(' '))}</p>`);
    buf.length = 0;
  };
  const para = [];

  while (i < lines.length) {
    const line = lines[i];

    // 空行
    if (!line.trim()) {
      flushParagraph(para);
      i += 1;
      continue;
    }

    // 独立公式块（整行 $$...$$）
    const blockMath = /^\s*\$\$(.+?)\$\$\s*$/.exec(line);
    if (blockMath) {
      flushParagraph(para);
      out.push(`<span class="math-block" data-tex="${esc(blockMath[1].trim())}"></span>`);
      i += 1;
      continue;
    }

    // 分隔线
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushParagraph(para);
      out.push('<hr>');
      i += 1;
      continue;
    }

    // 标题
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph(para);
      const level = heading[1].length;
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i += 1;
      continue;
    }

    // 表格
    if (line.includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      flushParagraph(para);
      const cells = (row) =>
        row.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim());
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
        rows.push(cells(lines[i]));
        i += 1;
      }
      out.push(
        `<table class="data"><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead>` +
          `<tbody>${rows
            .map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`)
            .join('')}</tbody></table>`
      );
      continue;
    }

    // 引用
    if (/^\s*>\s?/.test(line)) {
      flushParagraph(para);
      const buf = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ''));
        i += 1;
      }
      out.push(`<blockquote>${inline(buf.join(' '))}</blockquote>`);
      continue;
    }

    // 有序列表
    if (/^\s*\d+[.)]\s+/.test(line)) {
      flushParagraph(para);
      const items = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ''));
        i += 1;
      }
      out.push(`<ol>${items.map((t) => `<li>${inline(t)}</li>`).join('')}</ol>`);
      continue;
    }

    // 无序列表
    if (/^\s*[-*+]\s+/.test(line)) {
      flushParagraph(para);
      const items = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, ''));
        i += 1;
      }
      out.push(`<ul>${items.map((t) => `<li>${inline(t)}</li>`).join('')}</ul>`);
      continue;
    }

    para.push(line.trim());
    i += 1;
  }

  flushParagraph(para);
  return out.join('\n');
}

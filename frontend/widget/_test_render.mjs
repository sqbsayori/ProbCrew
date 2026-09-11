/**
 * 渲染器归一化验证（离线，不需浏览器）
 *
 * 直接加载真实的 widget/render.js，在 Node 里跑它的 Markdown 管线，
 * 验证 `\(...\)` / `\[...\]` 是否被正确归一化为 `$...$` / `$$...$$`。
 *
 * 用法：
 *     cd our-system/frontend
 *     node widget/_test_render.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));

// 构造一个最小的浏览器环境，让 render.js 的 IIFE 能跑起来
const win = { addEventListener() {}, removeEventListener() {} };
win.window = win;
globalThis.window = win;
globalThis.document = {
  createElement: () => ({ setAttribute() {}, style: {}, classList: { add() {}, contains: () => false } }),
  head: { appendChild() {} },
};

// 加载真实模块
const src = readFileSync(join(here, 'render.js'), 'utf8');
new Function('window', 'document', 'console', src)(win, globalThis.document, console);

const { md } = win.__PSA.render;

let pass = 0;
let fail = 0;

function check(name, input, mustContain, mustNotContain = []) {
  const out = md(input);
  const ok =
    mustContain.every((s) => out.includes(s)) && mustNotContain.every((s) => !out.includes(s));
  if (ok) {
    pass += 1;
    console.log(`  ✔ ${name}`);
  } else {
    fail += 1;
    console.log(`  ✘ ${name}`);
    console.log(`      输入: ${JSON.stringify(input)}`);
    console.log(`      输出: ${JSON.stringify(out)}`);
  }
}

console.log('=== LaTeX 定界符归一化 ===');

// 1) 模型常见的 \(...\) 行内写法 → 应变成 $...$ 占位符
check(
  '行内 \\(...\\) → 变成公式占位符',
  '在 \\(B\\) 发生的条件下，成因 \\(A_i\\) 的概率是后验概率。',
  ['class="psa-math-inline"', 'data-tex="B"', 'data-tex="A_i"'],
  ['\\(', '\\)']
);

// 2) 模型常见的 \[...\] 独立公式 → 应变成 $$...$$
check(
  '独立 \\[...\\] → 变成块级公式占位符',
  '公式：\\[ P(A_i\\mid B)=\\frac{P(A_i)P(B\\mid A_i)}{\\sum_j P(A_j)P(B\\mid A_j)} \\]',
  ['class="psa-math-block"', 'P(A_i\\mid B)'],
  ['\\[', '\\]']
);

// 3) 原本就正确的 $...$ / $$...$$ 不能被破坏
check(
  '原有 $...$ 保持可用',
  '已知 $P(B)>0$ 时成立。',
  ['class="psa-math-inline"', 'data-tex="P(B)&gt;0"']
);
check(
  '原有 $$...$$ 保持可用',
  '$$P(A)=\\sum_i P(B_i)P(A\\mid B_i)$$',
  ['class="psa-math-block"', 'P(A)=\\sum_i']
);

// 4) 普通文本不能被误伤
check(
  '普通括号与方括号不受影响',
  '价格是 100 元，折扣 (8折) 与区间 [1,2] 都应原样保留。',
  ['(8折)', '[1,2]'],
  ['psa-math']
);

// 5) 混合场景
check(
  '同一段里混用两种定界符',
  '先看 \\(P(A)\\)，再看 $$P(B)=\\sum_i P(A_i)P(B\\mid A_i)$$，最后 $x^2$。',
  ['data-tex="P(A)"', 'class="psa-math-block"', 'data-tex="x^2"'],
  ['\\(', '\\[']
);

console.log(`\n${pass}/${pass + fail} 通过`);
process.exit(fail ? 1 : 0);

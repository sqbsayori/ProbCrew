/**
 * 共享内核测试（无浏览器，node 直接跑）
 * ====================================
 *
 * 两类断言：
 *
 * **A. 单元**：SSE 分帧的边界、Markdown 归一化、转义、事件常量。
 *    这些是协议层，出错的后果是"事件丢帧/公式变源码/XSS"，必须逐条钉住。
 *
 * **B. ★ 等价性（本文件的核心）**：
 *    同一批输入分别喂给**主站侧**（`app/components/markdown.js`，走 shared）
 *    与**悬浮窗侧**（`widget/_shared.js` 生成产物，走同一份 shared），
 *    输出必须**逐字相同**。
 *    这条红灯就说明"统一技术栈"没做到 —— 它是这次重构的哨兵。
 *
 * 运行：
 *     node frontend/shared/_test_shared.mjs
 */
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(HERE, '..');

let failed = 0;
let passed = 0;

function check(name, fn) {
  try {
    fn();
    passed++;
    console.log(`  ✔ ${name}`);
  } catch (err) {
    failed++;
    console.log(`  ✘ ${name}\n      ${err.message}`);
  }
}

/* ------------------------------------------------------------------ *
 * 加载两侧：主站（ESM 源码）与悬浮窗（生成产物）
 * ------------------------------------------------------------------ */

const appSide = await import(join(FRONTEND, 'app', 'components', 'markdown.js'));
const shared = await import(join(FRONTEND, 'shared', 'markdown.js'));
const sse = await import(join(FRONTEND, 'shared', 'sse.js'));
const text = await import(join(FRONTEND, 'shared', 'text.js'));
const events = await import(join(FRONTEND, 'shared', 'events.js'));

/** 在沙箱里执行生成的经典脚本产物，拿到 __PSA.shared */
function loadWidgetBundle() {
  const src = readFileSync(join(FRONTEND, 'widget', '_shared.js'), 'utf8');
  const sandbox = {};
  // eslint-disable-next-line no-new-func
  new Function('window', src)(sandbox);
  return sandbox.__PSA?.shared;
}
const widgetSide = loadWidgetBundle();

/* ------------------------------------------------------------------ *
 * A. 单元
 * ------------------------------------------------------------------ */

console.log('\n=== A. 共享内核单元 ===');

check('SSE：一帧完整事件', () => {
  const [frames, rest] = sse.splitFrames('data: {"type":"plan"}\n\n');
  if (frames.length !== 1 || rest !== '') throw new Error(`分帧不对：${JSON.stringify([frames, rest])}`);
  const ev = sse.parseFrame(frames[0]);
  if (ev.type !== 'plan') throw new Error('解析结果不对');
});

check('SSE：跨 chunk 截断的帧要能拼回来', () => {
  let buffer = 'data: {"type":"agent.del';
  let [frames] = sse.splitFrames(buffer);
  if (frames.length !== 0) throw new Error('半个帧不该被当成完整帧');
  buffer += 'ta","text":"你好"}\n\n';
  [frames] = sse.splitFrames(buffer);
  if (frames.length !== 1) throw new Error('拼回来之后应该是 1 帧');
  const ev = sse.parseFrame(frames[0]);
  if (ev.text !== '你好') throw new Error('内容不对');
});

check('SSE：连续空行与收尾 {} 帧被忽略', () => {
  const [, rest] = sse.splitFrames('data: {}\n\n\n\n');
  if (sse.parseFrame('data: {}') !== null) throw new Error('{} 应被忽略');
  if (rest !== '') throw new Error('空行应被吃掉');
});

check('SSE：坏 JSON 不抛错（只警告）', () => {
  const ev = sse.parseFrame('data: {不是json');
  if (ev !== null) throw new Error('坏 JSON 应返回 null');
});

check('Markdown：latex 定界符归一化（\\(…\\) 与 $…$ 等价）', () => {
  const a = shared.markdownToHtml('公式 \\(x^2\\) 结束');
  const b = shared.markdownToHtml('公式 $x^2$ 结束');
  if (a !== b) throw new Error('两种定界符没归一化成同一个结果');
  if (!a.includes('class="math-inline"')) throw new Error('没有生成公式占位 span');
});

check('Markdown：XSS 被转义', () => {
  const html = shared.markdownToHtml('<img src=x onerror=alert(1)>');
  if (html.includes('<img')) throw new Error('原始 HTML 没被转义，存在 XSS');
  if (!html.includes('&lt;img')) throw new Error('转义结果不对');
});

check('Markdown：危险链接不被渲染成 <a>', () => {
  const html = shared.markdownToHtml('[点我](javascript:alert(1))');
  if (html.includes('<a ')) throw new Error('javascript: 链接被渲染了');
});

check('转义：五个字符全覆盖', () => {
  const out = text.escapeHtml(`&<>"'`);
  if (out !== '&amp;&lt;&gt;&quot;&#39;') throw new Error(`转义结果不对：${out}`);
});

check('事件常量：数量与契约一致，且覆盖全部类型', () => {
  const contract = JSON.parse(
    readFileSync(join(FRONTEND, '..', 'contracts', 'events.schema.json'), 'utf8')
  );
  const expected = contract.properties.type.enum;
  if (events.EVENT_TYPES.length !== expected.length) {
    throw new Error(`常量 ${events.EVENT_TYPES.length} 种 vs 契约 ${expected.length} 种`);
  }
  for (const t of expected) {
    if (!events.isKnownEventType(t)) throw new Error(`契约里的 ${t} 不在常量里`);
  }
});

/* ------------------------------------------------------------------ *
 * B. 等价性：主站侧 === 悬浮窗侧
 * ------------------------------------------------------------------ */

console.log('\n=== B. 等价性（主站 vs 悬浮窗，逐字对比）===');

const CASES = [
  '# 标题\n\n普通段落，含 **粗体** 与 `code`。',
  '公式 \\(x^2\\) 行内，以及块级：\n\n$$\\int_0^1 x dx$$',
  '| 列 A | 列 B |\n|---|---|\n| 1 | 2 |',
  '> 引用一行\n> 第二行',
  '- 项目 1\n- 项目 2\n\n1. 第一\n2. 第二',
  '<script>alert(1)</script> 与 [链接](https://example.com)',
  '', // 空输入
];

check('主站 markdownToHtml 与悬浮窗产物输出逐字相同', () => {
  for (const c of CASES) {
    const a = appSide.markdownToHtml(c);
    const b = widgetSide.markdownToHtml(c);
    if (a !== b) {
      throw new Error(`输入 ${JSON.stringify(c.slice(0, 24))} 两边输出不同：\n  主站: ${a.slice(0, 80)}\n  悬浮窗: ${b.slice(0, 80)}`);
    }
  }
});

check('悬浮窗产物确实带着共享内核（不是空壳）', () => {
  const need = ['markdownToHtml', 'consumeSSE', 'escapeHtml', 'texToHtml', 'EVENT_TYPES'];
  for (const k of need) {
    if (typeof widgetSide[k] === 'undefined') throw new Error(`产物里缺 ${k}`);
  }
});

check('两侧公式占位类名一致（曾经一个 math-* 一个 psa-math-*）', () => {
  const a = appSide.markdownToHtml('$x$');
  const b = widgetSide.markdownToHtml('$x$');
  if (!a.includes('math-inline') || !b.includes('math-inline')) throw new Error('类名没统一');
  if (a.includes('psa-math') || b.includes('psa-math')) throw new Error('还有旧的 psa- 前缀');
});

/* ------------------------------------------------------------------ */

console.log(
  failed === 0
    ? `\n共享内核测试通过（${passed}/${passed}）`
    : `\n${failed} 项失败（通过 ${passed}）`
);
process.exit(failed === 0 ? 0 : 1);

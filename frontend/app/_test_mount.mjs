/**
 * 前端页面挂载冒烟测试（无浏览器）
 * ==============================
 *
 * 为什么需要它
 * ------------
 * CI 的前端检查只有 `node --check`（语法）和渲染器归一化测试。语法对了
 * 不代表**页面能挂载**：同样一个 `ReferenceError: disposed is not defined`
 * —— 页面能进不能出 —— 语法检查一声不响。
 *
 * 这个脚本用一个最小 DOM 桩，把每个 feature 的 `mount()` / `unmount()`
 * 真跑一遍。它抓不到"样式对不对"，但能抓到"点进去白屏"这一类问题。
 *
 * 真实战绩：第一次跑就抓出 assistant 页 `unmount()` 引用了 mount 内部变量，
 * 离开页面必抛 ReferenceError。
 *
 * 运行
 * ----
 *     node frontend/app/_test_mount.mjs
 *
 * 说明：不 import 任何第三方库，节点 18+ 直接可跑。
 */
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..', '..');

/* ------------------------------------------------------------------ *
 * 最小 DOM 桩
 * ------------------------------------------------------------------ */

class StubNode {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.style = {};
    this.dataset = {};
    this._text = '';
    this.listeners = {};
    const classes = new Set();
    this.classList = {
      add: (...c) => c.forEach((x) => classes.add(x)),
      remove: (...c) => c.forEach((x) => classes.delete(x)),
      toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
      contains: (c) => classes.has(c),
    };
  }
  get className() { return this._cls || ''; }
  set className(v) { this._cls = v; }
  get firstChild() { return this.children[0] || null; }
  /** 注意 setter 会清空子节点 —— 与真实 DOM 行为一致，测试里靠 allText() 读文本 */
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set innerHTML(v) { this._html = String(v); }
  get innerHTML() { return this._html || ''; }
  set src(v) { this.attributes.src = v; }
  get src() { return this.attributes.src || ''; }
  set href(v) { this.attributes.href = v; }
  get href() { return this.attributes.href || ''; }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k]; }
  removeAttribute(k) { delete this.attributes[k]; }
  append(...nodes) {
    for (const n of nodes.flat(Infinity)) {
      if (n == null || n === false) continue;
      const node = n instanceof StubNode ? n : new StubText(String(n));
      node.parentNode = this;
      this.children.push(node);
    }
  }
  appendChild(n) { this.append(n); return n; }
  removeChild(n) {
    const i = this.children.indexOf(n);
    if (i >= 0) this.children.splice(i, 1);
    n.parentNode = null;
    return n;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn);
  }
  dispatchEvent(ev) { for (const fn of this.listeners[ev.type] || []) fn(ev); }
  querySelector() { return null; }
  querySelectorAll(sel) {
    const out = [];
    const walk = (n) => {
      for (const c of n.children) {
        if (!(c instanceof StubNode)) continue;
        if (sel === 'button' && c.tagName === 'BUTTON') out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  /** 整棵子树的文本 —— 用来断言页面确实渲染出了东西 */
  allText() {
    let s = this._text || '';
    for (const c of this.children) s += ' ' + (c.allText ? c.allText() : c._text || '');
    return s;
  }
  /** 统计整棵子树里某种标签的数量 */
  count(tag) {
    let n = this.tagName === String(tag).toUpperCase() ? 1 : 0;
    for (const c of this.children) if (c.count) n += c.count(tag);
    return n;
  }
}

class StubText extends StubNode {
  constructor(t) { super('#text'); this._text = String(t); }
}

const head = new StubNode('head');
const body = new StubNode('body');

globalThis.document = {
  head,
  body,
  documentElement: new StubNode('html'),
  createElement: (t) => new StubNode(t),
  createTextNode: (t) => new StubText(t),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  removeEventListener: () => {},
  execCommand: () => true,
};
globalThis.window = globalThis;
// dom.js 用 `child instanceof Node` 判断，Node 环境下没有这个全局
globalThis.Node = StubNode;
globalThis.HTMLElement = StubNode;
globalThis.isSecureContext = false;
Object.defineProperty(globalThis, 'navigator', { value: { clipboard: null }, configurable: true });
globalThis.location = { href: 'http://127.0.0.1:8000/', reload: () => {}, hash: '' };
globalThis.fetch = () => Promise.reject(new Error('冒烟测试不发网络请求'));
// 页面里大量用 setTimeout 做轮询 / 自动刷新；这里吞掉，避免异步回调影响断言。
// 代价：只验证同步装配路径 —— 这正是"白屏"最常发生的地方。
globalThis.setTimeout = () => 0;
globalThis.clearTimeout = () => {};
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
globalThis.localStorage = {
  _m: new Map(),
  getItem(k) { return this._m.has(k) ? this._m.get(k) : null; },
  setItem(k, v) { this._m.set(k, String(v)); },
  removeItem(k) { this._m.delete(k); },
  clear() { this._m.clear(); },
};

/* ------------------------------------------------------------------ *
 * 从注册表里读 feature 列表（单一事实来源）
 * ------------------------------------------------------------------ */

const registrySrc = readFileSync(join(HERE, 'features.registry.js'), 'utf8');
const features = [];
for (const m of registrySrc.matchAll(/\{"id":\s*"([^"]+)",\s*"dir":\s*"([^"]+)",\s*"title":\s*"([^"]+)"/g)) {
  features.push({ id: m[1], dir: m[2], title: m[3] });
}

if (!features.length) {
  console.error('✘ 没能从 features.registry.js 里解析出任何 feature');
  process.exit(1);
}

console.log(`=== 前端页面挂载冒烟（${features.length} 个页面）===`);

// router 会给 mount() 传第二个参数；照它的形状造一个
const mountCtx = {
  navigate: () => {},
  params: {},
  meta: null,
};

let failed = 0;

for (const f of features) {
  const host = new StubNode('div');
  body.append(host);

  let mod = null;
  try {
    mod = await import(pathToFileURL(join(HERE, 'features', f.dir, 'index.js')).href);
  } catch (err) {
    failed++;
    console.log(`  ✘ ${f.title.padEnd(8)} 模块导入失败：${err.message}`);
    continue;
  }

  if (typeof mod.mount !== 'function') {
    failed++;
    console.log(`  ✘ ${f.title.padEnd(8)} 没有导出 mount()`);
    continue;
  }

  try {
    mod.mount(host, mountCtx);
  } catch (err) {
    failed++;
    console.log(`  ✘ ${f.title.padEnd(8)} mount() 抛错：${err.message}`);
    continue;
  }

  // 渲染出了内容吗？（空 host = 白屏）
  const text = host.allText().trim();
  if (text.length < 10) {
    failed++;
    console.log(`  ✘ ${f.title.padEnd(8)} mount() 后页面几乎没有内容（${text.length} 字）`);
    continue;
  }

  // 能正常卸载吗？
  try {
    mod.unmount?.();
  } catch (err) {
    failed++;
    console.log(`  ✘ ${f.title.padEnd(8)} unmount() 抛错：${err.message}`);
    continue;
  }

  // 页面里不该残留没渲染的 markdown 加粗
  if (text.includes('**')) {
    failed++;
    console.log(`  ✘ ${f.title.padEnd(8)} 文本里有未渲染的 ** 加粗标记`);
    continue;
  }

  console.log(`  ✔ ${f.title.padEnd(8)} mount / unmount 正常（${text.length} 字，${host.count('iframe')} iframe）`);
  host.remove();
}

console.log(failed === 0 ? `\n全部页面通过（${features.length}/${features.length}）` : `\n${failed} 个页面失败`);

/* ------------------------------------------------------------------ *
 * 回归：换页必须回到顶部
 * ------------------------------------------------------------------ *
 * 症状（用户实际报过）：点侧栏「页面助手」，页面直接落在中下部的试玩 iframe 上，
 * 顶部 hero 完全看不见。原因有两个：
 *   1. router.navigate() 从来没有重置过滚动位置；
 *   2. iframe 从 about:blank 变成真实内容时文档长高，浏览器"滚动锚定"顺势推一把。
 * 这里把两件事都钉住，避免以后又被改回去。
 */
console.log('\n=== 回归：换页回到顶部 ===');

const shell = new Map();
for (const id of ['nav', 'view-host', 'pageTitle', 'pageSub']) shell.set(id, new StubNode('div'));
globalThis.document.getElementById = (id) => shell.get(id) || null;

const scrollCalls = [];
globalThis.scrollTo = (...args) => scrollCalls.push(args);
globalThis.addEventListener = () => {};
globalThis.setTimeout = (fn) => { fn(); return 0; }; // 立刻执行补正的守卫

let scrollFailed = 0;
const check2 = (name, fn) => {
  try {
    fn();
    console.log(`  ✔ ${name}`);
  } catch (err) {
    scrollFailed++;
    console.log(`  ✘ ${name}\n      ${err.message}`);
  }
};

const router = await import('./core/router.js');
const assistantMod = await import('./features/assistant/index.js');
const emptyMod = { mount: () => {}, unmount: () => {} };

check2('navigate() 会把滚动位置归零', () => {
  scrollCalls.length = 0;
  router.register({ id: 'zz-test', title: '测试页', route: 'zz-test', order: 999 }, emptyMod);
  router.navigate('zz-test');
  const ok = scrollCalls.some((a) => {
    const arg = a[0];
    return arg && typeof arg === 'object' && arg.top === 0;
  });
  if (!ok) throw new Error(`没有以 top:0 调用 scrollTo，实际调用：${JSON.stringify(scrollCalls)}`);
});

check2('assistant 试玩/探针 iframe 关闭了滚动锚定', () => {
  const css = readFileSync(join(HERE, 'features', 'assistant', 'styles.css'), 'utf8');
  if (!/overflow-anchor:\s*none/.test(css)) {
    throw new Error('styles.css 里没有 overflow-anchor: none —— iframe 加载会把页面推下去');
  }
  // 两个 iframe 的类名都必须在关闭列表里
  for (const cls of ['.as-frame', '.as-probe-frame']) {
    const block = css.split(cls)[1] || '';
    if (!/overflow-anchor:\s*none/.test(block.slice(0, 200))) {
      throw new Error(`${cls} 没有关掉滚动锚定`);
    }
  }
});

console.log(scrollFailed === 0 ? '\n回归检查通过' : `\n${scrollFailed} 项回归检查失败`);
process.exit(failed === 0 && scrollFailed === 0 ? 0 : 1);


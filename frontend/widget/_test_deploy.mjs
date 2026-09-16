/**
 * 部署无关化测试（无浏览器）
 * ==========================
 *
 * 为什么需要它
 * ------------
 * 任务 3 的目标是「换台机器/换个域名部署时，**不需要改任何源码**」。
 * 这件事最容易在几个月后被一次"顺手改一下"破坏掉：某人为了调试把
 * `@require http://192.168.x.x:8000/widget/api.js` 写回去，本地一切正常，
 * 直到部署那天才发现所有学生都要重装脚本。
 *
 * 所以这个测试守两件事：
 *   ① **静态**：前端源码里不许出现写死的后端地址；@require 必须是相对路径；
 *   ② **行为**：从油猴脚本里**真抽出** `resolveApiBase()` 逐条跑地址解析顺序
 *      （data-api → 配置块 → 本页同源 → GM_info 的 @require → 显式报错）。
 *
 * 第 ② 点用的是"把源码里的函数抽出来执行"，不是复制一份实现 ——
 * 复制一份的话，实现改了测试还在测旧的，等于没测。
 *
 * 运行
 * ----
 *     node frontend/widget/_test_deploy.mjs
 */
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..', '..');
const USER_JS = join(ROOT, 'frontend', 'widget', 'probstat-assistant.user.js');

let passed = 0;
const failures = [];

function check(ok, name, detail = '') {
  if (ok) {
    passed += 1;
    console.log(`  ✔ ${name}${detail ? `  — ${detail}` : ''}`);
  } else {
    failures.push(name);
    console.log(`  ✘ ${name}${detail ? `  — ${detail}` : ''}`);
  }
}

function section(title) {
  console.log(`\n=== ${title} ===`);
}

const source = readFileSync(USER_JS, 'utf8');

/* ------------------------------------------------------------------ *
 * 1. 从源码里抽出地址解析逻辑并真跑
 * ------------------------------------------------------------------ */

/**
 * 按 `function 名字(` 起、按**花括号配平**止，取一段函数源码。
 * 必须配平而不是"找第一个行首 `}`"：函数体里可能有含 `}` 的字符串
 * （拼报错文案时就会遇到），靠缩进判断会被截断。
 */
function extractFn(text, name) {
  const start = text.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`源码里找不到 function ${name}(`);

  let depth = 0;
  let quote = '';
  let escaped = false;
  let inLineComment = false;
  let inBlockComment = false;

  for (let i = start; i < text.length; i += 1) {
    const c = text[i];
    const next = text[i + 1];

    if (inLineComment) {
      if (c === '\n') inLineComment = false;
      continue;
    }
    if (inBlockComment) {
      if (c === '*' && next === '/') {
        inBlockComment = false;
        i += 1;
      }
      continue;
    }
    if (quote) {
      if (escaped) escaped = false;
      else if (c === '\\') escaped = true;
      else if (c === quote) quote = '';
      continue;
    }

    if (c === '/' && next === '/') {
      inLineComment = true;
      i += 1;
      continue;
    }
    if (c === '/' && next === '*') {
      inBlockComment = true;
      i += 1;
      continue;
    }
    if (c === '"' || c === "'" || c === '`') {
      quote = c;
      continue;
    }

    if (c === '{') depth += 1;
    else if (c === '}') {
      depth -= 1;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  throw new Error(`${name} 的结束花括号没找到（配平失败）`);
}

const pinMatch = /var API_BASE_PIN = '([^']*)';/.exec(source);
if (!pinMatch) {
  console.error('  ✘ 源码里找不到 API_BASE_PIN 配置块 —— 模板结构变了？');
  process.exit(1);
}

const docElWith = (v) => ({ getAttribute: (k) => (k === 'data-api' ? v : null) });
const loc = (protocol, origin, href) => ({ protocol, origin, href });

/**
 * 用**源码里的真实实现**（连同真实的配置块取值）解析一次地址。
 * @param {object} env  {documentElement, location, GM_info}
 * @param {string} [pin] 覆盖配置块取值，用于验证优先级
 */
function resolveBaseFor(env, pin) {
  // eslint-disable-next-line no-new-func
  const fn = new Function(
    'API_BASE_PIN',
    `"use strict";\n${extractFn(source, 'originFromGmInfo')}\n${extractFn(
      source,
      'resolveApiBase'
    )}\nreturn resolveApiBase;`
  )(pin === undefined ? pinMatch[1] : pin);
  return fn(env);
}

section('1. 地址解析顺序（真跑源码里的 resolveApiBase）');

check(
  resolveBaseFor({ documentElement: docElWith('https://a.example.edu/') }) === 'https://a.example.edu',
  '① data-api 优先级最高（并去掉尾部斜杠）'
);

check(
  resolveBaseFor(
    {
      documentElement: docElWith('https://from-page.example'),
      location: loc('https:', 'https://page.example'),
    },
    'https://pin.example'
  ) === 'https://from-page.example',
  '① data-api 优先于配置块'
);

check(
  resolveBaseFor({ location: loc('https:', 'https://page.example') }, 'https://pin.example') ===
    'https://pin.example',
  '② 配置块优先于本页同源'
);

check(
  resolveBaseFor({ location: loc('http:', 'http://192.168.1.20:8000') }) === 'http://192.168.1.20:8000',
  '③ 本页同源（后端同时托管前端时的主路径）',
  '换 IP / 换端口都不用改源码'
);

check(
  resolveBaseFor({ location: loc('https:', '', 'https://course.example/page') }) ===
    'https://course.example',
  '③ origin 缺失时能退回 href'
);

// Tampermonkey 相对路径的解析基准是"安装来源"；如果 @require 写的是绝对地址，
// 就从脚本元数据里把来源取出来 —— 这是 ④ 的存在意义。
const gmWith = (req) => ({
  script: { scriptMetaStr: `// ==UserScript==\n// @require ${req}\n// ==/UserScript==` },
});

check(
  resolveBaseFor({ location: loc('file:', '', 'file:///C:/x.html'), GM_info: gmWith('http://10.0.0.5:8000/widget/api.js') }) ===
    'http://10.0.0.5:8000',
  '④ file:// 页面下从 GM_info 的 @require 来源推断',
  '脚本从哪装就连哪'
);

check(
  resolveBaseFor({
    location: loc('file:', '', 'file:///C:/x.html'),
    GM_info: { script: { source: 'http://192.168.1.20:8000/widget/probstat-assistant.user.js' } },
  }) === 'http://192.168.1.20:8000',
  '④ file:// 下用安装来源 URL 推断（GM_info.script.source）',
  '从哪安装就连哪'
);

check(
  resolveBaseFor({
    location: loc('file:', '', 'file:///C:/x.html'),
    GM_info: gmWith('/widget/api.js'),
  }) === '',
  '⑤ 只有相对 @require、推断不出主机 → 返回空串（由调用方显式报错）',
  '不允许静默用一个空地址去请求'
);

check(
  resolveBaseFor({ location: loc('chrome-extension:', 'chrome-extension://abc') }) === '',
  '⑤ 非 http(s) 协议不猜地址'
);

section('2. 源码静态约束（不许写死地址）');

const executable = source
  .split('\n')
  .filter((line) => !line.trim().startsWith('//'))
  .join('\n');

check(
  !/127\.0\.0\.1|localhost/i.test(executable),
  '可执行代码里没有 127.0.0.1 / localhost',
  '注释里可以写（说明用法），代码里不行'
);

check(pinMatch[1] === '', '源码的 API_BASE_PIN 是空的（发布物才填）');

const requires = [...source.matchAll(/^\s*\/\/\s*@require\s+(\S+)\s*$/gm)].map((m) => m[1]);

// @require 清单**不以条数为准**，而是必须与生成产物 _modules.json 一致
// （docs/23 §四：清单由 scripts/build_widget.py 生成，油猴脚本由 CI 校验它跟上了）。
// 以前这里写死"7 条"，一加共享内核就报"失败"—— 那条断言守的是数字，不是事实。
const manifest = JSON.parse(readFileSync(join(ROOT, 'frontend', 'widget', '_modules.json'), 'utf8'));
const missing = manifest.ui.filter((m) => !requires.includes(m));
const extra = requires.filter((r) => !manifest.ui.includes(r));
check(
  missing.length === 0,
  `@require 覆盖了清单里的全部 ${manifest.ui.length} 个模块`,
  missing.length ? `缺：${missing.join(', ')}` : requires.join(', ')
);
check(extra.length === 0, '@require 没有清单之外的模块', extra.join(', ') || '（无多余项）');
check(
  requires[0] === manifest.shared,
  '共享内核 _shared.js 排在第一（后面的模块要从 __PSA.shared 取实现）',
  `实际第一条：${requires[0]}`
);
check(
  requires.every((r) => r.startsWith('/') && !/^[a-z]+:\/\//i.test(r)),
  '@require 全部是相对路径',
  '由 Tampermonkey 按安装来源解析'
);

const matches = [...source.matchAll(/^\/\/\s*@match\s+(\S+)\s*$/gm)].map((m) => m[1]);
check(
  matches.every((m) => !/\d{1,3}(\.\d{1,3}){3}|localhost/i.test(m)),
  '@match 里没有写死的主机/IP',
  matches.join('  ')
);

check(
  source.includes('@downloadURL') === false && source.includes('@updateURL') === false,
  '源码不写 @updateURL/@downloadURL',
  '这两个由 scripts/build_userscript.py 生成发布物时补上'
);

section('3. 前端其它入口（loader / SPA）');

const loader = readFileSync(join(ROOT, 'frontend', 'widget', 'loader.js'), 'utf8');
const loaderCode = loader
  .split('\n')
  .filter((line) => !line.trim().startsWith('*') && !line.trim().startsWith('//'))
  .join('\n');
check(!/127\.0\.0\.1|localhost/i.test(loaderCode), 'loader.js 可执行代码里没有写死地址');
check(
  loader.includes('__PSA_API__') && loader.includes('location.origin'),
  'loader.js 保留了「配置块 → 同源」两层兜底'
);

const coreApi = readFileSync(join(ROOT, 'frontend', 'app', 'core', 'api.js'), 'utf8');
check(!/https?:\/\/[a-z0-9.-]+/i.test(coreApi), 'SPA 的 core/api.js 全部走同源相对路径');

const indexHtml = readFileSync(join(ROOT, 'frontend', 'index.html'), 'utf8');
check(
  indexHtml.includes('__PSA_API__'),
  'index.html 提供 __PSA_API__ 配置块',
  '分域部署时只改这一处'
);

/* ------------------------------------------------------------------ *
 * 汇总
 * ------------------------------------------------------------------ */

console.log('');
if (failures.length) {
  console.log(`  ✘ ${failures.length} 项失败：`);
  for (const f of failures) console.log(`     ${f}`);
  console.log('\n  部署无关化的意义：换服务器时，学生和开发者都不该改源码。');
  process.exit(1);
}
console.log(`  ${passed}/${passed} 通过 —— 换机器部署不需要改源码`);

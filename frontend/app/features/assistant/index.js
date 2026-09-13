/**
 * 页面助手页 —— 「悬浮窗」这个产品形态本身。
 *
 * 这一页存在的理由
 * ----------------
 * 产品的最终形态不是"一个学习网站"，而是挂在第三方课程页面（智慧树）上的助手。
 * 所以这一页要回答三个问题，顺序不能反：
 *
 *   1. **它到底能看见什么？** → 「当前页面读取结果」（活体探针，不是表格里的承诺）
 *   2. **怎么装到平台上？**     → 「两条投递路线」（油猴脚本是主路，不是备选项）
 *   3. **装上去什么样？**       → 「现场试玩」（能切到具体动画，而不是只给一个导航页）
 *
 * 设计取舍（为什么不是原来那样）
 * ------------------------------
 * - 原来把"三套投递方式"平铺成三张等权重的卡：但团队真正要交付的是
 *   **改不了源码的第三方平台**，油猴脚本是主线；`/raw-live/` 只是本机开发时的
 *   便捷开关。三种并列会让人以为可以三选一。
 * - 原来只有承诺（表格 + 一句话），没有证据：现在加了活体读取面板，
 *   直接显示助手从 iframe 里抽出来的标题 / 正文 / 公式 / 动画状态。
 * - 原来"现场试玩"只能看 `/raw-live/` 的导航页，看不到具体某个动画：
 *   现在八个动画都成了可点选的目标。
 */
import { h, injectStyles, clear, toast } from '../../core/dom.js';
import * as api from '../../core/api.js';
import { store } from '../../core/store.js';

injectStyles('/app/features/assistant/styles.css');

/* ------------------------------------------------------------------ *
 * 常量
 * ------------------------------------------------------------------ */

const CAPABILITIES = [
  ['正文', '按阅读密度识别正文容器，剥离导航 / 侧栏 / 推荐位'],
  ['标题层级', '压成页面大纲，既喂给模型，也在面板里给用户看'],
  ['公式', '独立公式全收；行内只收"像公式的"，免得被 $A$、$B$ 淹掉'],
  ['划选文字', '鼠标抬起即感知，页宠旁冒出「解释这段」'],
  ['视频进度', '读 <video> 的 currentTime / duration，能回答"我学到哪了"'],
  ['动画状态', '知道学生正在看哪个动画、单步到第几步、是否在播放'],
  ['跨 iframe', '所有 frame 各注入一份，postMessage 汇总，按内容丰富度仲裁'],
];

const USERSCRIPT_SNIPPET = `// ==UserScript==
// @name         概率论伴学助手（智慧树）
// @namespace    probcrew
// @version      0.1.0
// @match        https://*.zhihuishu.com/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==
// 完整脚本由后端提供，随版本更新：
//   /widget/probstat-assistant.user.js`;

const LOADER_SNIPPET = `<script src="https://your-host/widget/loader.js"
        data-api="https://your-host"
        data-skin="pet"
        data-auto-open="false"></script>`;

/* ------------------------------------------------------------------ *
 * 小工具
 * ------------------------------------------------------------------ */

/** 复制到剪贴板。localhost 属安全上下文，navigator.clipboard 可用；失败则退回 execCommand。 */
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (err) {
    /* 落到兜底 */
  }
  try {
    const ta = h('textarea', { style: { position: 'fixed', top: '-1000px', opacity: '0' } });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  } catch (err) {
    return false;
  }
}

/** 等 iframe 里的助手模块就绪（loader 是异步按序加载的）。 */
function waitForWidget(win, timeoutMs = 5000) {
  return new Promise((resolve) => {
    const started = Date.now();
    (function poll() {
      let ready = false;
      try {
        ready = !!(win.__PSA && win.__PSA.frames && win.__PSA.frames.collectAll);
      } catch (err) {
        // 跨域访问会抛 —— 直接放弃，由调用方给出解释
        resolve({ error: 'cross-origin' });
        return;
      }
      if (ready) {
        resolve({ ok: true });
        return;
      }
      if (Date.now() - started > timeoutMs) {
        resolve({ error: 'timeout' });
        return;
      }
      setTimeout(poll, 120);
    })();
  });
}

const pct = (v) => (typeof v === 'number' ? `${Math.round(v * 100)}%` : '—');
const shortUrl = (u) => String(u || '').replace(/^https?:\/\/[^/]+/, '') || '/';

/* ------------------------------------------------------------------ *
 * 页面
 * ------------------------------------------------------------------ */

/**
 * 跨 mount/unmount 的模块级状态。
 *
 * 必须放在模块作用域：`unmount()` 不在 `mount()` 的词法作用域里，
 * 把 iframe / 定时器声明在 mount 内部的话，离开页面时会直接
 * `ReferenceError: disposed is not defined` —— 页面能进不能出。
 */
let disposed = false;
let probeTimer = null;
let probeFrame = null;
let playFrame = null;

export function mount(container) {
  disposed = false;
  probeTimer = null;
  probeFrame = null;
  playFrame = null;

  const health = store.get('health');

  /* ============ 1. 活体读取面板 ============ */

  probeFrame = h('iframe', {
    class: 'as-probe-frame',
    src: 'about:blank',
    title: '探针 iframe（助手在里面运行）',
  });
  const probe = probeFrame;
  const readOut = h('div', { class: 'as-read-out' });
  const readStatus = h('span', { class: 'as-read-status muted small' }, '等待选择探针页面…');
  let probeSrc = '';

  function setProbe(src) {
    probeSrc = src;
    try {
      probe.src = 'about:blank'; // 先卸载，确保同一个 src 也能触发完整重载
    } catch (err) {
      /* 忽略 */
    }
    setTimeout(() => {
      if (disposed) return;
      probe.src = src;
      clear(readOut);
      readOut.append(h('div', { class: 'empty small' }, '探针页面加载中…（助手模块就绪后自动读取）'));
      scheduleRead(800);
    }, 40);
  }

  function scheduleRead(delay) {
    if (probeTimer) clearTimeout(probeTimer);
    probeTimer = setTimeout(() => {
      if (!disposed) readProbe();
    }, delay);
  }

  /** 真正去 iframe 里调助手的抽取接口，把结果画出来。 */
  async function readProbe() {
    if (!probeSrc) return;
    let win = null;
    try {
      win = probeFrame.contentWindow;
    } catch (err) {
      win = null;
    }
    if (!win) {
      renderReadError('拿不到 iframe 的 window');
      return;
    }

    readStatus.textContent = '正在读取…';
    const state = await waitForWidget(win);
    if (disposed) return;

    if (state.error === 'cross-origin') {
      renderReadError('跨域：这个探针页面与主站不同源，前端读不到它的 DOM');
      return;
    }
    if (state.error) {
      renderReadError('超时：探针页面里的助手没在 5 秒内就绪（该页面可能没有注入 loader）');
      return;
    }

    let frames = [];
    try {
      frames = await win.__PSA.frames.collectAll();
    } catch (err) {
      renderReadError(`读取失败：${err.message}`);
      return;
    }
    if (disposed) return;
    renderFrames(frames);
  }

  function renderReadError(message) {
    readStatus.textContent = '读取失败';
    clear(readOut);
    readOut.append(h('div', { class: 'as-read-err' }, h('b', {}, '⚠ 读不到内容：'), message));
  }

  function renderFrames(frames) {
    const ranked = [...frames].sort((a, b) => (b.score || 0) - (a.score || 0));
    const top = ranked[0] || null;
    clear(readOut);

    if (!top) {
      readStatus.textContent = '读到了 0 个 frame';
      readOut.append(h('div', { class: 'empty small' }, '没有任何 frame 上报内容。'));
      return;
    }

    readStatus.textContent = `读到 ${frames.length} 个 frame，采用内容丰富度最高的一份`;

    // ---- 明细：把后端真正会用到的那份上下文逐条摆出来 ----
    const media = top.media;
    const anim = top.animation;
    const rows = [
      ['页面标题', top.title || '（空）'],
      ['正文来源', top._how ? `识别方式：${top._how}` : '—'],
      ['正文字数', `${(top.text || '').length} 字`],
      ['标题层级', (top.headings || []).map((x) => `H${x.level} ${x.text}`).join(' ｜ ') || '（无）'],
      [
        '公式',
        `${(top.formulas || []).length} 条` +
          ((top.formulas || []).length ? '：' + top.formulas.slice(0, 3).join(' ; ') : ''),
      ],
      ['划选文字', top.selection ? `「${top.selection}」` : '（当前无选区）'],
      [
        '视频进度',
        media
          ? `${media.kind || 'video'} · ${media.currentTime ?? '?'} / ${media.duration ?? '?'}`
          : '（本页无视频）',
      ],
      [
        '动画状态',
        anim
          ? `${anim.title || anim.id || '动画'} · ${anim.state || '未知状态'}` +
            (anim.steps != null ? ` · 第 ${anim.steps} 步` : '')
          : '（本页无动画）',
      ],
      ['阅读位置', pct(top.scroll_pct)],
      ['内容丰富度', String(top.score ?? 0)],
    ];

    readOut.append(
      h(
        'table',
        { class: 'data as-read-table' },
        h('tbody', {}, ...rows.map(([k, v]) => h('tr', {}, h('th', {}, k), h('td', {}, String(v)))))
      ),
      h(
        'details',
        { class: 'as-read-text' },
        h('summary', {}, '展开正文前 600 字（助手看到的就是这段）'),
        h('pre', {}, (top.text || '').slice(0, 600) || '（空）')
      )
    );

    // ---- 各 frame 对比：解释"为什么要仲裁" ----
    if (ranked.length > 1) {
      readOut.append(
        h('div', { class: 'as-read-more' }, h('b', {}, `另外 ${ranked.length - 1} 个 frame 的内容量对比`)),
        h(
          'div',
          { class: 'table-wrap' },
          h(
            'table',
            { class: 'data' },
            h(
              'thead',
              {},
              h(
                'tr',
                {},
                h('th', {}, 'frame 路径'),
                h('th', {}, '标题'),
                h('th', {}, '字数'),
                h('th', {}, '公式'),
                h('th', {}, '内容丰富度')
              )
            ),
            h(
              'tbody',
              {},
              ...ranked.map((f) =>
                h(
                  'tr',
                  { class: f === top ? 'as-row-top' : '' },
                  h('td', { class: 'mono small' }, shortUrl(f.url)),
                  h('td', { class: 'small' }, (f.title || '').slice(0, 26)),
                  h('td', { class: 'mono small' }, String((f.text || '').length)),
                  h('td', { class: 'mono small' }, String((f.formulas || []).length)),
                  h('td', { class: 'mono small' }, String(f.score ?? 0))
                )
              )
            )
          )
        )
      );
    }
  }

  probeFrame.addEventListener('load', () => scheduleRead(400));

  /* ============ 2. 现场试玩 ============ */

  playFrame = h('iframe', {
    class: 'as-frame',
    src: '/course/',
    title: '试玩 iframe',
  });
  const play = playFrame;
  const playLabel = h('span', { class: 'muted small' }, '演示课程页 /course/（划词 + 页宠）');

  const PLAY_TARGETS = [
    { key: 'course', label: '📘 演示课程页', src: '/course/', note: '演示课程页 /course/（划词 + 页宠）' },
    { key: 'nav', label: '🗂 动画导航页', src: '/raw-live/', note: '原始动画导航页 /raw-live/（8 个入口）' },
  ];

  const playBar = h(
    'div',
    { class: 'row wrap as-play-bar' },
    ...PLAY_TARGETS.map((t) =>
      h(
        'button',
        {
          class: 'btn btn-sm' + (t.key === 'course' ? ' btn-primary' : ''),
          dataset: { key: t.key },
          onclick: () => playTo(t),
        },
        t.label
      )
    ),
    h('span', { class: 'as-play-sep' }),
    h(
      'button',
      {
        class: 'btn btn-sm',
        title: '销毁 iframe，避免动画的 requestAnimationFrame 继续吃 CPU',
        onclick: () => {
          playFrame.src = 'about:blank';
          playLabel.textContent = '已卸载 iframe（省 CPU）';
          for (const btn of playBar.querySelectorAll('button')) btn.classList.remove('btn-primary');
        },
      },
      '⏏ 卸载'
    ),
    h('a', { class: 'btn btn-sm', href: '/course/', target: '_blank', rel: 'noopener' }, '↗ 新标签打开')
  );

  function playTo(target) {
    playFrame.src = target.src;
    playLabel.textContent = target.note;
    for (const btn of playBar.querySelectorAll('button')) {
      btn.classList.toggle('btn-primary', btn.dataset.key === target.key);
    }
  }

  /* ============ 3. 原始动画清单 ============ */

  const animList = h('div', { class: 'as-anim-list' });

  api
    .rawLiveList()
    .then((data) => {
      if (disposed) return;
      clear(animList);
      if (!data.available) {
        animList.append(
          h(
            'div',
            { class: 'as-read-err' },
            h('b', {}, '⚠ 没找到原始动画文件夹：'),
            data.hint ||
              '请把 8 个动画 html 放到预期位置，或使用分发包自带的 frontend/assets/animations/_raw。'
          )
        );
        return;
      }
      const items = data.items || [];
      animList.append(
        h(
          'div',
          { class: 'small muted mb-8' },
          `${data.source}：${data.count} 个页面。磁盘上的原文件一个字节都没改 —— 悬浮窗是后端在响应时注入的。`
        )
      );
      animList.append(
        h(
          'div',
          { class: 'table-wrap' },
          h(
            'table',
            { class: 'data as-anim-table' },
            h(
              'thead',
              {},
              h(
                'tr',
                {},
                h('th', {}, '动画页面'),
                h('th', {}, '注入后试玩'),
                h('th', {}, '打开原文件'),
                h('th', {}, '探针读取')
              )
            ),
            h(
              'tbody',
              {},
              ...items.map((item) =>
                h(
                  'tr',
                  {},
                  h('td', {}, item.file.replace(/\.html$/, '')),
                  h(
                    'td',
                    {},
                    h(
                      'button',
                      {
                        class: 'btn btn-sm btn-primary',
                        onclick: () =>
                          playTo({
                            key: 'raw:' + item.file,
                            src: item.url,
                            note: `原始动画（注入后）：${item.file}`,
                          }),
                      },
                      '▶ 在下方试玩'
                    )
                  ),
                  h(
                    'td',
                    {},
                    h('a', { class: 'btn btn-sm', href: item.raw_url, target: '_blank', rel: 'noopener' }, '原文件 ↗')
                  ),
                  h(
                    'td',
                    {},
                    h(
                      'button',
                      {
                        class: 'btn btn-sm',
                        title: '让上面的活体面板读这个页面',
                        onclick: () => {
                          setProbe(item.url);
                          toast(`探针已切到：${item.file.replace(/\.html$/, '')}`, 'info');
                        },
                      },
                      '🎯 探针'
                    )
                  )
                )
              )
            )
          )
        )
      );
      // 默认让探针指向第一个动画 —— 页面一进来就有结论可看，而不是空白等点击
      if (items.length) setProbe(items[0].url);
    })
    .catch((err) => {
      if (disposed) return;
      clear(animList);
      animList.append(h('div', { class: 'empty small' }, `读取失败：${err.message}`));
    });

  /* ============ 4. 投递方式 ============ */

  const METHOD_CARDS = [
    {
      key: 'userscript',
      badge: '主路线',
      badgeMain: true,
      icon: '🐒',
      title: '油猴脚本注入',
      sub: '改不了源码的平台 —— 也就是智慧树',
      desc:
        '平台页面一个字节都不改。脚本在所有 frame 各跑一份，用 postMessage 把内容汇总到顶层 —— ' +
        '这是读到课件 iframe 的唯一办法。',
      pros: ['平台侧零改动', '@require 绕开站点 CSP', '覆盖跨域 iframe'],
      cons: ['需要装 Tampermonkey', '改代码后要重新同步脚本', '⚠ 尚未在真实智慧树账号上验证'],
      snippet: USERSCRIPT_SNIPPET,
      cta: { label: '查看脚本源码 ↗', href: '/widget/probstat-assistant.user.js' },
    },
    {
      key: 'loader',
      badge: '自建站点',
      badgeMain: false,
      icon: '📄',
      title: '一行 script 嵌入',
      sub: '你自己能改源码的课程页',
      desc: '加一行 script 即可。改前端代码刷新就生效，不需要重新安装，还能配皮肤与是否自动展开。',
      pros: ['一行代码', '改代码即时生效', '可配 pet / ball 两套皮肤'],
      cons: ['需要能改站点源码'],
      snippet: LOADER_SNIPPET,
      cta: { label: '看演示课程页', playCourse: true },
    },
  ];

  const methodGrid = h('div', { class: 'as-methods' });

  for (const m of METHOD_CARDS) {
    methodGrid.append(
      h(
        'div',
        { class: 'as-method' + (m.badgeMain ? ' as-method-main' : '') },
        h(
          'div',
          { class: 'as-method-head' },
          h('span', { class: 'as-method-ico' }, m.icon),
          h(
            'div',
            {},
            h('h4', {}, m.title, h('span', { class: 'as-badge' + (m.badgeMain ? ' as-badge-main' : '') }, m.badge)),
            h('code', { class: 'mono' }, m.sub)
          )
        ),
        h('p', {}, m.desc),
        h('ul', { class: 'as-pros' }, ...m.pros.map((p) => h('li', {}, '✓ ' + p))),
        h('ul', { class: 'as-cons' }, ...m.cons.map((c) => h('li', {}, '· ' + c))),
        h('pre', { class: 'as-code' }, m.snippet),
        h(
          'div',
          { class: 'row wrap' },
          h(
            'button',
            {
              class: 'btn btn-sm',
              onclick: async () => {
                const ok = await copyText(m.snippet);
                toast(ok ? '已复制到剪贴板' : '复制失败，请手动选中代码', ok ? 'success' : 'warning');
              },
            },
            '⧉ 复制代码'
          ),
          m.cta.playCourse
            ? h('button', { class: 'btn btn-sm btn-primary', onclick: () => playTo(PLAY_TARGETS[0]) }, m.cta.label)
            : h(
                'a',
                { class: 'btn btn-sm btn-primary', href: m.cta.href, target: '_blank', rel: 'noopener' },
                m.cta.label
              )
        )
      )
    );
  }

  /* ============ 装配 ============ */

  container.append(
    h(
      'div',
      { class: 'wb-hero', style: { background: 'linear-gradient(135deg,#0ea5e9,#4f46e5 60%,#7c3aed)' } },
      h('h1', {}, '🐾 页面助手：悬浮球 / 虚拟页宠'),
      h(
        'p',
        {},
        '产品的最终形态不是"一个学习网站"，而是挂在任意在线课程页面上的助手。' +
          '它读得懂学生正在看的这一页 —— 正文、标题、公式、划选的文字、视频进度、' +
          '甚至正在操作的动画停在第几步 —— 然后用多个 Agent 协作答疑。'
      ),
      h(
        'div',
        { class: 'chips' },
        h('span', {}, 'Shadow DOM 完全隔离'),
        h('span', {}, '8 种状态由真实事件驱动'),
        h('span', {}, '可切换页宠 / 极简球'),
        h('span', {}, health?.provider?.resolved === 'mock' ? 'Mock 模式' : '真模型')
      )
    ),

    /* ---- 1. 它到底能看见什么 ---- */
    h(
      'div',
      { class: 'card mt-16' },
      h(
        'div',
        { class: 'card-title' },
        '👀 当前页面读取结果',
        h('span', { class: 'sub' }, '活体探针：同一段注入代码，在一个真 iframe 里跑给你看')
      ),
      h(
        'p',
        { class: 'small muted' },
        '左边这个 iframe 里跑着和智慧树上完全同一份注入代码。下面每一行都是父页面通过助手的抽取接口' +
          '真实读回来的 —— 不是写死的示例数据，读不到就会显示失败原因。'
      ),
      h(
        'div',
        { class: 'as-probe' },
        h(
          'div',
          { class: 'as-probe-left' },
          h(
            'div',
            { class: 'as-probe-bar' },
            readStatus,
            h('button', { class: 'btn btn-sm', title: '重新读取一次', onclick: () => readProbe() }, '⟲ 重读')
          ),
          h('div', { class: 'as-probe-frame-box' }, probeFrame)
        ),
        h('div', { class: 'as-probe-right' }, readOut)
      ),
      h(
        'p',
        { class: 'small muted mt-8' },
        '想换目标：下面「团队原始动画」表里每一行都有 🎯 探针按钮。' +
          '把探针切到某个动画后点它的「▶ 在下方试玩」，再回来点「⟲ 重读」—— ' +
          '「动画状态」那一行会跟着变。'
      )
    ),

    /* ---- 2. 现场试玩 ---- */
    h(
      'div',
      { class: 'card mt-16' },
      h(
        'div',
        { class: 'card-title' },
        '🎮 现场试玩',
        h('span', { class: 'sub' }, 'iframe 与主站同源，里面的页宠可以正常工作')
      ),
      playBar,
      h('div', { class: 'as-play-label-row' }, playLabel),
      h('div', { class: 'as-frame-box' }, playFrame),
      h(
        'p',
        { class: 'small muted mt-8' },
        '提示：在 iframe 正文里划选一句话，页宠旁会出现「💡 解释这段」。' +
          '动画页里还能用控制条单步、并把当前这一步讲给你听。' +
          '「⏏ 卸载」会把 iframe 换成空白页 —— 有的动画有停不掉的 rAF 循环，' +
          '不用了就该销毁，而不是留着后台空转。'
      )
    ),

    /* ---- 3. 怎么装到平台上 ---- */
    h(
      'div',
      { class: 'card mt-16' },
      h(
        'div',
        { class: 'card-title' },
        '📦 两条投递路线',
        h('span', { class: 'sub' }, '按"能不能改源码"分，主路线在左')
      ),
      methodGrid,
      h(
        'p',
        { class: 'small muted mt-12' },
        '另外还有一条只在开发时用的路：/raw-live/ —— 后端读原始动画文件，' +
          '在响应前把 loader 插到 </body> 前面返回。它不修改磁盘文件、与后端同源，' +
          '所以本地调试最省事；但它要求"服务器能读到那些文件"，不是给学生用的安装方式。'
      )
    ),

    /* ---- 4. 团队原始动画 ---- */
    h(
      'div',
      { class: 'card mt-16' },
      h(
        'div',
        { class: 'card-title' },
        '🎬 团队原始动画',
        h('span', { class: 'sub' }, '八个动画 · 注入版 / 原文件 / 探针，三列对照')
      ),
      animList
    ),

    /* ---- 5. 能力与边界 ---- */
    h(
      'div',
      { class: 'card mt-16' },
      h('div', { class: 'card-title' }, '👀 助手能读到什么'),
      h(
        'table',
        { class: 'data' },
        h('thead', {}, h('tr', {}, h('th', {}, '维度'), h('th', {}, '说明'), h('th', {}, '状态'))),
        h(
          'tbody',
          {},
          ...CAPABILITIES.map(([k, v]) =>
            h('tr', {}, h('td', {}, h('b', {}, k)), h('td', {}, v), h('td', {}, h('span', { class: 'as-ok' }, '✅ 已实现')))
          )
        )
      ),
      h(
        'p',
        { class: 'small muted mt-12' },
        '标题栏的 📖 按钮可随时关闭页面读取（隐私考虑）。读不到内容时面板顶部会显示黄色警告，' +
          '而不是沉默 —— 用户需要知道助手到底看见了什么。'
      ),
      h(
        'div',
        { class: 'as-warn' },
        h('b', {}, '⚠ 尚未验证的一件事：'),
        '上面这套注入 + 跨 frame 汇总的逻辑，还没有在真实的智慧树账号上跑过。' +
          '已知风险是平台 CSP、iframe 域名隔离、课件页的非常规 DOM 结构。' +
          '这是下一阶段优先级最高的验证项，也是这一页唯一不能自证的部分。'
      )
    )
  );
}

export function unmount() {
  /* iframe 会被 router 清空；有 rAF 的动画靠「⏏ 卸载」显式销毁。
     这里再把两个 iframe 主动置空一次：离开页面时不该留着动画在后台空转。 */
  disposed = true;
  if (probeTimer) clearTimeout(probeTimer);
  try {
    probeFrame.src = 'about:blank';
    playFrame.src = 'about:blank';
  } catch (err) {
    /* 忽略 */
  }
}

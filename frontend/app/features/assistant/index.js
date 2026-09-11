/**
 * 页面助手页 —— 把"悬浮窗"这个产品形态本身也接进 SPA。
 *
 * 为什么需要这一页：产品的最终形态不是一个学习网站，而是**挂在别人课程页面上的助手**。
 * 但 SPA 里原本完全没有体现这件事。这一页负责：
 *
 *   1. 讲清三套投递方式各自适用什么场景；
 *   2. **现场试玩**：内嵌 /course/ 与 /raw-live/ 页面（同源，页宠在 iframe 里也能跑）；
 *   3. 列出团队原始动画文件夹里可注入的页面，一键打开；
 *   4. 说明助手到底能读到页面的哪些东西。
 */
import { h, injectStyles, clear } from '../../core/dom.js';
import * as api from '../../core/api.js';
import { store } from '../../core/store.js';

injectStyles('/app/features/assistant/styles.css');

const METHODS = [
  {
    key: 'live',
    icon: '⚡',
    title: '免安装试用',
    sub: '/raw-live/ 后端动态注入',
    desc: '后端读原始文件，在响应的最后一刻把悬浮窗脚本插到 </body> 前再返回。磁盘上的原文件一个字节都没改。',
    pros: ['零安装，打开就有', '与后端同源，跨域问题消失', '原始动画文件保持干净'],
    cons: ['只适用于本机/内网可访问的页面'],
    cta: '打开原始动画（带页宠）',
    url: '/raw-live/',
  },
  {
    key: 'loader',
    icon: '📄',
    title: '自建站一行嵌入',
    sub: '<script src="/widget/loader.js">',
    desc: '自己控制的课程站点，加一行 script 即可。改前端代码刷新就生效，不需要重新安装。',
    pros: ['一行代码', '改代码即时生效', '可配皮肤与自动展开'],
    cons: ['需要能改站点源码'],
    cta: '看演示课程页',
    url: '/course/',
  },
  {
    key: 'userscript',
    icon: '🐒',
    title: '第三方平台注入',
    sub: '油猴脚本（超星 / 智慧树）',
    desc: '改不了源码的平台只能靠注入。脚本在所有 frame 各跑一份，用 postMessage 把内容汇总到顶层——这是读到 iframe 里课件的唯一办法。',
    pros: ['不用改平台源码', '@require 规避站点 CSP', '覆盖跨域 iframe'],
    cons: ['需要装 Tampermonkey', '改代码后要重新同步脚本'],
    cta: '安装油猴脚本',
    url: '/widget/probstat-assistant.user.js',
  },
];

const CAPABILITIES = [
  ['正文', '按阅读密度识别正文容器，剥离导航/侧栏/推荐位'],
  ['标题层级', '压成页面大纲，既喂给模型也给用户看'],
  ['公式', '独立公式全收；行内只收"像公式的"，免得被 $A$、$B$ 淹掉'],
  ['划选文字', '鼠标抬起即感知，页宠旁冒出「解释这段」'],
  ['视频进度', '读 <video> 的 currentTime / duration，能回答"我学到哪了"'],
  ['动画状态', '知道学生正在看哪个动画、已经单步到第几步'],
  ['跨 iframe', '所有 frame 各注入一份，postMessage 汇总，按内容丰富度仲裁'],
];

export function mount(container) {
  const health = store.get('health');

  /* ---------------- 现场试玩 ---------------- */
  const tryFrame = h('iframe', {
    class: 'as-frame',
    src: '/course/',
    title: '演示课程页（内含悬浮窗）',
  });

  const tryBar = h(
    'div',
    { class: 'row-between wrap mb-8' },
    h('div', { class: 'row' }, h('strong', {}, '现场试玩')),
    h(
      'div',
      { class: 'row wrap' },
      h(
        'button',
        {
          class: 'btn btn-sm',
          onclick: () => {
            tryFrame.src = '/course/';
            setActive('course');
          },
        },
        '课程页'
      ),
      h(
        'button',
        {
          class: 'btn btn-sm',
          onclick: () => {
            tryFrame.src = '/raw-live/';
            setActive('raw');
          },
        },
        '原始动画导航'
      ),
      h(
        'button',
        {
          class: 'btn btn-sm',
          onclick: () => {
            tryFrame.src = 'about:blank';
            setActive('');
          },
        },
        '卸载（省 CPU）'
      ),
      h(
        'a',
        { class: 'btn btn-sm', href: '/course/', target: '_blank', rel: 'noopener' },
        '↗ 新标签打开'
      )
    )
  );

  function setActive() {
    /* 目前只用于视觉反馈，保留扩展位 */
  }

  /* ---------------- 原始动画清单 ---------------- */
  const rawList = h('div', { class: 'as-raw-list' });

  api
    .rawLiveList()
    .then((data) => {
      clear(rawList);
      if (!data.available) {
        rawList.append(h('div', { class: 'empty small' }, `未找到原始动画文件夹：${data.dir}`));
        return;
      }
      rawList.append(
        h('div', { class: 'small muted mb-8' }, `来源：${data.dir}（${data.count} 个页面，磁盘文件未被修改）`)
      );
      const grid = h('div', { class: 'as-raw-grid' });
      for (const item of data.items) {
        grid.append(
          h(
            'div',
            { class: 'as-raw-item' },
            h('span', { class: 'as-raw-name' }, item.file.replace(/\.html$/, '')),
            h(
              'div',
              { class: 'row' },
              h('a', { class: 'btn btn-sm btn-primary', href: item.url, target: '_blank', rel: 'noopener' }, '带页宠'),
              h('a', { class: 'btn btn-sm', href: item.raw_url, target: '_blank', rel: 'noopener' }, '原文件')
            )
          )
        );
      }
      rawList.append(grid);
    })
    .catch((err) => {
      clear(rawList);
      rawList.append(h('div', { class: 'empty small' }, `读取失败：${err.message}`));
    });

  /* ---------------- 装配 ---------------- */
  container.append(
    h(
      'div',
      { class: 'wb-hero', style: { background: 'linear-gradient(135deg,#0ea5e9,#4f46e5 60%,#7c3aed)' } },
      h('h1', {}, '🐾 页面助手：悬浮球 / 虚拟页宠'),
      h(
        'p',
        {},
        '产品的最终形态不是"一个学习网站"，而是**挂在任意在线课程页面上的助手**。' +
          '它读得懂学生正在看的这一页——正文、标题、公式、划选的文字、视频进度、' +
          '甚至正在操作的动画停在第几步——然后用多个 Agent 协作答疑。'
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

    /* 三套投递方式 */
    h(
      'div',
      { class: 'card mt-16' },
      h('div', { class: 'card-title' }, '📦 三套投递方式', h('span', { class: 'sub' }, '按"能不能改源码"选')),
      h(
        'div',
        { class: 'as-methods' },
        ...METHODS.map((m) =>
          h(
            'div',
            { class: 'as-method' },
            h('div', { class: 'as-method-head' }, h('span', { class: 'as-method-ico' }, m.icon),
              h('div', {}, h('h4', {}, m.title), h('code', { class: 'mono' }, m.sub))),
            h('p', {}, m.desc),
            h('ul', { class: 'as-pros' }, ...m.pros.map((p) => h('li', {}, '✓ ' + p))),
            h('ul', { class: 'as-cons' }, ...m.cons.map((c) => h('li', {}, '· ' + c))),
            h(
              'a',
              {
                class: 'btn btn-sm btn-primary',
                href: m.url,
                target: m.key === 'userscript' ? '_blank' : '_self',
                rel: 'noopener',
                onclick: m.key === 'loader' ? (e) => { e.preventDefault(); tryFrame.src = '/course/'; } : undefined,
              },
              m.cta
            )
          )
        )
      )
    ),

    /* 现场试玩 */
    h(
      'div',
      { class: 'card mt-16' },
      h(
        'div',
        { class: 'card-title' },
        '🎮 现场试玩',
        h('span', { class: 'sub' }, 'iframe 与主站同源，里面的页宠可以正常工作')
      ),
      tryBar,
      h('div', { class: 'as-frame-box' }, tryFrame),
      h(
        'p',
        { class: 'small muted mt-8' },
        '提示：在下方 iframe 的正文里划选一句话，页宠旁会出现「💡 解释这段」。' +
          '注意底部是嵌套 iframe，页宠在右下角更靠内的位置。'
      )
    ),

    /* 原始动画清单 */
    h(
      'div',
      { class: 'card mt-16' },
      h(
        'div',
        { class: 'card-title' },
        '🎬 团队原始动画',
        h('span', { class: 'sub' }, '带页宠 / 原文件，两种打开方式对照')
      ),
      rawList
    ),

    /* 能力说明 */
    h(
      'div',
      { class: 'card mt-16' },
      h('div', { class: 'card-title' }, '👀 助手能读到什么'),
      h(
        'table',
        { class: 'data' },
        h('thead', {}, h('tr', {}, h('th', {}, '维度'), h('th', {}, '说明'))),
        h('tbody', {}, ...CAPABILITIES.map(([k, v]) => h('tr', {}, h('td', {}, h('b', {}, k)), h('td', {}, v))))
      ),
      h(
        'p',
        { class: 'small muted mt-12' },
        '标题栏的 📖 按钮可随时关闭页面读取（隐私考虑）。读不到内容时面板顶部会显示黄色警告，' +
          '而不是沉默——用户需要知道助手到底看见了什么。'
      )
    )
  );
}

export function unmount() {
  /* iframe 会被 router 清空；/course/ 里如果没有动画 iframe 就没有 rAF 泄漏问题 */
}

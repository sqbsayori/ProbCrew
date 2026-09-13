/**
 * 交互动画库 —— 把既有的 8 个自包含 HTML 动画纳入系统。
 *
 * 设计要点
 * -------
 * 1. **动画文件一字不改**。它们保持自包含、可离线、可单独分发；
 *    系统只是"发现 + 呈现 + 远程驱动"它们。
 * 2. 清单来自 `/api/animations`（读 manifest.json），**本文件不硬编码动画列表**，
 *    以后加动画只要改 manifest，前端自动出现。
 * 3. 播放器用同源 iframe 驱动 `#playBtn` 等控制（见 components/animation-player.js），
 *    离开本页时**必须销毁 iframe**：markov-chain 有停不掉的 rAF 循环。
 */
import { h, injectStyles, clear } from '../../core/dom.js';
import { store } from '../../core/store.js';
import * as api from '../../core/api.js';
import { createAnimationPlayer } from '../../components/animation-player.js';

injectStyles('/app/features/animations/styles.css');

let player = null;
let cleanup = [];

export function mount(container) {
  const all = store.get('animations') || [];
  const categories = store.get('animationCategories') || ['全部'];
  let activeCat = '全部';
  let keyword = '';

  if (!all.length) {
    container.append(
      h('div', { class: 'card' }, h('div', { class: 'card-title' }, '🎬 交互动画'),
        h('div', { class: 'empty' }, '未读取到动画清单（/api/animations），请确认后端已启动。'))
    );
    return;
  }

  const grid = h('div', { class: 'anim-grid' });
  const playerHost = h('div', { class: 'mt-16' });
  const recResult = h('div', { class: 'mt-12' });

  /* ---------- 搜索与推荐 ---------- */
  const searchInput = h('input', {
    class: 'input',
    placeholder: '搜索：贝叶斯、马尔科夫链、网络流量…（也可直接描述你想看的现象）',
    oninput: (ev) => {
      keyword = ev.target.value.trim();
      renderGrid();
    },
  });

  const recBtn = h(
    'button',
    {
      class: 'btn btn-primary',
      onclick: async () => {
        const q = searchInput.value.trim();
        if (!q) return;
        clear(recResult);
        recResult.append(h('span', { class: 'small muted' }, '推荐中…'));
        try {
          const res = await api.recommendAnimations(q, 3);
          clear(recResult);
          if (!res.length) {
            recResult.append(h('span', { class: 'small muted' }, '没有匹配到动画，换个说法试试。'));
            return;
          }
          recResult.append(
            h('div', { class: 'small muted mb-8' }, '按知识点匹配到的动画：'),
            h(
              'div',
              { class: 'row wrap' },
              ...res.map((m) =>
                h(
                  'button',
                  { class: 'btn btn-sm', onclick: () => open(m.id) },
                  `▶ ${m.title}`,
                  h('span', { class: 'tag tag-gray', style: { marginLeft: '6px' } }, m.score)
                )
              )
            )
          );
        } catch (err) {
          clear(recResult);
          recResult.append(h('span', { class: 'small', style: { color: 'var(--danger)' } }, `推荐失败：${err.message}`));
        }
      },
    },
    '🤖 按知识点推荐'
  );

  /* ---------- 卡片网格 ---------- */
  const tabs = h('div', { class: 'row wrap' });
  const buildTabs = () => {
    tabs.innerHTML = '';
    for (const c of categories) {
      tabs.append(
        h(
          'button',
          {
            class: `dist-chip${c === activeCat ? ' active' : ''}`,
            onclick: () => {
              activeCat = c;
              buildTabs();
              renderGrid();
            },
          },
          c
        )
      );
    }
  };

  function renderGrid() {
    clear(grid);
    const kw = keyword.toLowerCase();
    const items = all
      .filter((a) => activeCat === '全部' || a.category === activeCat)
      .filter((a) => {
        if (!kw) return true;
        const hay = [a.title, a.description, a.category, ...(a.concepts || [])].join(' ').toLowerCase();
        return hay.includes(kw);
      });

    if (!items.length) {
      grid.append(h('div', { class: 'empty' }, '没有匹配的动画，换个关键词试试。'));
      return;
    }

    for (const a of items) {
      grid.append(
        h(
          'div',
          { class: 'anim-card', style: { '--accent': a.accent || '#4f46e5' }, onclick: () => open(a.id) },
          h(
            'div',
            { class: 'anim-card-head' },
            h('div', { class: 'anim-card-ico' }, a.icon || '🎬'),
            h('span', { class: 'tag tag-gray' }, a.category || '')
          ),
          h('h3', {}, a.title),
          h('p', {}, a.description || ''),
          h(
            'div',
            { class: 'concepts' },
            ...(a.concepts || []).slice(0, 4).map((c) => h('span', { class: 'tag' }, c))
          ),
          h(
            'div',
            { class: 'row-between mt-8' },
            h(
              'span',
              { class: 'small muted' },
              `${(a.params || []).length} 个可调参数` +
                (a.canvasCount ? ` · ${a.canvasCount} 个画布` : '')
            ),
            h('span', { class: 'small', style: { color: 'var(--accent)' } }, '打开演示 →')
          )
        )
      );
    }
  }

  /* ---------- 打开动画 ---------- */
  async function open(id) {
    const a = all.find((x) => x.id === id);
    if (!a) return;
    destroyPlayer();
    clear(playerHost);

    // 再取一次详情拿 controls（列表接口已带，但保底）
    let detail = a;
    try {
      detail = await api.getJSON(`/api/animations/${encodeURIComponent(id)}`);
    } catch {
      /* 用列表里的数据即可 */
    }

    playerHost.append(
      h(
        'div',
        { class: 'row-between wrap mb-8' },
        h('div', { class: 'row' }, h('strong', {}, `正在播放：${a.title}`)),
        h(
          'button',
          {
            class: 'btn btn-sm',
            onclick: () => {
              destroyPlayer();
              clear(playerHost);
            },
          },
          '✕ 关闭'
        )
      )
    );

    const box = h('div', { class: 'card' });
    playerHost.append(box);

    player = createAnimationPlayer({
      url: detail.url,
      title: detail.title,
      description: detail.description,
      accent: detail.accent,
      controls: detail.controls || {},
      height: 640,
    });
    box.append(player.el);
    playerHost.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function destroyPlayer() {
    player?.destroy();
    player = null;
  }

  /* ---------- 装配 ---------- */
  container.append(
    h(
      'div',
      { class: 'card' },
      h(
        'div',
        { class: 'card-title' },
        '🎬 交互动画库',
        h('span', { class: 'sub' }, `${all.length} 个自包含 H5 · 无需联网 · 可被 Agent 自动推荐`)
      ),
      h('div', { class: 'row wrap' }, h('div', { style: { flex: '1', minWidth: '240px' } }, searchInput), recBtn),
      h('div', { class: 'mt-12' }, tabs),
      h('div', { class: 'mt-8' }, recResult)
    ),
    h('div', { class: 'mt-16' }, grid),
    playerHost,
    h(
      'div',
      { class: 'card mt-16' },
      h('div', { class: 'card-title' }, '🔧 控制原理'),
      h(
        'p',
        { class: 'small muted' },
        '这些动画本身没有对外接口。系统用「同源 iframe + 稳定 id 选择器」驱动它们的' +
          '播放 / 暂停 / 单步 / 重置按钮（8 个动画全部支持，无需改动原作）。' +
          '因此动画必须通过本系统（http）访问，直接双击本地 html 文件（file://）会因为浏览器同源策略而无法被驱动。'
      )
    )
  );

  buildTabs();
  renderGrid();

  cleanup.push(() => destroyPlayer());
}

export function unmount() {
  // 关键：必须销毁 iframe，否则部分动画的渲染循环会一直在后台烧 CPU
  cleanup.forEach((fn) => fn());
  cleanup = [];
}

/**
 * 路由 + Feature 注册表 + 页面插槽。
 *
 * 核心思想：**feature 自己声明"我是谁、我挂在哪个路由、我渲染到哪里"**，
 * 外壳只负责按注册表装配。因此新增一个页面 = 新增一个目录，
 * 不需要改 index.html、不需要改导航数组。
 *
 * 每个 feature 目录下的 `feature.json`：
 *   { "id": "animations", "title": "交互动画", "icon": "🎬",
 *     "route": "animations", "group": "资源", "order": 20 }
 */
import { bus, EV } from './bus.js';
import { byId, clear, h } from './dom.js';

/** id -> { meta, module, mounted, container } */
const features = new Map();
let currentRoute = null;
const routeListeners = [];
/** 换页后补正"回顶部"的定时器句柄（见 navigate 末尾） */
const resetScrollGuards = [];

/**
 * 注册一个 feature。
 * @param {object} meta  feature.json 的内容
 * @param {object} module 导出 { mount(container, ctx), unmount?() }
 */
export function register(meta, module) {
  if (features.has(meta.id)) {
    console.warn(`[router] feature 重复注册：${meta.id}`);
    return;
  }
  features.set(meta.id, { meta, module, mounted: false, container: null });
}

export const listFeatures = () =>
  [...features.values()].sort((a, b) => (a.meta.order ?? 100) - (b.meta.order ?? 100));

/** 渲染侧边栏导航（按 feature 的 group 分组） */
export function renderNav() {
  const nav = byId('nav');
  if (!nav) return;
  clear(nav);

  const groups = new Map();
  for (const f of listFeatures()) {
    if (f.meta.hidden) continue;
    const g = f.meta.group || '功能';
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(f);
  }

  for (const [group, items] of groups) {
    nav.append(h('div', { class: 'nav-label' }, group));
    for (const item of items) {
      const btn = h(
        'button',
        {
          class: 'nav-item',
          dataset: { route: item.meta.route },
          onclick: () => navigate(item.meta.route),
        },
        h('span', { class: 'ico' }, item.meta.icon || '•'),
        h('span', {}, item.meta.title)
      );
      nav.append(btn);
    }
  }
}

/** 切换路由 */
export function navigate(route, params = {}) {
  if (!features.has(route)) {
    console.warn(`[router] 未知路由：${route}`);
    return;
  }
  if (currentRoute && currentRoute !== route) {
    const prev = features.get(currentRoute);
    try {
      prev?.module.unmount?.();
    } catch (err) {
      console.error('[router] unmount 出错', err);
    }
    prev.mounted = false;
  }

  currentRoute = route;
  const entry = features.get(route);
  const host = byId('view-host');
  clear(host);

  // 高亮导航
  document.querySelectorAll('.nav-item').forEach((el) => {
    el.classList.toggle('active', el.dataset.route === route);
  });

  // 顶栏标题
  byId('pageTitle').textContent = entry.meta.title;
  byId('pageSub').textContent = entry.meta.subtitle || '概率论与数理统计 · 多智能体学习系统';

  const container = h('section', { class: 'page active', id: `page-${route}` });
  host.append(container);

  try {
    entry.module.mount(container, { navigate, params, meta: entry.meta });
    entry.mounted = true;
    entry.container = container;
  } catch (err) {
    console.error(`[router] ${route} 挂载失败`, err);
    container.append(
      h('div', { class: 'card' }, h('div', { class: 'card-title' }, '⚠️ 页面加载失败'),
        h('pre', { class: 'mono small' }, String(err?.stack || err)))
    );
  }

  location.hash = `#/${route}`;
  routeListeners.forEach((fn) => fn(route, params));
  bus.emit(EV.NAVIGATE, { route, params });

  // 换页必须回到顶部。
  //
  // 不重置的话会出现一个很难自查的现象：上一页比下一页高，切页时
  // clear(host) 把文档变短，浏览器把过大的 scrollY **钳制**到新的最大值，
  // 于是"点开某一页"直接落在页面中下部，用户以为页面跳错了。
  // 放在 mount 之后，保证这时文档已经是最新高度。
  //
  // 后两处补正：feature 挂载后常常还要异步拉数据 / 装载 iframe，文档随后
  // 还会长高，浏览器的滚动锚定会顺势把页面推下去（实测 assistant 页被送到
  // 905px）。用几个时间点兜住；**一旦用户自己滚动过就全部让位**，
  // 绝不跟用户抢滚动条。
  let userScrolled = false;
  const markUserScroll = () => {
    userScrolled = true;
  };
  for (const ev of ['wheel', 'touchmove', 'keydown']) {
    addEventListener(ev, markUserScroll, { passive: true, once: true });
  }

  scrollToTop();
  for (const delay of [180, 600, 1400]) {
    resetScrollGuards.push(
      setTimeout(() => {
        if (!userScrolled && window.scrollY > 4) window.scrollTo(0, 0);
      }, delay)
    );
  }
}

/** 回到顶部（并清掉上一页挂起的全部守卫） */
function scrollToTop() {
  while (resetScrollGuards.length) clearTimeout(resetScrollGuards.pop());
  window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
}

export const getRoute = () => currentRoute;
export const onRoute = (fn) => routeListeners.push(fn);

/** 从 location.hash 解析初始路由 */
export function initialRoute(fallback) {
  const m = /^#\/([\w-]+)/.exec(location.hash || '');
  return m && features.has(m[1]) ? m[1] : fallback;
}

/** 已挂载 feature 的容器（供跨 feature 通信时定位） */
export function containerOf(id) {
  return features.get(id)?.container || null;
}

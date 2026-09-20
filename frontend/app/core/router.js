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
import { byId, clear, h, toast } from './dom.js';
import {
  LOGIN_ROUTE,
  canEnter,
  canSee,
  defaultRoute,
  isLoggedIn,
} from './auth.js';

/** id -> { meta, module, mounted, container } */
const features = new Map();
let currentRoute = null;
const routeListeners = [];
/** 换页后补正"回顶部"的定时器句柄（见 render 末尾） */
const resetScrollGuards = [];

/* ---- "用户自己滚动过就让位"探针（必须可移除，见 render 末尾注释）---- */
const SCROLL_PROBE_EVENTS = ['wheel', 'touchmove', 'keydown'];
let userScrolled = false;
let scrollProbeArmed = false;
function onUserScroll() {
  userScrolled = true;
}
function clearScrollProbe() {
  if (!scrollProbeArmed) return;
  for (const ev of SCROLL_PROBE_EVENTS) window.removeEventListener(ev, onUserScroll);
  scrollProbeArmed = false;
  userScrolled = false;
}

/** hashchange 只注册一次 */
let hashListenerBound = false;
/** 上一次由 navigate() 显式导航出去的路由+参数（用于 hashchange 去重） */
let lastNav = null;

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

/** 渲染侧边栏导航（按 feature 的 group 分组）
 *
 *  ★ 这里同时是**角色过滤**发生的地方：规则集中在 `core/auth.js` 的
 *  `canSee()`，导航与路由守卫共用同一套，避免"菜单藏了但地址栏还能进"。
 *  ⚠️ 仍然只是体验层：真正的权限在服务端（`kernel/auth.py:require_admin`）。
 */
export function renderNav() {
  const nav = byId('nav');
  if (!nav) return;
  clear(nav);

  const groups = new Map();
  for (const f of listFeatures()) {
    if (f.meta.hidden) continue;
    if (!canSee(f.meta.route)) continue; // 未登录 / 角色不足 → 不显示
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

/** 把 route + params 编成 hash（`#/practice?q=ex-bayes-01&hint=1`）。
 *
 *  为什么必须做：主站的刷题进度、错题重做筛选、图谱选中节点都要**可寻址** ——
 *  否则刷新丢状态、不能分享、浏览器返回键无处可回（见 docs/21 §3.1）。
 */
export function buildHash(route, params = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v === undefined || v === null || v === '') continue;
    qs.set(k, String(v));
  }
  const q = qs.toString();
  return `#/${route}${q ? `?${q}` : ''}`;
}

/** 解析 hash → { route, params }。无法解析时 route 为 null。 */
export function parseHash(hash) {
  const m = /^#\/([\w-]+)(?:\?(.*))?$/.exec((hash || '').trim());
  if (!m) return { route: null, params: {} };
  return { route: m[1], params: Object.fromEntries(new URLSearchParams(m[2] || '')) };
}

/** 切换路由（会更新 URL；渲染统一走 render，避免两套路径）
 *
 *  ★ 行为约定：**navigate 必须同步完成渲染**。
 *  原因有二：① 调用方（功能页）在 navigate 之后立刻读 DOM；
 *  ② `_test_mount.mjs` 的"换页回到顶部"回归依赖它同步生效。
 *  为此：先按导航意图记录 lastNav，再改 hash —— 随后触发的 hashchange
 *  会发现"已经是这个路由+参数"而**跳过重复渲染**（若 hash 未变则不触发事件）。
 */
export function navigate(route, params = {}) {
  if (!features.has(route)) {
    console.warn(`[router] 未知路由：${route}`);
    return;
  }
  lastNav = { route, params };
  const hash = buildHash(route, params);
  if (location.hash !== hash) location.hash = hash; // 触发 hashchange → 被去重跳过
  render(route, params);
}

/**
 * 守卫拒绝时的兜底页。
 *
 * 两条硬要求：**绝不白屏**、**把原因说出来**（页面上写清楚是"没登录"还是"权限不够"，
 * 而不是留一片空白让人怀疑是不是崩了）。按钮文案随登录态变化。
 */
function renderBlocked(title, text) {
  const host = byId('view-host');
  if (!host) return;
  clear(host);
  currentRoute = null; // 下次导航到同一路由要重新渲染

  const loggedIn = isLoggedIn();
  const titleEl = byId('pageTitle');
  if (titleEl) titleEl.textContent = title;
  const subEl = byId('pageSub');
  if (subEl) subEl.textContent = '需要登录或换一个页面';

  const btn = h(
    'button',
    {
      class: 'btn btn-primary',
      onclick: () => navigate(loggedIn ? defaultRoute() : LOGIN_ROUTE),
    },
    loggedIn ? '回到首页' : '去登录'
  );

  host.append(
    h(
      'section',
      { class: 'page active' },
      h(
        'div',
        { class: 'empty-state' },
        h('div', { class: 'empty-state-ico' }, loggedIn ? '🚫' : '🔒'),
        h('div', { class: 'empty-state-title' }, title),
        h('div', { class: 'empty-state-text' }, text),
        btn
      )
    )
  );
}

/** 真正渲染一个路由（不碰 URL）。 */
function render(route, params = {}) {
  if (!features.has(route)) return;

  // ---- 路由守卫 ----
  // 两种拒绝要分开处理，否则用户会困惑：
  //   ① 没登录 → 去登录页（并带上想去哪，登录后可跳回）
  //   ② 登录了但角色不够（学生敲 /#/admin）→ 回落地页 + 提示，**不要**踢回登录页
  if (!canEnter(route)) {
    if (!isLoggedIn()) {
      if (features.has(LOGIN_ROUTE) && route !== LOGIN_ROUTE) {
        navigate(LOGIN_ROUTE, { next: route });
        return;
      }
      renderBlocked('需要登录', '登录页还没做好（features/login）。后端登录接口已经可用。');
      return;
    }
    const home = defaultRoute();
    if (route !== home && features.has(home)) {
      toast('你没有权限访问这个页面', 'error', 4000);
      navigate(home);
      return;
    }
    renderBlocked('无权访问', '当前账号的角色不能打开这个页面。');
    return;
  }

  // 卸载上一页：**路由变了要卸载；同一路由只换参数（如翻题）不卸载**，
  // 否则刷题页每次换题都会被重建，作答框与已用提示全丢。
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
  //
  // ⚠️ 这三个监听**必须可移除**：`once` 只在事件真的触发时才摘掉监听，
  // 而返回顶部这类导航未必伴随滚动 —— 不主动清理就会每次导航
  // 永久多挂 3 个 window 监听（实测：连续切页后监听数持续增长）。
  clearScrollProbe();
  scrollProbeArmed = true;
  for (const ev of SCROLL_PROBE_EVENTS) {
    window.addEventListener(ev, onUserScroll, { passive: true, once: true });
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

/* ------------------------------------------------------------------ *
 * hashchange / 监听清理
 * ------------------------------------------------------------------ */

/** 浏览器前进 / 后退 / 手改地址栏 —— 唯一的"URL 是状态源"入口 */
function onHashChange() {
  const { route, params } = parseHash(location.hash);
  if (!route || !features.has(route)) return; // 未知路由：保持当前视图，不白屏

  // 去重：navigate() 已经同步渲染过同一个路由+参数，事件是它自己触发的
  if (lastNav && lastNav.route === route && sameParams(lastNav.params, params)) return;
  lastNav = null;

  render(route, params);
}

/** 参数浅比较（值统一按字符串比，与 URL 语义一致） */
function sameParams(a = {}, b = {}) {
  const ka = Object.keys(a).filter((k) => a[k] !== undefined && a[k] !== null && a[k] !== '');
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  return ka.every((k) => String(a[k]) === String(b[k]));
}

/** 注册一次即可（幂等），由 bootstrap 调用 */
export function startRouter(fallback) {
  if (!hashListenerBound) {
    window.addEventListener('hashchange', onHashChange);
    hashListenerBound = true;
  }
  const { route, params } = parseHash(location.hash);
  const target = route && features.has(route) ? route : fallback;
  if (route && features.has(route)) {
    render(route, params); // 深链接：直接渲染，但不重复写 hash
  } else {
    navigate(target); // 无有效 hash：写入默认路由
  }
}

export const getRoute = () => currentRoute;
export const onRoute = (fn) => routeListeners.push(fn);

/** 从 location.hash 解析初始路由（保留旧签名，供既有调用点使用） */
export function initialRoute(fallback) {
  const { route } = parseHash(location.hash);
  return route && features.has(route) ? route : fallback;
}

/** 解析当前 hash 的完整状态（路由 + 参数）—— 供需要恢复现场的功能页使用 */
export const currentParams = () => parseHash(location.hash).params;

/** 已挂载 feature 的容器（供跨 feature 通信时定位） */
export function containerOf(id) {
  return features.get(id)?.container || null;
}

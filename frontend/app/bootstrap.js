/**
 * 应用启动器（Bootstrap）—— 唯一的"装配点"。
 *
 * 顺序很关键：
 *   1. 准备匿名会话 id（**只用于把学习记录串起来，不再是身份**；身份是账号令牌）
 *   2. 加载 KaTeX（公式渲染必须就绪，否则首屏公式会闪成源码）
 *   3. 按生成的注册表动态 import 各 feature 并注册
 *   4. 用本地令牌向后端确认登录态 → 渲染导航（按角色过滤）
 *   5. 拉取目录（Agent/工具/动画）→ 进入落地路由
 *
 * **依赖注入点**：认证模块需要"未登录时跳哪去"，但它不 import router
 * （否则 core 之间循环依赖）。所以在这里把动作注进去 —— 装配点只有一个，
 * 依赖方向就不会打结。
 *
 * 新增一个页面：在 app/features/ 下建目录 + feature.json + index.js，
 * 然后跑 `python scripts/gen_registry.py`。**本文件不需要修改。**
 */
import { loadKatex } from './components/katex.js';
import * as api from './core/api.js';
import * as auth from './core/auth.js';
import { EV, bus } from './core/bus.js';
import { byId, h, toast } from './core/dom.js';
import { listFeatures, navigate, register, renderNav, startRouter } from './core/router.js';
import { store } from './core/store.js';
import { FEATURES } from './features.registry.js';

/** 生成/复用一个浏览器级会话 id（匿名追踪，与登录账号无关） */
function ensureSessionId() {
  const KEY = 'probstat.session_id';
  let id = localStorage.getItem(KEY);
  if (!id) {
    id = `s_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36).slice(-4)}`;
    localStorage.setItem(KEY, id);
  }
  return id;
}

/** 侧栏底部：把后端真实状态亮出来，避免答辩时才发现 Key 没配 */
function renderSystemStatus(health) {
  const box = byId('sysStatus');
  if (!box) return;
  const isMock = health.provider?.resolved === 'mock';
  const dot = isMock ? 'dot-warn' : 'dot-ok';
  const label = isMock ? 'Mock 模式（无需 API Key）' : `真模型 · ${health.provider?.model || ''}`;
  const user = auth.currentUser();

  box.innerHTML = '';
  box.append(
    h('div', {}, h('span', { class: `badge-dot ${dot}` }), label),
    h('div', {}, `Agents ${health.registry?.agents ?? '—'} · Tools ${health.registry?.tools ?? '—'}`),
    h('div', {}, `动画 ${health.animations?.total ?? '—'} 个 · 知识库 ${health.knowledge_base?.sections ?? '—'} 段`),
    h(
      'div',
      { style: { marginTop: '6px' } },
      user
        ? `已登录：${auth.displayNameOf(user)}（${user.role === 'admin' ? '管理员' : '学生'}）`
        : '未登录'
    ),
    // 匿名会话 id 仍然保留：它把学习记录串起来（attempt.session_id），
    // 但**身份**已经由账号令牌决定，两者不是一回事。
    h(
      'div',
      { style: { color: '#475569' } },
      `匿名会话 ${store.get('sessionId')}`
    )
  );
}

/** 顶栏右侧：当前用户 + 健康状态小胶囊 */
function renderTopbar(health) {
  const box = byId('topbarRight');
  if (!box) return;
  box.innerHTML = '';
  const isMock = health.provider?.resolved === 'mock';
  const user = auth.currentUser();

  const nodes = [
    h('span', { class: `tag ${isMock ? 'tag-amber' : 'tag-green'}` }, isMock ? '🧪 Mock 模式' : '🔌 真模型'),
    h('span', { class: 'tag tag-gray' }, `HITL ${health.collaboration?.hitl_enabled ? '开' : '关'}`),
  ];

  if (user) {
    const name = auth.displayNameOf(user);
    nodes.push(
      h(
        'span',
        { class: 'user-chip' },
        h('span', { class: 'user-avatar' }, (name || '?').slice(0, 1)),
        h('span', {}, name),
        h('span', { class: `role-badge${user.role === 'admin' ? ' admin' : ''}` },
          user.role === 'admin' ? '管理员' : '学生')
      ),
      h('button', { class: 'btn btn-sm', onclick: onLogout, title: '退出登录' }, '退出')
    );
  } else {
    nodes.push(
      h('button', { class: 'btn btn-sm btn-primary', onclick: () => navigate('login') }, '登录')
    );
  }

  nodes.push(h('button', { class: 'btn btn-sm', onclick: hardReload, title: '清空匿名会话并重新加载' }, '⟲ 重置会话'));
  box.append(...nodes);
}

async function onLogout() {
  await auth.logout();
  toast('已退出登录', 'info', 2500);
  renderNav();
  navigate('login');
}

function hardReload() {
  localStorage.removeItem('probstat.session_id');
  location.reload();
}

/** 最近一次 health（登录态变化时要重画顶栏，但不想再请求一次） */
let lastHealth = null;

const hasLoginRoute = () => listFeatures().some((f) => f.meta.route === auth.LOGIN_ROUTE);

async function boot() {
  store.set('sessionId', ensureSessionId());

  // 1) 公式渲染引擎（本地 vendor）
  await loadKatex();

  // 2) 注册全部 feature
  const meta = byId('pageTitle');
  if (meta) meta.textContent = '加载中…';

  for (const item of FEATURES) {
    try {
      // 动态 import：每个 feature 一个目录，互不干扰
      const mod = await import(`./features/${item.dir}/index.js`);
      register(item, mod);
    } catch (err) {
      console.error(`[boot] feature 加载失败：${item.id}`, err);
      toast(`页面「${item.title}」加载失败：${err.message}`, 'error', 5000);
    }
  }

  // 3) 注入依赖 + 订阅登录态变化（core 之间不互相 import，装配点在这里）
  auth.setUnauthorizedHandler((reason) => {
    renderNav();
    if (reason) toast(reason, 'error', 4000);
    if (hasLoginRoute()) navigate(auth.LOGIN_ROUTE);
  });
  bus.on(EV.AUTH_CHANGE, () => {
    renderNav(); // 角色不同 → 能看到的菜单不同
    if (lastHealth) renderTopbar(lastHealth);
  });

  // 4) 用本地令牌向后端确认身份（令牌可能已在服务端被撤销/过期）
  await auth.refreshMe();
  renderNav();

  // 5) 目录（并行拉取，失败不阻塞进入首页）
  const [agents, tools, animations, distributions, health] = await Promise.allSettled([
    api.listAgents(),
    api.listTools(),
    api.listAnimations(),
    api.listDistributions(),
    api.health(),
  ]);

  if (agents.status === 'fulfilled') store.set('agents', agents.value.items || []);
  if (tools.status === 'fulfilled') store.set('tools', tools.value.items || []);
  if (animations.status === 'fulfilled') {
    store.set('animations', animations.value.items || []);
    store.set('animationCategories', animations.value.categories || ['全部']);
  }
  if (distributions.status === 'fulfilled') store.set('distributions', distributions.value.items || []);

  if (health.status === 'fulfilled') {
    lastHealth = health.value;
    store.set('health', health.value);
    renderSystemStatus(health.value);
    renderTopbar(health.value);
  } else {
    const box = byId('sysStatus');
    if (box) box.innerHTML =
      '<div><span class="badge-dot" style="background:var(--danger)"></span>后端未连接</div>';
    toast('无法连接后端 /api/health，请确认服务已启动', 'error', 6000);
  }

  // 6) 进入落地路由
  //    未登录 → 登录页；已登录 → 按角色落地（管理员直接进管理页）
  //    startRouter 会：① 绑定 hashchange（浏览器前进/后退从此可用）
  //                    ② 深链接（#/practice?q=…）直接按 URL 渲染
  //                    ③ 无有效 hash 时落到 fallback
  const fallback = auth.isLoggedIn()
    ? auth.defaultRoute()
    : hasLoginRoute()
      ? auth.LOGIN_ROUTE
      : FEATURES[0]?.route || 'workbench';
  startRouter(fallback);
}

boot().catch((err) => {
  console.error('[boot] 启动失败', err);
  document.getElementById('view-host').innerHTML = `
    <section class="page active">
      <div class="card">
        <div class="card-title">⚠️ 应用启动失败</div>
        <pre class="mono small">${String(err?.stack || err)}</pre>
      </div>
    </section>`;
});

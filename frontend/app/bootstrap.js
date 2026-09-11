/**
 * 应用启动器（Bootstrap）—— 唯一的"装配点"。
 *
 * 顺序很关键：
 *   1. 准备会话 id（替代登录系统，让学习记录能连起来）
 *   2. 加载 KaTeX（公式渲染必须就绪，否则首屏公式会闪成源码）
 *   3. 按生成的注册表动态 import 各 feature 并注册
 *   4. 渲染导航 → 拉取目录（Agent/工具/动画）→ 进入初始路由
 *
 * 新增一个页面：在 app/features/ 下建目录 + feature.json + index.js，
 * 然后跑 `python scripts/gen_registry.py`（或 npm 式的一行脚本）。
 * **本文件不需要修改。**
 */
import { loadKatex } from './components/katex.js';
import * as api from './core/api.js';
import { byId, h, toast } from './core/dom.js';
import { initialRoute, navigate, register, renderNav } from './core/router.js';
import { store } from './core/store.js';
import { FEATURES } from './features.registry.js';

/** 生成/复用一个浏览器级会话 id */
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

  box.innerHTML = '';
  box.append(
    h('div', {}, h('span', { class: `badge-dot ${dot}` }), label),
    h('div', {}, `Agents ${health.registry?.agents ?? '—'} · Tools ${health.registry?.tools ?? '—'}`),
    h('div', {}, `动画 ${health.animations?.total ?? '—'} 个 · 知识库 ${health.knowledge_base?.sections ?? '—'} 段`),
    h(
      'div',
      { style: { marginTop: '6px' } },
      h('a', { href: '/docs', style: { color: '#94a3b8' }, onclick: () => false }, `会话 ${store.get('sessionId')}`)
    )
  );
}

/** 顶栏右侧：健康状态小胶囊 */
function renderTopbar(health) {
  const box = byId('topbarRight');
  if (!box) return;
  box.innerHTML = '';
  const isMock = health.provider?.resolved === 'mock';
  box.append(
    h('span', { class: `tag ${isMock ? 'tag-amber' : 'tag-green'}` }, isMock ? '🧪 Mock 模式' : '🔌 真模型'),
    h('span', { class: 'tag tag-gray' }, `HITL ${health.collaboration?.hitl_enabled ? '开' : '关'}`),
    h(
      'button',
      {
        class: 'btn btn-sm',
        onclick: () => hardReload(),
        title: '清空会话并重新加载',
      },
      '⟲ 重置会话'
    )
  );
}

function hardReload() {
  localStorage.removeItem('probstat.session_id');
  location.reload();
}

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
  renderNav();

  // 3) 目录（并行拉取，失败不阻塞进入首页）
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
    store.set('health', health.value);
    renderSystemStatus(health.value);
    renderTopbar(health.value);
  } else {
    byId('sysStatus').innerHTML =
      '<div><span class="badge-dot" style="background:var(--danger)"></span>后端未连接</div>';
    toast('无法连接后端 /api/health，请确认服务已启动', 'error', 6000);
  }

  // 4) 进入初始路由
  navigate(initialRoute(FEATURES[0]?.route || 'workbench'));
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

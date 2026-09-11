/**
 * 工作台 —— 系统总览。
 *
 * 它回答三件事（也是答辩时最常被问的）：
 *   1. 系统由哪些 Agent 组成？各自负责什么？（角色卡，数据来自 /api/agents）
 *   2. 它们怎么协作？（拓扑图，对应 kernel/graph.py 的真实结构）
 *   3. 现在跑的是什么模型、有多少资产？（统计卡，数据来自 /api/health）
 *
 * 所有数据都从后端目录接口拉取，**本文件不硬编码任何 Agent 清单** ——
 * 别人新增 Agent 后，这一页自动更新。
 */
import { h, injectStyles, clear } from '../../core/dom.js';
import { store } from '../../core/store.js';
import * as api from '../../core/api.js';

injectStyles('/app/features/workbench/styles.css');

const ROLE_LABEL = {
  router: '调度者',
  generator: '生成者',
  verifier: '验证者',
  analyst: '分析者',
  tool: '工具',
};

function hero(health) {
  const isMock = health?.provider?.resolved === 'mock';
  return h(
    'div',
    { class: 'wb-hero' },
    h('h1', {}, '概率论与数理统计 · 多智能体学习系统'),
    h(
      'p',
      {},
      '一个可扩展、模块化的多 Agent 协作原型骨架：以 8 个自包含交互动画为可视化资产，' +
        '由 LangGraph 编排 6 个专业 Agent 协作完成「知识点讲解 / 题目讲解 / 分布可视化 / 学习分析」，' +
        '并用「生成—验证分权 + 人机协同」保证产出可信。'
    ),
    h(
      'div',
      { class: 'chips' },
      h('span', {}, `LLM：${isMock ? 'Mock（无需 Key）' : health?.provider?.model || 'DeepSeek'}`),
      h('span', {}, `HITL：${health?.collaboration?.hitl_enabled ? '已启用' : '已关闭'}`),
      h('span', {}, `生成/验证分权：${health?.collaboration?.verify_enabled ? '已启用' : '已关闭'}`),
      h('span', {}, '免构建前端 · 离线可用')
    )
  );
}

function stats(health) {
  const items = [
    { n: health?.registry?.agents ?? '—', label: '协作 Agent', extra: '新增一个文件即可扩展' },
    { n: health?.registry?.tools ?? '—', label: '可调用工具', extra: '角色门控授权' },
    { n: health?.animations?.total ?? '—', label: '交互动画', extra: '自包含 HTML，可离线' },
    { n: health?.knowledge_base?.sections ?? '—', label: '知识库片段', extra: `${health?.knowledge_base?.chapters ?? 0} 个章节` },
  ];
  return h(
    'div',
    { class: 'wb-stats' },
    ...items.map((it) =>
      h('div', { class: 'wb-stat' }, h('strong', {}, String(it.n)), h('span', {}, it.label), h('em', {}, it.extra))
    )
  );
}

function agentCards(agents) {
  const card = (a) =>
    h(
      'div',
      { class: 'agent-card', style: { '--accent': a.accent || '#4f46e5' } },
      h(
        'div',
        { class: 'agent-card-head' },
        h('div', { class: 'agent-card-ico' }, a.icon || '🤖'),
        h(
          'div',
          {},
          h('h3', {}, a.name),
          h('div', { class: 'role' }, `${ROLE_LABEL[a.role] || a.role} · ${a.id}`)
        )
      ),
      h('p', {}, a.description),
      h(
        'div',
        { class: 'tags' },
        ...(a.role === 'verifier'
          ? [h('span', { class: 'tag tag-red' }, `校验 ${(a.can_verify || []).join('/') || '—'}`)]
          : []),
        ...(a.intents || []).slice(0, 3).map((i) => h('span', { class: 'tag tag-gray' }, i)),
        ...(a.emits || []).map((e) => h('span', { class: 'tag' }, `产出 ${e}`))
      ),
      a.tools?.length
        ? h(
            'div',
            { class: 'tool-line' },
            '工具：',
            ...a.tools.map((t) => h('code', { class: 'mono' }, t))
          )
        : h('div', { class: 'tool-line' }, '工具：无（纯调度/校验）')
    );

  return h('div', { class: 'agent-cards' }, ...agents.map(card));
}

function flow(agents) {
  const exec = agents.filter((a) => !['router', 'verifier'].includes(a.role));
  const box = (label, accent, note) =>
    h(
      'div',
      { class: 'flow-box', style: { '--accent': accent } },
      label,
      note ? h('div', { class: 'flow-note' }, note) : null
    );

  return h(
    'div',
    { class: 'flow' },
    box('👤 用户提问', '#64748b'),
    h('div', { class: 'flow-arrow' }, '▼'),
    box('🧭 Orchestrator', '#4f46e5', '意图路由 + 调度计划（不产出内容）'),
    h('div', { class: 'flow-arrow' }, '▼ 条件边 · 并行 fan-out'),
    h(
      'div',
      { class: 'flow-parallel' },
      ...exec.map((a) => box(`${a.icon} ${a.name.split(' ')[0]}`, a.accent))
    ),
    h('div', { class: 'flow-arrow' }, '▼'),
    box('🔍 Verifier / Grader', '#ef4444', '独立校验：完整性 · 溯源 · 数值来源'),
    h('div', { class: 'flow-arrow' }, '▼ 高风险则挂起'),
    box('⏸ HITL 人工确认', '#f59e0b', 'LangGraph interrupt() 暂停，修正后从断点续跑'),
    h('div', { class: 'flow-arrow' }, '▼'),
    box('📦 Aggregate 聚合', '#0ea5e9', '汇总为最终答案 + 结构化产物')
  );
}

/* ------------------------------------------------------------------ *
 * 最近运行（把后端的留档能力露出来）
 * ------------------------------------------------------------------ */

function recentRunsCard(navigate) {
  const host = h('div', { class: 'wb-runs' });
  host.append(h('div', { class: 'empty small' }, '加载中…'));

  api
    .listRuns(5)
    .then((data) => {
      clear(host);
      if (!data.items.length) {
        host.append(
          h('div', { class: 'empty small' },
            '还没有运行记录 —— 去「知识讲解」或「题目讲解」问一个问题，这里就会出现。')
        );
        return;
      }
      const STATUS = {
        done: ['已完成', 'tag-green'],
        awaiting_hitl: ['等待人工确认', 'tag-amber'],
        running: ['进行中', 'tag'],
        error: ['出错', 'tag-red'],
      };
      for (const r of data.items) {
        const [label, cls] = STATUS[r.status] || STATUS.done;
        host.append(
          h(
            'div',
            { class: 'wb-run-row', onclick: () => navigate('runs') },
            h('span', { class: `tag ${cls}` }, label),
            h('span', { class: 'wb-run-q' }, r.query),
            h(
              'span',
              { class: 'wb-run-meta small muted' },
              `${r.intent || '—'} · ${r.agents.length} Agent · ${r.event_count} 事件`
            )
          )
        );
      }
      host.append(
        h(
          'button',
          { class: 'btn btn-sm mt-8', onclick: () => navigate('runs') },
          '查看完整轨迹 →'
        )
      );
    })
    .catch((err) => {
      clear(host);
      host.append(h('div', { class: 'empty small' }, `读取失败：${err.message}`));
    });

  return host;
}

/* ------------------------------------------------------------------ *
 * 知识库概览
 * ------------------------------------------------------------------ */

function knowledgeCard(navigate) {
  const host = h('div', { class: 'wb-kb' });
  host.append(h('div', { class: 'empty small' }, '加载中…'));

  api
    .knowledgeChapters()
    .then((data) => {
      clear(host);
      host.append(
        h('div', { class: 'small muted mb-8' },
          `${data.chapter_count} 章 · ${data.section_count} 个知识点（来源：本地教材知识库）`)
      );
      for (const ch of data.chapters) {
        host.append(
          h(
            'div',
            { class: 'wb-kb-row', onclick: () => navigate('knowledge') },
            h('span', { class: 'kb-ch-id' }, ch.id),
            h('span', { class: 'wb-kb-title' }, ch.title),
            h('span', { class: 'small muted' }, `${ch.section_count} 节`)
          )
        );
      }
      host.append(
        h(
          'p',
          { class: 'small muted mt-8' },
          'demo 阶段是本地 Markdown + bigram 检索；P2 阶段换成 Qdrant 混合检索，接口形态不变。'
        )
      );
    })
    .catch((err) => {
      clear(host);
      host.append(h('div', { class: 'empty small' }, `读取失败：${err.message}`));
    });

  return host;
}

export function mount(container, ctx) {
  const health = store.get('health');
  const agents = store.get('agents') || [];

  container.append(
    hero(health),
    stats(health),
    h(
      'div',
      { class: 'card mt-16' },
      h(
        'div',
        { class: 'card-title' },
        '🔀 协作拓扑',
        h('span', { class: 'sub' }, '与 backend/app/kernel/graph.py 一一对应')
      ),
      flow(agents)
    ),
    h(
      'div',
      { class: 'card mt-16' },
      h(
        'div',
        { class: 'card-title' },
        '🤖 Agent 角色',
        h('span', { class: 'sub' }, `共 ${agents.length} 个 · 来自 /api/agents 自动发现`)
      ),
      agents.length
        ? agentCards(agents)
        : h('div', { class: 'empty' }, '尚未读取到 Agent 清单，请确认后端已启动')
    ),
    h(
      'div',
      { class: 'card mt-16' },
      h('div', { class: 'card-title' }, '🚀 快速开始'),
      h(
        'div',
        { class: 'row wrap' },
        h('button', { class: 'btn btn-primary', onclick: () => ctx.navigate('knowledge') }, '📚 问一个知识点'),
        h('button', { class: 'btn', onclick: () => ctx.navigate('solver') }, '✏️ 解一道题（含 HITL 演练）'),
        h('button', { class: 'btn', onclick: () => ctx.navigate('visualize') }, '📊 观察一个分布'),
        h('button', { class: 'btn', onclick: () => ctx.navigate('assistant') }, '🐾 页面助手（悬浮窗）'),
        h('button', { class: 'btn', onclick: () => ctx.navigate('animations') }, `🎬 交互动画（${store.get('animations')?.length ?? 0}）`),
        h('button', { class: 'btn', onclick: () => ctx.navigate('runs') }, '🧵 运行轨迹'),
        h('button', { class: 'btn', onclick: () => ctx.navigate('architecture') }, '🧩 看架构与分工')
      ),
      h(
        'p',
        { class: 'small muted mt-12' },
        '提示：未配置 API Key 时系统会自动降级为 Mock 模式，全部功能仍可离线演示。'
      )
    ),

    /* 下面两块是"让首页有实际内容"的补充：最近运行 + 知识库概览 */
    h(
      'div',
      { class: 'grid grid-2 mt-16' },
      h(
        'div',
        { class: 'card' },
        h(
          'div',
          { class: 'card-title' },
          '🧵 最近运行',
          h('span', { class: 'sub' }, '来自 /api/runs，实时')
        ),
        recentRunsCard(ctx.navigate)
      ),
      h(
        'div',
        { class: 'card' },
        h(
          'div',
          { class: 'card-title' },
          '📖 知识库概览',
          h('span', { class: 'sub' }, '来自 /api/knowledge/chapters')
        ),
        knowledgeCard(ctx.navigate)
      )
    )
  );
}

export function unmount() {
  /* 本页无需清理 */
}

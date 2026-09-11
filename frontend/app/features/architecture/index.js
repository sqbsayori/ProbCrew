/**
 * 架构与分工页 —— 给团队自己看的"项目说明书"。
 *
 * 它把三件最容易在协作中走偏的事情固化在界面上：
 *   1. **契约**：前后端之间只有一条约定（事件协议），谁都不能私自改字段；
 *   2. **扩展点**：加 Agent / 工具 / 动画 / 页面各要动什么文件（都只动自己的目录）；
 *   3. **分工**：R1–R5 各 Own 什么，以及阶段里程碑。
 *
 * 数据（Agent、工具清单）实时来自后端，**不硬编码** —— 这样文档不会过期。
 */
import { h, injectStyles } from '../../core/dom.js';
import { store } from '../../core/store.js';

injectStyles('/app/features/architecture/styles.css');

const EVENT_ROWS = [
  ['run.start', '一次运行开始', 'run_id, session_id, query'],
  ['plan', 'Orchestrator 的调度计划', 'intent, steps[], reason'],
  ['agent.start', '某个 Agent 开始工作', 'agent, label'],
  ['agent.delta', 'LLM 流式增量文本', 'agent, text'],
  ['agent.end', '某个 Agent 结束', 'agent, ok, duration_ms, summary'],
  ['tool.call', '工具调用开始', 'agent, tool, args'],
  ['tool.result', '工具调用结束', 'tool, ok, data, duration_ms'],
  ['artifact', '结构化产出', 'kind（animation/chart/formula/steps/table）, payload'],
  ['hitl.request', '人机协同：暂停等待确认', 'hitl_id, agent, draft, options[]'],
  ['hitl.resolved', '人机协同：用户已处理', 'action（confirm/correct/supplement）, final'],
  ['run.end', '运行结束', 'status, final_answer'],
  ['error', '错误', 'message, agent?'],
];

const EXT_POINTS = [
  {
    title: '新增一个 Agent',
    files: ['backend/app/agents/<你的>.py'],
    body: '文件里声明 SPEC = AgentSpec(...) 并实现 async def run(state, ctx)。启动时被自动发现，自动挂进并行 fan-out。',
    never: '不需要改 graph.py / __init__.py / 路由表',
  },
  {
    title: '新增一个工具',
    files: ['backend/app/tools/<你的>.py'],
    body: '用 @tool("id", "名称", "说明") 装饰一个 async 函数即可。Agent 通过 SPEC.tools 声明自己有权限调用哪些工具（角色门控）。',
    never: '不需要改注册文件',
  },
  {
    title: '接入一个新动画',
    files: ['frontend/assets/animations/_raw/<你的>.html', 'frontend/assets/animations/manifest.json'],
    body: '把自包含 HTML 放进 _raw/，在 manifest.json 里加一条（含 id/title/controls/concepts）。前端动画库、Agent 推荐、可视化自动全部生效。',
    never: '不需要改任何前端 JS —— 清单是数据驱动的',
  },
  {
    title: '新增一个页面',
    files: ['frontend/app/features/<你的>/feature.json', 'frontend/app/features/<你的>/index.js', '（可选）styles.css'],
    body: 'feature.json 声明 id/title/route/icon/order，index.js 导出 mount/unmount。跑一次生成脚本即可出现在导航里。',
    never: '不需要改 index.html / bootstrap.js / 导航数组',
  },
  {
    title: '新增一个 API 模块',
    files: ['backend/app/api/<你的>.py'],
    body: '模块里导出 router = APIRouter(...)，启动时自动 include。',
    never: '不需要改 main.py',
  },
  {
    title: '换掉 RAG 实现（本地 → Qdrant）',
    files: ['backend/app/tools/kb_search.py'],
    body: '保持 kb_search / kb_stats 两个工具的行参和返回结构不变，把内部换成 Qdrant 混合检索即可。',
    never: '调用它的 Agent 一行都不用改',
  },
];

const ROLES = [
  { id: 'R1', name: '架构 / 集成', own: 'Knowledge Agent + RAG 对接 + 动画资产治理', lateral: '整体架构、契约把关、集成、周会' },
  { id: 'R2', name: '编排核心', own: 'LangGraph 图 + Orchestrator + Verifier + HITL', lateral: '状态图、条件边、流式事件、并发' },
  { id: 'R3', name: 'RAG 与数学工具', own: 'Visualization Agent + SymPy 工具链', lateral: 'Qdrant / 嵌入 / 分布计算 / 绘图数据' },
  { id: 'R4', name: '数据与前端', own: 'Analytics Agent + 学习记录 + 数据页', lateral: 'SQLite/PG、鉴权、前端联调兜底' },
  { id: 'R5', name: '质量与部署', own: '评估 / 可观测性 / 容器化 / CI', lateral: '内容入库 pipeline、Docker、Nginx、E2E' },
];

const PHASES = [
  { t: 'P0 · 骨架就绪', d: '本原型：契约冻结 + 图跑通 + 动画接入 + 免构建前端', done: true },
  { t: 'P1 · 契约联调', d: '五人各领一个 feature，按事件协议并行开发；每周一次集成' },
  { t: 'P2 · 真数据接入', d: '教材入库 → Qdrant 混合检索；替换 kb_search 实现' },
  { t: 'P3 · 质量闭环', d: 'Grader 多步批改 + 易错点规则库 + 人工修正回流' },
  { t: 'P4 · 评估与部署', d: 'RAGAS/自建 Eval + Docker Compose + Nginx/HTTPS' },
];

function table(title, columns, rows, sub) {
  return h(
    'div',
    { class: 'card' },
    h('div', { class: 'card-title' }, title, sub ? h('span', { class: 'sub' }, sub) : null),
    h(
      'div',
      { class: 'table-wrap' },
      h(
        'table',
        { class: 'data' },
        h('thead', {}, h('tr', {}, ...columns.map((c) => h('th', {}, c)))),
        h('tbody', {}, ...rows.map((r) => h('tr', {}, ...r.map((c) => h('td', {}, String(c ?? ''))))))
      )
    )
  );
}

export function mount(container) {
  const agents = store.get('agents') || [];
  const tools = store.get('tools') || [];
  const animations = store.get('animations') || [];

  container.append(
    h(
      'div',
      { class: 'wb-hero', style: { background: 'linear-gradient(135deg,#0f172a,#1e293b 60%,#334155)' } },
      h('h1', {}, '架构与分工'),
      h(
        'p',
        {},
        '本页是团队协作用的"活文档"：Agent / 工具清单由后端实时提供，不会过期。' +
          '核心设计目标是「多人并行开发时零文件冲突」——每个人只改自己目录里的文件。'
      ),
      h(
        'div',
        { class: 'chips' },
        h('span', {}, `${agents.length} 个 Agent`),
        h('span', {}, `${tools.length} 个工具`),
        h('span', {}, `${animations.length} 个动画`),
        h('span', {}, '契约优先 · 自动发现')
      )
    ),
    h('div', { class: 'mt-16' },
      table(
        '① 事件契约（前后端唯一约定）',
        ['事件', '含义', '关键字段'],
        EVENT_ROWS,
        'contracts/events.schema.json — 只增不改'
      )
    ),
    h(
      'div',
      { class: 'card mt-16' },
      h('div', { class: 'card-title' }, '② 扩展点：加东西时只动自己的文件'),
      h(
        'div',
        { class: 'ext-grid' },
        ...EXT_POINTS.map((e) =>
          h(
            'div',
            { class: 'ext-card' },
            h('h4', {}, e.title),
            h('div', { class: 'ext-files' }, ...e.files.map((f) => h('code', { class: 'mono' }, f))),
            h('p', {}, e.body),
            h('div', { class: 'ext-never' }, '✓ ', e.never)
          )
        )
      )
    ),
    h('div', { class: 'mt-16' },
      table(
        '③ 当前已注册的 Agent（自动发现）',
        ['id', '名称', '角色', '可调用工具', '可校验'],
        agents.map((a) => [a.id, a.name, a.role, (a.tools || []).join(', ') || '—', (a.can_verify || []).join(', ') || '—']),
        '/api/agents'
      )
    ),
    h('div', { class: 'mt-16' },
      table(
        '④ 当前已注册的工具',
        ['id', '名称', '负责人', '说明'],
        tools.map((t) => [t.id, t.name, t.owner || '—', t.description]),
        '/api/tools'
      )
    ),
    h('div', { class: 'mt-16' },
      table(
        '⑤ 五人分工（纵向 Own 模块 + 横向职责）',
        ['角色', '姓名/方向', '纵向 Own（实活）', '横向职责'],
        ROLES.map((r) => [r.id, r.name, r.own, r.lateral]),
        '对应《项目方案_多智能体学习部署规划》§4'
      )
    ),
    h(
      'div',
      { class: 'card mt-16' },
      h('div', { class: 'card-title' }, '⑥ 开发计划（阶段）'),
      h(
        'div',
        { class: 'phase-list' },
        ...PHASES.map((p) =>
          h(
            'div',
            { class: `phase-item${p.done ? ' done' : ''}` },
            h('span', { class: 'phase-dot' }, p.done ? '✓' : ''),
            h('div', {}, h('strong', {}, p.t), h('div', { class: 'small muted' }, p.d))
          )
        )
      ),
      h(
        'p',
        { class: 'small muted mt-12' },
        '详细分工、验收标准与风险应对见 docs/开发计划.md 与 docs/分工与协作规范.md。'
      )
    )
  );
}

export function unmount() {}

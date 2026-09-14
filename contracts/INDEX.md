# 契约总目录（Contract Index）

> **本文件是契约层的唯一入口。** `contracts/` 里每个文件都可以被本文件定位到，
> 不需要先读代码才知道某个字段归谁管。
>
> | | |
> |---|---|
> | 读者 | 前端、后端、评审 PR 的人 |
> | 与 schema 的分工 | 本文件讲**是什么、归谁、什么状态、有没有落地**；**字段的权威定义在 `*.schema.json`** |
> | 与 `MANIFEST.json` 的分工 | 机器读 `MANIFEST.json`（同样的元数据，JSON 格式，由 `check_contracts.py` 校验）；人读本文件 |
> | 快照 | `dev` @ `3ce581c`，2026-09-13 |

---

## 一、一分钟理解契约层

### 1.1 为什么单独成顶层目录

契约**不属于前端，也不属于后端，属于项目**。独立成 `contracts/` 是为了让它的地位一目了然。

没有契约时，多人并行开发的冲突与返工几乎全部来自"我以为你那边是这样"：

| 没有契约 | 有契约 |
|---|---|
| 前端说"后端发的字段不对" | 字段定义在 schema 里，两边照着写 |
| 后端改了个字段名，前端挂了 | schema 明写"改名是破坏性变更，需走 ADR" |
| 两个人对"校验通过"的理解不同 | `verification.schema.json` 定义了什么叫通过 |
| 联调时才发现接口对不上 | 契约先冻结，两边并行开工 |
| 新人问"这个字段是干嘛的" | schema 里有 `description` 和 `examples` |

### 1.2 三处必须同步（本项目最常见的返工来源）

```
contracts/*.schema.json      ← 权威定义（唯一真相）
        ▲
        │ 必须一致
        ▼
backend/.../events.py        ← 实现（含便捷构造器，Agent 里不要手拼 JSON）
        │
        ▼
docs/02-事件契约.md           ← 面向人的讲解（前端该怎么反应）
```

`scripts/check_contracts.py` **只能自动校验后两者**（schema ↔ 实现）。
文档靠变更时自觉更新 —— 这就是为什么每次契约变更都**必须**写 `CHANGELOG.md`。

### 1.3 按问题索引

| 我想知道… | 去哪 |
|---|---|
| 这条事件什么时候发、字段是什么 | §四 事件协议 → 再查 `events.schema.json` |
| 前端该怎么反应 | `docs/02-事件契约.md` §3 的事件清单表 |
| 什么叫"A 级验证" | §三 C3 → `verification.schema.json` |
| 工具返回什么样、怎么表示"没查到" | §三 C4 → `tool.schema.json` |
| 契约现在有没有做到 | **§五 实现状态与已知偏差** |
| 我想改契约 | §七 变更纪律 + `CHANGELOG.md` |
| 机器怎么拦我 | §八 机器校验 |

---

## 二、契约分层

契约不是一堆平级文件。按**变化的频率**分层，改上层不影响下层：

```
① 传输层  Transport    一次 run 怎么被送出去
          events.schema.json · api.md
             │  前后端唯一的运行时约定
             ▼
② 运行时层 Runtime      谁在跑、能调什么
          agent.schema.json · tool.schema.json
             │  声明式规格，由自动发现装配
             ▼
③ 数据层  Data          一次交互的输入与产物形状
          page-context.schema.json · math-task.schema.json · attempt.schema.json
             │  纯数据，不含行为
             ▼
④ 保证层  Assurance     我们敢对用户承诺什么
          verification.schema.json
             │  ★ 本项目的差异化所在
```

**依赖方向是单向的**：保证层读数据层，数据层不依赖运行时层。
所以换掉 `math-task` 的实现（比如换一个形式化器）不会波及事件协议。

---

## 三、契约登记表（**唯一权威**）

| # | 文件 | 层 | 管什么 | 状态 | Owner | 权威实现 | 谁消费 | 怎么校验 |
|---|---|---|---|---|---|---|---|---|
| C1 | `events.schema.json` | 传输 | ★ 运行时事件协议（14 种类型） | 🔒 冻结 v1.2 | R1 | `kernel/events.py` | `trace.js`、`assistant.js`、`widget/api.js` | `check_contracts.py`、`smoke_test.py`、`test_contract_events.py` |
| C2 | `api.md` | 传输 | HTTP 端点契约 | 🔒 冻结（自动生成） | R1 | `api/*.py`（FastAPI） | `widget/api.js`、`app/core/api.js` | `check_contracts.py` §5、CI 新鲜度关卡 |
| C3 | `verification.schema.json` | 保证 | ★ 验证报告：什么叫"这个答案是对的" | 🔒 冻结 v1.2 | R1 | `agents/verifier.py` | `kernel/events.py::verification_report`、前端 | `test_verifier.py`（6 项） |
| C4 | `tool.schema.json` | 运行时 | 工具规格 + 调用结果（三态） | 🔒 冻结 v1.2 | R2 | `kernel/specs.py::ToolSpec` | `tools/*.py`、`trace.js` | `check_contracts.py` §4 |
| C5 | `agent.schema.json` | 运行时 | Agent 规格：输入/输出/工具权限 | 🔒 冻结 v1.2 | R2 | `kernel/specs.py::AgentSpec` | `registry.py`、`graph.py`、架构页 | `check_contracts.py` §4 |
| C6 | `page-context.schema.json` | 数据 | 页面上下文（页面伴学） | 🔒 冻结 v1.2 | R4 | `kernel/page_context.py` | `tools/page_tools.py`、`widget/extractor.js`、`widget/frames.js` | `test_page_context.py`、`test_contract_events.py` |
| C7 | `math-task.schema.json` | 数据 | 形式化产物 MathTask | 🟡 **预留** | R3 | ⚠️ **不存在**（见 GAP-6） | 无 | 仅 schema 内嵌 examples |
| C8 | `attempt.schema.json` | 数据 | 作答事件（B 线） | 🟡 预留（B 线挂起） | R4 | — | 无 | 仅 schema 内嵌 examples |

状态图例：🔒 **冻结** = 只增不改，破坏性变更走 ADR ｜ 🟡 **预留** = 先冻结让实现方照着写，当前无产出方 ｜ ⚫ **废弃** = 不得使用

> **「权威实现」这一列很重要**：契约与代码**必须同步**。改了一处忘改另一处，
> 是本项目最常见的返工来源 —— 所以有 `scripts/check_contracts.py` 自动校验。
>
> ⚠️ 上一版这里把 C3 的权威实现写成 `kernel/verification.py`，**该文件不存在**。
> 实际在 `agents/verifier.py`（`check_contracts.py` 抓不到这种漂移，因为它是文档里的自由文本）。

---

## 四、事件协议（C1）

> 字段级定义见 `contracts/events.schema.json`；面向人的讲解见 `docs/02-事件契约.md`。
> 本节只讲**结构**：哪些事件存在、分几个阶段、按什么顺序出现。

### 4.1 传输格式

`POST /api/chat/stream` 与 `POST /api/hitl/{run_id}/resolve` 都返回 `text/event-stream`：

```
data: {"type":"run.start","ts":1730000000.1,"run_id":"run_ab12", ...}

data: {"type":"plan", ...}

...（大量 agent.delta / tool.call / tool.result / artifact）...

data: {"type":"run.end","ts":1730000002.9,"run_id":"run_ab12","status":"ok","final_answer":"..."}

event: end
data: {}
```

| 约定 | 值 |
|---|---|
| 一条事件 | 一行 `data: ` + 一个 JSON 对象，`\n\n` 结尾 |
| `null` 字段 | **不出现**（后端 `exclude_none=True`） |
| 流末尾 | 固定一帧 `event: end`，前端据此确认流正常关闭 |
| 中文 | 不转义（`ensure_ascii=False`），统一 UTF-8 |
| 未知事件类型 | **必须静默忽略** —— 这是"只增不改"能成立的前提 |

### 4.2 事件清单（14 种，按生命周期阶段）

| 阶段 | 事件 | 何时发 | 关键字段 | 发出者 |
|---|---|---|---|---|
| **open** | `run.start` | 运行开始 | `run_id`, `session_id`, `query` | `runner.py::stream_run` |
| | `context.received` | 助手已读取页面上下文 | `summary`, `data{title,chars,formula_count,frame_count,outline,…}` | `runner.py::_emit_context` |
| **route** | `plan` | Orchestrator 决策完成 | `intent`, `steps[{agent,label}]`, `reason` | `graph.py::orchestrator_node` |
| **work** | `agent.start` | 某 Agent 开始 | `agent`, `label` | `graph.py::_make_agent_node` |
| | `agent.delta` | LLM 吐出一段增量 | `agent`, `text` | `RunContext::stream_llm` |
| | `tool.call` | 工具调用开始 | `agent`, `tool`, `args` | `RunContext::emit_tool_call` |
| | `tool.result` | 工具调用结束 | `tool`, **`ok`**, `data`, `duration_ms` | `RunContext::emit_tool_result` |
| | `artifact` | 产出结构化内容 | `kind`, `payload` | `RunContext::emit_artifact` |
| | `agent.end` | 某 Agent 结束 | `agent`, `ok`, `duration_ms`, `summary` | `graph.py::_make_agent_node` |
| **verify** | `verification.report` | 所有 Agent 跑完、聚合之前 | `data`（报告全量）, `summary`, `ok` | `agents/verifier.py::verify` |
| **gate** | `hitl.request` | 图在 `interrupt()` 挂起 | `hitl_id`, `agent`, `draft`, `options[]` | `runner.py::stream_run` |
| | `hitl.resolved` | 用户已处理 | `action`, `final` | `runner.py::resume_run` |
| **close** | `run.end` | 运行结束 | `status`, `final_answer` | `runner.py::_invoke` |
| **any** | `error` | 出错 | `message`, `agent?` | `runner.py::_invoke` |

### 4.3 典型时序（实测，mock provider）

**解题类提问**（`intent=solve`）—— 注意结尾**没有** `run.end`，因为图挂起了：

```
run.start → agent.start/end(orchestrator) → plan
  → agent.start(solver) → tool.call → tool.result → agent.delta ×N
  → artifact ×2 → agent.end(solver)
  → agent.start(verifier) → tool.call → tool.result
  → verification.report → artifact → agent.end(verifier)
  → hitl.request            ← 挂起，等 /api/hitl/{run_id}/resolve
```

**概念类提问**（`intent=knowledge`）—— 正常闭合：

```
run.start → agent.start/end(orchestrator) → plan
  → agent.start(knowledge) → tool.call → tool.result → agent.delta ×N
  → artifact ×N → agent.end(knowledge)
  → agent.start(verifier) → … → verification.report → artifact → agent.end(verifier)
  → run.end                 ← status=ok, final_answer
```

### 4.4 兼容性铁律

| 变更类型 | 允许？ | 需要做什么 |
|---|---|---|
| 新增事件类型 / artifact kind | ✅ 兼容 | 加进 schema + 实现 + `CHANGELOG.md` |
| 给已有对象**新增可选字段** | ✅ 兼容 | 加进 schema，标注 since 版本 |
| 给已有对象**新增必填字段** | ⚠️ 需评估 | 先加可选、双写一段时间，再收紧 |
| 改字段名 / **改语义** | ❌ **破坏性** | 必须走 ADR（`docs/adr/`），并同步改实现与消费方 |
| 删除字段 / 删除枚举值 | ❌ **破坏性** | 同上，且需提供迁移期 |
| 收紧校验（可选→必填、放宽→收窄） | ❌ **破坏性** | 同上 |

> **「语义变更」同样算破坏性** —— 字段名没变但含义变了，比改名更危险，**因为它不会报错**。

---

## 五、Artifact 契约（`events.schema.json` 的 `kind`）

`artifact` 是"结构化产出"的载体，6 种 kind。**新增 kind 属兼容扩展；
修改已有 kind 的字段属破坏性变更**。完整 payload 示例见 `docs/02` §4。

| kind | 用途 | 关键 payload 字段 | 谁产出 |
|---|---|---|---|
| `animation` | 交互动画 | `id`, `title`, `url`, `category`, `reason`, `controls` | `tools/animation.py` |
| `chart` | 分布图（**数据，不是图片**） | `dist`, `name`, `kind`, `params`, `pdf{x,y}`, `cdf{x,y}` | `agents/visualizer.py` |
| `formula` | 公式卡 | `title`, `items[]`（**LaTeX 源串**） | `knowledge` / `solver` |
| `steps` | 解题步骤 | `title`, `count`, `steps[{index,title,body}]` | `agents/solver.py` |
| `table` | 表格 | `title`, `columns[]`, `rows[][]` | `knowledge` / `verifier` |
| `text` | 纯 Markdown 块 | `content` | 任意 Agent |

> `chart` **刻意不发 PNG**：发数据让前端用 Canvas 画 —— 可交互、可换主题、体积小、无需 matplotlib。
>
> ⚠️ `steps.payload.count` 不是装饰字段：Verifier 读它判断步骤完整性（`>= 3`）。

---

## 六、实现状态与已知偏差

> **这一节是契约层最重要的诚实清单。** 契约写了什么 ≠ 系统做到了什么。
> 每一条偏差都指向一个任务（编号见 `docs/17-模块化任务书.md`）。
> 机器可读副本在 `MANIFEST.json` 的 `known_gaps`。

| ID | 契约 | 契约承诺 | 实际 | 证据 | 修复任务 |
|---|---|---|---|---|---|
| **GAP-1** | `agent.schema.json` | 声明了工具集的 Agent 只能调被授权的工具，越权会被拒绝 | 门控逻辑在 `specs.py:99-101`，但唯一入口 `RunContext.use()`（`specs.py:200`）**写死 `allowed=None`**，全仓库无人传 `allowed` | **实测**：`orchestrator`（`AgentSpec.tools = ()`）调 `ctx.use("kb_search")` **成功返回 4 个片段**，无异常 | **K1** |
| **GAP-2** | `tool.schema.json` | `ok` 反映执行是否成功；`ok=false` 带 `error`；"查不到"是 `ok=true + empty=true` | `emit_tool_result`（`specs.py:186-190`）把 `ok` **硬编码为 `True`**；`specs.py:104` 调工具**无 try/except**；`empty` 只在 `data` 里，事件层不可见 | **实测**报文 `{"type":"tool.result","ok":true,…}`，即使 `kb_search` 自报 `empty:true`；前端 `trace.js:194` 失败分支永不触发 | **K2** |
| **GAP-3** | `verification.schema.json` + `docs/02:61,77` | 前端必须**显著**展示验证级别，不得出现"已校验"这类笼统表述 | 后端已发 `verification.report`，**前端零处理** | **实测**：`frontend/` 全目录 grep `verification` **零命中**；`trace.js` switch（99–258）与 `assistant.js` switch（924–983）均无该分支 | **X1** |
| **GAP-4** | `verification.schema.json` | A 级需 `sympy_recompute`、B 级需 `symbolic_equivalence` 支撑 | `checks` 里**从未出现**这两类 method → 按"手段封顶"规则 **A/B 恒不可达** | **实测**：数值题最终 `level=C`，证明题 `level=D` | **C2** |
| **GAP-5** | `verification.schema.json` | `disagreements` 承载多路求解分歧，"非空是重要信号" | **全仓库无任何代码产出该字段**，它只在 schema 的 `examples` 里出现过 | grep `disagreements` 在 `backend/` 下无产出方 | **C4** |
| **GAP-6** | `math-task.schema.json` | 权威实现为 `backend/app/domain/formalize.py` | **该文件不存在**；`MathTask` 只有 schema，没有产出方 | `backend/app/domain/` 下只有 `distributions.py` | **C2** |
| **GAP-7** | `events.schema.json`（`hitl.request` 触发条件） | —（契约里**根本没定义**"什么该挂起"） | 判定写在 `agents/verifier.py:238-247`（两处置 `needs_human=True`）里，属实现细节。证明题（`intent=solve`）也会触发 HITL，与 `docs/12` "高风险结论（解题）"的口径**是否一致无人裁定** | **实测**命中矩阵见 `docs/17` C3 卡片 | **C3** |

### 已闭环的偏差（保留记录，防止有人"重新发现"）

| 曾有的偏差 | 现状 | 提交 |
|---|---|---|
| `verification.report` 事件**从未在真实事件流中出现**；`verification_report()` 构造器全仓库零调用 | ✅ 已在 `verifier.py:292` 发出，实测命中并通过 schema 校验 | `3ce581c` |
| `verifier` 产出的报告**缺 `level`**、checks **缺 `method`**，且多出 5 个 `additionalProperties:false` 禁止的字段 | ✅ 报告已合规；`needs_human`/`notes`/`draft` 仍在 `verdict` 里供编排使用，但**不进报告** | `3ce581c` |
| `check_contracts.py` 的"每种事件都有便捷构造器"是**假绿**（字典硬编码 13 项，漏 `hitl.resolved`） | ✅ 改为**由事件枚举动态派生** | `a0923d8` |
| `check_contracts.py` / `smoke_test.py` / `gen_registry.py` 在中文 Windows 下 `UnicodeEncodeError` **直接崩溃**（CI 在 Linux 跑所以永远绿）。实际波及 **12 个脚本** | ✅ 统一用 `scripts/_console.py::utf8_output()` | `a0923d8` |

---

## 七、变更纪律

### 7.1 谁维护

**R1（架构/集成）是契约的唯一审批人。**

- 其他人可以提 PR：新增枚举值、新增可选字段
- 涉及**语义变更**或**破坏性变更**必须经 R1 确认，并在 `docs/adr/` 留一份 ADR
- **每次变更都要在 `CHANGELOG.md` 追加一条**

理由：契约是所有并行开发的地基。没有单一负责人，它会慢慢腐化，
最终表现为"前端说后端发的字段不对，后端说前端没按契约解析"。

### 7.2 一次契约变更要改哪些地方（清单，照着勾）

- [ ] `contracts/*.schema.json` —— 权威定义
- [ ] `backend/app/kernel/events.py` —— 实现（含便捷构造器）
- [ ] `contracts/MANIFEST.json` —— 若动了事件/kind 的目录，必须同步（`check_contracts.py` 会比对）
- [ ] `contracts/CHANGELOG.md` —— **必须**，写清"为什么改、影响谁"
- [ ] `docs/02-事件契约.md` —— 面向人的讲解（`check_contracts.py` **抓不到**这一处漂移）
- [ ] 消费方：`trace.js` / `assistant.js` / `artifacts.js`
- [ ] 破坏性变更：`docs/adr/NNNN-*.md`

### 7.3 schema 的写法约定

每份 schema 必须包含：

| 要求 | 为什么 |
|---|---|
| `title` + `description` | 读者不用看别处就知道它管什么 |
| 每个字段有 `description` | 尤其是**非直觉**的字段（如 `hint_used`、`method`） |
| 每个 schema 至少一个 `examples` | 可被自动校验，也是最好的文档 |
| 必填字段明确 `required` | 避免"这个字段到底有没有"的扯皮 |
| `additionalProperties: false` | 防止偷偷塞字段导致下游解析失败 |

**用 `examples` 而不是在 Markdown 里写示例** —— 前者能被 `check_contracts.py` 校验，后者会过期。

> ⚠️ `additionalProperties: false` 是**双刃剑**：`verifier.py` 落地 C1 时，
> 就因为有 5 个内部字段（`needs_human` / `notes` / `target_agent` / `draft` / `intent`）
> 被 schema 禁止，才不得不把它们留在 `verdict` 里、只发合规报告。
> **新增内部字段时先想清楚：它是契约的一部分，还是编排的内部状态。**

---

## 八、机器校验（不靠自觉）

```bash
python scripts/check_contracts.py
```

它做七件事（当前 **46 项**）：

| 节 | 校验内容 |
|---|---|
| 1 | **schema 自洽**：所有 `$ref` 能解析、无悬空引用、JSON 合法 |
| 2 | **示例有效**：schema 内嵌的 `examples` 必须能通过自己的校验（23 个） |
| 3 | **事件枚举与构造器一致**：`EventType` 与 `events.schema.json` 逐项比对；构造器清单**由枚举动态派生** |
| **3b** | **`MANIFEST.json` 不过期**：每份 schema 都已登记、状态值合法、`events.catalog` 与 schema 枚举一致、`events.total` 不是手写的谎话、artifact 目录一致 |
| 4 | **Agent / 工具规格一致**：7 个 AgentSpec + 16 个 ToolSpec 符合契约；Agent 声明的工具都真实存在；并**报出孤儿工具**（无 Agent 声明的死代码 —— 当前 6 个，见 `docs/17` K5） |
| 5 | **API 契约新鲜**：`api.md` 与当前 FastAPI 应用的 OpenAPI 一致 |
| 6 | **部署无关化**：前端不得写死后端地址 |

以及端到端自检里的契约检查：

```bash
python scripts/smoke_test.py        # 第 4 节：实际发出的事件是否都在白名单内
```

**CI 里必须跑这两个**（`.github/workflows/ci.yml`）。任何越界事件都会让流水线红灯 ——
这就是契约不会被悄悄破坏的原因。

### 还没被自动覆盖的盲区

| 盲区 | 后果 | 计划 |
|---|---|---|
| `docs/02-事件契约.md` 与 schema 的一致性 | 文档会漂移（C3 那处 `kernel/verification.py` 就是这么来的） | G2 之后由 `scripts/check_docs.py` 覆盖（见 `docs/18` §五 动作 D） |
| `docs/**` 里的路径、端点、数字 | 写错也没人发现（`api/learning_log.py` 不存在、`/api/runs/{id}` 端点名不对） | 同上 |
| `verification.schema.json` 的**报告实例**是否真的合规 | 已有覆盖（`test_verifier.py` 用 schema 校验真实 report 实例），但只在单测里，不在 `check_contracts.py` | 可考虑并入 §2 |

> ✅ `MANIFEST.json` 与 schema 的一致性**已不是盲区** —— §3b 就是为此加的。

---

## 九、自动生成与禁改清单

| 文件 | 规则 |
|---|---|
| `api.md` | **由 `scripts/gen_api_contract.py` 生成，请勿手工编辑。** 改 API 后跑 `python scripts/gen_api_contract.py`，`check_contracts.py` 会校验新鲜度 |
| `CHANGELOG.md` | 手工维护，**只追加不修改**历史条目 |
| `MANIFEST.json` | 手工维护；改动事件/kind 目录时必须同步 |
| `*.schema.json` | 手工维护；冻结后只增不改 |

---

## 十、与其他文档的关系

| 文档 | 关系 |
|---|---|
| `docs/02-事件契约.md` | 面向**人**的事件协议讲解（含前端该怎么反应、artifact payload 示例） |
| `docs/01-架构总览.md` | 契约在整个架构里的位置 |
| `docs/17-模块化任务书.md` | 每条 GAP 对应的任务卡片、写入范围与验收命令 |
| `docs/18-文档地图.md` | 每个主题的**单一权威文档**是哪一份 |
| `docs/09-主线范围与数据需求清单.md` | 主线要建什么，决定了契约要加什么 |
| `contracts/CHANGELOG.md` | 「为什么改」—— `check_contracts.py` 校验不了的唯一东西 |
| `contracts/MANIFEST.json` | 本文件 §三 §四 §六 的机器可读副本 |

# 契约变更历史

> **规则**：每次契约变更都必须在这里追加一条。
> 破坏性变更必须附 ADR 链接（见 `docs/adr/`）。
>
> 为什么这个文件重要：`check_contracts.py` 能校验「契约 ↔ 实现」一致，
> 但**校验不了「为什么改」**。半年后有人问"这个字段什么时候加的、为什么"，
> 答案只能在这里。

---

## 格式

```
## [契约版本] · YYYY-MM-DD

### 类型（破坏性 / 兼容 / 修正）
- **文件**：改了什么
  - 为什么改
  - 影响谁（哪些模块要跟着改）
```

---

## [v1.4] · 2026-09-16

### 新增 + 修正（账号体系落地 —— **有破坏性影响，需 ADR 追认**）

- **新增 `user.schema.json` v1.0（frozen）**：账号的对外视图。
  - 为什么：账号是权限的唯一来源，必须有契约层约束"返回什么、不返回什么"。
    `additionalProperties:false` 直接堵住"顺手把 password_hash 下发出去"这类事故。
  - 影响：`api/auth.py`、`api/admin.py` 的所有响应；`core/auth.js`、管理页。

- **`attempt.schema.json`：`student_id` 的语义变更（破坏性）**
  - 原：`student_id = session_id`（浏览器匿名 id）。
  - 现：`student_id = user_id`（账号 id），并新增 `user_id` 列。
  - 为什么：接口收紧为"必须登录"之后，身份只能来自令牌；
    按浏览器 session 归属会让"换个浏览器"变成另一个人（统计与越权都出问题）。
  - 影响：`student_attempt` 表加列 + 迁移脚本；`api/practice.py` 写入路径；
    **旧数据**统一归属到不可登录的 `usr_history` 账号。

- **`mastery` 聚合主键变更（破坏性）**：`(session_id, topic)` → `(user_id, topic)`
  - 为什么：同一个人换浏览器就是另一个 session，按 session 聚合会把掌握度拆成几份。
  - 影响：`docs/21 §5.3` 的表述、`tools/learning_log.py`、迁移脚本。

- **`api.md` 重生成**：新增 `auth/*`、`me/*`、`admin/*` 共 18 个端点；
  并标注 `/api/stats/{sid}`、`/api/wrong/{sid}` 为**旧口径**（身份以令牌为准，路径参数被忽略）。

- **新增"必须登录"约束**：除 `/api/health`、`/api/auth/login`、静态资源外，全部端点需 `Authorization: Bearer`。
  - 为什么：这是修一个**实测出来的泄漏** —— 未鉴权时 `GET /api/runs` 会明文返回所有人
    的提问原文（L2 数据），`/api/runs/{id}/timeline` 还会回传完整答案增量（单次 36 KB）。

> ⚠️ 破坏性变更应附 ADR（见 `docs/adr/`）。本次的三处修正**需要补一份 ADR**
> （账号体系与身份口径），否则违反 `contracts/README.md` 第三节的约定。

## [v1.3] · 2026-09-15

### 修正（`attempt.schema.json` 拆层 —— **无破坏性结构变更**）

- **`attempt.schema.json`**：把契约拆成**两层**，激活状态不同（`v1.2` → `v1.3`）
  - **① 记录层：已启用**（主站 `X5` 刷题 / `X6` 错题本）。
    本地 SQLite、按浏览器匿名 `session_id` 归属、不出校、无 PII。
    **不需要知情同意，不依赖 B线** —— 它与已经跑起来的 `qa_log` 表是同一合规性质。
  - **② 建模层：仍挂起**（B线：学习者建模 / 教师端），需知情同意 + 脱敏 + 权限隔离。
  - **为什么改**：`v1.2` 把整份契约标为「预留 —— B线挂起，暂不实现」。
    但 B线挂起的**真正原因**是「依赖真实学生数据（需知情同意 + 学校配合）」，
    而**记录作答这个动作本身并不触发那个前提**。把两者绑在一起造成两个实际损失：
    ① 主站错题本（`X6`）无谓地等一个外部不可控资源；
    ② 将来 B线启动时，历史作答数据是空白的 —— 而 `hint_used` / `duration_ms`
    这类字段**事后无法补录**。
  - **结构影响：无。** 字段、`required`、`enum`、`additionalProperties` 一律未动，
    `student_id` 在记录层取 `session_id` 同值即可满足。**没有破坏性变更，无需 ADR。**
  - **影响谁**：`docs/17` 的 `X6` 卡片（依赖从「B线」改为「立即」）；
    `docs/21` 的数据模型章节；`backend/app/tools/learning_log.py`（待新增 `attempt` 写入，
    `producer` 暂留 `null`，落地后回填）。
  - 新增 1 条 `examples`（记录层形态）；示例总数 3，`check_contracts.py` 变为 47 项。

### 修正（描述文本 —— 无结构变更）

- **`attempt.schema.json`**：`hint_used` 与 `source` 两处 `description` 里的 `\n`
  之前是**字面的反斜杠 n**（json.load 后渲染成 `\n` 两个字符），改为真正的换行。
- **`MANIFEST.json` 的 `GAP-4`**：原文写「A/B 恒不可达，实测数值题最终 level=C」——
  **实测该结论低估了缺陷**：`heuristic` 的上限即为 D，且「上游执行」检查无条件存在，
  因此**按最弱手段封顶后 A/B/C 三级全部不可达，所有解答恒为 D**，
  `confidence` 永久封顶 0.4。已按实测更正 `claim` / `reality` / `evidence` 三栏。

---

## [v1.2] · 2026-09-12

### 兼容新增

- **`events.schema.json`**：新增事件类型 `verification.report`
  - 主线 M1「正确性保障链」需要把验证结论作为一等事件发出来，
    而不是塞进 `artifact`。理由：它是一个独立的生命周期节点
    （所有 Agent 跑完、aggregate 之前），且前端要显著展示验证级别。
  - 影响：`backend/app/kernel/events.py`（新增 `verification_report()` 构造器）；
    前端如需展示验证级别，监听此事件。
  - **兼容性**：老前端忽略未知事件类型即可，无需改动。

- **`events.schema.json`**：补 9 条 `examples`
  - 之前这份最重要的契约一个示例都没有。示例可被 `check_contracts.py`
    自动校验，比在 Markdown 里写示例更不容易过期。

### 新增契约

- **`verification.schema.json`**（新）
  - 定义"什么叫这个答案是对的"，以及系统在什么情况下必须承认不确定。
  - 核心是 A/B/C/D 四级：A 数值可完全验证 / B 符号可强验证 /
    C 应用题可交叉验证 / D 证明题不做承诺。
  - **这条契约是主线对用户的承诺**：绝不允许在没有验证报告的情况下输出解答。

- **`math-task.schema.json`**（新）
  - M1.1 形式化的产物结构。后面的数值重算、符号校验、约束检查全依赖它。
  - 关键字段 `source_text`（每个已知量必须能追溯到题干原句）——
    没有出处的已知量就是幻觉的来源。

- **`agent.schema.json`**（新）
  - 把一直存在但没写下来的 AgentSpec / AgentResult 契约化。

- **`tool.schema.json`**（新）
  - 定义 `ok` / `empty` / `available` 三态约定。
    **「查不到」不等于「失败」** —— 混为一谈会让 Agent 误判为工具故障而反复重试。

- **`page-context.schema.json`**（新）
  - 把已经实现的页面上下文契约化。特别固定了 `score` 的计算口径
    （`len(text) + 40×公式 + 20×标题 + 600×选中 + 200×媒体`）——
    前后端必须用同一口径，否则多 frame 仲裁结果会不一致。

- **`attempt.schema.json`**（新，⏸ 预留）
  - B线的数据契约。**B线已挂起**（见 `docs/09`），此文件先行冻结，
    因为整条 B线的模型都吃这张表，schema 必须先定再动手。
  - 特别标注了 `hint_used` 与 `duration_ms` 两个字段：
    少了它们，BKT 会把"独立答对"与"被提示后答对"当成同一个观测，模型直接失效。

### 工具链

- **`scripts/check_contracts.py`**（新）
  - 5 类校验共 38 项：schema 自洽 / 示例有效 / 事件枚举一致 /
    Agent 与工具规格一致 / API 契约新鲜度。
  - 已用三个负向测试验证过它真的能拦住问题（见该文件注释）。
- **`scripts/gen_api_contract.py`**（新）
  - 从 FastAPI 应用生成 `contracts/api.md`。手写 API 文档一定会过期。
- **`contracts/api.md`**（新，自动生成）
  - 19 个端点的完整契约。**请勿手工编辑。**

---

## [v1.1] · 2026-09-11

### 兼容新增

- **`events.schema.json`**：新增事件类型 `context.received`
  - 页面伴学需要让用户**看得见助手读到了什么**。读不到时也要发
    （`chars: 0`），否则用户会困惑"为什么它不知道我指的是哪段"。

- **`events.schema.json`**：`run.end` 增加字段 `final_answer`
  - 前端要用聚合后的最终答案替换逐 Agent 的流式块。

---

## [v1.0] · 2026-09-11

### 首次冻结

- **`events.schema.json`**：12 种事件类型
  - `run.start` / `plan` / `agent.start` / `agent.delta` / `agent.end` /
    `tool.call` / `tool.result` / `artifact` / `hitl.request` /
    `hitl.resolved` / `run.end` / `error`
  - 这 12 种是前后端之间**唯一**的约定。冻结后所有并行开发以此为准。

- **`contracts/README.md`**：确立「只增不改」铁律与 R1 单一审批人制度。

---

## 待办（尚未落地，先记录）

| 事项 | 触发条件 |
|------|---------|
| `attempt.schema.json` **记录层**落地（`producer` 回填 + `consumers` 登记） | `X5`/`X6` 开工时 |
| `attempt.schema.json` **建模层**从"预留"转为"生效" | B线启动（见 `docs/09` 第六节） |
| 契约版本号写进 schema 的 `$id` | 第一次出现破坏性变更时 |
| `error.schema.json`（结构化错误码） | 当错误处理需要跨语言/跨进程区分时 |
| MCP 工具的契约扩展（`dangerous` 字段启用） | P2 之后接外部工具时 |

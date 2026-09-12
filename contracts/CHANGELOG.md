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
| `attempt.schema.json` 从"预留"转为"生效" | B线启动（见 `docs/09` 第六节） |
| 契约版本号写进 schema 的 `$id` | 第一次出现破坏性变更时 |
| `error.schema.json`（结构化错误码） | 当错误处理需要跨语言/跨进程区分时 |
| MCP 工具的契约扩展（`dangerous` 字段启用） | P2 之后接外部工具时 |

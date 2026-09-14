# contracts/ · 契约层

> **这是 ProbCrew 唯一的跨端、跨模块约定。**
> 独立成顶层目录，是为了让它的地位一目了然：它不属于前端，也不属于后端，**属于项目**。

---

## 一、为什么要有契约层

多人并行开发时，冲突与返工几乎全部来自"我以为你那边是这样"。
契约层的唯一目的就是**把这个"以为"变成白纸黑字**：

| 没有契约 | 有契约 |
|---------|--------|
| 前端说"后端发的字段不对" | 字段定义在 schema 里，两边照着写 |
| 后端改了个字段名，前端挂了 | schema 明写"改名是破坏性变更，需走 ADR" |
| 两个人对"校验通过"的理解不同 | `verification.schema.json` 定义了什么叫通过 |
| 联调时才发现接口对不上 | 契约先冻结，两边并行开工 |
| 新人问"这个字段是干嘛的" | schema 里有 description 和 example |

---

## 二、文件清单

| 文件 | 管什么 | 权威实现 | 状态 |
|------|--------|---------|------|
| **`events.schema.json`** | ★ 运行时事件协议（前后端唯一约定） | `backend/app/kernel/events.py` | 已冻结 v1 |
| **`verification.schema.json`** | ★ 验证级别与验证报告（M1 核心） | 报告构造：`backend/app/agents/verifier.py`；事件出口：`backend/app/kernel/events.py::verification_report()` | ✅ 已实现（A1） |
| **`math-task.schema.json`** | 形式化产物 MathTask（M1.1） | `backend/app/domain/formalize.py` | 待实现 |
| `agent.schema.json` | Agent 规格：输入 / 输出 / 工具权限 | `backend/app/kernel/specs.py::AgentSpec` | 已实现 |
| `tool.schema.json` | 工具规格：签名 / 返回值 / 错误 | `backend/app/kernel/specs.py::ToolSpec` | 已实现 |
| `page-context.schema.json` | 页面上下文（页面伴学） | `backend/app/kernel/page_context.py` | 已实现 |
| `api.md` | HTTP API 契约 | `backend/app/api/*.py` | **自动生成** |
| `attempt.schema.json` | 作答事件（B线用） | — | ⏸ 预留，B线挂起 |

**「权威实现」那一列很重要**：契约与代码**必须同步**。
改了一处忘改另一处，是本项目最常见的返工来源 —— 所以有 `scripts/check_contracts.py` 自动校验。

---

## 三、只增不改（Additive Only）

这是契约层的**铁律**。违反它的代价是所有人的代码同时出问题。

| 变更类型 | 允许？ | 需要做什么 |
|---------|--------|-----------|
| 新增枚举值（新事件类型 / 新 artifact kind） | ✅ 兼容 | 加进 schema + 实现 + `CHANGELOG.md` |
| 给已有对象**新增可选字段** | ✅ 兼容 | 加进 schema，标注 since 版本 |
| 给已有对象**新增必填字段** | ⚠️ 需评估 | 先加可选、双写一段时间，再收紧 |
| 改字段名 / 改语义 | ❌ **破坏性** | 必须走 ADR（`docs/adr/`），并同步改实现与消费方 |
| 删除字段 / 删除枚举值 | ❌ **破坏性** | 同上，且需提供迁移期 |
| 收紧校验（可选→必填、放宽→收窄取值范围） | ❌ **破坏性** | 同上 |

**「语义变更」同样算破坏性** —— 字段名没变但含义变了，比改名更危险，因为它不会报错。

---

## 四、谁维护

**R1（架构/集成）是契约的唯一审批人。**

- 其他人可以提 PR 新增枚举值 / 可选字段
- 涉及**语义变更**或**破坏性变更**必须经 R1 确认，并在 `docs/adr/` 留一份 ADR
- 每次契约变更都要在 `CHANGELOG.md` 追加一条

理由：契约是所有并行开发的地基。没有单一负责人，它会慢慢腐化，
最终表现为"前端说后端发的字段不对，后端说前端没按契约解析"。

---

## 五、机器校验（不靠自觉）

```bash
python scripts/check_contracts.py
```

它做四件事：

1. **schema 自洽**：所有 `$ref` 能解析、没有悬空引用、JSON 合法
2. **契约 ↔ 实现一致**：`EventType` 枚举与 `events.schema.json` 逐项比对
3. **示例有效**：schema 里内嵌的 `examples` 必须能通过自己的校验
4. **API 契约新鲜**：`api.md` 与当前 FastAPI 应用的 OpenAPI 一致

以及端到端自检里的契约检查：

```bash
python scripts/smoke_test.py        # 第 4 节：实际发出的事件是否都在白名单内
```

**CI 里必须跑这两个。** 任何越界事件都会让流水线红灯 —— 这就是契约不会被悄悄破坏的原因。

---

## 六、契约的写法约定

每份 schema 必须包含：

| 要求 | 为什么 |
|------|--------|
| `title` + `description` | 读者不用看别处就知道它管什么 |
| 每个字段有 `description` | 尤其是**非直觉**的字段（如 `hint_used`） |
| 每个 schema 至少一个 `examples` | 可被自动校验，也是最好的文档 |
| 必填字段明确 `required` | 避免"这个字段到底有没有"的扯皮 |
| `additionalProperties: false` | 防止偷偷塞字段导致下游解析失败 |

**用 `examples` 而不是在 Markdown 里写示例** —— 前者能被 `check_contracts.py` 验证，后者会过期。

---

## 七、和其他文档的关系

| 文档 | 关系 |
|------|------|
| `docs/02-事件契约.md` | 面向**人**的事件协议讲解（含前端该怎么反应） |
| `contracts/events.schema.json` | 面向**机器**的权威定义 |
| `backend/app/kernel/events.py` | **实现**（含便捷构造器，Agent 里不要手拼 JSON） |
| `docs/01-架构总览.md` | 契约在整个架构里的位置 |
| `docs/09-主线范围与数据需求清单.md` | 主线要建什么，决定了契约要加什么 |

**三处（文档 / schema / 实现）必须同步。**
`check_contracts.py` 只能自动校验后两者，文档靠变更时自觉更新 —— 这就是为什么每次契约变更都要写 CHANGELOG。

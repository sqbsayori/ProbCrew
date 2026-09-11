# 团队角色映射（R1–R5）

> **请每位成员在 Day 1–2 内把自己的名字填进来**，然后提交 PR。
> 这份文件是分工的最终依据；`docs/04-分工与协作规范.md` 定义了每个角色的 Own 目录。

---

## 角色表

| 角色 | 姓名 | Own 的目录（见 `docs/04` §2） | 主要交付 | 状态 |
|------|------|---------------------------|---------|------|
| **R1** 架构 / 集成 | _待填_ | `agents/knowledge.py`、`tools/kb_search.py`、`knowledge_base/`、`frontend/assets/animations/`、`features/knowledge/`、`features/animations/`、`contracts/` | 契约冻结、动画资产、内容与合规 | ⬜ |
| **R2** 编排核心 | _待填_ | `kernel/graph.py`、`kernel/state.py`、`kernel/runner.py`、`agents/orchestrator.py`、`agents/_router.py`、`agents/verifier.py`、`components/trace.js`、`components/run-panel.js` | 编排稳定性、HITL、批改闭环 | ⬜ |
| **R3** RAG 与数学工具 | _待填_ | `domain/distributions.py`、`tools/math_tools.py`、`agents/visualizer.py`、`features/visualize/` | Qdrant 混合检索、数学正确性 | ⬜ |
| **R4** 数据与前端 | _待填_ | `tools/learning_log.py`、`agents/analytics.py`、`api/chat.py`、`api/system.py`、`frontend/app/core/`、`components/artifacts.js`、`components/chart.js`、`features/analytics/` | 数据模型、鉴权、前端联调兜底 | ⬜ |
| **R5** 质量与部署 | _待填_ | `scripts/`、`backend/tests/`、`deployment/`（新建）、`docs/team-notes/` | CI/CD、内容入库、评估、部署 | ⬜ |

---

## 横向职责（不属于某一个人）

| 事项 | 负责人 | 说明 |
|------|--------|------|
| 契约变更审批 | R1 | 唯一审批人；破坏性变更需 ADR |
| 内核接口变更（`kernel/specs.py`） | R2 | 所有 Agent 都依赖它 |
| 数学结论最终把关 | R3 | 有争议时以教材/老师为准 |
| 前端交互风格统一 | R4 | 共享样式改动需在 PR 说明影响范围 |
| 演示环境守门 | R5 | 每次集成后确认 `dev` 可演示 |
| 周会主持与纪要 | R1 | 纪要入 `docs/team-notes/YYYY-MM-DD.md` |

---

## 技能盘点（用于后续任务派发）

> 填实后有助于把"最难的活给最合适的人"，也便于 R1 做负载均衡。

| 姓名 | Python | LangGraph | 前端 JS | Docker/运维 | 数学基础 | 备注 |
|------|--------|-----------|--------|------------|---------|------|
| _待填_ | | | | | | |
| _待填_ | | | | | | |
| _待填_ | | | | | | |
| _待填_ | | | | | | |
| _待填_ | | | | | | |

---

## 本周（P1 第一周）个人清单

见 `docs/05-开发计划.md` §7「立刻可执行：第一周清单」。
请在该文件里勾选，不要在这里重复维护。

---

## 联系方式

| 姓名 | 微信/QQ | 常用时段 |
|------|---------|---------|
| _待填_ | | |
| _待填_ | | |
| _待填_ | | |
| _待填_ | | |
| _待填_ | | |

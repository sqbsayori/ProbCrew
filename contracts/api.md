# contracts/api.md · HTTP API 契约

> **本文件由 `scripts/gen_api_contract.py` 自动生成，请勿手工编辑。**
> 修改 API 后运行 `python scripts/gen_api_contract.py` 重新生成。
> `scripts/check_contracts.py` 会校验本文件与实现是否一致。

## 约定

| 项 | 约定 |
|----|------|
| 基础路径 | 无前缀，直接挂在根上（`/api/...`） |
| 编码 | 请求与响应统一 UTF-8；中文不转义 |
| 内容类型 | `application/json`；流式端点为 `text/event-stream` |
| 错误格式 | FastAPI 默认：`{"detail": "..."}`；校验失败为 422 |
| 流式协议 | 见 `contracts/events.schema.json`（SSE 每帧 `data: <json>`） |
| 版本策略 | 只增不改；破坏性变更走 ADR（见 `contracts/README.md`） |

## 端点总览


| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/agents` | 所有已注册的 Agent（自动发现） |
| `GET` | `/api/tools` | 所有已注册的工具（自动发现） |
| `GET` | `/api/animations` | 交互动画清单 |
| `POST` | `/api/animations/recommend` | 按问题推荐交互动画 |
| `GET` | `/api/animations/{animation_id}` | 单个动画详情 |
| `GET` | `/api/distributions` | 可视化模块支持的分布 |
| `GET` | `/api/distributions/{dist}/properties` | 分布性质（SymPy 推导） |
| `GET` | `/api/distributions/{dist}/series` | 分布绘图数据（PDF/CDF） |
| `POST` | `/api/chat/stream` | 发起一次多 Agent 协作（SSE） |
| `POST` | `/api/hitl/{run_id}/resolve` | 人机协同：处理待确认结论（SSE） |
| `GET` | `/api/runs` | 最近的运行列表 |
| `GET` | `/api/runs/{run_id}` | 取回一次运行的完整事件轨迹 |
| `GET` | `/api/runs/{run_id}/timeline` | 单次运行的结构化轨迹 |
| `GET` | `/api/knowledge/chapters` | 课程章节目录（含知识点） |
| `GET` | `/api/problems/examples` | 典型例题库 |
| `GET` | `/api/problems/examples/{example_id}` | 单道例题详情 |
| `GET` | `/raw-live/` | 原始动画导航页（带悬浮窗） |
| `GET` | `/raw-live/{filename}` | 任意原始动画页（带悬浮窗） |
| `GET` | `/api/raw-live/list` | 可注入的原始动画清单 |
| `GET` | `/api/health` | 健康检查（含各子系统状态） |
| `GET` | `/api/stats/{session_id}` | 某会话的学习统计 |

## Agent 目录

### `GET /api/agents`

**所有已注册的 Agent（自动发现）**

响应：`200`

## 工具目录

### `GET /api/tools`

**所有已注册的工具（自动发现）**

响应：`200`

## 交互动画

### `GET /api/animations`

**交互动画清单**

响应：`200`, `422`

### `POST /api/animations/recommend`

**按问题推荐交互动画**

请求体：`RecommendRequest`（必填）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | `string` | ✓ |  |
| `top_k` | `integer` |  |  |

响应：`200`, `422`

### `GET /api/animations/{animation_id}`

**单个动画详情**

响应：`200`, `422`

## 分布计算

### `GET /api/distributions`

**可视化模块支持的分布**

响应：`200`

### `GET /api/distributions/{dist}/properties`

**分布性质（SymPy 推导）**

响应：`200`, `422`

### `GET /api/distributions/{dist}/series`

**分布绘图数据（PDF/CDF）**

响应：`200`, `422`

## 对话与编排

### `POST /api/chat/stream`

**发起一次多 Agent 协作（SSE）**

请求体：`ChatRequest`（必填）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | `string` | ✓ | 用户问题 |
| `session_id` | `string` |  |  |
| `chapter` | `string / null` |  |  |
| `page_context` | `object / null` |  | 当前页面上下文（页面伴学功能的数据来源） |

响应：`200`, `422`

## 人机协同（HITL）

### `POST /api/hitl/{run_id}/resolve`

**人机协同：处理待确认结论（SSE）**

请求体：`HitlResolveRequest`（必填）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | `string` |  |  |
| `text` | `string` |  |  |

响应：`200`, `422`

## 运行轨迹

### `GET /api/runs`

**最近的运行列表**

响应：`200`, `422`

### `GET /api/runs/{run_id}`

**取回一次运行的完整事件轨迹**

响应：`200`, `422`

### `GET /api/runs/{run_id}/timeline`

**单次运行的结构化轨迹**

把扁平的事件流整理成"阶段 + 条目"，便于前端画时间轴。

响应：`200`, `422`

## 知识库

### `GET /api/knowledge/chapters`

**课程章节目录（含知识点）**

响应：`200`

## 题库与例题

### `GET /api/problems/examples`

**典型例题库**

响应：`200`, `422`

### `GET /api/problems/examples/{example_id}`

**单道例题详情**

响应：`200`, `422`

## 其他

### `GET /raw-live/`

**原始动画导航页（带悬浮窗）**

`/raw-live/` 直接给导航页，省得手打 index.html。

响应：`200`

### `GET /raw-live/{filename}`

**任意原始动画页（带悬浮窗）**

响应：`200`, `422`

## 原始动画注入

### `GET /api/raw-live/list`

**可注入的原始动画清单**

列出 `/raw-live/` 下可访问的页面，方便前端做入口。

注意：**不回传绝对路径**。这个接口以前会返回 `str(RAW_ANIMATIONS_DIR)`，
等于把服务器的目录结构 + 用户名暴露给任何访问者；对分发包来说更是
毫无用处的信息。改用符号名 + 描述性 hint。

响应：`200`

## 系统

### `GET /api/health`

**健康检查（含各子系统状态）**

响应：`200`

## 学习统计

### `GET /api/stats/{session_id}`

**某会话的学习统计**

响应：`200`, `422`

---

*共 21 条路径 · 21 个端点*

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
| `GET` | `/api/admin/audit` | 审计日志 |
| `GET` | `/api/admin/export/students.csv` | 导出学生统计 CSV |
| `GET` | `/api/admin/overview` | 全班统计 |
| `GET` | `/api/admin/students` | 学生列表（分页 + 搜索 + 排序） |
| `POST` | `/api/admin/students` | 新建学生账号 |
| `POST` | `/api/admin/students/import` | CSV 批量建号 |
| `GET` | `/api/admin/students/{user_id}` | 学生详情 + 逐题明细 |
| `DELETE` | `/api/admin/students/{user_id}/data` | 删除某学生的全部数据 |
| `POST` | `/api/admin/students/{user_id}/reset-password` | 重置学生密码 |
| `POST` | `/api/admin/students/{user_id}/status` | 禁用 / 启用学生账号 |
| `POST` | `/api/auth/login` | 登录（返回服务端会话令牌） |
| `POST` | `/api/auth/logout` | 登出（撤销当前令牌） |
| `GET` | `/api/auth/me` | 当前登录用户 |
| `POST` | `/api/auth/password` | 修改自己的密码 |
| `GET` | `/api/me/mastery` | 我的知识点掌握度 |
| `GET` | `/api/me/stats` | 我的学习统计（主页用） |
| `GET` | `/api/me/wrong` | 我的错题本（按知识点聚合） |
| `POST` | `/api/practice/grade` | 判定作答（确定性批改 + 记录 attempt） |
| `GET` | `/api/practice/questions` | 题库列表（不含答案） |
| `GET` | `/api/practice/questions/{item_id}` | 单题题干（可含提示） |
| `GET` | `/api/wrong/{session_id}` | 错题本（旧路径，保留兼容） |
| `GET` | `/raw-live/` | 原始动画导航页（带悬浮窗） |
| `GET` | `/raw-live/{filename}` | 任意原始动画页（带悬浮窗） |
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
| `GET` | `/api/runs` | 最近的运行列表（只列自己的） |
| `GET` | `/api/runs/{run_id}` | 取回一次运行的完整事件轨迹 |
| `GET` | `/api/runs/{run_id}/timeline` | 单次运行的结构化轨迹 |
| `GET` | `/api/knowledge/chapters` | 课程章节目录（含知识点） |
| `GET` | `/api/problems/examples` | 典型例题库 |
| `GET` | `/api/problems/examples/{example_id}` | 单道例题详情 |
| `GET` | `/api/raw-live/list` | 可注入的原始动画清单 |
| `GET` | `/api/health` | 健康检查（含各子系统状态） |
| `GET` | `/api/stats/{session_id}` | 我的学习统计（旧路径，保留兼容） |

## 其他

### `GET /api/admin/audit`

**审计日志**

响应：`200`, `422`

### `GET /api/admin/export/students.csv`

**导出学生统计 CSV**

响应：`200`, `422`

### `GET /api/admin/overview`

**全班统计**

响应：`200`, `422`

### `GET /api/admin/students`

**学生列表（分页 + 搜索 + 排序）**

响应：`200`, `422`

### `POST /api/admin/students`

**新建学生账号**

请求体：`CreateStudentRequest`（必填）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `username` | `string` | ✓ |  |
| `display_name` | `string` |  |  |
| `password` | `string` |  |  |

响应：`201`, `422`

### `POST /api/admin/students/import`

**CSV 批量建号**

CSV 表头：`username,display_name,password`（password 可留空 → 自动生成）。

逐行处理、逐行报告：**重复用户名跳过**（不算失败，方便反复导入同一份名单），
格式错误行进 `failed` 并带行号，方便学生自己改表。

请求体：`ImportRequest`（必填）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `csv_text` | `string` | ✓ |  |

响应：`200`, `422`

### `GET /api/admin/students/{user_id}`

**学生详情 + 逐题明细**

响应：`200`, `422`

### `DELETE /api/admin/students/{user_id}/data`

**删除某学生的全部数据**

**不可逆**。删掉作答/问答/掌握度，并把账号脱敏（保留一行壳以便审计可追溯）。

前端必须二次确认（输入用户名那种），这里只负责执行 + 留痕。

响应：`200`, `422`

### `POST /api/admin/students/{user_id}/reset-password`

**重置学生密码**

响应：`200`, `422`

### `POST /api/admin/students/{user_id}/status`

**禁用 / 启用学生账号**

请求体：`StatusRequest`（必填）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `status` | `string` | ✓ |  |

响应：`200`, `422`

### `POST /api/auth/login`

**登录（返回服务端会话令牌）**

请求体：`LoginRequest`（必填）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `username` | `string` | ✓ |  |
| `password` | `string` | ✓ |  |

响应：`200`, `422`

### `POST /api/auth/logout`

**登出（撤销当前令牌）**

响应：`200`

### `GET /api/auth/me`

**当前登录用户**

响应：`200`

### `POST /api/auth/password`

**修改自己的密码**

改密 → **撤销该用户全部令牌** → 给当前设备发一张新的。

这样"我在别处登录过"的会话会立刻失效，而我自己不用重新登录。

请求体：`PasswordChangeRequest`（必填）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `old_password` | `string` | ✓ |  |
| `new_password` | `string` | ✓ |  |

响应：`200`, `422`

### `GET /api/me/mastery`

**我的知识点掌握度**

响应：`200`

### `GET /api/me/stats`

**我的学习统计（主页用）**

响应：`200`

### `GET /api/me/wrong`

**我的错题本（按知识点聚合）**

响应：`200`, `422`

### `POST /api/practice/grade`

**判定作答（确定性批改 + 记录 attempt）**

判定一次作答。

三态语义（`docs/21` §6.4 ①）：
  * `graded=true`  → 正确
  * `graded=false` → 错误（含错因定位）
  * `graded=null`  → **没能解析出答案**，不算错，**不写 attempt**，请学生换个写法

⚠️ 两条加固（上一轮审计的实测缺陷，这里必须守住）：
  1. `student_answer` 有长度上限（200 字）。旧版无上限，实测一个 10 万位的
     数字答案会让 `normalize_answer` 里的正则**平方级回溯**，把整个进程卡死两分钟；
     再加上 `9**9**9` 这种短但会算爆的表达式，一个请求就能让全站不可用。
  2. `grader.grade()` 是**纯 CPU 同步调用**，放在 `async def` 里会独占事件循环
     （实测：一个慢请求期间连 `/api/health` 都超时）。所以丢到线程池跑。

请求体：`GradeRequest`（必填）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `item_id` | `string` | ✓ |  |
| `student_answer` | `string` |  |  |
| `session_id` | `string` |  |  |
| `hint_used` | `integer` |  |  |
| `duration_ms` | `integer` |  |  |
| `reveal` | `boolean` |  |  |

响应：`200`, `422`

### `GET /api/practice/questions`

**题库列表（不含答案）**

列出可做的题。**响应中不含任何答案相关字段**（红线 1）。

响应：`200`, `422`

### `GET /api/practice/questions/{item_id}`

**单题题干（可含提示）**

响应：`200`, `422`

### `GET /api/wrong/{session_id}`

**错题本（旧路径，保留兼容）**

错题本。**身份以令牌为准**，路径里的 `session_id` 只作日志对照。

⚠️ 为什么必须这样：旧实现用路径参数当身份 → 改一个参数就能读别人的错题本
（上一轮审计实测：`GET /api/wrong/随便一个人` 返回 200）。
现在这个参数**不参与取数**，只保留在 URL 里让旧前端不 404。
新前端请用 `/api/me/wrong`。

响应：`200`, `422`

### `GET /raw-live/`

**原始动画导航页（带悬浮窗）**

`/raw-live/` 直接给导航页，省得手打 index.html。

响应：`200`

### `GET /raw-live/{filename}`

**任意原始动画页（带悬浮窗）**

响应：`200`, `422`

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

**最近的运行列表（只列自己的）**

★ 归属过滤：学生**只看到自己的运行**；管理员看全部。

这里曾经是实测到的泄漏点：无鉴权时这个接口会明文返回**所有人**的运行，
包括 `query`（提问原文）。提问原文是 L2 数据（`docs/13 §1.1`）。

响应：`200`, `422`

### `GET /api/runs/{run_id}`

**取回一次运行的完整事件轨迹**

★ 归属校验：只能看自己的运行（管理员可看全部）。

这里曾经是个实测出来的泄漏点：无鉴权时 `GET /api/runs` 会明文列出**所有人**
的提问原文，`/timeline` 还会回传完整答案增量。现在两条路径都以令牌为准。

响应：`200`, `422`

### `GET /api/runs/{run_id}/timeline`

**单次运行的结构化轨迹**

把扁平的事件流整理成"阶段 + 条目"，便于前端画时间轴。

★ 归属校验（与 `_owned_run` 同口径）：不是自己的运行一律 404 ——
这条路径以前会回传**完整答案增量**（实测单次 36 KB / 191 个事件）。

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

**我的学习统计（旧路径，保留兼容）**

按**令牌身份**返回统计；路径里的 `session_id` 不参与取数。

⚠️ 与 `/api/wrong/{session_id}` 同一处理：旧实现拿路径参数当身份，
改一个参数就能读别人的学习记录（实测确实是 200）。现在只保留 URL 形状。
新前端请用 `/api/me/stats`。

响应：`200`, `422`

---

*共 41 条路径 · 42 个端点*

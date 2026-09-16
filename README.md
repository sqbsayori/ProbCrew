# ProbCrew · 概率论伴学助手

[![CI](https://github.com/sqbsayori/ProbCrew/actions/workflows/ci.yml/badge.svg)](https://github.com/sqbsayori/ProbCrew/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![license](https://img.shields.io/badge/status-prototype-orange)

> **一个可以注入到在线课程页面上的 AI 伴学助手**（悬浮球 / 虚拟页宠）：
> 它读得懂学生正在看的这一页 —— 正文、标题层级、公式、划选的文字、视频进度、
> 甚至正在操作的动画停在第几步 —— 然后用 LangGraph 编排的多个 Agent 协作答疑。
>
> 技术栈：LangGraph 编排 + FastAPI + 免构建 ESM + Canvas 自绘形象 + SymPy。

| | |
|---|---|
| 仓库 | https://github.com/sqbsayori/ProbCrew |
| 当前阶段 | 原型骨架 |
| **现在做什么** | [`docs/17-模块化任务书.md`](docs/17-模块化任务书.md) —— 任务卡 + 验收命令 + 基线数字 |
| **为什么这么做** | [`docs/12-基础开发计划.md`](docs/12-基础开发计划.md)（M0–M6 阶段）· [`docs/09`](docs/09-主线范围与数据需求清单.md)（范围与数据需求） |
| **接口约定** | [`contracts/INDEX.md`](contracts/INDEX.md) —— 契约总目录（含**已知未落地项**） |
| **文档全图** | [`docs/18-文档地图.md`](docs/18-文档地图.md) —— 每个主题的**单一权威**是哪一份 |

### 该读哪一份（别乱翻）

| 我是谁 / 我想干什么 | 读这个 |
|---|---|
| **🔴 今天要领任务开工的成员** | **[`docs/19-成员上手与分工.md`](docs/19-成员上手与分工.md)** —— 15 分钟跑起来 + 怎么领任务 + 避冲突 |
| 第一次来，想跑起来 | [`docs/00-快速开始.md`](docs/00-快速开始.md) |
| 要接手写代码 | [`docs/17-模块化任务书.md`](docs/17-模块化任务书.md) §三 找一张任务卡 |
| 要理解整体架构 | [`docs/01-架构总览.md`](docs/01-架构总览.md) |
| 要改前后端接口 / 加事件 | [`contracts/INDEX.md`](contracts/INDEX.md) + [`docs/02-事件契约.md`](docs/02-事件契约.md) |
| 要分工、要走 PR 流程 | [`docs/04-分工与协作规范.md`](docs/04-分工与协作规范.md) |
| 要对老师/评委汇报 | [`docs/15-口径对照与偏差说明.md`](docs/15-口径对照与偏差说明.md) |
| 想知道**有什么坑、什么没做** | [`contracts/INDEX.md`](contracts/INDEX.md) §六 + [`docs/17`](docs/17-模块化任务书.md) §六 已知限制 |
| 想用/分发这个系统 | [`原型声明.md`](原型声明.md) → [`docs/07-部署与分发.md`](docs/07-部署与分发.md) |

---

## 若干时间跑起来

```powershell
# 最省事：双击 启动.bat（Linux/macOS 用 bash start.sh）
# 或手动：
cd 大创\ProbCrew
.\scripts\dev.ps1            # 有 API Key 用 DeepSeek，没 Key 自动降级 Mock
```

可选一步（想用**语义检索**时才需要，约 4.5 GB，装一次即可）：

```powershell
python scripts/setup_models.py     # 把 BGE-M3 + bge-reranker-v2-m3 拉到本机缓存
```

> 检索默认**只读本地权重、运行时不联网**（数据不出校）。不装也能跑：
> 向量层会自动退回离线降级实现，并在 `/api/health` 与检索结果里**如实标注**，
> 不会假装在做语义检索。详见 [`docs/16`](docs/16-检索升级对比.md)。

> ⚠️ **这是原型，不是成品。** 使用前请先读 **[`原型声明.md`](原型声明.md)**：
> 已知限制、数据流向（页面内容会发给大模型厂商）、第三方平台合规注意事项都在里面。
>
> 📌 **当前阶段的执行依据**是
> **[`docs/17-模块化任务书.md`](docs/17-模块化任务书.md)**（现在做什么、怎么验收、基线数字是多少）与
> **[`docs/12-基础开发计划.md`](docs/12-基础开发计划.md)**（M0–M6 阶段与完成标准）；
> 数据与部署约束见 **[`docs/13-数据分级与部署准备.md`](docs/13-数据分级与部署准备.md)**。
> 早期版本的 `docs/05-开发计划.md`、`docs/06-页面助手接入规范.md`、`docs/14-开发交接单.md`
> 部分口径已被取代，保留作为历史记录（权威归属见 [`docs/18-文档地图.md`](docs/18-文档地图.md)）。
>
> 🧭 **这个仓库是什么**：它承担的是大创项目「**做什么 + 怎么协作**」这一半 ——
> 产品骨架、事件契约、检索与校验链、工程设施（CI / 测试 / 部署无关化）。
> **不包含**：教材语料（L1，另有来源，见 `docs/13`）、自制评测基准题（C1，另立）、
> 学生数据与教师端（B 线，已挂起）。所以"仓库能跑"≠"项目已达标"，
> 结项验收还需要内容与评估两项证据，见 `docs/12` 的 M3/M4。

然后打开下面任一地址（默认 `http://127.0.0.1:8000`，实际地址由 `.env` 的
`APP_HOST` / `APP_PORT` 决定，`启动.bat` 会把真实地址打印出来）：

| 想试什么 | 地址 |
|---|---|
| **在原始动画页面上看悬浮窗**（推荐先试这个） | `/raw-live/` |
| 演示课程页（模拟真实课程平台课件页） | `/course/` |
| 独立站点外壳（工作台/动画库/分布可视化/架构） | `/` |
| 油猴脚本（第三方平台注入用） | `/widget/probstat-assistant.user.js` |

> 🌐 **想让局域网其他机器也能用**：在 `.env` 里设 `APP_HOST=0.0.0.0`、
> `CORS_ORIGINS=http://<本机IP>:8000`，重启即可 —— **不需要改任何代码**。
> 换机器/换域名部署时，油猴脚本也不用改：它的 `@require` 是相对路径，
> 地址按"从哪安装"自动推断（详见 [`docs/13`](docs/13-数据分级与部署准备.md) §2.2）。

`/raw-live/` 是**免安装**入口：后端把 `大创/动画` 那 8 个原始动画镜像出来，
在响应时动态注入悬浮窗 —— **磁盘上的原文件一个字节都没改**。

**不需要 `npm install`，不需要打包，不需要 Docker，不需要 API Key。**
KaTeX 已 vendor 到本地，8 个交互动画本身就是自包含 HTML。

### 三套投递方式

| | 免安装试用 | 自建站 | 第三方平台（智慧树等） |
|---|---|---|---|
| 方式 | `/raw-live/` 后端动态注入 | 一行 `<script>` | 油猴脚本 |
| 适用 | 立刻看效果 | 自己的课程站 | 改不了源码的平台 |
| 关键难点 | 无 | 无 | 课件在**跨域 iframe** 里 → 所有 frame 各注入一份，`postMessage` 汇总 |

详见 `docs/06-页面助手接入规范.md`。

---

## 这个助手独特在哪

普通聊天机器人不知道"这段"是哪段。本助手知道。

| 场景 | 助手的实际行为 |
|------|---------------|
| 划选"贝叶斯公式则是在已知 A 发生的条件下反推原因" → 问"这段什么意思" | 路由到 `page_tutor`，**只解释选中的那句**，补上跳过的推导 |
| 问"这一页讲了什么" | 先做**页内检索**，基于本页大纲与正文梳理，而不是泛泛讲教材 |
| 问"我学到哪了" | 报告章节位置 + 视频看到第几分几秒 + 滚动位置 |
| 问"这个推导为什么成立" | 页内找相关段落后讲解；页内没有才回退教材知识库，并**标注来源** |
| 在做一道题要批改 | 走 `solver` → `verifier` 独立校验 → **HITL 暂停等你确认**（关键结论不盲信模型） |
| 想看动态过程 | 从 8 个既有动画里按知识点推荐一个，面板内全屏播放 |

页宠的表情跟着真实 Agent 事件走：思考 / 讲解 / 完成 / **待你确认** / 出错。
学生不用看日志，看表情就知道系统在干什么。

---

## 目录结构

```
ProbCrew/
├── README.md
├── contracts/                    【契约层】前后端唯一约定
│   ├── INDEX.md                      ★ 契约总目录（登记表 / 事件协议 / 已知偏差）
│   ├── MANIFEST.json                 机器可读清单（供脚本校验）
│   ├── events.schema.json            14 种事件
│   └── CHANGELOG.md                  「为什么改」—— 唯一校验不了的东西
├── docs/
│   ├── 00-快速开始.md
│   ├── 01-架构总览.md
│   ├── 02-事件契约.md
│   ├── 03-动画接入规范.md
│   ├── 04-分工与协作规范.md
│   ├── 07-部署与分发.md
│   ├── 12-基础开发计划.md            （为什么这么做）
│   ├── 13-数据分级与部署准备.md
│   ├── 15-口径对照与偏差说明.md       （对老师汇报前必读）
│   ├── 17-模块化任务书.md            ★ 现在做什么（任务卡 + 验收命令）
│   ├── 18-文档地图.md                ★ 每个主题的单一权威是哪份
│   ├── 19-成员上手与分工.md           ★ 下发用：15 分钟跑起来 + 领任务流程
│   ├── archive/                      已归档文档（带归档抬头）
│   ├── adr/                          架构决策记录
│   └── notes/                        勘测与已知问题
├── scripts/  dev.ps1 · check_contracts.py · gen_registry.py · smoke_test.py · live_test.py
├── backend/                      【后端】FastAPI + LangGraph
│   └── app/
│       ├── kernel/               编排内核 + 页面上下文模型（page_context.py）
│       ├── agents/               7 个 Agent，一人一文件
│       │                         ★ page_tutor.py = 页面伴学
│       ├── tools/                16 个工具
│       │                         ★ page_tools.py = 页内检索/大纲/选中
│       ├── api/                  自动挂载
│       │                         ★ raw_live.py = 给原始动画页注入悬浮窗
│       ├── domain/               8 种分布的 SymPy 符号推导
│       ├── providers/            deepseek / mock
│       ├── knowledge_base/probstat.md
│       └── tests/                173 项单测（含契约、账号权限、检索、批改、验证报告）
└── frontend/
    ├── shared/                   ★ 跨形态共享内核（主站与悬浮窗共用同一份实现）
    │                             sse / markdown / math / api / events —— 口径见 docs/23
    ├── course/                   ★ 演示课程页（模拟真实课程平台）
    ├── widget/                   ★ 可注入的助手组件（经典脚本，走 @require）
    │   ├── _shared.js                    ★ 生成产物：shared/ 的经典脚本包（勿手工编辑）
    │   ├── _modules.json                 ★ 生成产物：模块加载清单
    │   ├── probstat-assistant.user.js   油猴脚本（第三方平台）
    │   ├── loader.js                    一行嵌入（自建站 / raw-live）
    │   ├── assistant.js                 主组件：面板/对话/HITL/皮肤/动画模式
    │   ├── anim-bridge.js               动画识别与驱动（★ 动画页面模式）
    │   ├── extractor.js                 页面内容抽取（含跨 frame）
    │   ├── frames.js                    跨 iframe 上下文汇总
    │   ├── pet.js                       虚拟页宠 / 悬浮球（Canvas）
    │   ├── render.js                    Markdown + KaTeX
    │   ├── api.js                       API 客户端 + SSE
    │   └── widget.css                   Shadow DOM 样式
    ├── assets/animations/        8 个既有动画（原样未改）+ manifest + adapter
    ├── vendor/katex/             本地 KaTeX（离线公式渲染）
    └── app/                      独立站点外壳（工作台/动画库/架构说明等）
        ├── core/ · components/ · features/
```

---

## 扩展点（新增东西只动自己的文件）

| 想做什么 | 只改这些 | **不需要**改 |
|---------|---------|------------|
| 新增 Agent | `backend/app/agents/<你的>.py` | graph.py、`__init__.py`、路由表 |
| 新增工具 | `backend/app/tools/<你的>.py` | 任何注册文件 |
| 新增 API | `backend/app/api/<你的>.py` | main.py |
| 接入新动画 | `_raw/*.html` + `manifest.json` | 任何前端 JS |
| 新增页面 | `frontend/app/features/<你的>/` | index.html、bootstrap.js |
| 换 RAG 实现 | `backend/app/tools/kb_search.py` | 所有调用它的 Agent |
| 支持新的课程平台 | 油猴脚本的 `@match` 一行 | 其余全部 |

---

## 怎么登录（账号体系）

**首次启动**会自动创建一个种子管理员，**密码打印在启动日志里**（形如 `pc-1a2b3c-4321`）：

```
  ★ 已创建种子管理员：admin  密码：pc-1a2b3c-4321
     （请立刻登录并修改；改完这行日志就失去意义）
```

- 打开站点 → 未登录会被守卫送到**登录页**；
- 学生看到「刷题 / 知识库 / 我的掌握情况」；管理员额外看到「学生数据管理」；
- **建学生账号**有三种方式：管理页「批量导入 CSV」、管理页「＋」单个建、命令行：

```powershell
python scripts/manage_users.py create --username s01 --display-name 张三
python scripts/manage_users.py list
python scripts/manage_users.py reset-password --username s01
python scripts/manage_users.py delete-data --username s01 --yes   # 不可逆
```

> ⚠️ **悬浮窗要单独登录一次**：它注入在第三方页面上，localStorage 与主站不共享。
> ⚠️ 老库（匿名 session 时代）需要跑一次迁移，见 `python scripts/migrate_to_accounts.py`。

---

## 自检

```powershell
cd ProbCrew
$env:PYTHONIOENCODING="utf-8"     # 中文 Windows 必需（脚本已自处理，设了更保险）

python scripts/check_contracts.py      # 契约 + 注册表 + 部署无关化，50 项
python scripts/migrate_to_accounts.py --check   # 账号数据迁移状态
python scripts/smoke_test.py           # 端到端自检，25 项
python -m pytest backend/tests -q      # 单测，173 收集（CI 跑的就是这条）
python scripts/gen_registry.py --check # 前端注册表一致性
node frontend/app/_test_mount.mjs      # 页面挂载（改前端必跑）
node frontend/widget/_test_render.mjs  # 渲染器
node frontend/widget/_test_deploy.mjs  # 部署无关化
python scripts/live_test.py            # 真模型联调（需服务已启动）
```

> 完整的**基线数字**（多少 Agent / 多少工具 / 多少事件 / 哪些工具是死代码）只在
> [`docs/17-模块化任务书.md`](docs/17-模块化任务书.md) §六 维护一处，README 不再复写 ——
> 复写必然漂移。

---

## 打包分发

```powershell
python scripts/package.py --version 0.1.0
# → dist/probstat-assistant-prototype-v0.1.0.zip   （约 1 MB）
```

打包脚本会**扫描密钥并在命中时中止打包**（不是警告 —— 密钥一旦分发就收不回），
排除 `*.sqlite`（学习记录属隐私）与 `__pycache__`，并生成含逐文件 SHA256 的
`PACKAGE-INFO.txt`。

收到包的人只需三步：解压 → 双击 `启动.bat` → 打开窗口里打印的地址（默认
`http://127.0.0.1:8000/course/`）。
包内自带 8 个动画，`/raw-live/` 开箱即用，不依赖外部文件夹。

部署方式（本机 / 局域网 / 服务器 + Docker + Nginx + HTTPS）见
**[`docs/07-部署与分发.md`](docs/07-部署与分发.md)**；
"靠配置切换环境、不改源码"的约定见 **[`docs/13`](docs/13-数据分级与部署准备.md)**。

---

## 已实现 / 未实现（不夸大）

**已实现**
- 页面上下文：正文/标题/公式/选中文字/视频进度/动画状态，**跨 iframe 汇总**
- LangGraph：Orchestrator → 条件边并行 fan-out → Verifier → HITL 闸门 → Aggregate
- 7 个 Agent（含 `page_tutor` 页面伴学）、16 个工具（其中 **6 个尚无 Agent 声明**，见 `docs/17` 任务 K5）
- 真实 SSE 事件流 + 协作轨迹可视化；`context.received` 让用户看见"读到了什么"
- **LangGraph 原生 `interrupt()`** 人机协同（确认/修正/补充，修正**回流最终答案**）
- 生成/验证分权：Verifier 独立复检步骤完整性、教材依据、公式定界符
- 悬浮球 / 虚拟页宠两套皮肤，8 种状态由真实事件驱动
- 8 个既有动画：同源 iframe 远程驱动 + 按知识点推荐 + 面板内全屏播放
- 8 种分布的 SymPy 符号推导 + 交互式绘图（纯 Canvas）
- Shadow DOM 完全隔离，不污染宿主课程平台
- Mock Provider：无 Key / 断网可完整演示
- **部署无关化**：前端零写死地址（油猴 `@require` 相对路径 + 五层地址解析），
  后端 host/port/CORS/DB 全走 `.env`，换机器只改配置不改代码
- **混合检索**：BM25 + **BGE-M3**（本地推理）+ **bge-reranker-v2-m3** 重排，
  命中带出处（章 / 小节 / 行号 / 片段）；40 题对比数据见 [`docs/16`](docs/16-检索升级对比.md)

**未实现（迭代二）**
- 向量库外置（Qdrant 等）：当前向量索引在进程内，教材规模上来后再换
- 知识点依赖图（DAG）与级联定位薄弱根源
- 做题/测验交互与错题库闭环
- 用户系统（当前用浏览器本地 session id）
- **在真实智慧树账号上的验证**（演示页是仿造的，真机验证是 P1 必修项）
- 部署（Docker / Nginx / HTTPS）、RAGAS 自动评估

### ⚠️ 已经写了、但**还没真正做到**的（契约与实现之间的差额）

上面"已实现"是**能力层面**的。下面几条是**契约层面许了但实现没跟上**的，
逐条都有实测证据，已登记在 [`contracts/INDEX.md`](contracts/INDEX.md) §六 与
[`docs/17-模块化任务书.md`](docs/17-模块化任务书.md)：

| 现象 | 任务 |
|---|---|
| **验证级别用户看不见**：后端已发 `verification.report`，**前端零处理**（`frontend/` 里 grep `verification` 无命中） | X1 |
| **A/B 级恒不可达**：`verifier` 从没做过数值重算 / 符号等价性，所以所有题实际只到 C 或 D | C2 |
| **工具门控形同虚设**：`orchestrator` 能调到它没声明的 `kb_search`（实测成功） | K1 |
| **工具失败看不出来**：`tool.result.ok` 被硬编码为 `true`，前端红色分支永不触发 | K2 |
| **6 个工具是死代码**：`grade_answer`（521 行 + 10 题题库 + 16 项测试）等在用户链路里用不到 | K3/K4/K5 |
| **HITL 触发口径没定义**：判定写在代码里，契约层没说"什么该挂起" | C3 |

> **"仓库能跑" ≠ "项目已达标"。** 上面这些不影响演示，但影响"M1 正确性保障链"这个卖点的成色。


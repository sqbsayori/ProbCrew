# 概率论伴学助手 · 多智能体原型骨架

> **一个可以注入到在线课程页面上的 AI 伴学助手**（悬浮球 / 虚拟页宠）：
> 它读得懂学生正在看的这一页 —— 正文、标题层级、公式、划选的文字、视频进度、
> 甚至正在操作的动画停在第几步 —— 然后用 LangGraph 编排的多个 Agent 协作答疑。
>
> 技术栈：LangGraph 编排 + FastAPI + 免构建 ESM + Canvas 自绘形象 + SymPy。

---

## 30 秒跑起来

```powershell
# 最省事：双击 启动.bat（Linux/macOS 用 bash start.sh）
# 或手动：
cd 大创\our-system
.\scripts\dev.ps1            # 有 API Key 用 DeepSeek，没 Key 自动降级 Mock
```

> ⚠️ **这是原型，不是成品。** 使用前请先读 **[`原型声明.md`](原型声明.md)**：
> 已知限制、数据流向（页面内容会发给大模型厂商）、第三方平台合规注意事项都在里面。
>
> 📌 **当前阶段的执行依据**是
> **[`docs/09-主线范围与数据需求清单.md`](docs/09-主线范围与数据需求清单.md)**：
> 主线 = 不依赖学生数据的**可靠解题助手**（正确性保障链 + 检索加强 + 评估体系）；
> 依赖真实学生数据的学习者建模方案（`docs/08`）已**挂起**，等数据到位再启动。

然后打开下面任一地址：

| 想试什么 | 地址 |
|---|---|
| **在原始动画页面上看悬浮窗**（推荐先试这个） | http://127.0.0.1:8000/raw-live/ |
| 演示课程页（模拟真实课程平台课件页） | http://127.0.0.1:8000/course/ |
| 独立站点外壳（工作台/动画库/分布可视化/架构） | http://127.0.0.1:8000/ |
| 油猴脚本（第三方平台注入用） | http://127.0.0.1:8000/widget/probstat-assistant.user.js |

`/raw-live/` 是**免安装**入口：后端把 `大创/动画` 那 8 个原始动画镜像出来，
在响应时动态注入悬浮窗 —— **磁盘上的原文件一个字节都没改**。

**不需要 `npm install`，不需要打包，不需要 Docker，不需要 API Key。**
KaTeX 已 vendor 到本地，8 个交互动画本身就是自包含 HTML。

### 三套投递方式

| | 免安装试用 | 自建站 | 第三方平台（超星等） |
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
our-system/
├── README.md
├── contracts/                    【契约层】前后端唯一约定
│   └── events.schema.json            13 种事件（含 context.received）
├── docs/
│   ├── 00-快速开始.md
│   ├── 01-架构总览.md
│   ├── 02-事件契约.md
│   ├── 03-动画接入规范.md
│   ├── 04-分工与协作规范.md
│   ├── 05-开发计划.md                ← 12 周分阶段计划
│   ├── 06-页面助手接入规范.md          ← ★ 产品形态与注入方案
│   └── notes/动画接入勘测.md
├── scripts/  dev.ps1 · gen_registry.py · smoke_test.py · live_test.py
├── backend/                      【后端】FastAPI + LangGraph
│   └── app/
│       ├── kernel/               编排内核 + 页面上下文模型（page_context.py）
│       ├── agents/               7 个 Agent，一人一文件
│       │                         ★ page_tutor.py = 页面伴学
│       ├── tools/                15 个工具
│       │                         ★ page_tools.py = 页内检索/大纲/选中
│       ├── api/                  自动挂载
│       │                         ★ raw_live.py = 给原始动画页注入悬浮窗
│       ├── domain/               8 种分布的 SymPy 符号推导
│       ├── providers/            deepseek / mock
│       ├── knowledge_base/probstat.md
│       └── tests/                test_kernel.py · test_page_context.py
└── frontend/
    ├── course/                   ★ 演示课程页（模拟真实课程平台）
    ├── widget/                   ★ 可注入的助手组件
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

## 自检

```powershell
cd our-system
python scripts/smoke_test.py                    # 端到端 25 项
python backend/tests/test_kernel.py             # 内核 16 项
python backend/tests/test_page_context.py       # 页面伴学 15 项
python scripts/gen_registry.py --check          # 前端注册表一致性
python scripts/live_test.py                     # 真模型联调（需服务已启动）
```

---

## 打包分发

```powershell
python scripts/package.py --version 0.1.0
# → dist/probstat-assistant-prototype-v0.1.0.zip   （约 1 MB）
```

打包脚本会**扫描密钥并在命中时中止打包**（不是警告 —— 密钥一旦分发就收不回），
排除 `*.sqlite`（学习记录属隐私）与 `__pycache__`，并生成含逐文件 SHA256 的
`PACKAGE-INFO.txt`。

收到包的人只需三步：解压 → 双击 `启动.bat` → 打开 `http://127.0.0.1:8000/course/`。
包内自带 8 个动画，`/raw-live/` 开箱即用，不依赖外部文件夹。

部署方式（本机 / 局域网 / 服务器 + Docker + Nginx + HTTPS）见
**[`docs/07-部署与分发.md`](docs/07-部署与分发.md)**。

---

## 已实现 / 未实现（不夸大）

**已实现**
- 页面上下文：正文/标题/公式/选中文字/视频进度/动画状态，**跨 iframe 汇总**
- LangGraph：Orchestrator → 条件边并行 fan-out → Verifier → HITL 闸门 → Aggregate
- 7 个 Agent（含 `page_tutor` 页面伴学）、15 个工具
- 真实 SSE 事件流 + 协作轨迹可视化；`context.received` 让用户看见"读到了什么"
- **LangGraph 原生 `interrupt()`** 人机协同（确认/修正/补充，修正**回流最终答案**）
- 生成/验证分权：Verifier 独立复检步骤完整性、教材依据、公式定界符
- 悬浮球 / 虚拟页宠两套皮肤，8 种状态由真实事件驱动
- 8 个既有动画：同源 iframe 远程驱动 + 按知识点推荐 + 面板内全屏播放
- 8 种分布的 SymPy 符号推导 + 交互式绘图（纯 Canvas）
- Shadow DOM 完全隔离，不污染宿主课程平台
- Mock Provider：无 Key / 断网可完整演示

**未实现（迭代二）**
- 真实 RAG：Qdrant 混合检索（当前是本地 Markdown + bigram TF-IDF，接口已冻结）
- 知识点依赖图（DAG）与级联定位薄弱根源
- 做题/测验交互与错题库闭环
- 用户系统（当前用浏览器本地 session id）
- **在真实超星账号上的验证**（演示页是仿造的，真机验证是 P1 必修项）
- 部署（Docker / Nginx / HTTPS）、RAGAS 自动评估

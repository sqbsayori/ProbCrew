"""ProbCrew 后端入口。

启动即完成全部装配，**装配过程不需要人工登记任何清单**：
    app/agents/*.py   → 自动发现 Agent
    app/tools/*.py    → 自动发现 @tool
    app/api/*.py      → 自动挂载 APIRouter

因此 5 个人各自新增文件后，直接重启就生效，不会互相冲突。

启动：
    cd ProbCrew/backend
    python -m app.main
然后浏览器打开 http://<APP_HOST>:<APP_PORT>（默认 127.0.0.1:8000，由 .env 决定）。
"""
from __future__ import annotations

import importlib
import pkgutil
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import __name__ as api_pkg_name
from .config import ANIMATIONS_DIR, FRONTEND_DIR, RAW_ANIMATIONS_DIR, settings
from .kernel.graph import build_graph, make_checkpointer
from .kernel.registry import discover_agents, discover_tools
from .providers import get_provider

API_PACKAGE = api_pkg_name


def discover_routers() -> list[APIRouter]:
    """扫描 app/api 包，收集所有导出了 `router` 的模块。"""
    pkg = importlib.import_module(API_PACKAGE)
    routers: list[APIRouter] = []
    for _finder, name, _ispkg in pkgutil.iter_modules(pkg.__path__):
        if name.startswith("_"):
            continue
        module = importlib.import_module(f"{API_PACKAGE}.{name}")
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            routers.append(router)
    return routers


def _bootstrap_accounts() -> None:
    """启动时准备金库账号。

    做两件事，都**不阻塞启动**（库坏了也要能让 /api/health 把原因说出来）：
    1. 库里一个管理员都没有 → 用 `ADMIN_INIT_*` 建种子管理员，并把密码打到日志；
    2. 打印现有账号数，让"这台机器到底能不能登录"一眼可见。

    ⚠️ 已有管理员时**绝不动**已有密码 —— 每次启动重置管理员密码是最糟的设计。
    """
    try:
        from .kernel.auth import ensure_seed_admin
        from .tools import accounts

        created = ensure_seed_admin()
        if created:
            print(f"  ★ 已创建种子管理员：{created['username']}"
                  f"  密码：{created.get('_initial_password', '')}")
            print("     （请立刻登录并修改；改完这行日志就失去意义）")
        users = accounts.list_users()
        admins = [u for u in users if u["role"] == accounts.ROLE_ADMIN]
        students = [u for u in users if u["role"] == accounts.ROLE_STUDENT]
        print(f"  账号          : 管理员 {len(admins)} · 学生 {len(students)}")
    except Exception as exc:  # noqa: BLE001 —— 起不来服务比"不能登录"更糟
        print(f"  ⚠️ 账号库初始化异常：{exc}")
        print("     登录相关接口可能不可用；请检查 DB_PATH 与文件权限。")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    print("\n" + "=" * 62)
    print("  概率论与数理统计 · 多智能体学习系统（原型骨架）")
    print("=" * 62)
    print(f"  LLM Provider : {settings.resolved_provider}"
          f"{'（未配置 Key，已自动降级为 mock）' if settings.resolved_provider == 'mock' else ''}")
    print(f"  Agents ({len(app.state.agents.all())})    : "
          + ", ".join(e.spec.id for e in app.state.agents.all()))
    print(f"  Tools  ({len(app.state.tools.all())})    : "
          + ", ".join(t.id for t in app.state.tools.all()))
    print(f"  HITL / Verify: {settings.hitl_enabled} / {settings.verify_enabled}")
    print(f"  Frontend     : {FRONTEND_DIR}")
    print(f"  CORS 白名单   : {', '.join(settings.cors_origin_list)}")
    print(f"  学习记录库    : {settings.resolved_db_path}")
    _bootstrap_accounts()
    if RAW_ANIMATIONS_DIR.exists():
        n = len(list(RAW_ANIMATIONS_DIR.glob("*.html")))
        print(f"  原始动画      : {RAW_ANIMATIONS_DIR}  ({n} 个 html)")
    base = f"http://{settings.app_host}:{settings.app_port}"
    print(f"  → {base}")
    print(f"  → {base}/raw-live/  （★ 推荐先试：原始动画 + 悬浮窗，后端响应时注入）")
    print(f"  → {base}/course/    （演示课程页，模拟真实课程平台）")
    if RAW_ANIMATIONS_DIR.exists():
        # 注意区分这两个入口，很容易搞混：
        #   /raw-live/  = 动画 + 悬浮窗（后端注入），这才是能试助手的地方
        #   /raw/       = 同一批动画的静态目录，**没有**悬浮窗（改 /raw-live 前遗留的旧入口）
        print(f"  → {base}/raw/       （原始动画静态文件，不含悬浮窗）")
    if settings.app_host == "0.0.0.0":  # noqa: S104 - 部署时明确要求监听全部网卡
        print("  提示：APP_HOST=0.0.0.0 时，请从局域网其他机器用本机 IP 访问；")
        print("        并把 CORS_ORIGINS 设成实际来源白名单（默认 * 仅适合内网试用）。")
    print("=" * 62 + "\n")
    yield


def build_app() -> FastAPI:
    # ---- 装配 ----
    agents = discover_agents()
    tools = discover_tools()
    llm = get_provider(settings)
    checkpointer = make_checkpointer()
    graph = build_graph(agents, tools, checkpointer, settings=settings)

    app = FastAPI(
        title="概率论与数理统计 · 多智能体学习系统",
        description="基于 LangGraph 的多 Agent 协作原型骨架（可扩展 / 模块化）",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.agents = agents
    app.state.tools = tools
    app.state.llm = llm
    app.state.graph = graph
    app.state.settings = settings

    # CORS 由配置决定（`CORS_ORIGINS`，逗号分隔）：
    #   本地开发保持 `*`，行为与改造前完全一致；
    #   服务器上设成白名单（例如 `https://probstat.example.edu`）即收窄。
    # 注意：`*` 与 `allow_credentials=True` 在浏览器里是无效组合，
    # 所以只有收窄成白名单时才允许带凭证，避免"看起来配了其实不生效"。
    origins = settings.cors_origin_list
    allow_credentials = settings.cors_allow_credentials and "*" not in origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- 路由（在静态挂载之前注册，优先级更高）----
    for router in discover_routers():
        app.include_router(router)

    # ---- 静态资源 ----
    # 1) 交互动画（ProbCrew 内的副本 + manifest）：必须由 http(s) 提供，
    #    才能同源驱动 iframe 内的控制按钮（file:// 下 contentDocument 会被拒绝）
    if ANIMATIONS_DIR.exists():
        app.mount("/animations", StaticFiles(directory=str(ANIMATIONS_DIR)), name="animations")
    # 2) 团队**原始**动画文件夹（`大创/动画`）——原样提供，不做任何修改。
    #    这是给"在原始动画页面上试用悬浮窗"用的：把 file:// 换成 http://，
    #    CORS 与同源问题一次性消失。
    if RAW_ANIMATIONS_DIR.exists():
        app.mount("/raw", StaticFiles(directory=str(RAW_ANIMATIONS_DIR), html=True), name="raw-animations")
    # 3) 前端外壳
    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app


app = build_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


if __name__ == "__main__":
    main()

"""ProbCrew 后端入口。

启动即完成全部装配，**装配过程不需要人工登记任何清单**：
    app/agents/*.py   → 自动发现 Agent
    app/tools/*.py    → 自动发现 @tool
    app/api/*.py      → 自动挂载 APIRouter

因此 5 个人各自新增文件后，直接重启就生效，不会互相冲突。

启动：
    cd ProbCrew/backend
    python -m app.main
然后浏览器打开 http://127.0.0.1:8000
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
    if RAW_ANIMATIONS_DIR.exists():
        n = len(list(RAW_ANIMATIONS_DIR.glob("*.html")))
        print(f"  原始动画      : {RAW_ANIMATIONS_DIR}  ({n} 个 html) -> /raw/")
    print(f"  → http://{settings.app_host}:{settings.app_port}")
    print(f"  → http://{settings.app_host}:{settings.app_port}/course/   （演示课程页）")
    if RAW_ANIMATIONS_DIR.exists():
        print(f"  → http://{settings.app_host}:{settings.app_port}/raw/      （原始动画 + 悬浮窗）")
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

    # 开发期放开 CORS：前端如果是独立 dev server（如 Vite）也能直连
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
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

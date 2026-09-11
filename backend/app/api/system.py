"""系统 API —— 健康检查与学习统计。前端顶栏的"系统状态"用它。

对应主计划的验收要求：一眼看出"当前跑的是真模型还是 mock、知识库有多少内容"，
避免答辩时才发现 Key 没配、知识库是空的。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..tools import animation as anim_tool
from ..tools import kb_search

router = APIRouter(tags=["system"])


@router.get("/api/health", summary="健康检查（含各子系统状态）")
async def health(request: Request) -> dict[str, Any]:
    state = request.app.state
    settings = state.settings

    kb = await kb_search.kb_stats(ctx=None)
    animations = anim_tool.all_animations()

    return {
        "status": "ok",
        "provider": {
            "resolved": settings.resolved_provider,
            "configured": settings.llm_provider,
            "model": settings.deepseek_model
            if settings.resolved_provider == "deepseek"
            else "mock（确定性假模型）",
            "has_api_key": bool(settings.deepseek_api_key.strip()),
        },
        "collaboration": {
            "hitl_enabled": settings.hitl_enabled,
            "verify_enabled": settings.verify_enabled,
        },
        "registry": {
            "agents": len(state.agents.all()),
            "tools": len(state.tools.all()),
        },
        "knowledge_base": {
            "sections": kb.get("section_count", 0),
            "chapters": len(kb.get("chapters", [])),
        },
        "animations": {
            "total": len(animations),
            "categories": anim_tool.load_manifest().get("categories", []),
        },
    }


@router.get("/api/stats/{session_id}", summary="某会话的学习统计")
async def stats(session_id: str, request: Request, limit: int = 20) -> dict[str, Any]:
    return await request.app.state.tools.call(
        "learning_stats", _NullCtx(request.app.state), session_id=session_id, limit=limit
    )


class _NullCtx:
    def __init__(self, app_state: Any) -> None:
        self.run_id = "system"
        self.agent = "system"
        self.tools = app_state.tools
        self.llm = app_state.llm
        self.settings = app_state.settings

    def emit(self, *_: Any, **__: Any) -> None:
        pass

    def emit_tool_call(self, *_: Any, **__: Any) -> None:
        pass

    def emit_tool_result(self, *_: Any, **__: Any) -> None:
        pass

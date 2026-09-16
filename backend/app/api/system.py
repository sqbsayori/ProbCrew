"""系统 API —— 健康检查与学习统计。前端顶栏的"系统状态"用它。

对应主计划的验收要求：一眼看出"当前跑的是真模型还是 mock、知识库有多少内容"，
避免答辩时才发现 Key 没配、知识库是空的。

部署无关化（docs/13 §2.3）后，健康检查还要能回答两个问题：
    1. 数据目录/学习记录库**在不在、连不连得上**（换机器部署最常见的故障）
    2. 知识库语料**有多少条**（L1 教材换进来以后，条数是部署是否成功的直接证据）
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Request

from ..kernel import auth as A
from ..tools import animation as anim_tool
from ..tools import kb_search
from . import _aggregate

router = APIRouter(tags=["system"])


def _database_health(db_path: Any) -> dict[str, Any]:
    """探测学习记录库。**连不上就如实说**，不吞异常（失败必须显式）。"""
    info: dict[str, Any] = {"path": str(db_path)}
    try:
        info["parent_writable"] = db_path.parent.is_dir()
        conn = sqlite3.connect(str(db_path), timeout=5)
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'student_%'"
            )
            info["student_tables"] = sorted(r[0] for r in cur.fetchall())
        finally:
            conn.close()
        info["connected"] = True
        info["error"] = ""
    except Exception as exc:  # noqa: BLE001 - 健康检查要报出任何原因
        info["connected"] = False
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


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
        # 账号体系体检：部署后最常见的疑问是"这台机器能不能登录、种子管理员建了没有"
        "accounts": _accounts_health(settings.resolved_db_path),
        "knowledge_base": {
            "sections": kb.get("section_count", 0),
            "chapters": len(kb.get("chapters", [])),
            "path": kb.get("path", ""),
            "exists": kb.get("exists", False),
            # 语料两来源体检：教材（L1）放进来没有、放了几份
            "corpus": kb.get("corpus", {}),
        },
        # 检索层状态：部署后最常见的疑问是"向量/重排到底生效了没有"
        "retrieval": kb.get("retrieval", {}),
        "database": _database_health(settings.resolved_db_path),
        "deployment": {
            "app_host": settings.app_host,
            "app_port": settings.app_port,
            "cors_origins": settings.cors_origin_list,
        },
        "animations": {
            "total": len(animations),
            "categories": anim_tool.load_manifest().get("categories", []),
        },
    }


@router.get("/api/stats/{session_id}", summary="我的学习统计（旧路径，保留兼容）")
async def stats(session_id: str, user: A.CurrentUser, request: Request, limit: int = 20) -> dict[str, Any]:
    """按**令牌身份**返回统计；路径里的 `session_id` 不参与取数。

    ⚠️ 与 `/api/wrong/{session_id}` 同一处理：旧实现拿路径参数当身份，
    改一个参数就能读别人的学习记录（实测确实是 200）。现在只保留 URL 形状。
    新前端请用 `/api/me/stats`。
    """
    data = _aggregate.my_stats(user["user_id"], recent_limit=max(1, min(int(limit), 50)))
    data["session_id"] = session_id
    data["deprecated"] = "旧路径：身份已改为以令牌为准，请改用 /api/me/stats"
    return data


def _accounts_health(db_path: Any) -> dict[str, Any]:
    """账号库体检。**连不上就如实说**，并且报出"有没有管理员"——
    没有管理员意味着**谁都登不进来**，这是冷启动最常见的故障。"""
    info: dict[str, Any] = {}
    try:
        from ..tools import accounts

        users = accounts.list_users()
        admins = [u for u in users if u["role"] == accounts.ROLE_ADMIN]
        students = [u for u in users if u["role"] == accounts.ROLE_STUDENT]
        info = {
            "admins": len(admins),
            "students": len(students),
            "login_ready": len(admins) > 0,
            "token_ttl_days": settings.auth_token_ttl_days,
            "lock_policy": f"{settings.auth_max_failed} 次 / {settings.auth_lock_seconds} 秒",
        }
        if not admins:
            info["hint"] = "库里没有管理员 —— 重启服务会自动创建种子管理员，或用 scripts/manage_users.py seed"
    except Exception as exc:  # noqa: BLE001
        info = {"error": f"{type(exc).__name__}: {exc}", "login_ready": False}
    return info


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

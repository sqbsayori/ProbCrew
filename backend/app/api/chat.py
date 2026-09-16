"""对话 / 编排 API —— 前端的主入口。

两个流式端点都返回 `text/event-stream`，事件格式见 `contracts/events.schema.json`：

    POST /api/chat/stream              发起一次多 Agent 协作
    POST /api/hitl/{run_id}/resolve    人机协同：确认 / 修正 / 补充后继续执行
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..kernel import events as E
from ..kernel import runner
from ..kernel import auth as A
from ..kernel.page_context import from_payload
from ..kernel.runs import RUNS

router = APIRouter(tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 让 Nginx 不要缓冲 SSE
}


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000, description="用户问题")
    session_id: str = Field(default="default", max_length=64)
    chapter: str | None = None
    #: 助手注入页面时上报的上下文（见 kernel/page_context.py）。
    #: 富客户端可传完整结构；简单调用只传 {"text": "...", "selection": "..."} 也行。
    page_context: dict[str, Any] | None = Field(
        default=None, description="当前页面上下文（页面伴学功能的数据来源）"
    )


class HitlResolveRequest(BaseModel):
    action: str = Field(default="confirm", pattern="^(confirm|correct|supplement)$")
    text: str = Field(default="", max_length=4000)


def _sse(lines: AsyncIterator[str]) -> AsyncIterator[bytes]:
    """把事件 JSON 行包装成 SSE 帧。"""

    async def gen() -> AsyncIterator[bytes]:
        try:
            async for line in lines:
                yield f"data: {line}\n\n".encode("utf-8")
        except Exception as exc:  # noqa: BLE001 —— 保证前端一定收到终止帧
            import json

            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n".encode(
                "utf-8"
            )
        yield b"event: end\ndata: {}\n\n"

    return gen()


@router.post("/api/chat/stream", summary="发起一次多 Agent 协作（SSE）")
async def chat_stream(req: ChatRequest, request: Request, user: A.CurrentUser) -> StreamingResponse:
    graph = request.app.state.graph
    run = RUNS.create(req.session_id, req.query)

    # 解析页面上下文（解析失败返回 None，绝不阻塞提问）
    page_context = from_payload(req.page_context)

    # 注入运行时依赖（不进 LangGraph state，避免被 checkpointer 序列化）
    run.runtime = {
        "llm": request.app.state.llm,
        "tools": request.app.state.tools,
        "settings": request.app.state.settings,
        "page_context": page_context,
        #: ★ 归属：这次运行属于谁。HITL 续跑与轨迹查询都靠它做归属校验 ——
        #: 没有它，任何登录用户拿到 run_id 就能续跑/查看别人的对话。
        "user_id": user["user_id"],
        "user_role": user["role"],
    }
    # 注意：context.received 事件由 kernel.runner._emit_context() 统一发出，
    # 这样任何调用方（HTTP / CLI / 测试）都能拿到同一份行为。

    async def gen() -> AsyncIterator[str]:
        async for line in runner.stream_run(
            run, graph, query=req.query, session_id=req.session_id, chapter=req.chapter
        ):
            yield line

        # 正常结束后落库（挂起时 answer 为空，等 resolve 时再落）
        await _persist(request, run, req.session_id)

    return StreamingResponse(_sse(gen()), media_type="text/event-stream", headers=SSE_HEADERS)


def _owned_run(run_id: str, user: dict[str, Any]) -> Any:
    """取出 run 并校验归属。**不是自己的运行一律当作不存在**（不泄露"存在但无权"）。"""
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"运行不存在或已过期：{run_id}")
    owner = (run.runtime or {}).get("user_id")
    if owner and owner != user.get("user_id") and user.get("role") != "admin":
        raise HTTPException(status_code=404, detail=f"运行不存在或已过期：{run_id}")
    return run


@router.post("/api/hitl/{run_id}/resolve", summary="人机协同：处理待确认结论（SSE）")
async def hitl_resolve(
    run_id: str, req: HitlResolveRequest, request: Request, user: A.CurrentUser
) -> StreamingResponse:
    run = _owned_run(run_id, user)
    if run.interrupt_payload is None:
        raise HTTPException(status_code=409, detail="该运行当前没有待确认的结论")

    graph = request.app.state.graph

    async def gen() -> AsyncIterator[str]:
        async for line in runner.resume_run(
            run, graph, action=req.action, text=req.text
        ):
            yield line
        await _persist(request, run, run.session_id)

    return StreamingResponse(_sse(gen()), media_type="text/event-stream", headers=SSE_HEADERS)


async def _persist(request: Request, run: Any, session_id: str) -> None:
    """把完成的问答写入学习记录。

    挂起（HITL）中的运行不会落库 —— 等用户确认后再落，避免把未定稿的结论记进档案。
    落库失败只记日志、不抛错：用户拿到答案比统计完整更重要。
    """
    if not (run.finished and run.answer):
        return
    try:
        # ★ 归属：写 user_id（统计按账号聚合）。session_id 仍记，只作匿名追踪。
        # 老数据（迁移前的）全挂在 usr_history 名下，不会混进任何真实学生的统计。
        user_id = (run.runtime or {}).get("user_id") or ""
        if not user_id:
            return
        await request.app.state.tools.call(
            "log_qa",
            _NullCtx(run.run_id, request.app.state),
            user_id=user_id,
            session_id=session_id,
            query=run.query,
            intent=_last_intent(run),
            agents=_agents(run),
            answer=run.answer,
            run_id=run.run_id,
        )
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger("probcrew").warning("学习记录落库失败 run_id=%s: %s", run.run_id, exc)


# --------------------------------------------------------------------------
# 轨迹查询（演示复盘 / 后续评估用）
# --------------------------------------------------------------------------


@router.get("/api/runs/{run_id}", summary="取回一次运行的完整事件轨迹")
async def get_run(run_id: str, user: A.CurrentUser) -> dict[str, Any]:
    """★ 归属校验：只能看自己的运行（管理员可看全部）。

    这里曾经是个实测出来的泄漏点：无鉴权时 `GET /api/runs` 会明文列出**所有人**
    的提问原文，`/timeline` 还会回传完整答案增量。现在两条路径都以令牌为准。
    """
    run = _owned_run(run_id, user)
    return {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "query": run.query,
        "finished": run.finished,
        "awaiting_hitl": run.interrupt_payload is not None,
        "answer": run.answer,
        "events": [e.model_dump(exclude_none=True) for e in run.timeline_events()],
    }


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def _last_intent(run: Any) -> str:
    for evt in reversed(run.events):
        if getattr(evt, "type", "") == "plan":
            return getattr(evt, "intent", "") or ""
    return ""


def _agents(run: Any) -> list[str]:
    for evt in reversed(run.events):
        if getattr(evt, "type", "") == "plan":
            return [s.get("agent", "") for s in (getattr(evt, "steps", None) or [])]
    return []


class _NullCtx:
    """工具调用需要一个 ctx 来发事件；落库发生在流结束之后，事件已无意义。"""

    def __init__(self, run_id: str, app_state: Any) -> None:
        self.run_id = run_id
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

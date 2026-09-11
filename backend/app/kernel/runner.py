"""运行器（Runner）—— 把 LangGraph 的执行过程变成一个可流式消费的事件队列。

关键设计：**流式与编排解耦**
---------------------------
SSE 消费的是 `run.queue`，而不是 LangGraph 的 stream_mode。
因此 Agent 内部可以自由地 emit 任意事件（工具调用、产物、进度），
前端不需要理解 LangGraph，LangGraph 也不需要理解 HTTP。

三种结束方式
-----------
- 正常结束   → 队列收到哨兵 `None`，SSE 收尾
- HITL 挂起  → 队列收到哨兵 `PAUSE`，SSE 收尾但 run 仍存活，等 /api/hitl/{run_id}/resolve
- 异常       → emit error + run.end，然后收尾
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from . import events as E
from .runs import Run
from .state import AgentState

#: 哨兵：图因 interrupt() 挂起（区别于正常结束的 None）
PAUSE = object()


def _extract_interrupt(result: Any) -> dict[str, Any]:
    """从 LangGraph 返回值中提取 interrupt 载荷。"""
    if not isinstance(result, dict):
        return {}
    raw = result.get("__interrupt__")
    if not raw:
        return {}
    first = raw[0] if isinstance(raw, (list, tuple)) and raw else raw
    value = getattr(first, "value", None)
    if isinstance(value, dict):
        return value
    return {"draft": str(value)}


async def _invoke(run: Run, graph: Any, payload: Any) -> None:
    """在后台执行一次图调用，并把结果翻译成哨兵。"""
    try:
        result = await graph.ainvoke(payload, {"configurable": {"thread_id": run.run_id}})
    except Exception as exc:  # noqa: BLE001 —— 编排层异常不应让连接静默断开
        run.emit(E.error(run.run_id, f"编排执行失败：{exc}"))
        run.emit(E.run_end(run.run_id, status="error"))
        run.finish()
        return

    payload_out = _extract_interrupt(result)
    if payload_out:
        run.interrupt_payload = payload_out
        # 用 signal：PAUSE 是给 SSE 生成器的哨兵，不是事件，不能进轨迹
        run.signal(PAUSE)
    else:
        # aggregate 节点已把最终答案写进 run.answer，随 run.end 一起回传前端
        run.emit(E.run_end(run.run_id, status="ok", final_answer=run.answer))
        run.finish()


async def _drain(run: Run) -> AsyncIterator[str]:
    """把队列里的事件转成 SSE 数据行，直到遇到哨兵。"""
    while True:
        item = await run.queue.get()
        if item is None:
            return
        if item is PAUSE:
            return
        yield item.wire()


async def stream_run(
    run: Run, graph: Any, *, query: str, session_id: str, chapter: str | None = None
) -> AsyncIterator[str]:
    """启动一次运行并流式产出 SSE 数据行。"""
    initial: AgentState = {
        "run_id": run.run_id,
        "session_id": session_id,
        "query": query,
        "chapter": chapter,
        "results": [],
    }
    run.emit(E.run_start(run.run_id, session_id, query))
    _emit_context(run)

    task = asyncio.create_task(_invoke(run, graph, initial))

    async for line in _drain(run):
        yield line
    await task

    if run.interrupt_payload:
        payload = run.interrupt_payload
        evt = E.hitl_request(
            run.run_id,
            run.run_id,
            payload.get("agent", "verifier"),
            payload.get("draft", ""),
        )
        # 这条事件已经脱离了 _drain 循环，用 record 留档即可（不能走 emit，
        # 否则 resume 时会被重复读出）。轨迹页要靠它显示"HITL 在哪一步挂起"。
        run.record(evt)
        yield evt.wire()


def _emit_context(run: Run) -> None:
    """把"助手读到了什么"作为事件发出去。

    只在调用方**提供了** page_context 时才发（即助手被注入到页面上）。
    纯 API 调用方（如 SPA 或脚本）不传这个字段，就不会收到这条噪音事件。

    这么做的价值：用户能看见助手到底读到了什么，读不到时也知道原因，
    而不是困惑"为什么它不知道我指的是哪一段"。
    """
    pc = (run.runtime or {}).get("page_context")
    if pc is None:
        return

    if getattr(pc, "has_content", False):
        run.emit(
            E.context_received(
                run.run_id,
                pc.summary_line(),
                {
                    "title": pc.title,
                    "url": pc.url,
                    "chars": pc.char_count,
                    "selection_chars": len(pc.selection or ""),
                    "formula_count": len(pc.formulas or []),
                    "frame_count": len(pc.frames or []),
                    "has_media": bool(pc.media),
                    "animation": pc.animation,
                    "outline": pc.outline(12),
                },
            )
        )
    else:
        run.emit(
            E.context_received(
                run.run_id,
                "未读取到页面内容（本次将只用教材知识库回答）",
                {"chars": 0},
            )
        )


async def resume_run(
    run: Run, graph: Any, *, action: str, text: str = ""
) -> AsyncIterator[str]:
    """用户处理完 HITL 后继续执行（LangGraph `Command(resume=...)`）。"""
    from langgraph.types import Command

    run.interrupt_payload = None
    run.emit(E.ev("hitl.resolved", run_id=run.run_id, action=action, final=text))  # type: ignore[arg-type]

    task = asyncio.create_task(
        _invoke(run, graph, Command(resume={"action": action, "text": text}))
    )

    async for line in _drain(run):
        yield line
    await task
    # 注意：run.end 已由 _invoke() 统一发出（携带 final_answer），此处不要重复发。

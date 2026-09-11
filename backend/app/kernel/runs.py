"""运行注册表（Run Registry）—— 连接 LangGraph 节点与 SSE 流的桥。

为什么需要它
-----------
LangGraph 的节点函数签名是 `(state, config)`。我们不把 emitter 塞进 config
（config 会被 checkpointer 序列化，放函数对象不安全），而是：

    run_id 存在 state 里  →  节点用 run_id 来查 RUNS  →  拿到 emitter

这样既绕开序列化问题，又让 Agent 可以脱离 LangGraph 单独测试。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

from .specs import RunContext


class Run:
    """一次运行的运行时对象：事件队列 + 待办 HITL。"""

    def __init__(self, run_id: str, session_id: str, query: str) -> None:
        self.run_id = run_id
        self.session_id = session_id
        self.query = query
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        self.created_at = time.time()
        self.finished = False
        self.answer: str = ""
        self.events: list[Any] = []  # 轨迹留档，供回放/评估
        #: HITL 挂起时的 interrupt 载荷（由 runner 写入）
        self.interrupt_payload: Optional[dict[str, Any]] = None
        #: 运行时依赖（llm / tools / settings），由 API 层装配后注入。
        #: 不放进 LangGraph state 是因为 checkpointer 需要序列化 state。
        self.runtime: dict[str, Any] = {}

    def emit(self, event: Any) -> None:
        self.events.append(event)
        self.queue.put_nowait(event)

    def record(self, event: Any) -> None:
        """只记进轨迹，**不进队列**。

        用于"已经脱离 _drain 循环、但事件仍需留档"的场合（例如 HITL 挂起时
        由 runner 补发的那条 hitl.request）。不能走 emit —— 那条事件会在
        resume 时被 _drain 重复读出来，前端会看到两次挂起。
        """
        self.events.append(event)

    def signal(self, item: Any) -> None:
        """只进队列、**不记轨迹**。专供哨兵（PAUSE / None）使用。

        这些哨兵不是事件，混进 events 会让"轨迹回放"接口拿到非事件对象
        （曾经真的因此报过 AttributeError）。
        """
        self.queue.put_nowait(item)

    def timeline_events(self) -> list[Any]:
        """轨迹里真正的事件（过滤掉可能混入的哨兵，双保险）。"""
        return [e for e in self.events if hasattr(e, "model_dump")]

    def finish(self) -> None:
        self.finished = True
        self.signal(None)  # 哨兵：通知 SSE 生成器收尾


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def create(self, session_id: str, query: str, run_id: str | None = None) -> Run:
        rid = run_id or f"run_{uuid.uuid4().hex[:12]}"
        run = Run(rid, session_id, query)
        self._runs[rid] = run
        self._gc()
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def recent(self, limit: int = 20) -> list[Run]:
        """按开始时间倒序返回最近的运行（供"运行轨迹"页使用）。"""
        runs = sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)
        return runs[: max(1, min(limit, 100))]

    def _gc(self, keep: int = 200) -> None:
        if len(self._runs) <= keep:
            return
        for rid in sorted(self._runs, key=lambda r: self._runs[r].created_at)[: len(self._runs) - keep]:
            self._runs.pop(rid, None)


RUNS = RunRegistry()


def make_context(
    run: Run,
    *,
    llm: Any,
    tools: Any,
    settings: Any = None,
    agent: str = "",
) -> RunContext:
    """为某个 Agent 构造 RunContext。

    page_context 从 `run.runtime` 取（API 层解析请求体后放进这里），
    这样每个 Agent 与工具都能看到"学生当前在看什么页面"。
    """
    ctx = RunContext(
        run_id=run.run_id,
        session_id=run.session_id,
        emit=run.emit,
        llm=llm,
        tools=tools,
        settings=settings,
        agent=agent,
        page_context=run.runtime.get("page_context") if run.runtime else None,
    )
    return ctx

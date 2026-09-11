"""LangGraph 图装配 —— 本项目的编排核心。

拓扑
----
                       ┌──────────────┐
    START ────────────▶│  orchestrator │  意图路由 + 调度计划（发 plan 事件）
                       └──────┬───────┘
                              │ 条件边：按 selection 并行 fan-out
        ┌───────────┬─────────┼─────────┬────────────┐
        ▼           ▼         ▼         ▼            ▼
   knowledge     solver   visualizer  analytics   （可扩展）
        └───────────┴─────────┼─────────┴────────────┘
                              ▼
                        ┌───────────┐
                        │ verifier  │  生成/验证分权：校验产出、决定是否要人审
                        └─────┬─────┘
                              ▼
                        ┌───────────┐
                        │ hitl_gate │  interrupt() 暂停（可开关）
                        └─────┬─────┘
                              ▼
                        ┌───────────┐
                        │ aggregate │  汇总为 answer
                        └─────┬─────┘
                              ▼
                             END

扩展方式：在 `app/agents/` 新建一个带 SPEC 的文件即可被自动发现并纳入 fan-out，
**本文件无需改动**（选择哪些 Agent 由 orchestrator 的 selection 决定）。
"""
from __future__ import annotations

import time
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from ..agents import orchestrator as orchestrator_mod
from ..agents import verifier as verifier_mod
from . import events as E
from .registry import AgentEntry, AgentRegistry, ToolRegistry
from .runs import RUNS
from .state import AgentState

AGGREGATE = "aggregate"
HITL_GATE = "hitl_gate"


def _cfg(state: AgentState) -> dict[str, Any]:
    """从 state 里取出运行时配置（provider / settings）。"""
    run = RUNS.get(state.get("run_id", ""))
    return dict(run.runtime) if run else {}


# --------------------------------------------------------------------------
# 节点
# --------------------------------------------------------------------------


def _make_agent_node(entry: AgentEntry):
    """把一个 Agent 模块包装成 LangGraph 节点。"""

    async def node(state: AgentState) -> dict[str, Any]:
        cfg = _cfg(state)
        run = RUNS.get(state["run_id"])
        if run is None:
            return {"results": []}
        from .runs import make_context

        ctx = make_context(
            run,
            llm=cfg.get("llm"),
            tools=cfg.get("tools"),
            settings=cfg.get("settings"),
            agent=entry.spec.id,
        )
        t0 = time.time()
        ctx.emit(E.agent_start(run.run_id, entry.spec.id, entry.spec.name))
        try:
            result = await entry.module.run(state, ctx)
            payload = {
                "agent": result.agent,
                "text": result.text,
                "ok": result.ok,
                "data": result.data,
                "artifacts": result.artifacts,
                "needs_hitl": result.needs_hitl,
                "hitl_draft": result.hitl_draft,
            }
            ctx.emit(
                E.agent_end(
                    run.run_id,
                    entry.spec.id,
                    ok=result.ok,
                    duration_ms=int((time.time() - t0) * 1000),
                    summary=(result.text or "")[:80],
                )
            )
            return {"results": [payload]}
        except Exception as exc:  # noqa: BLE001 —— 一个 Agent 失败不应拖垮整图
            ctx.emit(E.error(run.run_id, f"{entry.spec.name} 执行失败：{exc}", entry.spec.id))
            ctx.emit(
                E.agent_end(
                    run.run_id,
                    entry.spec.id,
                    ok=False,
                    duration_ms=int((time.time() - t0) * 1000),
                    summary=str(exc)[:80],
                )
            )
            return {"results": [{"agent": entry.spec.id, "text": "", "ok": False, "error": str(exc)}]}

    node.__name__ = f"node_{entry.spec.id}"
    return node


async def orchestrator_node(state: AgentState) -> dict[str, Any]:
    cfg = _cfg(state)
    run = RUNS.get(state["run_id"])
    if run is None:
        return {"selection": [], "intent": "knowledge"}
    from .runs import make_context

    ctx = make_context(
        run,
        llm=cfg.get("llm"),
        tools=cfg.get("tools"),
        settings=cfg.get("settings"),
        agent=orchestrator_mod.SPEC.id,
    )
    t0 = time.time()
    ctx.emit(E.agent_start(run.run_id, orchestrator_mod.SPEC.id, orchestrator_mod.SPEC.name))
    decision = await orchestrator_mod.decide(state, ctx)
    ctx.emit(
        E.agent_end(
            run.run_id,
            orchestrator_mod.SPEC.id,
            ok=True,
            duration_ms=int((time.time() - t0) * 1000),
            summary=decision.get("reason", ""),
        )
    )
    ctx.emit(
        E.plan(
            run.run_id,
            decision["intent"],
            [
                {"agent": a, "label": orchestrator_mod.label_of(a)}
                for a in decision["selection"]
            ],
            reason=decision.get("reason", ""),
        )
    )
    return {
        "intent": decision["intent"],
        "selection": decision["selection"],
        "reason": decision.get("reason", ""),
        "plan": [{"agent": a} for a in decision["selection"]],
    }


def route_after_orchestrator(state: AgentState) -> list[str]:
    """条件边：返回列表 = 并行 fan-out。"""
    selection = state.get("selection") or ["knowledge"]
    return selection


async def verifier_node(state: AgentState) -> dict[str, Any]:
    cfg = _cfg(state)
    run = RUNS.get(state["run_id"])
    if run is None:
        return {"verification": {}}
    from .runs import make_context

    ctx = make_context(
        run,
        llm=cfg.get("llm"),
        tools=cfg.get("tools"),
        settings=cfg.get("settings"),
        agent=verifier_mod.SPEC.id,
    )
    t0 = time.time()
    ctx.emit(E.agent_start(run.run_id, verifier_mod.SPEC.id, verifier_mod.SPEC.name))
    verdict = await verifier_mod.verify(state, ctx)
    ctx.emit(
        E.agent_end(
            run.run_id,
            verifier_mod.SPEC.id,
            ok=verdict.get("passed", True),
            duration_ms=int((time.time() - t0) * 1000),
            summary=verdict.get("notes", "")[:80],
        )
    )
    return {"verification": verdict}


async def hitl_gate_node(state: AgentState) -> dict[str, Any]:
    """人机协同闸门。

    这里用的是 **LangGraph 原生 `interrupt()`**：
    - 触发时整图在此挂起，checkpointer 保存现场；
    - 前端收到 hitl.request 后，用户点"确认/修正/补充"；
    - 后端用 `Command(resume=...)` 从断点继续，**不重跑已完成节点**。

    关闭开关：settings.hitl_enabled = False 时本节点直接放行。
    """
    cfg = _cfg(state)
    settings = cfg.get("settings")
    verdict = state.get("verification", {})

    if settings is not None and not getattr(settings, "hitl_enabled", True):
        return {"hitl": {"skipped": True}}
    if not verdict.get("needs_human"):
        return {"hitl": {"skipped": True}}

    decision = interrupt(
        {
            "kind": "hitl",
            "agent": verdict.get("target_agent", "verifier"),
            "draft": verdict.get("draft", ""),
            "notes": verdict.get("notes", ""),
            "options": ["confirm", "correct", "supplement"],
        }
    )
    decision = decision or {}
    action = decision.get("action", "confirm")
    correction = (decision.get("text") or "").strip()
    return {
        "hitl": {
            "action": action,
            "text": correction,
            "resolved": True,
        }
    }


async def aggregate_node(state: AgentState) -> dict[str, Any]:
    """汇总各 Agent 产出为最终答案。纯内核逻辑，不调 LLM。"""
    run = RUNS.get(state["run_id"])
    parts: list[str] = []
    for item in state.get("results", []):
        if not item.get("ok") or not item.get("text"):
            continue
        parts.append(item["text"].strip())

    answer = "\n\n".join(p for p in parts if p)

    hitl = state.get("hitl", {})
    if hitl.get("resolved"):
        action = hitl.get("action")
        extra = hitl.get("text", "")
        if action == "correct" and extra:
            answer += f"\n\n> ✏️ **已按你的修正重写：** {extra}"
        elif action == "supplement" and extra:
            answer += f"\n\n> ➕ **你的补充：** {extra}"
        else:
            answer += "\n\n> ✅ 已人工确认。"

    if not answer:
        answer = "抱歉，本轮没有产出内容，请换一种问法或检查模型配置。"

    verification = state.get("verification", {})
    if verification.get("notes"):
        answer += f"\n\n---\n🔎 **校验：** {verification['notes']}"

    if run is not None:
        run.answer = answer
    return {"answer": answer}


# --------------------------------------------------------------------------
# 装配
# --------------------------------------------------------------------------


def build_graph(
    agents: AgentRegistry,
    tools: ToolRegistry,
    checkpointer: Any = None,
    *,
    settings: Any = None,
) -> Any:
    builder = StateGraph(AgentState)

    # 把 Agent 中文名注入 orchestrator，供 plan 事件显示（避免反向依赖）
    orchestrator_mod.bind_labels({e.spec.id: e.spec.name for e in agents.all()})

    builder.add_node(orchestrator_mod.SPEC.id, orchestrator_node)

    # 动态注册所有被发现的可执行 Agent（排除 orchestrator / verifier）
    executable: list[str] = []
    for entry in agents.all():
        if entry.spec.id in (orchestrator_mod.SPEC.id, verifier_mod.SPEC.id):
            continue
        if entry.spec.role == "router":
            continue
        builder.add_node(entry.spec.id, _make_agent_node(entry))
        executable.append(entry.spec.id)

    builder.add_node(verifier_mod.SPEC.id, verifier_node)
    builder.add_node(HITL_GATE, hitl_gate_node)
    builder.add_node(AGGREGATE, aggregate_node)

    builder.set_entry_point(orchestrator_mod.SPEC.id)
    builder.add_conditional_edges(
        orchestrator_mod.SPEC.id,
        route_after_orchestrator,
        {name: name for name in executable},
    )

    for name in executable:
        builder.add_edge(name, verifier_mod.SPEC.id)

    builder.add_edge(verifier_mod.SPEC.id, HITL_GATE)
    builder.add_edge(HITL_GATE, AGGREGATE)
    builder.add_edge(AGGREGATE, END)

    return builder.compile(checkpointer=checkpointer)


def make_checkpointer() -> Any:
    """优先内存 checkpointer（demo 够用且零依赖）。"""
    try:
        from langgraph.checkpoint.memory import InMemorySaver  # langgraph >= 0.3

        return InMemorySaver()
    except Exception:  # pragma: no cover
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()

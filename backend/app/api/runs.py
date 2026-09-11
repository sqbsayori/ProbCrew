"""运行轨迹 API —— 把"多 Agent 到底怎么协作的"完整留档露出来。

每次 `POST /api/chat/stream` 产生的所有事件都按序记在 `run.events` 里
（见 `kernel/runs.py`）。本模块把这份留档变成前端可回放的轨迹，
用途有三：

1. **演示**：答辩时能回放"刚才那一轮到底发生了什么"，而不是只看最终答案；
2. **调试**：哪一步慢、哪个工具失败、路由为什么这样决策，一目了然；
3. **评估**：这份轨迹就是后续做 RAGAS / 自建 Eval 的数据集雏形。

注意：当前运行记录存在**内存**里（checkpointer 也是内存版），
服务重启即清空。这也意味着本页只显示"本次启动之后"的运行 ——
界面上会明确写出来，不误导人。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..kernel.runs import RUNS

router = APIRouter(tags=["runs"])


def _summarize(run: Any) -> dict[str, Any]:
    """从事件轨迹里提炼一份摘要。"""
    intent = ""
    agents: list[str] = []
    tools: list[str] = []
    artifacts: list[str] = []
    hitl = False
    errors: list[str] = []
    duration_ms: int | None = None

    for e in run.timeline_events():
        t = getattr(e, "type", "")
        if t == "plan":
            intent = getattr(e, "intent", "") or ""
            agents = [s.get("agent", "") for s in (getattr(e, "steps", None) or [])]
        elif t == "tool.call":
            tool = getattr(e, "tool", "")
            if tool and tool not in tools:
                tools.append(tool)
        elif t == "artifact":
            kind = getattr(e, "kind", "")
            if kind and kind not in artifacts:
                artifacts.append(kind)
        elif t == "hitl.request":
            hitl = True
        elif t == "error":
            errors.append(getattr(e, "message", "") or "")
        elif t == "agent.end":
            d = getattr(e, "duration_ms", None)
            if d:
                duration_ms = (duration_ms or 0) + d

    return {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "query": run.query,
        "status": "error"
        if errors
        else ("awaiting_hitl" if run.interrupt_payload is not None else ("done" if run.finished else "running")),
        "intent": intent,
        "agents": agents,
        "tools": tools,
        "artifacts": artifacts,
        "hitl": hitl,
        "errors": errors,
        "event_count": len(run.events),
        "answer_len": len(run.answer or ""),
        "agent_ms": duration_ms,
        "created_at": run.created_at,
    }


@router.get("/api/runs", summary="最近的运行列表")
async def list_runs(limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
    runs = RUNS.recent(limit)
    items = [_summarize(r) for r in runs]

    # 汇总统计，便于页面顶部展示
    total_events = sum(i["event_count"] for i in items)
    return {
        "count": len(items),
        "total_events": total_events,
        "items": items,
        "note": "运行记录保存在内存中，服务重启即清空（当前仅显示本次启动之后的运行）。",
    }


@router.get("/api/runs/{run_id}/timeline", summary="单次运行的结构化轨迹")
async def run_timeline(run_id: str) -> dict[str, Any]:
    """把扁平的事件流整理成"阶段 + 条目"，便于前端画时间轴。"""
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行不存在或已过期（服务可能已重启）")

    phases: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def phase(key: str, title: str, icon: str) -> dict[str, Any]:
        nonlocal current
        current = {"key": key, "title": title, "icon": icon, "items": []}
        phases.append(current)
        return current

    phase("input", "输入与上下文", "📥")

    for e in run.timeline_events():
        t = getattr(e, "type", "")
        label = ""
        detail: dict[str, Any] = {}

        if t == "run.start":
            label = f"收到提问：{getattr(e, 'query', '')}"
        elif t == "context.received":
            label = getattr(e, "summary", "") or "页面上下文"
            detail = {"data": getattr(e, "data", None)}
        elif t == "plan":
            phase("plan", "调度决策", "🧭")
            label = f"意图：{getattr(e, 'intent', '')}"
            detail = {
                "reason": getattr(e, "reason", ""),
                "steps": getattr(e, "steps", None),
            }
        elif t == "agent.start":
            # 每个 Agent 开一个阶段（简单起见：按出现顺序平铺）
            phase(f"agent:{getattr(e, 'agent', '')}", f"{getattr(e, 'label', '')}", "🤖")
            label = "开始工作"
        elif t == "agent.end":
            label = (
                f"结束（{'成功' if getattr(e, 'ok', True) else '失败'}，"
                f"{getattr(e, 'duration_ms', 0)}ms）"
            )
            detail = {"summary": getattr(e, "summary", "")}
        elif t == "tool.call":
            label = f"调用工具 {getattr(e, 'tool', '')}"
            detail = {"args": getattr(e, "args", None)}
        elif t == "tool.result":
            label = f"工具 {getattr(e, 'tool', '')} 返回"
            detail = {"ok": getattr(e, "ok", None), "data": getattr(e, "data", None)}
        elif t == "artifact":
            label = f"产出 {getattr(e, 'kind', '')}"
            payload = getattr(e, "payload", None) or {}
            detail = {"title": payload.get("title", "")}
        elif t == "hitl.request":
            phase("hitl", "人机协同", "⏸")
            label = "已暂停，等待人工确认"
            detail = {"draft": getattr(e, "draft", "")}
        elif t == "hitl.resolved":
            label = f"用户处理：{getattr(e, 'action', '')}"
        elif t == "run.end":
            phase("output", "聚合输出", "📤")
            label = f"结束（{getattr(e, 'status', '')}）"
            detail = {"answer_len": len(getattr(e, "final_answer", "") or "")}
        elif t == "error":
            label = f"错误：{getattr(e, 'message', '')}"
        else:
            continue

        # agent.delta 数量巨大（一次回答上千条），只统计不逐条列
        if t == "agent.delta":
            continue

        if current is not None:
            current["items"].append(
                {
                    "type": t,
                    "agent": getattr(e, "agent", None),
                    "label": label,
                    "detail": detail,
                    "ts": getattr(e, "ts", None),
                }
            )

    # 统计 delta 数量单独给一行
    deltas = sum(1 for e in run.timeline_events() if getattr(e, "type", "") == "agent.delta")

    return {
        "summary": _summarize(run),
        "phases": phases,
        "delta_count": deltas,
        "answer": run.answer,
        "events": [e.model_dump(exclude_none=True) for e in run.timeline_events()],
    }

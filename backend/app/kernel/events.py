"""事件协议（Event Protocol）—— Agent 运行时 → 前端的唯一契约。

设计原则
--------
1. **唯一事实源**：本文件与 `contracts/events.schema.json` 一一对应。
   前端只认 `type` 字段，不认识 Agent 内部实现。
2. **只增不改**：新增事件类型是安全扩展；修改已有字段必须走 ADR（docs/adr/）。
3. **可回放**：一次 run 的全部事件按序落盘即是一条完整轨迹，可用于
   `docs/` 里的演示复盘与后续评估（Eval）。

约定
----
- 每个事件都是 UTF-8 JSON 对象，SSE 中以 `data: {...}` 单行传输。
- 所有事件都带 `type` 与 `ts`（epoch 秒）。
- 属于某次运行的事件带 `run_id`；属于某个 Agent 的带 `agent`。

事件类型总览（前端按需订阅，未知类型必须忽略而不是报错）
--------------------------------------------------------
    run.start           运行开始
    context.received    已收到页面上下文（页面伴学）
    plan                Orchestrator 的调度计划（可见"多 Agent 协作"的决策过程）
    agent.start         某个 Agent 开始工作
    agent.delta         LLM 流式增量文本
    agent.end           某个 Agent 结束（含耗时，前端画甘特/轨迹）
    tool.call           工具调用开始
    tool.result         工具调用结束
    artifact            结构化产出（动画 / 图表 / 公式 / 解题步骤）
    verification.report 验证报告（级别 A/B/C/D，前端必须显著展示）
    hitl.request        人机协同：暂停等待用户确认或修正
    hitl.resolved       人机协同：用户已处理
    run.end             运行结束
    error               错误

    共 14 种。**只增不改**：以 `contracts/events.schema.json` 的 `type.enum` 为准，
    本清单必须与它逐项一致（`scripts/check_contracts.py` 会比对）。
"""
from __future__ import annotations

import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

EventType = Literal[
    "run.start",
    "context.received",
    "plan",
    "agent.start",
    "agent.delta",
    "agent.end",
    "tool.call",
    "tool.result",
    "artifact",
    "verification.report",
    "hitl.request",
    "hitl.resolved",
    "run.end",
    "error",
]

ArtifactKind = Literal["animation", "chart", "formula", "steps", "text", "table"]

HitlAction = Literal["confirm", "correct", "supplement"]


class Event(BaseModel):
    """一条事件。字段按 type 取用，未用到的为 None。"""

    type: EventType
    ts: float = Field(default_factory=time.time)

    run_id: Optional[str] = None
    agent: Optional[str] = None
    label: Optional[str] = None

    # run.start
    session_id: Optional[str] = None
    query: Optional[str] = None

    # plan / agent.start / agent.end / tool.call / tool.result
    intent: Optional[str] = None
    step: Optional[int] = None
    steps: Optional[list[dict[str, Any]]] = None
    reason: Optional[str] = None
    ok: Optional[bool] = None
    duration_ms: Optional[int] = None
    summary: Optional[str] = None

    # agent.delta
    text: Optional[str] = None

    # tool.call / tool.result
    tool: Optional[str] = None
    args: Optional[dict[str, Any]] = None
    data: Optional[dict[str, Any]] = None

    # artifact
    kind: Optional[ArtifactKind] = None
    payload: Optional[dict[str, Any]] = None

    # hitl
    hitl_id: Optional[str] = None
    draft: Optional[str] = None
    options: Optional[list[HitlAction]] = None
    action: Optional[HitlAction] = None
    final: Optional[str] = None

    # run.end / error
    status: Optional[str] = None
    message: Optional[str] = None
    #: 仅 run.end 携带：聚合后的最终答案（含校验说明与 HITL 修正）
    final_answer: Optional[str] = None

    def wire(self) -> str:
        """序列化为 SSE 传输用的一行 JSON（剔除 None 字段以减小体积）。"""
        return self.model_dump_json(exclude_none=True)


def ev(type_: EventType, **kw: Any) -> Event:
    """构造事件的语法糖：`ev("agent.start", agent="knowledge", label="知识讲解")`"""
    return Event(type=type_, **kw)


# --------------------------------------------------------------------------
# 便捷构造器：让 Agent 代码更短、更不容易写错字段名
# --------------------------------------------------------------------------


def run_start(run_id: str, session_id: str, query: str) -> Event:
    return ev("run.start", run_id=run_id, session_id=session_id, query=query)


def context_received(run_id: str, summary: str, data: dict[str, Any]) -> Event:
    """助手已读取当前页面上下文。

    单独发一条事件的意义：让用户**看得见助手读到了什么**。
    读不到内容时，前端会提示"该页面无法读取"，而不是让用户疑惑"为什么它不知道我指哪段"。
    """
    return ev("context.received", run_id=run_id, summary=summary, data=data)


def plan(
    run_id: str,
    intent: str,
    steps: list[dict[str, Any]],
    reason: str | None = None,
) -> Event:
    """调度计划。

    `reason` 是**路由理由**，会显示在前端的协作轨迹里
    （例如"检测到你在页面上划选了 31 字，优先解释选中的内容"）。
    这条信息是让用户理解"系统为什么这样调度"的关键，不要省略。
    """
    return ev("plan", run_id=run_id, intent=intent, steps=steps, reason=reason)


def agent_start(run_id: str, agent: str, label: str, step: int = 0) -> Event:
    return ev("agent.start", run_id=run_id, agent=agent, label=label, step=step)


def agent_delta(run_id: str, agent: str, text: str) -> Event:
    return ev("agent.delta", run_id=run_id, agent=agent, text=text)


def agent_end(
    run_id: str,
    agent: str,
    ok: bool = True,
    duration_ms: int = 0,
    summary: str | None = None,
) -> Event:
    return ev(
        "agent.end",
        run_id=run_id,
        agent=agent,
        ok=ok,
        duration_ms=duration_ms,
        summary=summary,
    )


def tool_call(run_id: str, agent: str, tool: str, args: dict[str, Any]) -> Event:
    return ev("tool.call", run_id=run_id, agent=agent, tool=tool, args=args)


def tool_result(
    run_id: str,
    tool: str,
    ok: bool,
    data: dict[str, Any] | None = None,
    duration_ms: int = 0,
) -> Event:
    return ev(
        "tool.result",
        run_id=run_id,
        tool=tool,
        ok=ok,
        data=data or {},
        duration_ms=duration_ms,
    )


def artifact(run_id: str, kind: ArtifactKind, payload: dict[str, Any]) -> Event:
    return ev("artifact", run_id=run_id, kind=kind, payload=payload)


def verification_report(run_id: str, report: dict[str, Any]) -> Event:
    """验证报告（M1 核心）。

    契约见 `contracts/verification.schema.json`。
    **绝不允许在没有验证报告的情况下输出解答** —— 这是主线对用户的承诺。

    报告走 `data` 字段（结构由 verification.schema.json 定义），
    `summary` 放级别说明，方便前端不解析 data 也能直接显示。
    """
    return ev(
        "verification.report",
        run_id=run_id,
        data=report,
        summary=report.get("levelLabel") or f"验证级别 {report.get('level', 'D')}",
        ok=bool(report.get("passed")),
    )


def hitl_request(
    run_id: str,
    hitl_id: str,
    agent: str,
    draft: str,
    options: list[HitlAction] | None = None,
) -> Event:
    return ev(
        "hitl.request",
        run_id=run_id,
        hitl_id=hitl_id,
        agent=agent,
        draft=draft,
        options=options or ["confirm", "correct", "supplement"],
    )


def hitl_resolved(
    run_id: str,
    action: HitlAction,
    final: str | None = None,
    hitl_id: str | None = None,
    agent: str | None = None,
) -> Event:
    """用户已处理 HITL 请求。

    与 `hitl_request` 成对出现：`hitl_id` 指回被处理的那次请求，
    `action` 是用户选的动作，`final` 是修正/补充后的最终文本。
    """
    return ev(
        "hitl.resolved",
        run_id=run_id,
        hitl_id=hitl_id,
        agent=agent,
        action=action,
        final=final,
    )


def run_end(
    run_id: str, status: str = "ok", duration_ms: int = 0, final_answer: str | None = None
) -> Event:
    return ev(
        "run.end",
        run_id=run_id,
        status=status,
        duration_ms=duration_ms,
        final_answer=final_answer,
    )


def error(run_id: str | None, message: str, agent: str | None = None) -> Event:
    return ev("error", run_id=run_id, agent=agent, message=message)

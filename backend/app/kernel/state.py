"""LangGraph 状态定义。

状态设计要点
-----------
- `results` 用 `operator.add` reducer：**并行分支各自 append，自动合并**，
  这是 LangGraph 做 fan-out（一个 Orchestrator 同时唤起多个 Agent）的关键。
- 状态里只放"数据"，不放函数/连接对象（checkpointer 要序列化它）。
  事件通道走 `kernel.runs.RUNS[run_id].queue`，与状态彻底分离。
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    # ---- 输入 ----
    run_id: str
    session_id: str
    query: str
    chapter: str | None

    # ---- 编排（Orchestrator 产出）----
    intent: str  # knowledge | solve | visualize | analytics | multi
    selection: list[str]  # 本次要唤醒的 Agent id 列表
    reason: str  # 路由理由（前端"计划"面板展示）
    plan: list[dict[str, Any]]

    # ---- 各 Agent 产出（并行合并）----
    results: Annotated[list[dict[str, Any]], operator.add]

    # ---- 验证（生成/验证分权）----
    verification: dict[str, Any]

    # ---- 人机协同 ----
    hitl: dict[str, Any]

    # ---- 输出 ----
    answer: str

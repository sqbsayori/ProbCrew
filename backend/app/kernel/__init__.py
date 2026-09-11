"""编排内核：事件协议、注册表、状态、图、运行器。与业务 Agent 解耦。"""

from .specs import AgentResult, AgentSpec, RunContext, ToolRegistry, tool  # noqa: F401

__all__ = ["AgentSpec", "AgentResult", "RunContext", "ToolRegistry", "tool"]

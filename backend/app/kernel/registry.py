"""自动发现：把 `app/agents/*.py` 与 `app/tools/*.py` 装配成注册表。

为什么这么做
-----------
多人并行开发时，最容易冲突的文件是"注册表 / __init__.py / 路由表"。
本模块用目录扫描替代手工登记：

    新增 Agent → 丢一个 `app/agents/xxx.py` 进去，声明 SPEC 即可
    新增 Tool  → 丢一个 `app/tools/xxx.py` 进去，写 `@tool(...)` 即可

**没有任何共享文件需要修改。** 这是本项目"便于分工协作"的关键设计。
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any

from .specs import AgentSpec, ToolRegistry

AGENT_PACKAGE = "app.agents"
TOOL_PACKAGE = "app.tools"


@dataclass
class AgentEntry:
    spec: AgentSpec
    module: Any

    @property
    def id(self) -> str:
        return self.spec.id


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentEntry] = {}

    def register(self, spec: AgentSpec, module: Any) -> None:
        if spec.id in self._agents:
            raise ValueError(f"Agent id 重复：{spec.id}（检查 app/agents/ 下是否重名）")
        self._agents[spec.id] = AgentEntry(spec=spec, module=module)

    def get(self, agent_id: str) -> AgentEntry | None:
        return self._agents.get(agent_id)

    def all(self) -> list[AgentEntry]:
        return sorted(self._agents.values(), key=lambda e: e.spec.id)

    def by_intent(self, intent: str) -> list[AgentEntry]:
        return [e for e in self.all() if intent in e.spec.intents]

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "id": e.spec.id,
                "name": e.spec.name,
                "role": e.spec.role,
                "description": e.spec.description,
                "intents": list(e.spec.intents),
                "tools": list(e.spec.tools),
                "emits": list(e.spec.emits),
                "can_verify": list(e.spec.can_verify),
                "accent": e.spec.accent,
                "icon": e.spec.icon,
            }
            for e in self.all()
        ]


def discover_agents() -> AgentRegistry:
    """扫描 app/agents 包，收集所有声明了 SPEC 的模块。"""
    registry = AgentRegistry()
    pkg = importlib.import_module(AGENT_PACKAGE)
    for _finder, name, _ispkg in pkgutil.iter_modules(pkg.__path__):
        if name.startswith("_") or name == "base":
            continue
        module = importlib.import_module(f"{AGENT_PACKAGE}.{name}")
        spec = getattr(module, "SPEC", None)
        if isinstance(spec, AgentSpec):
            if not callable(getattr(module, "run", None)):
                raise TypeError(f"{AGENT_PACKAGE}.{name} 声明了 SPEC 但缺少 async def run()")
            registry.register(spec, module)
    return registry


def discover_tools() -> ToolRegistry:
    """扫描 app/tools 包，收集所有被 @tool 装饰的函数。"""
    registry = ToolRegistry()
    pkg = importlib.import_module(TOOL_PACKAGE)
    for _finder, name, _ispkg in pkgutil.iter_modules(pkg.__path__):
        if name.startswith("_") or name == "base":
            continue
        module = importlib.import_module(f"{TOOL_PACKAGE}.{name}")
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            spec = getattr(obj, "__tool_spec__", None)
            if spec is not None:
                registry.register(spec)
    return registry

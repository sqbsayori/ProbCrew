"""Agent / Tool 的规格（Spec）与运行时上下文。

这是"可扩展 + 便于分工"的核心机制：
一个 Agent = 一个文件，文件里声明 SPEC 并实现 run()。
一个 Tool  = 一个文件，文件里用 @tool 装饰器注册。

任何人新增 Agent/Tool **不需要修改任何共享文件**（不需要改 __init__.py、
不需要改图定义、不需要改路由表），因此 5 个人并行开发不会产生冲突。
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Optional

AgentRole = Literal["router", "generator", "verifier", "analyst", "tool"]
ArtifactKind = Literal["animation", "chart", "formula", "steps", "text", "table"]


@dataclass(frozen=True)
class AgentSpec:
    """Agent 的对外声明。前端据此渲染角色卡片，Orchestrator 据此做路由候选。"""

    id: str  # 唯一英文 id，例如 "knowledge"
    name: str  # 中文名，例如 "知识讲解 Agent"
    role: AgentRole  # 角色：生成 / 验证 / 调度 / 分析
    description: str
    intents: tuple[str, ...] = ()  # 能处理哪些意图
    tools: tuple[str, ...] = ()  # 允许调用的工具 id（角色门控的雏形）
    emits: tuple[ArtifactKind, ...] = ()  # 可能产出的结构化产物类型
    accent: str = "#4F46E5"  # 前端主题色
    icon: str = "🤖"
    can_verify: tuple[str, ...] = ()  # 能校验哪些 Agent 的产出（生成/验证分权）


@dataclass
class AgentResult:
    """Agent 的一次产出。会被写进 LangGraph state.results，并聚合为最终答案。"""

    agent: str
    text: str
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    needs_hitl: bool = False
    hitl_draft: str = ""


@dataclass
class ToolSpec:
    id: str
    name: str
    description: str
    fn: Callable[..., Awaitable[Any]]
    owner: str = ""  # 负责该工具的角色/人名，便于分工追踪
    dangerous: bool = False


class ToolRegistry:
    """工具注册表。Agent 只能调用自己 SPEC.tools 里声明的工具（角色门控）。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.id in self._tools:
            raise ValueError(f"工具 id 重复注册：{spec.id}")
        self._tools[spec.id] = spec

    def get(self, tool_id: str) -> Optional[ToolSpec]:
        return self._tools.get(tool_id)

    def all(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda t: t.id)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "owner": t.owner,
                "dangerous": t.dangerous,
            }
            for t in self.all()
        ]

    async def call(
        self,
        tool_id: str,
        ctx: "RunContext",
        *,
        allowed: tuple[str, ...] | None = None,
        **kwargs: Any,
    ) -> Any:
        spec = self.get(tool_id)
        if spec is None:
            raise KeyError(f"未注册的工具：{tool_id}")
        if allowed is not None and tool_id not in allowed:
            raise PermissionError(
                f"角色门控：{ctx.agent} 未被授权调用 {tool_id}（允许：{allowed}）"
            )
        ctx.emit_tool_call(tool_id, kwargs)
        result = spec.fn(ctx=ctx, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        ctx.emit_tool_result(tool_id, result)
        return result


def tool(
    tool_id: str,
    name: str,
    description: str,
    *,
    owner: str = "",
    dangerous: bool = False,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """把函数标记为工具。由 kernel.registry 在启动时自动收集。

    用法::

        @tool("kb_search", "知识库检索", "在概率论教材中做混合检索")
        async def kb_search(query: str, ctx=None, top_k: int = 5): ...
    """

    def deco(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        setattr(
            fn,
            "__tool_spec__",
            ToolSpec(
                id=tool_id,
                name=name,
                description=description,
                fn=fn,
                owner=owner,
                dangerous=dangerous,
            ),
        )
        return fn

    return deco


class RunContext:
    """一次运行的上下文，注入给每个 Agent。

    Agent 通过它：发事件（前端实时可见）、调 LLM、调工具、读配置。
    它把"Agent 实现"与"传输通道(SSE)/编排框架(LangGraph)"彻底解耦，
    因此单个 Agent 可以脱离图单独测试（见 backend/tests/test_agents.py）。
    """

    def __init__(
        self,
        run_id: str,
        session_id: str,
        emit: Callable[[Any], None],
        llm: Any,
        tools: ToolRegistry,
        settings: Any = None,
        agent: str = "",
        page_context: Any = None,
    ) -> None:
        self.run_id = run_id
        self.session_id = session_id
        self._emit = emit
        self.llm = llm
        self.tools = tools
        self.settings = settings
        self.agent = agent
        #: 学生当前所在页面的上下文（PageContext）。工具（如 page_search）靠它工作，
        #: 因此放在 ctx 上而不是 state 里传参 —— 工具签名保持干净。
        self.page_context = page_context
        self.trace: list[dict[str, Any]] = []
        self.artifacts: list[dict[str, Any]] = []

    # ---- 事件 ----
    def emit(self, event: Any) -> None:
        self._emit(event)

    def emit_tool_call(self, tool_id: str, args: dict[str, Any]) -> None:
        from . import events as E

        self.emit(E.tool_call(self.run_id, self.agent, tool_id, _safe(args)))

    def emit_tool_result(self, tool_id: str, result: Any) -> None:
        from . import events as E

        data = result if isinstance(result, dict) else {"value": _safe(result)}
        self.emit(E.tool_result(self.run_id, tool_id, True, data))

    def emit_artifact(self, kind: str, payload: dict[str, Any]) -> None:
        from . import events as E

        self.artifacts.append({"kind": kind, "payload": payload})
        self.emit(E.artifact(self.run_id, kind, payload))  # type: ignore[arg-type]

    # ---- 工具 ----
    async def use(self, tool_id: str, **kwargs: Any) -> Any:
        return await self.tools.call(tool_id, self, allowed=None, **kwargs)

    # ---- LLM ----
    async def stream_llm(self, system: str, user: str, *, agent: str | None = None) -> str:
        """调用 LLM 并把增量文本实时 emit 成 agent.delta，返回完整文本。"""
        from . import events as E

        who = agent or self.agent
        chunks: list[str] = []
        async for piece in self.llm.stream(system=system, user=user, agent=who):
            chunks.append(piece)
            self.emit(E.agent_delta(self.run_id, who, piece))
        return "".join(chunks)

    async def llm_text(self, system: str, user: str) -> str:
        return await self.llm.complete(system=system, user=user, agent=self.agent)


def _safe(obj: Any, depth: int = 0) -> Any:
    """把任意对象裁剪成可 JSON 序列化的浅结构，避免事件序列化失败。"""
    if depth > 3:
        return str(obj)[:200]
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe(v, depth + 1) for k, v in list(obj.items())[:50]}
    if isinstance(obj, (list, tuple)):
        return [_safe(v, depth + 1) for v in list(obj)[:50]]
    return str(obj)[:200]

"""Orchestrator（总调度 / Supervisor）。

职责：意图路由 → 产出调度计划 → 交给 LangGraph 条件边做并行 fan-out。
它是唯一有权"决定唤起哪些 Agent"的角色（对应架构重构建议里的 Danus Main Agent）。

**注意它自己不产出学习内容** —— 分权：调度者不生成，生成者不调度。
"""
from __future__ import annotations

from ..kernel.specs import AgentResult, AgentSpec, RunContext
from . import _router

SPEC = AgentSpec(
    id="orchestrator",
    name="Orchestrator 总调度",
    role="router",
    description="意图识别、任务分发、调度计划生成；本身不产出学习内容。",
    intents=("knowledge", "solve", "visualize", "analytics", "animation", "multi"),
    tools=(),
    emits=(),
    accent="#4F46E5",
    icon="🧭",
)

#: Agent id -> 中文名。由 kernel.graph.build_graph() 在装配时注入，
#: 避免 orchestrator 反向依赖其他 Agent 模块（降低耦合）。
_LABELS: dict[str, str] = {}


def bind_labels(labels: dict[str, str]) -> None:
    _LABELS.clear()
    _LABELS.update(labels)


def label_of(agent_id: str) -> str:
    return _LABELS.get(agent_id, agent_id)


async def decide(state: dict, ctx: RunContext) -> dict:
    """产出路由决策：{intent, selection, reason}。

    注意 `ctx.page_context`：当助手被注入到课程页面时，它是"学生正看着什么"。
    路由必须知道这件事 —— 「这段什么意思」不能被丢给教材知识库。
    """
    query = (state.get("query") or "").strip()
    page_context = getattr(ctx, "page_context", None)

    intent, selection, reason = _router.route(query, page_context)

    # 规则没命中任何特征词、问题较长、且没有页面上下文时，才让 LLM 兜底分类（省一次调用）
    if (
        not _router.match_intents(query)
        and len(query) >= 12
        and not (page_context is not None and getattr(page_context, "has_content", False))
        and ctx.llm.name != "mock"
    ):
        guess = await _llm_intent(query, ctx)
        if guess:
            intent = guess
            selection = _router.INTENT_AGENTS.get(guess, ["knowledge"])
            reason = f"规则未命中，LLM 判定为「{_router.INTENT_LABELS.get(guess, guess)}」"

    resolved = [a for a in selection if a in _LABELS] or ["knowledge"]
    return {"intent": intent, "selection": resolved, "reason": reason}


async def _llm_intent(query: str, ctx: RunContext) -> str | None:
    """让 LLM 在 6 个意图里选一个。失败/越界一律返回 None（回退到规则结果）。"""
    system = (
        "你是概率论答疑系统的路由器。只输出一个英文单词，不要解释、不要标点。\n"
        "knowledge=概念/公式/定理讲解; solve=解题/批改; visualize=分布性质/画图; "
        "analytics=学习进度/薄弱点; animation=要看动画演示; multi=跨多领域综合问题"
    )
    try:
        text = (await ctx.llm_text(system, f"用户问题：{query}")).strip().lower()
    except Exception:  # noqa: BLE001 —— 路由失败绝不能阻塞主流程
        return None
    for token in text.replace(".", " ").split():
        if token in _router.INTENT_AGENTS:
            return token
    return None


async def run(state: dict, ctx: RunContext) -> AgentResult:
    """供注册表校验用的标准入口（图内实际调用 decide()，因为它还需要回写 state）。"""
    decision = await decide(state, ctx)
    return AgentResult(
        agent=SPEC.id,
        text=decision["reason"],
        data=decision,
    )

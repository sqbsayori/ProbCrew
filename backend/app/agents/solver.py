"""Problem Solver Agent —— 题目讲解（逐步解题 + 易错点）。

分权约定：本 Agent **只负责"做出来"**，不负责任"判对错"。
判对错是 `verifier.py`（Grader）的职责 —— 这是架构重构建议里的 P0 机制。
"""
from __future__ import annotations

import re
from typing import Any

from ..kernel.specs import AgentResult, AgentSpec, RunContext

SPEC = AgentSpec(
    id="solver",
    name="Problem Solver 题目讲解",
    role="generator",
    description="给出逐步解题过程、思路分析与易错点；结论交由验证者复核。",
    intents=("solve", "multi"),
    tools=("kb_search", "math_check"),
    emits=("steps", "formula"),
    accent="#FF9F43",
    icon="✏️",
    can_verify=("solver",),
)

SYSTEM_PROMPT = """你是《概率论与数理统计》习题导师。请分步骤解答学生的问题。

格式要求（严格遵守，下游会解析）：
**Step 1 · <这一步做什么>**
<这一步的推理与公式，公式必须用 $...$ 或 $$...$$>
**Step 2 · <...>**
...

在步骤之后，另起两节：
## 思路分析
（说明这类题的通用抓手）
## 易错点
（列出 2-3 条）

其他要求：
- 至少 3 个 Step，每步都要有明确的数学依据。
- 涉及数值计算时给出中间结果。
- 不要编造题目条件；题目信息不足时明确指出缺什么。
- 只依据给定教材片段与通用数学知识。

【教材片段】
{context}
"""

_STEP_RE = re.compile(r"\*\*\s*Step\s*(\d+)\s*[·:：]?\s*([^*]*?)\*\*\s*(.*?)(?=\*\*\s*Step|\Z)", re.S)


def parse_steps(text: str) -> list[dict[str, Any]]:
    """把 LLM 输出解析成结构化步骤，供前端做逐步高亮/逐步批改。"""
    steps: list[dict[str, Any]] = []
    for m in _STEP_RE.finditer(text):
        steps.append(
            {
                "index": int(m.group(1)),
                "title": m.group(2).strip(),
                "body": m.group(3).strip()[:1200],
            }
        )
    return steps


async def run(state: dict, ctx: RunContext) -> AgentResult:
    query = state.get("query", "")

    kb = await ctx.use("kb_search", query=query, top_k=3)
    chunks = kb.get("chunks", []) if isinstance(kb, dict) else []
    context = (
        "\n\n".join(f"[{c.get('heading')}]\n{c.get('content')}" for c in chunks)[:2200]
        if chunks
        else "（未检索到相关教材片段）"
    )

    answer = await ctx.stream_llm(
        SYSTEM_PROMPT.format(context=context), f"【用户问题】{query}", agent=SPEC.id
    )

    steps = parse_steps(answer)
    artifacts: list[dict[str, Any]] = []
    if steps:
        artifacts.append(
            {
                "kind": "steps",
                "payload": {
                    "title": "解题步骤",
                    "count": len(steps),
                    "steps": steps,
                },
            }
        )

    formulas = re.findall(r"\$\$(.+?)\$\$", answer, re.S)
    if formulas:
        artifacts.append(
            {
                "kind": "formula",
                "payload": {"title": "用到的公式", "items": [f.strip() for f in formulas[:3]]},
            }
        )

    for art in artifacts:
        ctx.emit_artifact(art["kind"], art["payload"])

    return AgentResult(
        agent=SPEC.id,
        text=answer,
        data={"steps": len(steps), "retrieved": len(chunks)},
        artifacts=artifacts,
    )

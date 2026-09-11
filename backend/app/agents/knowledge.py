"""Knowledge Agent —— 知识点讲解（检索增强 + 交互动画推荐）。

协作关系
-------
- 调用 `kb_search` 做教材检索（RAG 接缝）
- 调用 `recommend_animation` 把 8 个既有交互动画接进来（本项目"建立在 HTML 上"的落点）
- 产出三类 artifact：formula（公式卡）、animation（可播放动画）、table（检索来源）
"""
from __future__ import annotations

import re
from typing import Any

from ..kernel.specs import AgentResult, AgentSpec, RunContext

SPEC = AgentSpec(
    id="knowledge",
    name="Knowledge Agent 知识讲解",
    role="generator",
    description="检索教材并组织知识点讲解；重点公式用 LaTeX，并按需挂载交互动画。",
    intents=("knowledge", "visualize", "multi", "animation"),
    tools=("kb_search", "recommend_animation"),
    emits=("formula", "animation", "table"),
    accent="#2F6DF6",
    icon="📚",
    can_verify=("knowledge",),
)

SYSTEM_PROMPT = """你是《概率论与数理统计》课程的助教。请依据给定的教材片段回答问题。

要求：
1. 先用一句话给结论，再展开。
2. 所有数学公式必须用 LaTeX：行内用 $...$，独立公式用 $$...$$。
3. 只用教材片段与通用数学知识作答；片段没覆盖到的，明确说明"教材中未检索到"。
4. 不要编造定理名称、编者或页码。
5. 用中文回答，结构清晰（可用小标题与列表），不要啰嗦客套。

【教材片段】
{context}
"""

_FORMULA_BLOCK = re.compile(r"\$\$(.+?)\$\$", re.S)


def extract_formulas(text: str, limit: int = 3) -> list[str]:
    """从文本中抽出独立公式块，供前端渲染公式卡。"""
    out: list[str] = []
    for m in _FORMULA_BLOCK.finditer(text):
        body = m.group(1).strip()
        if body and body not in out:
            out.append(body)
        if len(out) >= limit:
            break
    return out


def _context(chunks: list[dict[str, Any]], max_chars: int = 2400) -> str:
    if not chunks:
        return "（未检索到相关教材片段）"
    parts: list[str] = []
    used = 0
    for c in chunks:
        block = f"[{c.get('chapter', '')} · {c.get('heading', '')}]\n{c.get('content', '')}"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n---\n\n".join(parts)


async def run(state: dict, ctx: RunContext) -> AgentResult:
    query = state.get("query", "")
    artifacts: list[dict[str, Any]] = []

    # ---- 1. 检索教材 ----
    kb = await ctx.use("kb_search", query=query, top_k=4)
    chunks = kb.get("chunks", []) if isinstance(kb, dict) else []

    if chunks:
        artifacts.append(
            {
                "kind": "table",
                "payload": {
                    "title": "教材检索来源",
                    "columns": ["章节", "小节", "相关度"],
                    "rows": [
                        [c.get("chapter", ""), c.get("heading", ""), c.get("score", 0)]
                        for c in chunks
                    ],
                },
            }
        )

    # ---- 2. 生成讲解（流式）----
    prompt = SYSTEM_PROMPT.format(context=_context(chunks))
    answer = await ctx.stream_llm(prompt, f"【用户问题】{query}", agent=SPEC.id)

    # ---- 3. 公式卡 ----
    formulas = extract_formulas(answer)
    if formulas:
        artifacts.append(
            {"kind": "formula", "payload": {"title": "关键公式", "items": formulas}}
        )

    # ---- 4. 交互动画推荐（复用既有 8 个 HTML 动画）----
    rec = await ctx.use("recommend_animation", query=query, top_k=2)
    matches = rec.get("matches", []) if isinstance(rec, dict) else []
    for m in matches[:2]:
        artifacts.append(
            {
                "kind": "animation",
                "payload": {
                    "id": m["id"],
                    "title": m["title"],
                    "url": m["url"],
                    "category": m.get("category"),
                    "description": m.get("description"),
                    "reason": f"与「{query[:24]}」知识点相关（匹配度 {m.get('score')}）",
                },
            }
        )

    for art in artifacts:
        ctx.emit_artifact(art["kind"], art["payload"])

    return AgentResult(
        agent=SPEC.id,
        text=answer,
        data={
            "retrieved": len(chunks),
            "formulas": len(formulas),
            "animations": len(matches),
            "grounded": len(chunks) > 0,
        },
        artifacts=artifacts,
    )

"""Analytics Agent —— 学习数据分析（进度 / 历史 / 薄弱点）。

demo 阶段边界（对齐架构重构建议 §2.1）：
只做"读取错题库 + 单点正确率排序"的简易诊断，
**不做知识点依赖图的级联定位**（那依赖内容入库完成，属迭代二）。
"""
from __future__ import annotations

from typing import Any

from ..kernel.specs import AgentResult, AgentSpec, RunContext

SPEC = AgentSpec(
    id="analytics",
    name="Analytics Agent 学习分析",
    role="analyst",
    description="读取本地学习记录，输出进度、历史与薄弱知识点排序（不做级联定位）。",
    intents=("analytics",),
    tools=("learning_stats",),
    emits=("table",),
    accent="#8A63D2",
    icon="📈",
)

SYSTEM_PROMPT = """你是学习数据管理助手。下面是从学习记录里统计出来的真实数据。

要求：
- 用简洁的中文说明当前学习情况，给出 1-2 条可执行的下一步建议。
- **不要编造数据**，只使用下面给出的数字。
- 不要输出客套话。

【统计数据】
{stats}
"""


def _fmt_stats(stats: dict[str, Any]) -> str:
    lines = [
        f"累计问答：{stats.get('total_qa', 0)} 次",
        f"最近记录：{len(stats.get('recent', []))} 条",
    ]
    weak = stats.get("weak_topics", [])
    if weak:
        lines.append("薄弱知识点（正确率升序）：")
        for w in weak:
            lines.append(
                f"  - {w['topic']}：{w['correct']}/{w['attempts']}（{w['accuracy']:.0%}）"
            )
    else:
        lines.append("薄弱知识点：暂无足够练习数据")
    return "\n".join(lines)


async def run(state: dict, ctx: RunContext) -> AgentResult:
    query = state.get("query", "")
    session_id = state.get("session_id", "anonymous")

    stats = await ctx.use("learning_stats", session_id=session_id, limit=10)
    if not isinstance(stats, dict):
        stats = {}

    table = {
        "kind": "table",
        "payload": {
            "title": "最近学习记录",
            "columns": ["提问", "意图"],
            "rows": [[r["query"][:40], r.get("intent", "")] for r in stats.get("recent", [])],
        },
    }
    if stats.get("recent"):
        ctx.emit_artifact("table", table["payload"])

    weak_table = None
    if stats.get("weak_topics"):
        weak_table = {
            "kind": "table",
            "payload": {
                "title": "薄弱知识点",
                "columns": ["知识点", "作答", "正确率"],
                "rows": [
                    [w["topic"], f"{w['correct']}/{w['attempts']}", f"{w['accuracy']:.0%}"]
                    for w in stats["weak_topics"]
                ],
            },
        }
        ctx.emit_artifact("table", weak_table["payload"])

    advice = await ctx.stream_llm(
        SYSTEM_PROMPT.format(stats=_fmt_stats(stats)),
        f"【用户问题】{query}",
        agent=SPEC.id,
    )

    artifacts = [t for t in (table, weak_table) if t]
    return AgentResult(
        agent=SPEC.id,
        text=advice,
        data={"total_qa": stats.get("total_qa", 0), "weak": len(stats.get("weak_topics", []))},
        artifacts=artifacts,
    )

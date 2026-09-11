"""Visualization Agent —— 分布性质计算 + 绘图数据。

关键点：**公式与数值全部来自 SymPy（tools/math_tools.py），LLM 只负责解读**。
这样"期望/方差算错"这一类幻觉在架构上就不可能发生。
"""
from __future__ import annotations

import re
from typing import Any

from ..kernel.specs import AgentResult, AgentSpec, RunContext
from . import _router

SPEC = AgentSpec(
    id="visualizer",
    name="Visualization Agent 分布可视化",
    role="generator",
    description="用 SymPy 推导分布性质，并产出可交互的 PDF/CDF 绘图数据。",
    intents=("visualize", "animation", "multi"),
    tools=("list_distributions", "distribution_properties", "plot_distribution"),
    emits=("chart", "formula"),
    accent="#12B886",
    icon="📊",
    can_verify=("visualizer",),
)

SYSTEM_PROMPT = """你是概率分布专家。下面已经用符号计算软件（SymPy）算好了结论，
请你**只做解读与教学说明**，绝对不要重新计算或改动任何数值与公式。

要求：
- 用 2-4 句话说明这个分布的形状特点、参数如何影响形状。
- 指出这个分布的一个典型应用场景。
- 不要重复罗列下面已给出的公式。
- 用中文，不要客套。

【已算好的结论】
{digest}
"""


def _pick_distribution(query: str) -> tuple[str, dict[str, float]]:
    dist, params = _router.extract_distribution(query)
    if dist:
        return dist, params
    # 没识别到分布名时，看是否提到"分布"泛词，给一个教学感更好的默认
    return "normal", {}


async def run(state: dict, ctx: RunContext) -> AgentResult:
    query = state.get("query", "")
    dist, params = _pick_distribution(query)

    props = await ctx.use("distribution_properties", dist=dist, params=params)
    if not props.get("ok"):
        return AgentResult(
            agent=SPEC.id,
            text=f"未能完成分布推导：{props.get('error')}",
            ok=False,
            data=props,
        )

    pdf = await ctx.use("plot_distribution", dist=dist, params=props["params"], mode="pdf")
    cdf = await ctx.use("plot_distribution", dist=dist, params=props["params"], mode="cdf")

    name = props["name"]
    formula_payload = {
        "title": f"{name} · 性质",
        "items": [
            props["pdf_latex"],
            props["cdf_latex"],
            props["mean_latex"],
            props["var_latex"],
            props["mgf_latex"],
        ],
    }
    chart_payload = {
        "title": f"{name} 的 {'PMF' if props['kind'] == 'discrete' else 'PDF'} / CDF",
        "dist": dist,
        "name": name,
        "kind": props["kind"],
        "params": props["params"],
        "mean": props["mean"],
        "var": props["var"],
        "std": props["std"],
        "note": props["note"],
        "pdf": {"x": pdf.get("x", []), "y": pdf.get("y", [])},
        "cdf": {"x": cdf.get("x", []), "y": cdf.get("y", [])},
    }

    ctx.emit_artifact("formula", formula_payload)
    ctx.emit_artifact("chart", chart_payload)

    digest = (
        f"分布：{name}\n"
        f"参数：{props['params']}\n"
        f"E[X] = {props['mean']:.6g}\n"
        f"Var(X) = {props['var']:.6g}\n"
        f"标准差 = {props['std']:.6g}\n"
        f"PDF/PMF：${props['pdf_latex']}$\n"
        f"矩母函数：${props['mgf_latex']}$\n"
        f"备注：{props['note']}"
    )
    commentary = await ctx.stream_llm(
        SYSTEM_PROMPT.format(digest=digest), f"【用户问题】{query}", agent=SPEC.id
    )

    return AgentResult(
        agent=SPEC.id,
        text=f"### {name}\n\n{commentary}",
        data={
            "dist": dist,
            "params": props["params"],
            "mean": props["mean"],
            "var": props["var"],
        },
        artifacts=[
            {"kind": "formula", "payload": formula_payload},
            {"kind": "chart", "payload": chart_payload},
        ],
    )

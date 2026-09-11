"""Verifier / Grader —— 验证者。**本项目区别于"普通聊天机器人"的关键节点。**

分权原则
-------
凡"产出内容"的 Agent，都必须有独立的验证者：
    knowledge  → 讲解校验     （概念是否溯源到教材）
    solver     → 批改/复核     （步骤是否完整、结论是否可靠）
    visualizer → 数值校验     （公式必须来自 SymPy，不由 LLM 生成）

验证策略（demo 阶段：确定性优先，可测、免费、不依赖模型）
-------------------------------------------------------
1. **必检项**（不调 LLM）：
   - 上游 Agent 是否失败；
   - 结构化产物是否齐全（解题必须有 >= 3 步）；
   - 是否成功溯源到教材片段（groundedness）。
2. **风险分级**：解题类结论属于"关键结论"，即使校验通过也要走 HITL 人工确认
   （对应架构重构建议闭环四：先走内部闭环，仍不通过/高风险才打断用户）。
"""
from __future__ import annotations

import re
from typing import Any

from ..kernel.specs import AgentResult, AgentSpec, RunContext

SPEC = AgentSpec(
    id="verifier",
    name="Verifier 讲解校验 / Grader 批改",
    role="verifier",
    description="独立校验上游产出：完整性、可溯源性、数值可信度，并决定是否需人工确认。",
    intents=(),
    tools=("kb_search",),
    emits=(),
    accent="#EF4444",
    icon="🔍",
    can_verify=("knowledge", "solver", "visualizer"),
)

#: 关键结论（高风险）类型：必须人工确认
HIGH_RISK_AGENTS = {"solver"}

MIN_STEPS = 3


def _grams(text: str) -> set[str]:
    text = text.lower()
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    return set(re.findall(r"[a-z0-9_]{2,}", text)) | {
        "".join(chars[i : i + 2]) for i in range(max(len(chars) - 1, 0))
    }


def overlap_ratio(answer: str, chunks: list[dict[str, Any]]) -> float:
    """产出与教材片段的词汇重合度（信息性指标，不作为唯一判据）。

    说明：LLM 的组织语言天然不会逐字复述教材，因此这个数字通常偏低，
    它只用来发现"完全脱离教材"的极端情况，阈值也设得很宽。
    """
    if not answer.strip() or not chunks:
        return 0.0
    source = _grams(" ".join(c.get("content", "") for c in chunks))
    probe = _grams(answer)
    if not probe:
        return 0.0
    return round(len(probe & source) / len(probe), 3)


def formula_balanced(text: str) -> bool:
    """检查 $$ 是否成对 —— 直接对应验收标准里的"KaTeX 公式渲染零错误"。"""
    if not text:
        return True
    return text.count("$$") % 2 == 0


async def verify(state: dict, ctx: RunContext) -> dict[str, Any]:
    query = state.get("query", "")
    results: list[dict[str, Any]] = state.get("results", []) or []
    intent = state.get("intent", "knowledge")
    agents = {r.get("agent") for r in results}

    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    # ---- 1. 上游是否失败 ----
    failed = [r["agent"] for r in results if not r.get("ok", True)]
    checks.append(
        {
            "name": "上游执行",
            "passed": not failed,
            "detail": "全部成功" if not failed else f"失败：{', '.join(failed)}",
        }
    )
    if failed:
        notes.append(f"⚠️ {', '.join(failed)} 未能完成，结论不完整。")

    # ---- 2. 教材依据（独立再检索一次，不信任上游自己报的数）----
    kb = await ctx.use("kb_search", query=query, top_k=4)
    chunks = kb.get("chunks", []) if isinstance(kb, dict) else []
    has_source = bool(chunks)
    checks.append(
        {
            "name": "教材依据",
            "passed": has_source,
            "detail": f"命中 {len(chunks)} 个片段"
            if has_source
            else "教材中未检索到直接依据（结论主要来自模型自身知识）",
        }
    )

    # ---- 3. 结构化产物完整性 ----
    for r in results:
        if r.get("agent") == "solver":
            step_art = next(
                (a for a in r.get("artifacts", []) if a.get("kind") == "steps"), None
            )
            count = (step_art or {}).get("payload", {}).get("count", 0)
            ok = count >= MIN_STEPS
            checks.append(
                {
                    "name": "解题步骤完整性",
                    "passed": ok,
                    "detail": f"解析到 {count} 步（要求 ≥ {MIN_STEPS}）",
                }
            )
            if not ok:
                notes.append(f"⚠️ 解题步骤仅 {count} 步，可能不完整，建议人工复核。")

        if r.get("agent") == "visualizer":
            has_chart = any(a.get("kind") == "chart" for a in r.get("artifacts", []))
            from_sympy = "dist" in (r.get("data") or {}) and "params" in (r.get("data") or {})
            checks.append(
                {
                    "name": "数值来源",
                    "passed": has_chart and from_sympy,
                    "detail": "公式与数值均由 SymPy 推导，非模型生成"
                    if has_chart and from_sympy
                    else "缺少绘图数据或未经符号计算",
                }
            )

    # ---- 4. 公式渲染完整性（对应验收标准：KaTeX 零错误）----
    combined = "\n".join(r.get("text", "") for r in results)
    balanced = formula_balanced(combined)
    formula_count = combined.count("$$") // 2
    checks.append(
        {
            "name": "公式完整性",
            "passed": balanced,
            "detail": f"{formula_count} 个独立公式块，定界符成对"
            if balanced
            else "检测到未闭合的 $$ 定界符，前端渲染会出错",
        }
    )
    if not balanced:
        notes.append("⚠️ 公式定界符未闭合，请检查后重试。")

    # ---- 5. 溯源率（信息性，阈值很宽）----
    ratio = overlap_ratio(combined, chunks)
    if ratio < 0.08:
        notes.append(
            "ℹ️ 本回答以模型自身知识组织为主，与教材原文措辞重合度低，建议对照教材核对。"
        )

    # ---- 6. 风险分级 → 是否打断用户 ----
    needs_human = False
    target = ""
    draft = ""
    if failed:
        needs_human = True
        target = failed[0]
        draft = "上游执行失败，请确认是否重试或改用其他问法。"
    elif agents & HIGH_RISK_AGENTS:
        # 关键结论：解题/批改结论必须人工确认后才能作为最终答案
        needs_human = True
        target = "solver"
        draft = (
            "以上解题结论属于**关键结论**，按流程需你确认后才能作为最终答案。"
            "你可以：✅ 确认直接采纳、✏️ 修正其中某一步、➕ 补充额外条件。"
        )

    passed = all(c["passed"] for c in checks)
    summary_note = "；".join(notes) if notes else "全部检查通过"
    confidence = round(sum(1 for c in checks if c["passed"]) / max(len(checks), 1), 3)

    verdict = {
        "passed": passed,
        "confidence": confidence,
        "checks": checks,
        "notes": summary_note,
        "needs_human": needs_human,
        "target_agent": target,
        "draft": draft,
        "intent": intent,
        "traceability": ratio,
    }

    ctx.emit_artifact(
        "table",
        {
            "title": "独立校验结果",
            "columns": ["检查项", "结论", "说明"],
            "rows": [
                [c["name"], "通过" if c["passed"] else "需注意", c["detail"]] for c in checks
            ],
        },
    )
    return verdict


async def run(state: dict, ctx: RunContext) -> AgentResult:
    verdict = await verify(state, ctx)
    return AgentResult(
        agent=SPEC.id,
        text=verdict.get("notes", ""),
        ok=verdict.get("passed", True),
        data=verdict,
    )

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
from typing import Any, Literal

from ..kernel import events as E
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

# --------------------------------------------------------------------------
# 验证级别（契约：contracts/verification.schema.json；口径：docs/09 §二）
# --------------------------------------------------------------------------
#
#   A  纯数值题      —— SymPy 独立重算 / 符号等价性（确定性，不一致就一定有问题）
#   B  公式推导      —— 符号等价性检验
#   C  应用题        —— 多路一致性 / 约束检查 / 反向代入（交叉验证）
#   D  证明题·开放题 —— 只能人工，明确"未做自动验证"
#
# ⚠️ 诚实性要求（docs/12 M3 红线、docs/15）：级别受两道约束，就低不就高 ——
#   ① **题型封顶**：证明题/开放题（D 类）无论检索到多少依据都只能报 D，
#      因为"逻辑严谨性"本来就不是当前手段能验证的东西；
#   ② **手段封顶**：报了哪一级，就必须真的做过那一级的检查。
# 当前实现只有启发式与溯源类检查，所以**到不了 A/B** —— 那需要 verifier 真的独立重算
# （M1.2 的活，尚未实现）。宁可如实报 C 或 D，也不假装做了符号验证。
VerifyLevel = Literal["A", "B", "C", "D"]

#: 级别 → 置信度上限（schema 明确规定：C 级全通过也不应高于 0.85，D 级 ≤ 0.4）
LEVEL_CONFIDENCE_CAP: dict[str, float] = {"A": 1.0, "B": 0.95, "C": 0.85, "D": 0.4}

#: 各手段能支撑的最高级别（就低不就高：只有启发式 → D）
METHOD_CEILING: dict[str, str] = {
    "sympy_recompute": "A",
    "symbolic_equivalence": "B",
    "back_substitute": "B",
    "multi_path": "C",
    "constraint": "C",
    "grounding": "C",
    "heuristic": "D",
}

#: 题型封顶：证明题/开放题不做承诺（`docs/09` §二）。检测的是**提问**，不是回答。
PROOF_LIKE_PATTERNS = ("证明", "求证", "论证", "推导过程", "说明理由", "为什么成立")

LEVEL_LABEL: dict[str, str] = {
    "A": "已通过数值重算验证",
    "B": "已通过符号等价性验证",
    "C": "已交叉验证（未做形式化证明）",
    "D": "未做自动验证，请自行判断",
}

_LEVEL_ORDER = ["D", "C", "B", "A"]


def is_proof_like(query: str) -> bool:
    """证明题/开放题：属于 D 类，不做自动验证承诺（`docs/09` §二）。"""
    text = (query or "").strip()
    return any(p in text for p in PROOF_LIKE_PATTERNS)


def _achieved_level(checks: list[dict[str, Any]], query: str = "") -> str:
    """由**题型 + 实际用过的检查手段**推出验证级别（两道封顶，就低不就高）。"""
    if is_proof_like(query):
        return "D"  # 题型封顶：证明题不做承诺
    methods = {c.get("method") for c in checks}
    if not methods:
        return "D"
    # 手段封顶：取"最弱的那条检查"能支撑的级别（木桶原理，不取最强）
    ceilings = [METHOD_CEILING.get(m, "D") for m in methods]
    weakest = min(ceilings, key=_LEVEL_ORDER.index)
    return weakest


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
            # 这一项看的是"别人有没有失败"，本身不做任何独立计算 —— 如实标 heuristic
            "method": "heuristic",
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
            # 验证者**独立再检索一次**去核对依据，不采信上游自报 —— 这是溯源检查
            "method": "grounding",
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
                    # 数的是"有没有 >= 3 步"，没有逐步验算步骤正确性 —— 如实标 heuristic
                    "method": "heuristic",
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
                    # 看的是"数值是否由 SymPy 推导"（来源），verifier 自己不重算 —— heuristic
                    "method": "heuristic",
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
            # 数的是 $$ 定界符是否成对（渲染层面），不涉及数学正确性 —— heuristic
            "method": "heuristic",
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

    # ---- 7. 验证级别 + 合规报告（契约：contracts/verification.schema.json）----
    #
    # 级别受两道封顶（见文件头）：题型（证明题只能 D）+ 实际手段（木桶原理）。
    # 所以多数情况落在 C；没有交叉验证手段、或本身就是证明题时，如实退到 D。
    level = _achieved_level(checks, query)
    confidence = min(
        round(sum(1 for c in checks if c["passed"]) / max(len(checks), 1), 3),
        LEVEL_CONFIDENCE_CAP[level],
    )
    summary_note = "；".join(notes) if notes else "全部检查通过"

    #: 无法自动验证的部分 —— 必须如实列出（前端会明确展示，不允许静默忽略）
    unsupported: list[str] = []
    if is_proof_like(query):
        unsupported.append("本题为证明题/开放题：解答的逻辑严谨性无法自动验证，只能人工判断")
    if not has_source:
        unsupported.append("没有教材片段作为依据：结论主要来自模型自身知识，未做事实性核验")
    if not balanced:
        unsupported.append("公式定界符未闭合：渲染层面的问题，已单独标出")
    if level == "D" and not is_proof_like(query):
        unsupported.append(
            "本轮未做独立重算或符号等价性检验（M1.2 数值校验、M1.3 步骤校验尚未实现）"
        )
    # 通过与否不改变"哪些部分没被验证" —— 这里只列**能力所不及**的部分
    report: dict[str, Any] = {
        "level": level,
        "levelLabel": LEVEL_LABEL[level],
        "passed": passed,
        "checks": checks,
        "confidence": confidence,
    }
    if unsupported:
        report["unsupported"] = unsupported

    #: 权威出口：契约事件（前端"显著展示验证级别"订阅的就是它）。
    #: 下面的 table artifact 保留 —— 它是人读的渲染视图，不是判定依据。
    ctx.emit(E.verification_report(state.get("run_id", ""), report))

    verdict = {
        # --- 以下属于合规报告（写入事件的 data，供前端与外部消费）---
        **report,
        # --- 以下仅供编排内部使用（报告 is additionalProperties:false，不能混进去）---
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

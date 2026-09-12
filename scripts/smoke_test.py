#!/usr/bin/env python
"""端到端自检 —— 不启动 HTTP 服务也能验证整条链路。

用途
----
1. 新人 clone 后第一条命令：确认环境没问题。
2. CI 里跑：任何人提交后自动检查契约有没有被破坏。
3. 答辩前跑：确认"能演"。

覆盖范围
-------
- 装配：Agent / 工具自动发现数量
- 编排：mock 模式下跑通「知识问答」「解题 + HITL + 恢复」
- 契约：事件类型是否都在 events.schema.json 的白名单里
- 资产：manifest.json 里每个动画的 controls 选择器是否真实存在于 HTML 中
- 计算：SymPy 分布推导的期望/方差是否与解析解一致

用法：
    cd ProbCrew
    python scripts/smoke_test.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("LLM_PROVIDER", "mock")  # 自检必须确定性、不花钱、不联网

PASS, FAIL = "✔", "✘"
results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((ok, name, detail))
    print(f"  {PASS if ok else FAIL} {name}" + (f"  — {detail}" if detail else ""))
    return ok


def section(title: str) -> None:
    print(f"\n=== {title} ===")


async def drain(run, graph, **kw) -> list:
    from app.kernel import runner

    out = []
    async for line in runner.stream_run(run, graph, **kw):
        out.append(json.loads(line))
    return out


async def drain_resume(run, graph, **kw) -> list:
    from app.kernel import runner

    out = []
    async for line in runner.resume_run(run, graph, **kw):
        out.append(json.loads(line))
    return out


async def main() -> int:
    from app.main import build_app
    from app.kernel.runs import RUNS

    print("=" * 64)
    print("  概率论与数理统计 · 多智能体学习系统 —— 端到端自检")
    print("=" * 64)

    app = build_app()
    agents = app.state.agents
    tools = app.state.tools
    graph = app.state.graph

    def new_run(query: str, session: str = "smoke"):
        run = RUNS.create(session, query)
        run.runtime = {
            "llm": app.state.llm,
            "tools": app.state.tools,
            "settings": app.state.settings,
        }
        return run

    # ---------------- 1. 装配 ----------------
    section("1. 装配（自动发现）")
    ids = [e.spec.id for e in agents.all()]
    check(len(ids) >= 6, f"发现 {len(ids)} 个 Agent", ", ".join(ids))
    check(
        {"orchestrator", "knowledge", "solver", "verifier", "visualizer", "analytics"} <= set(ids),
        "6 个核心 Agent 齐全",
    )
    tool_ids = [t.id for t in tools.all()]
    check(len(tool_ids) >= 10, f"发现 {len(tool_ids)} 个工具")
    check("kb_search" in tool_ids and "distribution_properties" in tool_ids, "关键工具已注册")
    check(app.state.llm.name == "mock", "自检强制使用 mock provider", app.state.llm.name)

    # ---------------- 2. 知识问答 ----------------
    section("2. 编排：知识问答（单 Agent）")
    run = new_run("什么是贝叶斯公式？")
    events = await drain(run, graph, query=run.query, session_id="smoke")
    types = {e["type"] for e in events}
    check("plan" in types, "产生调度计划")
    check("run.end" in types, "正常结束")
    check("artifact" in types, "产出结构化 artifact")
    arts = [e["kind"] for e in events if e["type"] == "artifact"]
    check("formula" in arts, "产出公式卡", str(arts))
    check("animation" in arts, "推荐了交互动画", str(arts))
    final = next((e.get("final_answer") for e in events if e["type"] == "run.end"), "")
    check(bool(final and len(final) > 50), "最终答案非空", f"{len(final or '')} 字符")

    # ---------------- 3. 解题 + HITL ----------------
    section("3. 编排：解题 → 人机协同 → 断点恢复")
    run2 = new_run("求解：已知 P(B1)=0.5，P(A|B1)=0.2，求 P(A)")
    events2 = await drain(run2, graph, query=run2.query, session_id="smoke")
    hitl = [e for e in events2 if e["type"] == "hitl.request"]
    check(bool(hitl), "触发 LangGraph interrupt() 挂起")
    check(run2.interrupt_payload is not None, "运行保持存活并记录 interrupt 载荷")
    check(
        any(e["type"] == "artifact" and e["kind"] == "steps" for e in events2),
        "产出结构化解题步骤",
    )
    check(
        any(e["type"] == "artifact" and e["kind"] == "table" for e in events2),
        "Verifier 产出独立校验表",
    )
    if hitl:
        events3 = await drain_resume(
            run2, graph, action="correct", text="请补充完备事件组说明"
        )
        types3 = [e["type"] for e in events3]
        check(types3.count("run.end") == 1, "恢复后只发一次 run.end", str(types3))
        final3 = next((e.get("final_answer") for e in events3 if e["type"] == "run.end"), "")
        check("已按你的修正重写" in (final3 or ""), "用户修正已回流进最终答案")
        check("校验" in (final3 or ""), "最终答案包含校验说明")

    # ---------------- 4. 契约合规 ----------------
    section("4. 契约：事件类型必须在 schema 白名单内")
    schema_path = ROOT / "contracts" / "events.schema.json"
    allowed = set()
    if schema_path.exists():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        allowed = set(schema["properties"]["type"]["enum"])
    check(bool(allowed), "读到 events.schema.json", f"{len(allowed)} 种事件")
    seen = {e["type"] for e in events} | {e["type"] for e in events2}
    unknown = seen - allowed
    check(not unknown, "实际发出的事件都在白名单内", f"越界：{unknown}" if unknown else "全部合规")

    # ---------------- 5. 动画资产 ----------------
    section("5. 动画资产：manifest 与真实文件一致性")
    from app.tools import animation as anim_tool

    manifest = anim_tool.load_manifest()
    items = manifest.get("animations", [])
    check(len(items) == 8, f"清单包含 {len(items)} 个动画")
    raw_dir = ROOT / "frontend" / "assets" / "animations" / "_raw"
    missing, bad_ctl = [], []
    for a in items:
        path = raw_dir / a["file"]
        if not path.exists():
            missing.append(a["file"])
            continue
        html = path.read_text(encoding="utf-8")
        real_ids = set(re.findall(r'id="([A-Za-z0-9_\-]+)"', html))
        for key, sel in (a.get("controls") or {}).items():
            if sel and sel.startswith("#") and sel[1:] not in real_ids:
                bad_ctl.append(f"{a['id']}.{key}={sel}")
    check(not missing, "所有动画文件存在", f"缺失：{missing}" if missing else f"{len(items)} 个文件")
    check(not bad_ctl, "所有 controls 选择器在真实 HTML 中存在", f"失效：{bad_ctl}" if bad_ctl else "8/8 可驱动")

    # ---------------- 6. 数学正确性 ----------------
    section("6. SymPy 符号计算正确性")
    from app.domain import distributions as D

    cases = [
        ("binomial", {"n": 20, "p": 0.3}, 6.0, 4.2),
        ("poisson", {"lambda": 4}, 4.0, 4.0),
        ("normal", {"mu": 0, "sigma": 1}, 0.0, 1.0),
        ("exponential", {"lambda": 2}, 0.5, 0.25),
        ("uniform", {"a": 0, "b": 1}, 0.5, 1 / 12),
        ("geometric", {"p": 0.25}, 4.0, 12.0),
        ("gamma", {"alpha": 2, "beta": 3}, 6.0, 18.0),
        ("beta", {"alpha": 2, "beta": 2}, 0.5, 0.05),
    ]
    all_ok = True
    for key, prm, exp_mean, exp_var in cases:
        p = D.properties(key, prm)
        ok = abs(p["mean"] - exp_mean) < 1e-9 and abs(p["var"] - exp_var) < 1e-9
        all_ok &= ok
        if not ok:
            print(f"      {FAIL} {key}: E={p['mean']} (期望 {exp_mean}), Var={p['var']} (期望 {exp_var})")
    check(all_ok, f"{len(cases)} 种分布的期望/方差与解析解一致")

    # 归一性：离散看"概率和"，连续看"梯形积分"（密度的值本身不求和为 1）
    def normalized(key: str, prm: dict) -> float:
        s = D.series(key, prm, mode="pdf")
        xs, ys = s["x"], s["y"]
        if D.DISTRIBUTIONS[key].kind == "discrete":
            return sum(ys)
        area = 0.0
        for i in range(1, len(xs)):
            area += (ys[i] + ys[i - 1]) / 2 * (xs[i] - xs[i - 1])
        return area

    bad_norm = []
    for k, prm, _, _ in cases:
        total = normalized(k, prm)
        if abs(total - 1) >= 0.02:
            bad_norm.append(f"{k}={total:.4f}")
    check(
        not bad_norm,
        "8 种分布均已归一（离散求概率和 / 连续求积分）",
        f"偏差过大：{bad_norm}" if bad_norm else "误差 < 2%",
    )

    # ---------------- 汇总 ----------------
    failed = [r for r in results if not r[0]]
    print("\n" + "=" * 64)
    print(f"  结果：{len(results) - len(failed)}/{len(results)} 项通过")
    if failed:
        print("  失败项：")
        for _, name, detail in failed:
            print(f"    {FAIL} {name} {detail}")
        print("=" * 64)
        return 1
    print("  ✔ 全部通过 —— 骨架可运行")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

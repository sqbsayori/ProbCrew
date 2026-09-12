"""内核与领域层的单元测试（不联网、不调 LLM）。

运行：
    cd ProbCrew/backend
    python -m pytest tests -q
或（不装 pytest 也能跑）：
    python tests/test_kernel.py

测试策略
-------
只测**确定性**的部分：领域数学、路由规则、事件协议、动画清单、工具注册。
LLM 相关的一律走 `providers/mock.py`，保证结果可复现。
端到端流程见 `scripts/smoke_test.py`。
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LLM_PROVIDER", "mock")


# --------------------------------------------------------------------------
# 领域层：分布数学
# --------------------------------------------------------------------------


def test_distribution_mean_var_match_analytic() -> None:
    from app.domain import distributions as D

    cases = [
        ("binomial", {"n": 20, "p": 0.3}, 6.0, 4.2),
        ("poisson", {"lambda": 4}, 4.0, 4.0),
        ("geometric", {"p": 0.25}, 4.0, 12.0),
        ("normal", {"mu": 1.5, "sigma": 2}, 1.5, 4.0),
        ("exponential", {"lambda": 2}, 0.5, 0.25),
        ("uniform", {"a": 0, "b": 1}, 0.5, 1 / 12),
        ("gamma", {"alpha": 2, "beta": 3}, 6.0, 18.0),
        ("beta", {"alpha": 2, "beta": 2}, 0.5, 0.05),
    ]
    for key, prm, mean, var in cases:
        p = D.properties(key, prm)
        assert math.isclose(p["mean"], mean, rel_tol=0, abs_tol=1e-9), (key, p["mean"], mean)
        assert math.isclose(p["var"], var, rel_tol=0, abs_tol=1e-9), (key, p["var"], var)


def test_distribution_normalized() -> None:
    """离散求概率和，连续求梯形积分，都应约等于 1。"""
    from app.domain import distributions as D

    for key in D.DISTRIBUTIONS:
        s = D.series(key, None, mode="pdf")
        xs, ys = s["x"], s["y"]
        if D.DISTRIBUTIONS[key].kind == "discrete":
            total = sum(ys)
        else:
            total = sum(
                (ys[i] + ys[i - 1]) / 2 * (xs[i] - xs[i - 1]) for i in range(1, len(xs))
            )
        assert abs(total - 1) < 0.03, (key, total)


def test_cdf_monotonic_and_bounded() -> None:
    from app.domain import distributions as D

    for key in D.DISTRIBUTIONS:
        s = D.series(key, None, mode="cdf")
        ys = s["y"]
        assert all(-1e-9 <= v <= 1 + 1e-9 for v in ys), key
        assert all(ys[i] >= ys[i - 1] - 1e-9 for i in range(1, len(ys))), key


def test_coerce_params_fills_defaults_and_rejects_garbage() -> None:
    from app.domain import distributions as D

    prm = D.coerce_params("normal", {"mu": "0.5", "sigma": "not-a-number"})
    assert prm["mu"] == 0.5
    assert prm["sigma"] == 1.0  # 回落到默认值，不能抛异常


# --------------------------------------------------------------------------
# 路由规则（确定性，不调 LLM）
# --------------------------------------------------------------------------


def test_router_intents() -> None:
    from app.agents import _router

    assert _router.route("什么是贝叶斯公式")[0] == "knowledge"
    assert _router.route("求解这道题")[0] == "solve"
    assert _router.route("画一下正态分布的密度曲线")[0] == "visualize"
    assert _router.route("我的学习进度怎么样")[0] == "analytics"


def test_router_fanout_on_multi_domain() -> None:
    """跨领域问题应当并行调度多个 Agent。"""
    from app.agents import _router

    intent, selection, _ = _router.route("求解这道题，并画一下它的正态分布密度曲线")
    assert intent == "multi"
    assert "solver" in selection
    assert "visualizer" in selection
    assert "knowledge" in selection


def test_extract_distribution_from_natural_language() -> None:
    from app.agents import _router

    d, prm = _router.extract_distribution("正态分布 N(0,1) 的期望")
    assert d == "normal" and prm == {"mu": 0.0, "sigma": 1.0}

    d2, prm2 = _router.extract_distribution("泊松分布 λ=3")
    assert d2 == "poisson" and prm2["lambda"] == 3.0

    d3, _ = _router.extract_distribution("今天天气不错")
    assert d3 is None


# --------------------------------------------------------------------------
# 内核：事件协议 / 注册表
# --------------------------------------------------------------------------


def test_events_serialize_without_none_fields() -> None:
    from app.kernel import events as E

    wire = E.agent_start("run_1", "knowledge", "知识讲解").wire()
    assert '"type":"agent.start"' in wire
    assert "None" not in wire and "null" not in wire


def test_all_emitted_event_types_are_in_schema() -> None:
    import json

    from app.kernel import events as E

    schema_path = Path(__file__).resolve().parents[2] / "contracts" / "events.schema.json"
    allowed = set(json.loads(schema_path.read_text(encoding="utf-8"))["properties"]["type"]["enum"])
    declared = set(E.EventType.__args__)  # type: ignore[attr-defined]
    assert declared == allowed, f"代码与契约不一致：{declared ^ allowed}"


def test_registries_discover_without_manual_registration() -> None:
    from app.kernel.registry import discover_agents, discover_tools

    agents = discover_agents()
    ids = {e.spec.id for e in agents.all()}
    assert {"orchestrator", "knowledge", "solver", "verifier", "visualizer", "analytics"} <= ids

    tools = discover_tools()
    tool_ids = {t.id for t in tools.all()}
    assert {"kb_search", "distribution_properties", "plot_distribution", "recommend_animation"} <= tool_ids


def test_agent_specs_are_wellformed() -> None:
    from app.kernel.registry import discover_agents, discover_tools

    tools = {t.id for t in discover_tools().all()}
    for entry in discover_agents().all():
        spec = entry.spec
        assert spec.id and spec.name and spec.description
        assert spec.role in ("router", "generator", "verifier", "analyst", "tool")
        # 角色门控：Agent 声明的工具必须真实存在
        unknown = set(spec.tools) - tools
        assert not unknown, f"{spec.id} 声明了不存在的工具：{unknown}"


# --------------------------------------------------------------------------
# 工具：知识库 / 动画
# --------------------------------------------------------------------------


def test_kb_search_returns_relevant_section() -> None:
    from app.tools import kb_search

    hits = kb_search.search("什么是贝叶斯公式", top_k=3)
    assert hits, "知识库检索不应为空"
    assert "贝叶斯" in hits[0]["heading"] or "贝叶斯" in hits[0]["content"]


def test_animation_recommendation_maps_concepts() -> None:
    from app.tools import animation as A

    assert len(A.all_animations()) == 8
    assert A.recommend("贝叶斯公式和后验概率", 1)[0]["id"] == "bayes"
    assert A.recommend("中心极限定理 样本均值趋近正态", 1)[0]["id"] == "clt"
    assert A.recommend("网络排队 拥塞 吞吐量", 1)[0]["id"] == "network-traffic"


def test_animation_control_selectors_exist_in_real_files() -> None:
    """接入动画最容易犯的错：controls 写了不存在的 #id。这里自动抓出来。"""
    import re

    from app.config import ANIMATIONS_DIR
    from app.tools import animation as A

    raw = ANIMATIONS_DIR / "_raw"
    for item in A.all_animations():
        path = raw / item["file"]
        assert path.exists(), f"动画文件缺失：{item['file']}"
        html = path.read_text(encoding="utf-8")
        ids = set(re.findall(r'id="([A-Za-z0-9_\-]+)"', html))
        for key, sel in (item.get("controls") or {}).items():
            if sel and sel.startswith("#"):
                assert sel[1:] in ids, f"{item['id']}.{key}={sel} 在 {item['file']} 中不存在"


def test_math_check_detects_equivalence() -> None:
    import asyncio

    from app.tools import math_tools

    same = asyncio.run(math_tools.math_check(left="(x+1)**2", right="x**2+2*x+1"))
    assert same["ok"] and same["equal"] is True

    diff = asyncio.run(math_tools.math_check(left="x+1", right="x+2"))
    assert diff["ok"] and diff["equal"] is False


def test_math_eval_rejects_dangerous_expression() -> None:
    import asyncio

    from app.tools import math_tools

    bad = asyncio.run(math_tools.math_eval(expr="__import__('os').system('echo hi')"))
    assert bad["ok"] is False


# --------------------------------------------------------------------------
# 手动运行入口（无 pytest 时）
# --------------------------------------------------------------------------


def _run_all() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✔ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✘ {name}\n      {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✘ {name}\n      {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())

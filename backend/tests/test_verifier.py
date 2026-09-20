"""验证报告契约（A1）。

守护什么
--------
`contracts/verification.schema.json` 是这个项目的核心契约 ——
它定义了"什么叫这个答案是对的"，以及系统在什么情况下必须承认自己不确定。

它曾经**完全没有生效**：`verification_report()` 构造器零调用、事件从不发出、
`verifier.py` 的产出缺 schema 必需的 `level`、每条 check 缺 `method`，
还多出 `additionalProperties:false` 禁止的字段。前端因此从来没有验证级别可展示。

本文件把"报告必须合规、级别必须诚实"钉死在 CI 里。

跑法
----
    python -m pytest backend/tests/test_verifier.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import os  # noqa: E402

os.environ.setdefault("LLM_PROVIDER", "mock")

from _console import utf8_output  # noqa: E402

utf8_output()

import jsonschema  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VERIFICATION_SCHEMA = ROOT / "contracts" / "verification.schema.json"

#: schema 里 check.method 的合法枚举 —— 硬编码在这里是有意的：
#: 如果契约新增了手段，这条测试会红，逼人回来看"我们的检查到底算不算那种手段"。
ALLOWED_METHODS = {
    "sympy_recompute",
    "symbolic_equivalence",
    "constraint",
    "multi_path",
    "back_substitute",
    "grounding",
    "heuristic",
}


def _validator():
    schema = json.loads(VERIFICATION_SCHEMA.read_text(encoding="utf-8"))
    return jsonschema.Draft7Validator(schema)


def _capture_report_for(query: str) -> dict:
    """真跑一次问答，取回发出去的 `verification.report` 的 data。"""
    from fastapi.testclient import TestClient

    from _auth import login_client
    from app.main import app

    reports: list[dict] = []
    with TestClient(app) as client:
        login_client(client)  # 对话接口需要登录（账号体系）
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"query": query, "session_id": "verifier-contract"},
        ) as resp:
            assert resp.status_code == 200, f"问答接口未成功：{resp.status_code}"
            for line in resp.iter_lines():
                if not line:
                    continue
                text = line.decode("utf-8") if isinstance(line, bytes) else line
                if not text.startswith("data:"):
                    continue
                payload = text[len("data:") :].strip()
                if not payload:
                    continue
                event = json.loads(payload)
                if isinstance(event, dict) and event.get("type") == "verification.report":
                    reports.append(event.get("data") or {})
    assert reports, "这次运行没有发出 verification.report 事件 —— 验证闭环又断了"
    return reports[0]


def test_report_conforms_to_verification_schema() -> None:
    """真实报告必须通过 `contracts/verification.schema.json`（不是只校验内嵌 examples）。"""
    report = _capture_report_for("什么是全概率公式？")
    errors = list(_validator().iter_errors(report))
    assert not errors, "验证报告违反契约：\n  " + "\n  ".join(
        f"{'/'.join(str(p) for p in e.absolute_path) or '(根)'}: {e.message}" for e in errors
    )


def test_every_check_declares_a_capability_method() -> None:
    """每条检查都必须声明 `method` —— 它决定这条检查有多可信。"""
    report = _capture_report_for("什么是全概率公式？")
    checks = report.get("checks") or []
    assert checks, "报告里没有任何检查项"

    missing = [c.get("name") for c in checks if not c.get("method")]
    assert not missing, f"这些检查项没有声明 method：{missing}"

    unknown = sorted({c["method"] for c in checks} - ALLOWED_METHODS)
    assert not unknown, f"出现了契约未定义的 method：{unknown}"


def test_level_is_honest_about_what_was_actually_done() -> None:
    """级别必须由**实际做过的手段**决定，不能虚报。

    当前实现只有启发式与溯源类检查（还没有独立重算），
    所以级别不应是 A/B；真正做了确定性验证时才会升上去。
    """
    report = _capture_report_for("什么是全概率公式？")
    methods = {c.get("method") for c in report.get("checks") or []}

    if not methods & {"sympy_recompute", "symbolic_equivalence", "back_substitute"}:
        assert report["level"] in {"C", "D"}, (
            f"没有任何确定性验证手段，却报了级别 {report['level']}（虚报）"
        )


def test_confidence_respects_level_cap() -> None:
    """置信度上限按 schema：C 级不得高于 0.85，D 级不得高于 0.4。"""
    report = _capture_report_for("什么是全概率公式？")
    caps = {"A": 1.0, "B": 0.95, "C": 0.85, "D": 0.4}
    cap = caps[report["level"]]
    assert report["confidence"] <= cap + 1e-9, (
        f"级别 {report['level']} 的置信度 {report['confidence']} 超过上限 {cap}"
    )


def test_proof_like_question_is_reported_as_unverified() -> None:
    """证明题这类无法自动验证的题，必须**如实**给出 unsupported，而不是假装通过。"""
    report = _capture_report_for("证明：若 A 与 B 独立，则 A 与 B 的补也独立。（要求写出证明过程）")
    assert report["level"] == "D", (
        f"这题没有可自动验证的结论，级别应为 D，实际 {report['level']}"
    )
    assert report.get("unsupported"), "D 级报告必须列出 unsupported（哪些部分无法自动验证）"


def test_level_helper_is_low_ball_not_optimistic() -> None:
    """单元级：级别由题型 + 手段两道封顶推出，就低不就高。"""
    from app.agents.verifier import _achieved_level, is_proof_like

    # 没有检查手段 → D
    assert _achieved_level([]) == "D"
    # 只有启发式 → D（启发式支撑不了任何承诺）
    assert _achieved_level([{"method": "heuristic"}]) == "D"
    # 木桶原理：只要有一条是启发式，整体就退到 D —— 不取最强的那条
    assert _achieved_level([{"method": "grounding"}, {"method": "heuristic"}]) == "D"
    # 只有交叉验证类 → C
    assert _achieved_level([{"method": "grounding"}]) == "C"
    assert _achieved_level([{"method": "constraint"}]) == "C"
    # 确定性手段如实映射：sympy_recompute 支撑 A（数值不一致就一定有问题），
    # 符号等价性支撑 B。注意"当前实现到不了 A"不是靠这里压低，
    # 而是**因为检查项里根本没有 sympy_recompute 这种手段**（M1.2 尚未实现）。
    assert _achieved_level([{"method": "sympy_recompute"}]) == "A"
    assert _achieved_level([{"method": "symbolic_equivalence"}]) == "B"

    # 题型封顶：证明题只能 D，哪怕检索到了依据
    proof = "证明：若 A 与 B 独立，则 A 与 B 的补也独立"
    assert is_proof_like(proof)
    assert _achieved_level([{"method": "grounding"}], proof) == "D"
    assert not is_proof_like("什么是全概率公式？")

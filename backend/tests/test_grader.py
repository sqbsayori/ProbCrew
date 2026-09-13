"""批改闭环（立项书 M3 的 Grader，最小版）单元测试。

守什么
------
1. **标准答案可信**：题库里的每一步都能解析、`final` 与独立复算一致；
2. **判定靠算不靠猜**：`0.026` / `2.6%` / `13/28` 这些等价写法要判对，
   接近但不相等的要判错（容差不能宽到把错的算成对的）；
3. **诊断要具体**：典型错答（如贝叶斯漏分母）要点出"错在哪、为什么"，
   而不是只说一句"不正确"；
4. **失败显式**：题目不在库里、解析不出答案、题库为空 —— 三种情况都要如实说，
   `graded=None` 表示"没判定"，绝不糊一个结果出来。

运行：
    cd ProbCrew/backend
    python -m pytest tests/test_grader.py -q
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LLM_PROVIDER", "mock")


# --------------------------------------------------------------------------
# 答案解析
# --------------------------------------------------------------------------


def test_normalize_accepts_common_forms() -> None:
    from app.tools.grader import normalize_answer

    assert normalize_answer("0.026")["expr"] == "0.026"
    assert normalize_answer("P(D)=0.026")["expr"] == "0.026"
    assert normalize_answer("答案是 0.026")["expr"] == "0.026"
    assert normalize_answer("≈ 0.026")["expr"] == "0.026"
    assert normalize_answer("$0.026$")["expr"] == "0.026"
    assert normalize_answer("13/28")["expr"] == "(13)/(28)", "纯分数不应被当成算式"
    assert normalize_answer("45*0.05**2*0.95**8")["kind"] == "expression", "整算式要整体保留"


def test_normalize_converts_percent_to_decimal() -> None:
    from app.tools.grader import normalize_answer

    got = normalize_answer("2.6%")
    assert got["expr"].startswith("0.0")
    assert abs(float(got["expr"]) - 0.026) < 1e-9
    assert got["percent"] is True


def test_normalize_reports_unparsed_input() -> None:
    from app.tools.grader import normalize_answer

    for bad in ("", "不知道", "我算不出来"):
        got = normalize_answer(bad)
        assert got["expr"] == "", bad
        assert got["kind"] in ("empty", "unparsed")


# --------------------------------------------------------------------------
# 判定
# --------------------------------------------------------------------------


def test_correct_answer_passes() -> None:
    from app.tools.grader import grade

    r = grade(problem_id="ex-total-prob-01", student_answer="0.026")
    assert r["ok"] and r["available"] and r["graded"] is True
    assert r["verdict"] == "正确"
    assert r["basis"], "要说明判定依据（符号等价 / 数值近似）"
    assert r["steps"], "要给出逐步比对结果"


def test_equivalent_forms_are_accepted() -> None:
    """等价写法必须判对：2.6% 与 0.026 是同一个答案。"""
    from app.tools.grader import grade

    for ans in ("2.6%", "0.026", "$0.026$", "P(D)=0.026"):
        r = grade(problem_id="ex-total-prob-01", student_answer=ans)
        assert r["graded"] is True, ans


def test_fraction_equivalence() -> None:
    """13/28 与 10/28+3/28 是同一个答案（符号等价）。"""
    from app.tools.grader import grade

    r = grade(problem_id="ex-cond-prob-01", student_answer="13/28")
    assert r["graded"] is True
    r2 = grade(problem_id="ex-cond-prob-01", student_answer="0.4643")
    assert r2["graded"] is True, "手算四舍五入到 4 位应当接受"


def test_wrong_answer_fails_with_specific_diagnosis() -> None:
    """贝叶斯那道题只写分子（漏了分母里健康人误判那部分）→ 要点出这一点。"""
    from app.tools.grader import grade

    r = grade(problem_id="ex-bayes-01", student_answer="0.00099")
    assert r["graded"] is False
    assert r["verdict"] == "不正确"
    diag = r.get("diagnosis") or {}
    assert diag.get("kind") == "distractor", diag
    assert "分母" in diag.get("message", ""), diag
    assert r.get("pitfalls"), "典型错误要附上易错点"


def test_stalled_at_intermediate_step_is_diagnosed() -> None:
    """学生只算到中间量（如 P(+)=0.05094）→ 告诉他"还需要继续算到最终结果"。

    注意取的是**最靠后**匹配的那一步：0.05094 同时等于第 2 步的算式与第 3 步的结果，
    学生实际算到的是第 3 步。
    """
    from app.tools.grader import grade

    r = grade(problem_id="ex-bayes-01", student_answer="0.05094")
    assert r["graded"] is False
    diag = r.get("diagnosis") or {}
    assert diag.get("kind") == "stalled"
    assert diag.get("index") == 3, diag
    assert "继续" in diag.get("message", "")


def test_tolerance_boundary_is_sane() -> None:
    """容差边界：标准答案只给到 2 位有效数字，所以 0.0265 判对、0.03 判错。

    这条测试的由来：容差一开始用了 1e-3 相对误差，导致 0.03 也被判对；
    改成"按精度"后又一度按学生答案的位数算，导致 0.0265 被判错。
    两个方向都踩过，所以把边界固定下来。
    """
    from app.tools.grader import grade

    # 同量级的四舍五入 → 判对（标准答案自己只写到 0.026 / 2.6%）
    assert grade(problem_id="ex-total-prob-01", student_answer="0.0265")["graded"] is True
    assert grade(problem_id="ex-total-prob-01", student_answer="0.026")["graded"] is True
    # 明显错的 → 判错（差 15% / 差 8%）
    assert grade(problem_id="ex-total-prob-01", student_answer="0.03")["graded"] is False
    assert grade(problem_id="ex-total-prob-01", student_answer="0.024")["graded"] is False
    assert grade(problem_id="ex-total-prob-01", student_answer="0")["graded"] is False


def test_numeric_variants_of_same_answer_pass() -> None:
    """0.0746 与 45×0.05²×0.95⁸ 是同一个答案。"""
    from app.tools.grader import grade

    assert grade(problem_id="ex-binomial-01", student_answer="0.0746")["graded"] is True
    assert (
        grade(
            problem_id="ex-binomial-01", student_answer="45*0.05**2*0.95**8"
        )["graded"]
        is True
    )


# --------------------------------------------------------------------------
# 失败必须显式
# --------------------------------------------------------------------------


def test_unknown_problem_says_unavailable() -> None:
    from app.tools.grader import grade

    r = grade(problem_id="不存在的题", student_answer="0.5")
    assert r["available"] is False and r["ok"] is False
    assert "无法批改" in r["error"]
    assert r.get("gradable"), "要给出当前可批改的题目清单"


def test_unparsable_answer_is_not_guessed() -> None:
    from app.tools.grader import grade

    r = grade(problem_id="ex-total-prob-01", student_answer="我不会")
    assert r["available"] is True
    assert r["graded"] is None, "解析不出答案时不许猜对错"
    assert "解析" in r["error"]


# --------------------------------------------------------------------------
# 题库自身
# --------------------------------------------------------------------------


def test_bank_loads_strict_and_is_self_consistent() -> None:
    """strict 加载会校验每步 expr 可解析、id 不重复、final 存在。"""
    from app.tools.grader import load_bank

    problems = load_bank(strict=True)
    assert len(problems) >= 9, "批改最小版至少要能覆盖例题库里的题"
    for p in problems:
        assert p["id"] and p["final"]["expr"]
        assert p["steps"], f"{p['id']} 应当给出标准解法的步骤"
        for st in p["steps"]:
            assert st["index"] and st["expr"]


def test_bank_covers_the_example_library() -> None:
    """例题库里能批改的题要尽量都在题库里 —— 否则'做题—批改'会断档。"""
    import json

    root = Path(__file__).resolve().parents[2]
    examples = json.loads(
        (root / "backend" / "knowledge_base" / "examples.json").read_text(encoding="utf-8")
    )["examples"]
    example_ids = {e["id"] for e in examples}

    from app.tools.grader import load_bank

    bank_ids = {p["id"] for p in load_bank(strict=False)}
    missing = example_ids - bank_ids
    assert not missing, f"这些例题还不可批改：{sorted(missing)}"


def test_grader_is_discovered_as_tool() -> None:
    """新工具必须被自动发现（零登记），且能通过契约校验。"""
    from app.kernel.registry import discover_tools

    ids = {t.id for t in discover_tools().all()}
    assert "grade_answer" in ids


def test_grade_answer_tool_wraps_grade() -> None:
    import asyncio

    from app.tools.grader import grade_answer

    out = asyncio.run(grade_answer(problem_id="ex-total-prob-01", student_answer="0.026"))
    assert out["graded"] is True


# --------------------------------------------------------------------------
# 手动运行入口（无 pytest 时）
# --------------------------------------------------------------------------


def _run_all() -> int:
    import traceback

    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✔ {name}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"  ✘ {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())

#!/usr/bin/env python
"""题库复核脚本 —— 逐题用 SymPy 独立复算标准答案。

为什么必须有它
--------------
批改的可信度**完全取决于标准答案**。一旦某题的标准解写错，
批改就会一本正经地判学生错 —— 这比不批改更糟。
所以本脚本对每道题做三件事：

1. **自洽**：每一步的 expr 与 final.expr 都能被解析、能求出数值；
2. **独立复算**：把「标准解法」的关键中间量与**独立算出的值**逐项比对
   （比对表写在本脚本里，与题库文件分离，避免"改题干顺手把答案也改了"）；
3. **错答有效性**：`distractors` 里的典型错答**必须与标准答案不等价**
   （否则诊断会误报"你犯了典型错误"）。

用法
----
    cd ProbCrew
    python scripts/verify_question_bank.py
    python scripts/verify_question_bank.py --json     # 机器可读输出
"""
from __future__ import annotations

from _console import utf8_output

utf8_output()

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sympy import N, binomial, exp, simplify  # noqa: E402

from app.tools.grader import _parse, load_bank, normalize_answer  # noqa: E402

#: 期望值（**独立算出**，不从题库读）：{题目 id: {量名: (题库里的表达式, 期望数值)}}
EXPECTED: dict[str, dict[str, tuple[str, float]]] = {
    "ex-total-prob-01": {
        "final": ("0.026", 0.20 * 0.06 + 0.30 * 0.03 + 0.50 * 0.01),
    },
    "ex-bayes-01": {
        "分母": ("0.05094", 0.99 * 0.001 + 0.05 * 0.999),
        "final": ("0.00099/0.05094", 0.99 * 0.001 / (0.99 * 0.001 + 0.05 * 0.999)),
    },
    "ex-cond-prob-01": {
        "同色": ("(binomial(5,2)+binomial(3,2))/binomial(8,2)", (10 + 3) / 28),
        "第二球白": ("5/8", 5 / 8),
    },
    "ex-binomial-01": {
        "组合数": ("binomial(10,2)", 45),
        "final": ("45*0.05**2*0.95**8", 45 * 0.05**2 * 0.95**8),
    },
    "ex-poisson-01": {
        "λ": ("2/3", 2 / 3),
        "P(X=0)": ("exp(-2/3)", float(N(exp(-2 / 3)))),
        "P(X≤1)": ("exp(-2/3)*(1+2/3)", float(N(exp(-2 / 3) * (1 + 2 / 3)))),
    },
    "ex-normal-01": {
        "final": ("0.9332-0.1587", 0.9332 - 0.1587),
    },
    "ex-exp-01": {
        "final": ("exp(-0.5)", float(N(exp(-0.5)))),
    },
    "ex-expectation-01": {
        "E[X]": ("2/3", 2 / 3),
        "E[X²]": ("1/2", 0.5),
        "Var": ("1/2 - (2/3)**2", 0.5 - (2 / 3) ** 2),
    },
    "ex-clt-01": {
        "σ(X̄)": ("2", 12 / 36**0.5),
        "final": ("0.6827", 0.8413 - 0.1587),
    },
    "ex-marginal-01": {
        "f_X(x) 在 x=0.5": ("2*0.5", 1.0),
        "f_Y(y) 在 y=0.5": ("3*0.5**2", 0.75),
        "独立判据": ("0", 0.0),
    },
}

#: 允许的相对误差（这些数值来自课本表格/四舍五入，不可能精确到 1e-12）
TOL = 5e-3


def _num(expr: str) -> float:
    return float(N(_parse(expr)))


def main() -> int:
    ap = argparse.ArgumentParser(description="逐题复核题库标准答案")
    ap.add_argument("--json", action="store_true", help="输出 JSON（供 CI 或其他脚本消费）")
    args = ap.parse_args()

    problems = load_bank(strict=True)  # strict 会在这里做第一层自洽检查
    results: list[dict[str, object]] = []
    failures = 0

    for p in problems:
        pid = p["id"]
        entry: dict[str, object] = {"id": pid, "title": p.get("title", ""), "checks": [], "ok": True}

        # ---- 1. 题库自带步骤/最终答案可解析且能求值 ----
        try:
            got = _num(str(p["final"]["expr"]))
            entry["final_value"] = round(got, 6)
        except Exception as exc:  # noqa: BLE001
            entry["ok"] = False
            entry["checks"].append({"name": "final 可求值", "ok": False, "detail": str(exc)})
            failures += 1
            results.append(entry)
            continue

        # ---- 2. 与独立算出的期望值比对 ----
        expected = EXPECTED.get(pid)
        if expected is None:
            entry["checks"].append(
                {"name": "独立复算", "ok": False, "detail": "本脚本没有为该题登记期望值"}
            )
            entry["ok"] = False
            failures += 1
        else:
            for name, (expr, want) in expected.items():
                try:
                    have = _num(expr)
                except Exception as exc:  # noqa: BLE001
                    entry["checks"].append({"name": name, "ok": False, "detail": f"无法求值：{exc}"})
                    entry["ok"] = False
                    failures += 1
                    continue
                ok = abs(have - want) <= TOL * max(1.0, abs(want))
                entry["checks"].append(
                    {"name": name, "ok": ok, "have": round(have, 6), "want": round(want, 6)}
                )
                if not ok:
                    entry["ok"] = False
                    failures += 1

        # ---- 3. 典型错答必须与标准答案不等价 ----
        for d in p.get("distractors") or []:
            hit, _detail = _safe_equal(str(d["expr"]), str(p["final"]["expr"]))
            if hit:
                entry["checks"].append(
                    {
                        "name": f"错答 {d.get('label')} 应不等价",
                        "ok": False,
                        "detail": "该错答与标准答案等价 —— 会误报'你犯了典型错误'",
                    }
                )
                entry["ok"] = False
                failures += 1

        results.append(entry)

    if args.json:
        print(json.dumps({"problems": results, "failures": failures}, ensure_ascii=False, indent=2))
        return 1 if failures else 0

    print("=" * 66)
    print("  题库复核（逐题 SymPy 独立复算）")
    print("=" * 66)
    for entry in results:
        flag = "✔" if entry["ok"] else "✘"
        print(f"\n  {flag} {entry['id']}  {entry.get('title', '')}")
        for c in entry["checks"]:
            mark = "✔" if c["ok"] else "✘"
            extra = ""
            if "have" in c:
                extra = f"  得到 {c['have']} / 期望 {c['want']}"
            elif c.get("detail"):
                extra = f"  {c['detail']}"
            print(f"      {mark} {c['name']}{extra}")
    print()
    print("=" * 66)
    if failures:
        print(f"  ✘ {failures} 项未通过 —— **标准答案不可信，先修题库再开批改**")
        return 1
    print(f"  ✔ {len(results)} 道题全部通过（含典型错答有效性检查）")
    print("=" * 66)
    return 0


def _safe_equal(a: str, b: str) -> tuple[bool, str]:
    try:
        return bool(simplify(_parse(a) - _parse(b)) == 0), ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


if __name__ == "__main__":
    raise SystemExit(main())

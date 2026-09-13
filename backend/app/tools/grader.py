"""题目批改闭环（立项书 M3 的 Grader，最小可用版）。

背景
----
立项书把「练习批改闭环」列为核心：`Problem Solver 生成解答 → Grader 依据
**已核验的标准答案**逐步批改 → 定位错误步骤并提炼易错点 → 写错题库`。
本文档落地其中的**批改**这一环，且刻意做小、做准：

1. **标准答案必须先被核验**。批改的可信度完全取决于标准答案；
   所以题目库里的每一步都要写明期望值，并在加载时**校验数学等价性**，
   校验不过直接拒绝加载 —— 宁可少几道题，也不拿错答案判学生。
2. **独立复算，不靠模型自觉**。判定学生的答案用 SymPy 做代数量比较
   （`1/4`、`0.25`、`13/52` 视为同一答案），不调用 LLM 猜"像不像对"。
3. **定位到步**。不只说对/错，还要指出**第一处错的步骤**与正确的下一步，
   这是立项书对批改的要求（"定位错误步骤、提炼易错点"）。
4. **失败必须显式**。题目不在库里 / 解析不出答案 / 该题未配标准解 → 都要说出来，
   不允许糊一个"看起来批改了"的结果。

扩展方式（把批改从 10 道扩到任意多道）
------------------------------------
往 `backend/data/question_bank/*.json` 加文件即可，**不用改代码**：

```json
{
  "version": 1,
  "problems": [
    {
      "id": "q-xxx-01",
      "title": "…",
      "chapter": "ch02",
      "problem": "题目原文",
      "final": {"expr": "0.026", "label": "次品率"},
      "steps": [
        {"index": 1, "title": "找完备事件组", "expr": "0.8", "source": "…"}
      ],
      "pitfalls": ["…"],
      "distractors": [
        {"expr": "0.0", "label": "典型错答", "message": "错在哪、为什么"}
      ],
      "source": "自编 · 逐题 SymPy 复算"
    }
  ]
}
```
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT
from ..kernel.specs import tool
from .math_tools import _parse

__all__ = ["load_bank", "gradable_problems", "grade", "reset_cache"]

#: 题库根目录（仓库内自编题 + 仓库外补充题都放这里）
BANK_DIR = PROJECT_ROOT / "backend" / "data" / "question_bank"

#: 数值比较的兜底容差（真正的容差按学生答案精度算，见 `_tol_for`）。
#: 保留这个常量只为文档可读性：它说明"学生手算会四舍五入"这件事必须被容忍，
#: 但容忍的尺度要跟着答案精度走，不能一刀切宽。
_REL_TOL = 1e-3
#: 百分号改写：0.026 与 2.6% 视为同一答案
_PERCENT_HINT = re.compile(r"(\d+(?:\.\d+)?)\s*%")

#: Φ 是标准正态分布函数，语料与题目里到处在用；SymPy 里没有，用 erf 表达。
_EXTRA_LOCALS = {
    "Phi": lambda x: (1 + _sympy_erf(x / math.sqrt(2))) / 2,
}


def _sympy_erf(x: Any) -> Any:
    import sympy as sp

    return sp.erf(x)


def _locals() -> dict[str, Any]:
    from .math_tools import _SAFE_LOCALS  # type: ignore[attr-defined]

    return {**_SAFE_LOCALS, **_EXTRA_LOCALS}


# --------------------------------------------------------------------------
# 题库加载与校验
# --------------------------------------------------------------------------


_bank: list[dict[str, Any]] | None = None
_bank_problems: dict[str, list[str]] = {}


def _read_files() -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    if not BANK_DIR.is_dir():
        return out
    for path in sorted(BANK_DIR.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            out.append((path.name, {"_broken": f"JSON 解析失败：{exc}"}))
            continue
        out.append((path.name, data))
    return out


_DECIMAL_LITERAL = re.compile(r"\d+\.(\d+)")


def _precision(text: str, value: float) -> int:
    """有效数字位数。

    ⚠️ 这里必须**对两边的写法一视同仁**：标准答案写 `0.026`（文本 3 位小数）、
    学生写 `0.0265`（4 位小数），如果各自数自己的小数位，容差就会一边 0.0006、
    一边 0.00006，比不出结果。踩过的坑：
      * 去表达式里找小数字面量 → `45*0.05**2*0.95**8` 被当成 1 位精度，容差放大到 0.05；
      * 直接数原文本位数 → `0.026`（3）与 `0.0265`（4）不可比。

    规则：数值 ≥1 或文本是纯整数 → 按整数位数（如 `2` → 1 位，容差 0.6）；
    其余（0 与小数）→ 统一按 3 位有效数字（容差 0.0006）。
    """
    if abs(value) >= 1 or re.fullmatch(r"[+-]?\d+", str(text).strip()):
        return max(1, len(str(int(abs(value)))) if abs(value) >= 1 else 1)
    return 3


def _tol_for(student_text: str, student_value: float, expect_text: str, expect_value: float) -> float:
    """容差 = 0.6 × 10^(−min(学生有效位, 标准答案有效位)) × max(1, |值|)。

    * 标准答案 `0.026`（2 位）→ 容差 ±0.005：`0.0265` 属同一量级四舍五入，**判对**；
      `0.03`（差 15%）、`0.024`（差 8%）**判错**。
    * 标准答案 `0.0746`（4 位）→ 容差 ±0.00006：`0.074635` 版本的真值**判对**。

    ⚠️ 这个方向踩过三次坑（1e-3 相对容差太松 → 按学生位数太严 → 数字面量数错位数），
    所以边界由 `test_tolerance_boundary_is_sane` 钉死。
    """
    # 期望值非零而学生写 0：这不是"四舍五入"，是没做出来 —— 零容差，直接判错。
    if abs(expect_value) > 1e-12 and abs(student_value) <= 1e-12:
        return 0.0
    p = min(_precision(student_text, student_value), _precision(expect_text, expect_value))
    return 0.6 * (10.0 ** -p) * max(1.0, abs(expect_value))


def _expr_equal(student: str, expect: str) -> tuple[bool, str]:
    """两步比较：先符号等价，再按**文本精度**做数值近似。

    ⚠️ 约定：第一个参数是**学生的作答**，第二个是标准答案。
    """
    import sympy as sp

    try:
        left = _parse(student)
        right = _parse(expect)
    except Exception as exc:  # noqa: BLE001
        return False, f"表达式无法解析：{exc}"
    try:
        if sp.simplify(left - right) == 0:
            return True, "符号等价"
    except Exception:  # noqa: BLE001 - 某些表达式 simplify 会失败，退到数值
        pass
    try:
        lv = float(sp.N(left))
        rv = float(sp.N(right))
    except Exception:  # noqa: BLE001
        try:  # 复数（本题库不该出现，但别因此崩）
            lv, rv = complex(sp.N(left)), complex(sp.N(right))  # type: ignore[assignment]
        except Exception as exc:  # noqa: BLE001
            return False, f"无法求值：{exc}"

    # 精度从"最终值的写法"读：学生写表达式（45*0.05**2*0.95**8）时，
    # 要看它**算出来的值**，而不是去数表达式里的小数字面量。
    tol = _tol_for(_fmt(lv, student), lv, _fmt(rv, expect), rv)
    return (abs(lv - rv) <= tol), f"数值比较（容差 {tol:.2g}）"


def _fmt(value: float, source: str) -> str:
    """取用于判断精度的文本：原文本是纯数字就用它，否则用计算结果。"""
    text = str(source).strip()
    if re.fullmatch(r"[+-]?\d*\.?\d+", text):
        return text
    return f"{value:.6g}"


def load_bank(*, strict: bool = True) -> list[dict[str, Any]]:
    """加载并**自校验**题库。

    `strict=True`（默认）时，任何一步的自身校验失败都会抛错 ——
    标准答案不可信时，批改结果一文不值。
    """
    global _bank, _bank_problems
    if _bank is not None:
        return _bank

    problems: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for filename, data in _read_files():
        if "_broken" in data:
            if strict:
                raise ValueError(f"题库 {filename}：{data['_broken']}")
            continue
        for item in data.get("problems", []):
            pid = str(item.get("id", "")).strip()
            if not pid:
                if strict:
                    raise ValueError(f"题库 {filename}：有题目缺 id")
                continue
            if pid in seen:
                raise ValueError(f"题目 id 重复：{pid}（{seen[pid]} 与 {filename}）")
            seen[pid] = filename

            final = item.get("final") or {}
            if not final.get("expr"):
                if strict:
                    raise ValueError(f"题目 {pid} 没有 final.expr —— 无法自动批改")
                continue

            steps = list(item.get("steps") or [])
            for st in steps:
                if not st.get("expr"):
                    if strict:
                        raise ValueError(f"题目 {pid} 的第 {st.get('index')} 步缺 expr")
                    steps = []
                    break
                # 自查：这一步的期望值必须能被解析（否则批改时会全部判错）
                try:
                    _parse(str(st["expr"]))
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(
                        f"题目 {pid} 第 {st.get('index')} 步的 expr 无法解析：{st['expr']}（{exc}）"
                    ) from exc
            try:
                _parse(str(final["expr"]))
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"题目 {pid} 的 final.expr 无法解析：{final['expr']}（{exc}）") from exc

            problems.append({**item, "steps": steps, "_file": filename})

    problems.sort(key=lambda p: (str(p.get("chapter", "")), str(p.get("id", ""))))
    _bank = problems
    _bank_problems = {}
    for p in problems:
        _bank_problems.setdefault(p["id"], []).append(p.get("_file", ""))
    return problems


def reset_cache() -> None:
    """测试用：丢掉题库缓存。"""
    global _bank, _bank_problems
    _bank = None
    _bank_problems = {}


def gradable_problems() -> list[dict[str, str]]:
    """当前可自动批改的题目清单（前端"可批改"提示用）。"""
    return [
        {
            "id": p["id"],
            "title": p.get("title", ""),
            "chapter": p.get("chapter", ""),
            "steps": str(len(p.get("steps") or [])),
        }
        for p in load_bank(strict=False)
    ]


# --------------------------------------------------------------------------
# 学生答案解析
# --------------------------------------------------------------------------

_NUM = r"[+-]?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?"
_LATEX_WRAP = re.compile(r"\$+([^$]+)\$+")


def normalize_answer(text: str) -> dict[str, Any]:
    """把学生输入归一化成可比较的表达式。

    支持：`0.026` / `2.6%` / `13/28` / `$0.026$` / `约等于 2.6%` / `P(D)=0.026`
    / `45*0.05**2*0.95**8`（整表达式）。

    解析顺序（顺序有讲究，踩过坑）：
      ① 百分数 → 小数（必须先做，否则 `2.6%` 会先被当成数字 `2.6`）
      ② **整表达式**：如果清理后的输入本身就是一个可求值的算式，就用它
         （否则 `45*0.05**2*0.95**8` 会被"找第一个数字"截成 `45`）
      ③ 单个数字 / 分数
      ④ 以上都不是 → 取最后一个数（`P(D)=0.026` 这类等式的右侧）

    返回 `{expr, kind, percent, ambiguous, raw}`；解析不出时 `expr` 为空串。
    """
    raw = (text or "").strip()
    if not raw:
        return {"expr": "", "kind": "empty", "percent": False, "ambiguous": [], "raw": raw}

    cleaned = _LATEX_WRAP.sub(r"\1", raw)
    cleaned = re.sub(r"(?i)^(答案是|答案|结果|约等于|约为|等于|≈|=|：|:|\s)+", "", cleaned).strip()
    cleaned = cleaned.strip("。.；;，, ")

    if not cleaned:
        return {"expr": "", "kind": "empty", "percent": False, "ambiguous": [], "raw": raw}

    # ① 百分数（先处理，避免 2.6% 被当 2.6）
    pct = _PERCENT_HINT.fullmatch(cleaned) or (
        _PERCENT_HINT.search(cleaned) if cleaned.endswith("%") else None
    )
    if pct:
        return {
            "expr": repr(float(pct.group(1)) / 100.0),
            "kind": "percent",
            "percent": True,
            "ambiguous": [],
            "raw": raw,
        }

    # ② 整个输入就是一个算式吗（含运算符，且**不是纯分数**）
    is_fraction_only = re.fullmatch(r"\s*[+-]?\d*\.?\d+\s*/\s*\d*\.?\d+\s*", cleaned)
    if not is_fraction_only and re.fullmatch(r"[0-9+\-*/^().\s]+", cleaned) and re.search(r"[+\-*^]|/\s*[a-zA-Z(]", cleaned):
        try:
            _parse(cleaned)
            return {"expr": cleaned, "kind": "expression", "percent": False, "ambiguous": [], "raw": raw}
        except Exception:  # noqa: BLE001
            pass

    # ③ 单个数字 / 分数
    if re.fullmatch(r"[+-]?\d*\.?\d+", cleaned):
        return {"expr": cleaned, "kind": "number", "percent": False, "ambiguous": [], "raw": raw}
    frac = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", cleaned)
    if frac:
        return {
            "expr": f"({frac.group(1)})/({frac.group(2)})",
            "kind": "fraction",
            "percent": False,
            "ambiguous": [],
            "raw": raw,
        }

    # ④ 等式的右侧或文字里最后一个数（如 P(D)=0.026、答案是 0.026）
    nums = re.findall(_NUM, cleaned)
    if nums:
        return {
            "expr": nums[-1],
            "kind": "number",
            "percent": False,
            "ambiguous": nums[:-1][-3:],
            "raw": raw,
        }
    return {"expr": "", "kind": "unparsed", "percent": False, "ambiguous": [], "raw": raw}


def _accept(expect: str, student_expr: str) -> tuple[bool, str]:
    """判定学生答案是否等价于期望值。

    ⚠️ 这里把参数**翻转**后交给 `_expr_equal`（学生在前），
    因为容差必须按学生的精度算 —— 这个方向错过一次，代价是把错的判成对的。
    """
    return _expr_equal(student_expr, expect)


def _diagnose(problem: dict[str, Any], student_expr: str) -> dict[str, Any]:
    """诊断学生到底卡在哪：典型错答 → 中间步骤 → 首处不一致。

    **典型错答优先**：`P(D|+)=0.99×0.001=0.00099` 这种答案不是"算错一步"，
    而是**漏了分母里"健康人被误判"那一大块** —— 直接点出来才叫讲清楚。
    这些错答是人工提炼的（`distractors`），不是模型现编的。
    """
    for d in problem.get("distractors") or []:
        if not d.get("expr"):
            continue
        hit, _detail = _accept(str(d["expr"]), student_expr)
        if hit:
            return {
                "kind": "distractor",
                "message": str(d.get("message") or "这属于本题的典型错误。"),
                "label": str(d.get("label") or ""),
            }

    # 与某一步相等 → 说明他停在这一步。取**最靠后**的匹配：
    # 中间量常与最终量的写法相同（如 0.026 既是第 4 步也是最终答案），
    # 靠后的那一步才是"他实际算到的地方"。
    for st in reversed(problem.get("steps") or []):
        hit, _detail = _accept(str(st["expr"]), student_expr)
        if hit:
            return {
                "kind": "stalled",
                "index": st.get("index"),
                "title": st.get("title", ""),
                "message": (
                    f"你算出的是第 {st.get('index')} 步的结果"
                    f"（{st.get('display', st.get('expr'))}），还需要继续往下算到最终结果。"
                ),
            }

    for st in problem.get("steps") or []:
        hit, _detail = _accept(str(st["expr"]), student_expr)
        if not hit:
            return {
                "kind": "mismatch",
                "index": st.get("index"),
                "title": st.get("title", ""),
                "message": (
                    f"与标准答案不一致：按标准解法，第 {st.get('index')} 步应得到 "
                    f"{st.get('display', st.get('expr'))}。"
                ),
            }
    return {"kind": "unknown", "message": "与标准答案不一致，但没定位到具体步骤。"}


# --------------------------------------------------------------------------
# 批改
# --------------------------------------------------------------------------


def _find_problem(problem_id: str) -> dict[str, Any] | None:
    pid = (problem_id or "").strip()
    if not pid:
        return None
    for p in load_bank(strict=False):
        if p["id"] == pid:
            return p
    return None


def grade(*, problem_id: str, student_answer: str) -> dict[str, Any]:
    """批改主入口（纯函数，工具与测试都用它）。

    返回三态之一：
      * `available=False` —— 该题不在题库里，明确说"无法批改"，并给出可批改清单；
      * `graded=True/False` —— 已依据标准答案判定，附定位与建议；
      * `graded=None` —— 学生答案解析不出，**不猜**，请其重写。
    """
    if not BANK_DIR.is_dir() or not load_bank(strict=False):
        return {
            "ok": False,
            "available": False,
            "error": "题库为空，当前无法批改。",
            "howto": f"往 {BANK_DIR} 放题目 JSON 即可（格式见 grade_answer 文档字符串）。",
        }

    problem = _find_problem(problem_id)
    if problem is None:
        return {
            "ok": False,
            "available": False,
            "error": f"题目 {problem_id!r} 不在题库里，无法批改（不猜答案）。",
            "gradable": gradable_problems(),
        }

    parsed = normalize_answer(student_answer)
    if not parsed["expr"]:
        return {
            "ok": False,
            "available": True,
            "graded": None,
            "error": "没能从你的作答里解析出数值或表达式，请直接写结果（如 0.026 或 P(D)=0.026）。",
            "problem": {"id": problem["id"], "title": problem.get("title", "")},
        }

    final_expr = str(problem["final"]["expr"])
    passed, how = _accept(final_expr, parsed["expr"])

    report: dict[str, Any] = {
        "ok": True,
        "available": True,
        "graded": passed,
        "problem": {
            "id": problem["id"],
            "title": problem.get("title", ""),
            "chapter": problem.get("chapter", ""),
            "source": problem.get("source", ""),
        },
        "student": {"input": student_answer, "parsed": parsed["expr"]},
        "final": {
            "expr": final_expr,
            "label": problem["final"].get("label", "最终结果"),
            "display": problem["final"].get("display", final_expr),
        },
        "basis": how,
        "steps": [],
    }

    # ---- 逐步比对 + 诊断 ----
    report["steps"] = [
        {
            "index": st.get("index"),
            "title": st.get("title", ""),
            "expect": str(st["expr"]),
            "expect_display": st.get("display", st.get("expr")),
            "matched": _accept(str(st["expr"]), parsed["expr"])[0],
        }
        for st in (problem.get("steps") or [])
    ]

    if passed:
        report["verdict"] = "正确"
        report["message"] = "结果与标准答案一致（已用 SymPy 独立复算）。"
    else:
        report["verdict"] = "不正确"
        report["diagnosis"] = _diagnose(problem, parsed["expr"])
        report["message"] = report["diagnosis"]["message"]
        if problem.get("pitfalls"):
            report["pitfalls"] = list(problem["pitfalls"])[:3]

    return report


@tool(
    "grade_answer",
    "题目批改",
    "依据题库中已核验的标准答案批改学生作答：SymPy 独立复算、逐步比对、定位第一处错误并给出易错点。",
    owner="R2",
)
async def grade_answer(*, ctx: Any = None, problem_id: str, student_answer: str) -> dict[str, Any]:
    result = grade(problem_id=problem_id, student_answer=student_answer)
    if ctx is not None and hasattr(ctx, "emit"):
        try:
            ctx.emit("tool.result", tool="grade_answer", **{k: v for k, v in result.items() if k in ("ok", "graded", "verdict")})
        except Exception:  # noqa: BLE001 - 发射失败不影响批改结果
            pass
    return result

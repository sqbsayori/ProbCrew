"""数学计算工具（SymPy 符号计算）——幻觉防线。

**为什么必须有这个工具**：LLM 会算错。凡是"可验证的计算"，都交给 SymPy，
LLM 只负责组织语言。这条原则写在主计划的风险应对里。

本文件提供三个工具：
- `distribution_properties`：分布的 PDF/CDF/期望/方差/矩母函数（符号推导）
- `math_check`：校验一个表达式是否等于另一个（批改/验证 Agent 用）
- `math_eval`：对表达式求数值
"""
from __future__ import annotations

import math
from typing import Any

import sympy as sp

from ..domain import distributions as D
from ..kernel.specs import tool

_SAFE_LOCALS: dict[str, Any] = {
    "sqrt": sp.sqrt,
    "exp": sp.exp,
    "log": sp.log,
    "sin": sp.sin,
    "cos": sp.cos,
    "pi": sp.pi,
    "E": sp.E,
    "oo": sp.oo,
    "Abs": sp.Abs,
    "factorial": sp.factorial,
    "binomial": sp.binomial,
    "Gamma": sp.gamma,
    "erf": sp.erf,
}


def _parse(expr: str) -> Any:
    """解析表达式。只允许白名单符号，禁止任意代码执行。"""
    if len(expr) > 500:
        raise ValueError("表达式过长（>500 字符），已拒绝")
    for bad in ("__", "import", "eval", "exec", "lambda", "open", "os.", "sys."):
        if bad in expr:
            raise ValueError(f"表达式包含被禁止的片段：{bad}")
    return sp.sympify(expr, locals=_SAFE_LOCALS)


@tool(
    "distribution_properties",
    "分布性质推导",
    "用 SymPy 符号推导指定分布的 PDF/CDF/期望/方差/矩母函数，返回 LaTeX 与数值。",
    owner="R3",
)
async def distribution_properties(
    *, ctx: Any = None, dist: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    if dist not in D.DISTRIBUTIONS:
        return {
            "ok": False,
            "error": f"不支持的分布：{dist}",
            "supported": list(D.DISTRIBUTIONS),
        }
    try:
        result = D.properties(dist, params)
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"符号推导失败：{exc}"}


@tool(
    "plot_distribution",
    "分布绘图数据",
    "生成分布的 PDF/PMF 或 CDF 采样序列，供前端 Canvas 绘图（不发图片，保持可交互）。",
    owner="R3",
)
async def plot_distribution(
    *,
    ctx: Any = None,
    dist: str,
    params: dict[str, Any] | None = None,
    mode: str = "pdf",
    points: int = 181,
) -> dict[str, Any]:
    if dist not in D.DISTRIBUTIONS:
        return {"ok": False, "error": f"不支持的分布：{dist}"}
    if mode not in ("pdf", "cdf"):
        return {"ok": False, "error": "mode 只能是 pdf 或 cdf"}
    points = max(21, min(int(points), 601))
    try:
        data = D.series(dist, params, mode=mode, points=points)
        return {"ok": True, **data}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"采样失败：{exc}"}


@tool(
    "math_check",
    "表达式等价校验",
    "判断两个数学表达式是否等价（用于批改与生成/验证分权中的交叉校验）。",
    owner="R3",
)
async def math_check(*, ctx: Any = None, left: str, right: str) -> dict[str, Any]:
    try:
        a, b = _parse(left), _parse(right)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "equal": None, "error": f"解析失败：{exc}"}
    try:
        diff = sp.simplify(a - b)
        equal = bool(diff == 0)
        if not equal:
            # 兜底：数值抽样比较（处理 simplify 不收敛的情形）
            equal = bool(sp.simplify(sp.N(diff, 12)) == 0)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "equal": None, "error": f"化简失败：{exc}"}
    return {
        "ok": True,
        "equal": equal,
        "left_simplified": sp.latex(sp.simplify(a)),
        "right_simplified": sp.latex(sp.simplify(b)),
    }


@tool(
    "math_eval",
    "表达式数值求值",
    "对数学表达式做数值求值，支持 sqrt/exp/log/Gamma 等白名单函数。",
    owner="R3",
)
async def math_eval(
    *, ctx: Any = None, expr: str, subs: dict[str, Any] | None = None
) -> dict[str, Any]:
    try:
        parsed = _parse(expr)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"解析失败：{exc}"}
    subs = subs or {}
    try:
        value = parsed.subs({sp.Symbol(k, real=True): v for k, v in subs.items()})
        num = float(sp.N(value))
        if math.isnan(num) or math.isinf(num):
            return {"ok": False, "error": "结果不是有限实数"}
        return {"ok": True, "value": num, "latex": sp.latex(sp.simplify(parsed))}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"求值失败：{exc}"}


@tool(
    "list_distributions",
    "列出支持的分布",
    "列出可视化模块支持的分布及其参数（供前端渲染选择器）。",
    owner="R3",
)
async def list_distributions(*, ctx: Any = None) -> dict[str, Any]:
    items = D.describe_catalog()
    return {"count": len(items), "items": items}

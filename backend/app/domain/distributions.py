"""领域层：概率分布的符号性质与数值采样。

**纯领域代码**：不依赖 LLM、不依赖 HTTP、不依赖 LLM 框架。
- 符号部分用 SymPy 推导，保证"公式是对的"，而不是让 LLM 编公式（幻觉防线）。
- 数值部分用标准库 math 实现，零额外依赖，前端可直接拿去画图。

新增分布 = 在 DISTRIBUTIONS 里加一条，**不需要改任何其他文件**。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import sympy as sp

x, k, t = sp.symbols("x k t", real=True)
n, p, lam, mu, sigma, a, b, alpha, beta = sp.symbols(
    "n p lambda mu sigma a b alpha beta", positive=True
)

SYMBOLS: dict[str, Any] = {
    "n": n,
    "p": p,
    "lambda": lam,
    "mu": mu,
    "sigma": sigma,
    "a": a,
    "b": b,
    "alpha": alpha,
    "beta": beta,
}


@dataclass
class ParamSpec:
    key: str
    label: str
    default: float
    min: float
    max: float
    step: float = 0.1
    #: 该参数在 sympy 里对应的符号（用于把数值代回公式）
    symbol: str = ""


@dataclass
class Distribution:
    key: str
    name: str
    kind: str  # discrete | continuous
    params: list[ParamSpec]
    pdf_latex: Callable[[], str]
    cdf_latex: Callable[[], str]
    mean_expr: Callable[[], Any]
    var_expr: Callable[[], Any]
    mgf_latex: str
    note: str = ""
    #: 数值 pdf/pmf 与 cdf
    _pdf: Callable[[dict[str, float], float], float] = field(repr=False, default=None)  # type: ignore[assignment]
    _cdf: Callable[[dict[str, float], float], float] = field(repr=False, default=None)  # type: ignore[assignment]
    support: Callable[[dict[str, float]], tuple[float, float]] = field(repr=False, default=None)  # type: ignore[assignment]


# --------------------------------------------------------------------------
# 数值实现（纯 math，零依赖）
# --------------------------------------------------------------------------


def _lgamma(v: float) -> float:
    return math.lgamma(max(v, 1e-9))


def _log_beta(al: float, be: float) -> float:
    return _lgamma(al) + _lgamma(be) - _lgamma(al + be)


# --------------------------------------------------------------------------
# 分布定义
# --------------------------------------------------------------------------


def _binom_pmf(prm: dict[str, float], xv: float) -> float:
    nn, pp = int(round(prm["n"])), prm["p"]
    kk = int(round(xv))
    if kk < 0 or kk > nn:
        return 0.0
    if pp <= 0:
        return 1.0 if kk == 0 else 0.0
    if pp >= 1:
        return 1.0 if kk == nn else 0.0
    logc = _lgamma(nn + 1) - _lgamma(kk + 1) - _lgamma(nn - kk + 1)
    return math.exp(logc + kk * math.log(pp) + (nn - kk) * math.log(1 - pp))


def _binom_cdf(prm: dict[str, float], xv: float) -> float:
    kk = int(math.floor(xv))
    return min(1.0, sum(_binom_pmf(prm, i) for i in range(0, max(kk, -1) + 1)))


def _pois_pmf(prm: dict[str, float], xv: float) -> float:
    ll, kk = prm["lambda"], int(round(xv))
    if kk < 0:
        return 0.0
    return math.exp(-ll + kk * math.log(max(ll, 1e-12)) - _lgamma(kk + 1))


def _pois_cdf(prm: dict[str, float], xv: float) -> float:
    kk = int(math.floor(xv))
    return min(1.0, sum(_pois_pmf(prm, i) for i in range(0, max(kk, -1) + 1)))


def _geom_pmf(prm: dict[str, float], xv: float) -> float:
    pp, kk = prm["p"], int(round(xv))
    if kk < 1:
        return 0.0
    return (1 - pp) ** (kk - 1) * pp


def _geom_cdf(prm: dict[str, float], xv: float) -> float:
    kk = int(math.floor(xv))
    if kk < 1:
        return 0.0
    return 1 - (1 - prm["p"]) ** kk


def _norm_pdf(prm: dict[str, float], xv: float) -> float:
    s = max(prm["sigma"], 1e-9)
    z = (xv - prm["mu"]) / s
    return math.exp(-0.5 * z * z) / (s * math.sqrt(2 * math.pi))


def _norm_cdf(prm: dict[str, float], xv: float) -> float:
    s = max(prm["sigma"], 1e-9)
    return 0.5 * (1 + math.erf((xv - prm["mu"]) / (s * math.sqrt(2))))


def _exp_pdf(prm: dict[str, float], xv: float) -> float:
    return 0.0 if xv < 0 else prm["lambda"] * math.exp(-prm["lambda"] * xv)


def _exp_cdf(prm: dict[str, float], xv: float) -> float:
    return 0.0 if xv < 0 else 1 - math.exp(-prm["lambda"] * xv)


def _unif_pdf(prm: dict[str, float], xv: float) -> float:
    lo, hi = prm["a"], prm["b"]
    return 1.0 / (hi - lo) if lo <= xv <= hi else 0.0


def _unif_cdf(prm: dict[str, float], xv: float) -> float:
    lo, hi = prm["a"], prm["b"]
    if xv < lo:
        return 0.0
    if xv > hi:
        return 1.0
    return (xv - lo) / (hi - lo)


def _gamma_pdf(prm: dict[str, float], xv: float) -> float:
    al, be = prm["alpha"], prm["beta"]
    if xv <= 0:
        return 0.0
    return math.exp(
        (al - 1) * math.log(xv) - xv / be - al * math.log(be) - _lgamma(al)
    )


def _beta_pdf(prm: dict[str, float], xv: float) -> float:
    al, be = prm["alpha"], prm["beta"]
    if xv <= 0 or xv >= 1:
        return 0.0
    return math.exp(
        (al - 1) * math.log(xv) + (be - 1) * math.log(1 - xv) - _log_beta(al, be)
    )


def _betacf(al: float, be: float, xv: float) -> float:
    """正则化不完全 Beta 函数的连分式部分（Lentz 算法，Numerical Recipes 风格）。

    注意：本函数**不含**前面的 `bt/al` 因子，也不做递归 —— 递归版本在
    alpha == beta 且 x == 0.5 时会对称地无限调用自己（已修复的 bug）。
    """
    tiny = 1e-30
    qab, qap, qam = al + be, al + 1.0, al - 1.0
    c = 1.0
    d = 1.0 - qab * xv / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (be - m) * xv / ((qam + m2) * (al + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(al + m) * (qab + m) * xv / ((al + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def _beta_cdf(prm: dict[str, float], xv: float) -> float:
    """正则化不完全 Beta 函数 I_x(α, β)，即 Be(α, β) 的累积分布函数。"""
    al, be = prm["alpha"], prm["beta"]
    if xv <= 0:
        return 0.0
    if xv >= 1:
        return 1.0
    bt = math.exp(
        _lgamma(al + be)
        - _lgamma(al)
        - _lgamma(be)
        + al * math.log(xv)
        + be * math.log(1 - xv)
    )
    if xv < (al + 1) / (al + be + 2):
        return bt * _betacf(al, be, xv) / al
    return 1.0 - bt * _betacf(be, al, 1 - xv) / be


DISTRIBUTIONS: dict[str, Distribution] = {
    "binomial": Distribution(
        key="binomial",
        name="二项分布 B(n, p)",
        kind="discrete",
        params=[
            ParamSpec("n", "试验次数 n", 20, 1, 100, 1),
            ParamSpec("p", "成功概率 p", 0.5, 0.01, 0.99, 0.01),
        ],
        pdf_latex=lambda: r"P(X=k)=\binom{n}{k}p^{k}(1-p)^{n-k}",
        cdf_latex=lambda: r"F(x)=\sum_{k=0}^{\lfloor x\rfloor}\binom{n}{k}p^{k}(1-p)^{n-k}",
        mean_expr=lambda: n * p,
        var_expr=lambda: n * p * (1 - p),
        mgf_latex=r"M_X(t)=\left(1-p+p\,e^{t}\right)^{n}",
        note="n 次独立重复试验中成功的次数。",
        _pdf=_binom_pmf,
        _cdf=_binom_cdf,
        support=lambda prm: (-0.5, prm["n"] + 0.5),
    ),
    "poisson": Distribution(
        key="poisson",
        name="泊松分布 P(λ)",
        kind="discrete",
        params=[ParamSpec("lambda", "强度 λ", 4, 0.1, 30, 0.1)],
        pdf_latex=lambda: r"P(X=k)=\frac{\lambda^{k}e^{-\lambda}}{k!}",
        cdf_latex=lambda: r"F(x)=\sum_{k=0}^{\lfloor x\rfloor}\frac{\lambda^{k}e^{-\lambda}}{k!}",
        mean_expr=lambda: lam,
        var_expr=lambda: lam,
        mgf_latex=r"M_X(t)=e^{\lambda(e^{t}-1)}",
        note="单位时间/面积内稀有事件的发生次数；期望等于方差。",
        _pdf=_pois_pmf,
        _cdf=_pois_cdf,
        support=lambda prm: (-0.5, max(8.0, prm["lambda"] * 3 + 3)),
    ),
    "geometric": Distribution(
        key="geometric",
        name="几何分布 G(p)",
        kind="discrete",
        params=[ParamSpec("p", "成功概率 p", 0.3, 0.01, 0.99, 0.01)],
        pdf_latex=lambda: r"P(X=k)=(1-p)^{k-1}p,\quad k=1,2,\dots",
        cdf_latex=lambda: r"F(x)=1-(1-p)^{\lfloor x\rfloor}",
        mean_expr=lambda: 1 / p,
        var_expr=lambda: (1 - p) / p**2,
        mgf_latex=r"M_X(t)=\frac{p\,e^{t}}{1-(1-p)e^{t}}",
        note="首次成功所需的试验次数；具有无记忆性。",
        _pdf=_geom_pmf,
        _cdf=_geom_cdf,
        support=lambda prm: (0.5, min(40.0, 6 / max(prm["p"], 0.02))),
    ),
    "normal": Distribution(
        key="normal",
        name="正态分布 N(μ, σ²)",
        kind="continuous",
        params=[
            ParamSpec("mu", "均值 μ", 0, -10, 10, 0.1),
            ParamSpec("sigma", "标准差 σ", 1, 0.1, 5, 0.1),
        ],
        pdf_latex=lambda: r"f(x)=\frac{1}{\sqrt{2\pi}\,\sigma}e^{-\frac{(x-\mu)^{2}}{2\sigma^{2}}}",
        cdf_latex=lambda: r"F(x)=\Phi\!\left(\frac{x-\mu}{\sigma}\right)",
        mean_expr=lambda: mu,
        var_expr=lambda: sigma**2,
        mgf_latex=r"M_X(t)=e^{\mu t+\frac{1}{2}\sigma^{2}t^{2}}",
        note="中心极限定理的极限分布；线性变换后仍为正态。",
        _pdf=_norm_pdf,
        _cdf=_norm_cdf,
        support=lambda prm: (prm["mu"] - 4 * prm["sigma"], prm["mu"] + 4 * prm["sigma"]),
    ),
    "exponential": Distribution(
        key="exponential",
        name="指数分布 Exp(λ)",
        kind="continuous",
        params=[ParamSpec("lambda", "速率 λ", 1, 0.05, 5, 0.05)],
        pdf_latex=lambda: r"f(x)=\lambda e^{-\lambda x},\quad x>0",
        cdf_latex=lambda: r"F(x)=1-e^{-\lambda x},\quad x\ge 0",
        mean_expr=lambda: 1 / lam,
        var_expr=lambda: 1 / lam**2,
        mgf_latex=r"M_X(t)=\frac{\lambda}{\lambda-t},\quad t<\lambda",
        note="唯一具有无记忆性的连续分布。",
        _pdf=_exp_pdf,
        _cdf=_exp_cdf,
        support=lambda prm: (0.0, 6 / max(prm["lambda"], 0.05)),
    ),
    "uniform": Distribution(
        key="uniform",
        name="均匀分布 U(a, b)",
        kind="continuous",
        params=[
            ParamSpec("a", "下界 a", 0, -10, 5, 0.1),
            ParamSpec("b", "上界 b", 1, -5, 10, 0.1),
        ],
        pdf_latex=lambda: r"f(x)=\frac{1}{b-a},\quad a<x<b",
        cdf_latex=lambda: r"F(x)=\frac{x-a}{b-a},\quad a\le x\le b",
        mean_expr=lambda: (a + b) / 2,
        var_expr=lambda: (b - a) ** 2 / 12,
        mgf_latex=r"M_X(t)=\frac{e^{tb}-e^{ta}}{t(b-a)}",
        note="几何概型的连续版本。",
        _pdf=_unif_pdf,
        _cdf=_unif_cdf,
        support=lambda prm: (prm["a"] - 0.2 * (prm["b"] - prm["a"]), prm["b"] + 0.2 * (prm["b"] - prm["a"])),
    ),
    "gamma": Distribution(
        key="gamma",
        name="伽马分布 Ga(α, β)",
        kind="continuous",
        params=[
            ParamSpec("alpha", "形状 α", 2, 0.2, 10, 0.2),
            ParamSpec("beta", "尺度 β", 1, 0.1, 5, 0.1),
        ],
        pdf_latex=lambda: r"f(x)=\frac{x^{\alpha-1}e^{-x/\beta}}{\beta^{\alpha}\Gamma(\alpha)},\quad x>0",
        cdf_latex=lambda: r"F(x)=\frac{\gamma(\alpha,\,x/\beta)}{\Gamma(\alpha)}",
        mean_expr=lambda: alpha * beta,
        var_expr=lambda: alpha * beta**2,
        mgf_latex=r"M_X(t)=(1-\beta t)^{-\alpha},\quad t<1/\beta",
        note="α 个独立同指数分布之和；指数分布是其 α=1 的特例。",
        _pdf=_gamma_pdf,
        _cdf=lambda prm, xv: _gamma_cdf(prm, xv),
        support=lambda prm: (0.0, prm["alpha"] * prm["beta"] * 4),
    ),
    "beta": Distribution(
        key="beta",
        name="贝塔分布 Be(α, β)",
        kind="continuous",
        params=[
            ParamSpec("alpha", "形状 α", 2, 0.2, 8, 0.2),
            ParamSpec("beta", "形状 β", 2, 0.2, 8, 0.2),
        ],
        pdf_latex=lambda: r"f(x)=\frac{x^{\alpha-1}(1-x)^{\beta-1}}{B(\alpha,\beta)},\quad 0<x<1",
        cdf_latex=lambda: r"F(x)=I_x(\alpha,\beta)",
        mean_expr=lambda: alpha / (alpha + beta),
        var_expr=lambda: alpha * beta / ((alpha + beta) ** 2 * (alpha + beta + 1)),
        mgf_latex="（无初等闭式；可用合流超几何函数表示）",
        note="取值在 (0,1)，常作为「概率的概率」的先验分布。",
        _pdf=_beta_pdf,
        _cdf=_beta_cdf,
        support=lambda prm: (0.0, 1.0),
    ),
}


def _gamma_cdf(prm: dict[str, float], xv: float) -> float:
    """下不完全 Gamma 函数（级数展开）。"""
    al, be = prm["alpha"], prm["beta"]
    if xv <= 0:
        return 0.0
    z = xv / be
    if z < al + 1:
        term = 1.0 / al
        total = term
        for i in range(1, 300):
            term *= z / (al + i)
            total += term
            if abs(term) < 1e-14 * abs(total):
                break
        return total * math.exp(-z + al * math.log(z) - _lgamma(al))
    return 1.0 - _gamma_upper(prm, xv)


def _gamma_upper(prm: dict[str, float], xv: float) -> float:
    """上不完全 Gamma（连分式）。"""
    al, be = prm["alpha"], prm["beta"]
    z = xv / be
    tiny = 1e-30
    b0 = z + 1 - al
    c, d = 1.0 / tiny, 1.0 / b0
    h = d
    for i in range(1, 300):
        an = -i * (i - al)
        b0 += 2
        d = an * d + b0
        if abs(d) < tiny:
            d = tiny
        c = b0 + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = c * d
        h *= delta
        if abs(delta - 1) < 1e-14:
            break
    return h * math.exp(-z + al * math.log(z) - _lgamma(al))


# --------------------------------------------------------------------------
# 对外 API
# --------------------------------------------------------------------------


def coerce_params(dist_key: str, raw: dict[str, Any] | None) -> dict[str, float]:
    """把外部传入的参数规整为完整的 float 字典（缺的用默认值）。"""
    dist = DISTRIBUTIONS[dist_key]
    out: dict[str, float] = {}
    raw = raw or {}
    for spec in dist.params:
        value = raw.get(spec.key, spec.default)
        try:
            out[spec.key] = float(value)
        except (TypeError, ValueError):
            out[spec.key] = float(spec.default)
    return out


def properties(dist_key: str, raw_params: dict[str, Any] | None = None) -> dict[str, Any]:
    """符号推导：PDF/CDF/期望/方差/矩母函数的 LaTeX + 期望方差的数值。"""
    dist = DISTRIBUTIONS[dist_key]
    prm = coerce_params(dist_key, raw_params)
    subs = {SYMBOLS[s.key]: prm[s.key] for s in dist.params if s.key in SYMBOLS}

    mean_tex = sp.latex(sp.simplify(dist.mean_expr()))
    var_tex = sp.latex(sp.simplify(dist.var_expr()))
    mean_val = float(sp.N(dist.mean_expr().subs(subs)))
    var_val = float(sp.N(dist.var_expr().subs(subs)))

    return {
        "dist": dist.key,
        "name": dist.name,
        "kind": dist.kind,
        "params": prm,
        "pdf_latex": dist.pdf_latex(),
        "cdf_latex": dist.cdf_latex(),
        "mean_latex": f"E[X]={mean_tex}",
        "var_latex": f"\\mathrm{{Var}}(X)={var_tex}",
        "mgf_latex": dist.mgf_latex,
        "mean": mean_val,
        "var": var_val,
        "std": math.sqrt(max(var_val, 0.0)),
        "note": dist.note,
    }


def series(
    dist_key: str,
    raw_params: dict[str, Any] | None = None,
    *,
    mode: str = "pdf",
    points: int = 181,
) -> dict[str, Any]:
    """生成绘图数据（离散给点，连续给曲线）。"""
    dist = DISTRIBUTIONS[dist_key]
    prm = coerce_params(dist_key, raw_params)
    lo, hi = dist.support(prm)
    fn = dist._pdf if mode == "pdf" else dist._cdf

    xs: list[float] = []
    ys: list[float] = []
    if dist.kind == "discrete":
        for i in range(int(math.floor(lo)), int(math.ceil(hi)) + 1):
            xs.append(float(i))
            ys.append(float(fn(prm, i)))
    else:
        span = hi - lo
        for i in range(points):
            xv = lo + span * i / (points - 1)
            xs.append(round(xv, 6))
            ys.append(float(fn(prm, xv)))

    return {
        "dist": dist.key,
        "name": dist.name,
        "kind": dist.kind,
        "mode": mode,
        "params": prm,
        "x": xs,
        "y": ys,
    }


def describe_catalog() -> list[dict[str, Any]]:
    """列出所有支持的分布，供前端渲染选择器。"""
    return [
        {
            "key": d.key,
            "name": d.name,
            "kind": d.kind,
            "note": d.note,
            "params": [
                {
                    "key": s.key,
                    "label": s.label,
                    "default": s.default,
                    "min": s.min,
                    "max": s.max,
                    "step": s.step,
                }
                for s in d.params
            ],
        }
        for d in DISTRIBUTIONS.values()
    ]

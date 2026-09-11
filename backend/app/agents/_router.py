"""意图路由规则（确定性）—— 不调 LLM 也能正确路由。

**为什么要有规则路由**：路由是所有请求的必经之路。
- 走 LLM = 每次请求多花一次调用、多 1–2 秒延迟、结果还不稳定；
- 走规则 = 免费、毫秒级、100% 可复现、可写单元测试。

因此策略是「**规则优先，LLM 兜底**」：
规则命中就直接路由（覆盖绝大多数课堂提问）；
规则完全没命中且问题较长时，才让 LLM 做一次分类，失败再回退到 knowledge。

注意：文件以 `_` 开头，`kernel.registry` 会跳过它，不会当成 Agent 注册。
"""
from __future__ import annotations

import re
from typing import Iterable

#: 意图 -> 关键词。顺序即优先级（越靠前越具体）。
INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "analytics": (
        "进度", "记录", "历史", "薄弱", "学习情况", "学习数据", "我学了",
        "统计", "报告", "掌握", "错题", "复习计划",
    ),
    "visualize": (
        "分布", "画", "绘图", "可视化", "图像", "曲线", "密度函数", "pdf", "cdf",
        "正态", "泊松", "二项", "指数分布", "均匀分布", "伽马", "贝塔", "几何分布",
        "期望", "方差", "标准差", "矩母函数", "数字特征",
    ),
    "solve": (
        "求解", "计算", "求", "解这道", "解一下", "答案", "怎么做", "做题", "练习",
        "一道题", "题目", "批改", "错在哪", "证明", "已知", "设随机变量",
    ),
    "animation": (
        "动画", "演示", "模拟", "仿真", "动态", "直观", "看看过程", "跑一遍",
    ),
    "knowledge": (
        "什么是", "为什么", "怎么理解", "解释", "讲解", "概念", "定义", "定理",
        "公式", "区别", "联系", "含义", "介绍一下", "讲讲",
    ),
}

#: 意图 -> 需要唤醒的 Agent（这就是"多 Agent 协作"的调度表）
INTENT_AGENTS: dict[str, list[str]] = {
    "knowledge": ["knowledge"],
    "solve": ["solver"],
    "visualize": ["visualizer", "knowledge"],
    "analytics": ["analytics"],
    "animation": ["visualizer", "knowledge"],
    "multi": ["knowledge", "solver", "visualizer"],
    # 页面伴学：学生问的是"我眼前这一页"
    "explain_page": ["page_tutor"],
    "explain_selection": ["page_tutor"],
}

INTENT_LABELS: dict[str, str] = {
    "knowledge": "知识点讲解",
    "solve": "题目讲解",
    "visualize": "分布可视化",
    "analytics": "学习数据分析",
    "animation": "交互动画演示",
    "multi": "综合问题（多 Agent 协作）",
    "explain_page": "当前页面伴学",
    "explain_selection": "解释选中内容",
}

#: 指代"当前页面"的说法。出现这些词时优先走页面伴学，而不是教材知识库。
PAGE_REFERENCE_WORDS = (
    "这一页", "本页", "当前页", "这页", "页面", "这段", "这里", "这句", "这个图",
    "这节课", "本节", "这一节", "上面", "刚才", "下面", "课件", "讲义", "屏幕上",
    "老师讲", "课本上", "这一章",
)

#: 需要"解释/说明"的动作词。与选中文字组合时判定为 explain_selection。
EXPLAIN_ACTION_WORDS = (
    "解释", "什么意思", "啥意思", "为什么", "怎么理解", "讲讲", "说明", "看不懂",
    "没听懂", "不懂", "翻译", "这是啥", "是什么", "推导", "怎么来的", "展开",
)

_INTENT_ORDER = ("analytics", "visualize", "solve", "animation", "knowledge")


def match_intents(query: str) -> list[str]:
    """返回命中的意图列表（按 INTENT_ORDER 排序，可能多个）。"""
    q = (query or "").lower()
    hits: list[str] = []
    for intent in _INTENT_ORDER:
        for kw in INTENT_KEYWORDS.get(intent, ()):
            if kw in q:
                hits.append(intent)
                break
    return hits


def route(query: str, page_context: object | None = None) -> tuple[str, list[str], str]:
    """规则路由：返回 (intent, selection, reason)。

    参数 `page_context` 是 `kernel.page_context.PageContext`（或 None）。
    它改变路由优先级：当学生正在一个课程页面上提问时，
    "这段/这一页/这里"这类指代必须先被页面伴学接住，而不能丢给教材知识库。
    """
    q = (query or "").strip()
    pc = page_context if page_context is not None else None
    has_selection = bool(pc is not None and getattr(pc, "has_selection", False))
    has_page = bool(pc is not None and getattr(pc, "has_content", False))

    # ---- 优先级 1：划选了文字，并且在问"这是什么意思" ----
    # 短问题（<= 12 字）也按选中内容理解 —— 学生划完词通常只打两个字
    if has_selection and (
        any(w in q for w in EXPLAIN_ACTION_WORDS) or len(q) <= 12
    ):
        return (
            "explain_selection",
            ["page_tutor"],
            f"检测到你在页面上划选了 {len(str(getattr(pc, 'selection', '')).strip())} 字，"
            "优先解释选中的内容",
        )

    # ---- 优先级 2：明确指代"当前页面" ----
    if has_page and any(w in q for w in PAGE_REFERENCE_WORDS):
        return "explain_page", ["page_tutor"], "问的是当前页面的内容，交给页面伴学"

    hits = match_intents(q)

    # ---- 优先级 3：完全没命中任何特征词，但正在看课程页 → 默认页面伴学 ----
    # 这是"伴学助手"该有的默认行为：坐在旁边，随时接住问题。
    if not hits and has_page:
        return "explain_page", ["page_tutor"], "未命中教材类特征词，按当前页面问题处理"

    if not hits:
        return "knowledge", ["knowledge"], "未命中任何特征词，默认走知识讲解"

    # "animation" 是元意图（想看电影式的演示），不参与"跨领域"判定
    core = [h for h in hits if h != "animation"]

    # 命中 >= 2 个实质领域 → 综合问题，多 Agent 并行
    # 例：「求解这道题，并画一下它的正态分布密度曲线」应同时唤起 solver 与 visualizer
    if len(core) >= 2:
        agents: list[str] = []
        for h in core:
            for a in INTENT_AGENTS.get(h, []):
                if a not in agents:
                    agents.append(a)
        return (
            "multi",
            agents,
            f"同时命中 {'/'.join(core)} 多个领域，并行调度 {len(agents)} 个 Agent",
        )

    primary = hits[0]
    agents = INTENT_AGENTS.get(primary, ["knowledge"])
    return primary, agents, f"命中「{INTENT_LABELS.get(primary, primary)}」特征词"


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def extract_distribution(query: str) -> tuple[str | None, dict[str, float]]:
    """从自然语言里抽取分布类型与参数，例如「正态分布 N(0,1)」「泊松 λ=3」。

    这是"规则优先"的另一个落点：分布名与参数都能用正则稳定抽出，
    没必要让 LLM 猜（猜错会直接导致算错）。
    """
    q = (query or "").lower()
    aliases: dict[str, str] = {
        "正态": "normal", "高斯": "normal", "normal": "normal",
        "泊松": "poisson", "poisson": "poisson",
        "二项": "binomial", "binomial": "binomial",
        "几何分布": "geometric", "geometric": "geometric",
        "指数分布": "exponential", "指数": "exponential", "exponential": "exponential",
        "均匀": "uniform", "uniform": "uniform",
        "伽马": "gamma", "gamma": "gamma", "Γ": "gamma",
        "贝塔": "beta", "beta": "beta",
    }
    dist: str | None = None
    for key, value in aliases.items():
        if key in q:
            dist = value
            break
    if dist is None:
        return None, {}

    params: dict[str, float] = {}

    def num(pattern: str) -> float | None:
        m = re.search(pattern, q)
        if not m:
            return None
        try:
            return float(m.group(1))
        except (TypeError, ValueError):
            return None

    if dist == "normal":
        m = re.search(r"[nN]\s*\(\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*\)", q)
        if m:
            params["mu"] = float(m.group(1))
            params["sigma"] = abs(float(m.group(2))) or 1.0
        else:
            mu = num(r"[μu]\s*[=＝]\s*(-?\d+(?:\.\d+)?)")
            sigma = num(r"[σs]\s*(?:\^?2)?\s*[=＝]\s*(-?\d+(?:\.\d+)?)")
            if mu is not None:
                params["mu"] = mu
            if sigma is not None:
                params["sigma"] = sigma
    elif dist == "binomial":
        nn = num(r"[nN]\s*[=＝]\s*(\d+(?:\.\d+)?)")
        pp = num(r"[pP]\s*[=＝]\s*(0?\.\d+|\d+(?:\.\d+)?)")
        if nn is not None:
            params["n"] = nn
        if pp is not None:
            params["p"] = pp
    elif dist == "poisson":
        ll = num(r"[λl]\s*[=＝]\s*(\d+(?:\.\d+)?)")
        if ll is not None:
            params["lambda"] = ll
    elif dist == "exponential":
        ll = num(r"[λl]\s*[=＝]\s*(\d+(?:\.\d+)?)")
        if ll is not None:
            params["lambda"] = ll
    elif dist == "geometric":
        pp = num(r"[pP]\s*[=＝]\s*(0?\.\d+|\d+(?:\.\d+)?)")
        if pp is not None:
            params["p"] = pp
    elif dist == "uniform":
        m = re.search(r"[uU]\s*\(\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*\)", q)
        if m:
            lo, hi = float(m.group(1)), float(m.group(2))
            if hi > lo:
                params["a"], params["b"] = lo, hi
    elif dist in ("gamma", "beta"):
        al = num(r"[αa]\s*[=＝]\s*(\d+(?:\.\d+)?)")
        be = num(r"[βb]\s*[=＝]\s*(\d+(?:\.\d+)?)")
        if al is not None:
            params["alpha"] = al
        if be is not None:
            params["beta"] = be

    return dist, params

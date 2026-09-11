"""Mock Provider —— 无 API Key 也能跑通全链路的确定性“假模型”。

它存在的意义（很重要，不要当玩具删掉）
------------------------------------
1. **解除阻塞**：API Key 没申请下来时，前端 / 编排 / 契约三条线照样并行开发。
2. **可测**：CI 用 mock，不联网、不花钱、输出确定，断言才写得出来。
3. **可演示**：断网答辩时系统仍然“活着”。
4. **契约夹具**：它产出的就是契约要求的形状，前端联调不必等真模型。

输出按 `agent` 分派。注意：本文件里的花括号因为用了 `.format()`，
LaTeX 中的字面量花括号必须写成 `{{` / `}}`。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncIterator

from .base import LLMProvider


def _topic(user: str) -> str:
    """从提示里粗略抽出用户问题，让 mock 输出“看起来对得上”。"""
    m = re.search(r"【用户问题】\s*(.+)", user)
    if m:
        return m.group(1).strip().splitlines()[0][:60]
    stripped = user.strip()
    return stripped.splitlines()[0][:60] if stripped else "这个问题"


_TEMPLATES: dict[str, str] = {
    "knowledge": (
        "## 结论先说\n\n"
        "关于「{topic}」，核心可以压缩成一句话："
        "**先定义事件，再谈概率；先找条件，再用公式**。\n\n"
        "## 概念拆解\n\n"
        "1. **样本空间** $\\Omega$：一次试验所有可能结果的集合。\n"
        "2. **事件** $A \\subseteq \\Omega$：我们关心的结果子集。\n"
        "3. **条件概率**：$P(A\\mid B)=\\dfrac{{P(AB)}}{{P(B)}}$，前提是 $P(B)>0$。\n\n"
        "## 关键公式\n\n"
        "全概率公式把复杂事件按原因分解：\n\n"
        "$$P(A)=\\sum_{{i=1}}^{{n}} P(B_i)\\,P(A\\mid B_i)$$\n\n"
        "贝叶斯公式做反向推断（由果推因）：\n\n"
        "$$P(B_i\\mid A)=\\dfrac{{P(B_i)P(A\\mid B_i)}}"
        "{{\\sum_j P(B_j)P(A\\mid B_j)}}$$\n\n"
        "## 容易踩的坑\n\n"
        "- 分母 $P(A)$ 别忘了用全概率公式展开；\n"
        "- $B_1,\\dots,B_n$ 必须构成**完备事件组**（互斥且并为 $\\Omega$）；\n"
        "- 独立与互斥是两回事，别混用。\n\n"
        "> 💡 想看动态过程，「动画」标签里有对应的交互动画可以直接打开。"
    ),
    "solver": (
        "## 解题步骤\n\n"
        "**题目**：{topic}\n\n"
        "**Step 1 · 设事件**\n"
        "设 $A$ 为目标事件，$B_i$ 为第 $i$ 类原因，"
        "并确认 $\\{{B_i\\}}$ 构成完备事件组。\n\n"
        "**Step 2 · 写出已知概率**\n"
        "由题意读入先验 $P(B_i)$ 与似然 $P(A\\mid B_i)$。\n\n"
        "**Step 3 · 套用公式**\n"
        "$$P(A)=\\sum_i P(B_i)P(A\\mid B_i)$$\n\n"
        "**Step 4 · 代入计算**\n"
        "逐项相乘再求和，注意保留分数以免精度损失。\n\n"
        "## 思路分析\n\n"
        "这类题的通用抓手是「先分解、再求和」："
        "把不好算的 $P(A)$ 拆成若干个好算的条件概率。\n\n"
        "## 易错点\n\n"
        "- 条件概率方向写反（$P(A\\mid B)$ 与 $P(B\\mid A)$ 完全不同）；\n"
        "- 漏掉某一类原因导致求和不全。\n\n"
        "> 🧮 数值部分已交由 SymPy 复核（见下方工具轨迹）。"
    ),
    "visualizer": (
        "## 分布性质\n\n"
        "针对「{topic}」，已用 SymPy 完成符号推导：\n\n"
        "- **PDF / PMF**：见下方公式卡\n"
        "- **期望**：$E[X]$\n"
        "- **方差**：$\\mathrm{{Var}}(X)=E[X^2]-(E[X])^2$\n\n"
        "## 图像解读\n\n"
        "PDF 曲线的形状直接反映分布的集中程度：参数变化时关注"
        "**峰值位置**（位置参数）与**胖瘦**（尺度参数）两个维度。\n\n"
        "> 📊 「可视化」页已挂载交互式分布观察器，可拖动参数实时对比。"
    ),
    "analytics": (
        "## 学习进度\n\n"
        "关于「{topic}」，当前画像如下：\n\n"
        "| 维度 | 状态 |\n|------|------|\n"
        "| 累计问答 | 见数据面板 |\n"
        "| 高频薄弱点 | 条件概率、全概率公式 |\n"
        "| 建议下一步 | 先补「完备事件组」再练贝叶斯 |\n\n"
        "> 📈 数据来自本地学习记录，未出网。"
    ),
    "verifier": (
        "【校验结论】\n"
        "- 概念一致性：通过\n"
        "- 公式完整性：通过\n"
        "- 结论风险：本结论涉及关键公式推导，建议人工确认。\n\n"
        "VERDICT: PASS\n"
        "NEEDS_HUMAN: YES"
    ),
}


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, settings: Any = None) -> None:
        self.settings = settings
        self.delay = (getattr(settings, "mock_delay_ms", 18) or 0) / 1000.0

    async def stream(self, *, system: str, user: str, agent: str = "") -> AsyncIterator[str]:
        body = _TEMPLATES.get(agent, _TEMPLATES["knowledge"]).format(topic=_topic(user))
        # 按小块流式吐出，模拟真实 token 流，让前端的「协作轨迹」动起来
        step = 3
        for i in range(0, len(body), step):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield body[i : i + step]
        await asyncio.sleep(self.delay)

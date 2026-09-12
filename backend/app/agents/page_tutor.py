"""Page Tutor Agent —— 页面伴学助手（本项目新增的核心 Agent）。

它和 Knowledge Agent 的区别
--------------------------
Knowledge Agent 回答的是"**概率论里的**某个知识点"（检索教材知识库）。
Page Tutor 回答的是"**我眼前这一页**"的问题：

    「这段是什么意思？」        → 解释用户选中的文字
    「这一页讲了什么？」        → 基于页面大纲与正文做结构化梳理
    「这个推导为什么成立？」    → 在页内检索相关段落后讲解
    「我看到哪了？」            → 报告视频进度 / 滚动位置
    「给我出个类似的题」        → 基于页面上的例题生成变式

检索策略：**先页内，后教材**。学生问的是眼前的东西，答案首先应该来自那一页；
页内确实没有时，才回退到教材知识库补全。
"""
from __future__ import annotations

import re
from typing import Any

from ..kernel.page_context import PageContext
from ..kernel.specs import AgentResult, AgentSpec, RunContext
from ._router import PROGRESS_WORDS  # 单一事实源：路由与本 Agent 必须用同一份词表

SPEC = AgentSpec(
    id="page_tutor",
    name="Page Tutor 页面伴学",
    role="generator",
    description="读取学生当前浏览的课程页面（含选中文字、视频进度、页内公式），就地答疑。",
    intents=("explain_page", "explain_selection"),
    tools=("page_search", "page_outline", "page_selection", "kb_search"),
    emits=("formula", "table", "text"),
    accent="#0EA5E9",
    icon="🐾",
    can_verify=("page_tutor",),
)

# 问"我学到哪了"的信号词从 _router 导入（见文件头 import），
# 不在这里重复定义 —— 路由和本 Agent 必须用同一份词表，
# 否则会出现「路由判成 explain_selection，但 Agent 里按进度答」这类错位。

#: 所有会输出公式的 Prompt 都必须带上这一条。
#: 实测：DeepSeek 默认习惯输出 `\(...\)` 与 `\[...\]`，而前端 Markdown 渲染器
#: 只认 `$...$` / `$$...$$`。渲染器侧已做归一化兜底，这里再明确要求一次（双保险）。
MATH_RULE = (
    "数学公式一律用 $ 定界：行内写 $...$，独立成行写 $$...$$。"
    "**不要**使用 \\(...\\) 或 \\[...\\] 这两种写法，前端不识别。"
)

EXPLAIN_PROMPT = """你是一位坐在学生旁边的助教，正在看学生屏幕上的这一页课件。

学生的屏幕内容如下：
{page}

学生的问题：{query}

请遵守：
1. **先回答学生问的那一点**，不要复述整页内容。
2. 需要引用页面原文时，直接引用关键句，并说明它在页面的哪一部分。
3. """ + MATH_RULE + """
4. 如果页面上有例题，讲解时要紧扣那道题的设定与数字。
5. 页面里没有依据的内容，明确说"这一页没有讲"，可以补充通用知识但要标注出来。
6. 中文回答，像真人助教一样自然，不要客套，不要"希望对您有帮助"这类话。
"""

SELECTION_PROMPT = """学生正在看一页《概率论与数理统计》课件，并且**划选了其中一段**，想让你解释。

截图内容（整页上下文）：
{page}

学生选中的那段文字：
<<<
{selection}
>>>

学生的问题：{query}

请遵守：
1. **直接解释选中的那段**，这是本次回答的唯一目标。不要泛泛讲整章。
2. 把那段话里的每个关键概念、每个符号的含义讲清楚；如果它是推导，请补上跳过的中间步骤。
3. 如果选中内容里有公式，用 LaTeX 重新写一遍再解释。""" + MATH_RULE + """
4. 指出这段内容容易误解的地方（1-2 条即可）。
5. 如果学生的问题是在问"对不对/为什么"，正面回答。
6. 中文，语气自然，不要客套。
"""

PROGRESS_PROMPT = """学生问你他现在学到哪了。下面是他屏幕上的真实信息：

{page}

请用两三句话报告：
- 正在学的是哪一节（用页面标题/大纲判断）
- 视频看到了多少（如果有视频进度）
- 当前位置大致在页面的什么部分（有滚动比例就用它）
最后给一句简短的下一步建议。不要编造页面里没有的信息。
"""


def _page_block(pc: PageContext, max_chars: int = 4000) -> str:
    return pc.to_prompt(max_chars=max_chars)


def _formulas_from(text: str, limit: int = 4) -> list[str]:
    """从一段文字里抽出独立公式块。"""
    out: list[str] = []
    for m in re.finditer(r"\$\$(.+?)\$\$", text or "", re.S):
        body = m.group(1).strip()
        if body and body not in out:
            out.append(body)
        if len(out) >= limit:
            break
    return out


def _chunks_block(chunks: list[dict[str, Any]], max_chars: int = 2600) -> str:
    """把页内检索结果拼成 prompt 片段（带位置标记，便于引用）。"""
    if not chunks:
        return "（页内没有检索到直接相关的段落）"
    parts: list[str] = []
    used = 0
    for c in chunks:
        block = f"[页内位置 #{c.get('index')}]\n{c.get('content', '')}"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n---\n\n".join(parts)


async def run(state: dict, ctx: RunContext) -> AgentResult:
    query = (state.get("query") or "").strip()
    pc: PageContext | None = getattr(ctx, "page_context", None)
    intent = state.get("intent", "explain_page")

    if pc is None or not pc.has_content:
        return AgentResult(
            agent=SPEC.id,
            text=(
                "我目前读不到这个页面的内容。\n\n"
                "可能的原因：\n"
                "- 助手脚本没有在这个页面上启用；\n"
                "- 课件在跨域 iframe 里，浏览器安全策略不允许读取；\n"
                "- 页面正文太少（比如是纯视频页）。\n\n"
                "你可以直接描述问题，我会用教材知识库来回答。"
            ),
            ok=False,
            data={"page_context": False},
        )

    artifacts: list[dict[str, Any]] = []

    # ---- 1. 页面结构（让学生看见"助手读到了什么"，建立信任）----
    if pc.headings:
        artifacts.append(
            {
                "kind": "table",
                "payload": {
                    "title": f"已读取的页面结构 · {pc.title or pc.url}",
                    "columns": ["层级", "标题"],
                    "rows": [
                        ["H" + str(h.get("level", 2)), str(h.get("text", ""))[:60]]
                        for h in (pc.headings or [])[:14]
                    ],
                },
            }
        )

    # ---- 2. 选择分支 ----
    if intent == "explain_selection" and pc.has_selection:
        prompt = SELECTION_PROMPT.format(
            page=_page_block(pc, 3000),
            selection=pc.selection.strip()[:2000],
            query=query or "请解释这段内容",
        )
        answer = await ctx.stream_llm(prompt, f"【学生问题】{query or '这段是什么意思？'}", agent=SPEC.id)
        formulas = _formulas_from(pc.selection) or _formulas_from(answer)
        if formulas:
            artifacts.append(
                {"kind": "formula", "payload": {"title": "选中内容涉及的公式", "items": formulas}}
            )
        agent_data = {"mode": "selection", "selection_chars": len(pc.selection)}

    # ---- 3. 进度分支 ----
    elif any(w in query for w in PROGRESS_WORDS):
        answer = await ctx.stream_llm(
            PROGRESS_PROMPT.format(page=_page_block(pc, 2000)),
            f"【学生问题】{query}",
            agent=SPEC.id,
        )
        agent_data = {"mode": "progress", "has_media": bool(pc.media)}

    # ---- 4. 默认：页内检索后就地讲解 ----
    else:
        hits = await ctx.use("page_search", query=query, top_k=4)
        chunks = hits.get("chunks", []) if isinstance(hits, dict) else []

        # 页内没有依据时，回退到教材知识库补全（并在回答里说明）
        kb_note = ""
        if not chunks:
            kb = await ctx.use("kb_search", query=query, top_k=3)
            kb_chunks = kb.get("chunks", []) if isinstance(kb, dict) else []
            if kb_chunks:
                kb_note = (
                    "\n\n【补充：本页未直接讲到，以下来自教材知识库】\n"
                    + "\n\n".join(
                        f"[{c.get('chapter')} · {c.get('heading')}]\n{c.get('content', '')[:800]}"
                        for c in kb_chunks
                    )
                )

        prompt = (
            EXPLAIN_PROMPT.format(page=_page_block(pc, 2500), query=query)
            + "\n\n【学生这一页里与问题最相关的段落】\n"
            + _chunks_block(chunks)
            + kb_note
        )
        answer = await ctx.stream_llm(prompt, f"【学生问题】{query}", agent=SPEC.id)

        formulas = _formulas_from(answer) or (pc.formulas[:3] if pc.formulas else [])
        if formulas:
            artifacts.append(
                {"kind": "formula", "payload": {"title": "相关公式", "items": formulas}}
            )
        agent_data = {"mode": "explain", "page_hits": len(chunks), "kb_fallback": bool(kb_note)}

    for art in artifacts:
        ctx.emit_artifact(art["kind"], art["payload"])

    return AgentResult(
        agent=SPEC.id,
        text=answer,
        data={
            **agent_data,
            "page_title": pc.title,
            "page_chars": pc.char_count,
            "page_url": pc.url,
        },
        artifacts=artifacts,
    )

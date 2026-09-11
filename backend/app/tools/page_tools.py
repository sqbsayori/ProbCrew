"""页面上下文工具 —— 让学生在**当前页面**里检索与提问。

与 `kb_search` 的分工
--------------------
- `kb_search`：在**教材知识库**里找依据（跨页面、权威、但可能没收录）；
- `page_search`：在**学生正看的这一页**里找依据（精确、就地、一定相关）。

先 page 后 kb 是这个助手的基本策略：学生问"这段为什么这样推"，
答案首先应该来自他眼前那一段，而不是别处的教材。

页面文本通过 `ctx.page_context` 取得（由 API 层解析请求体后注入），
因此这些工具**不需要**把整页正文当参数传进来。
"""
from __future__ import annotations

import re
from typing import Any

from ..kernel.page_context import chunk_text
from ..kernel.specs import tool


def _grams(text: str) -> list[str]:
    """中文 bigram + 英文/公式词。与 kb_search 保持一致的切分口径。"""
    text = text.lower()
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = ["".join(chars[i : i + 2]) for i in range(max(len(chars) - 1, 0))]
    latin = re.findall(r"[a-z0-9_\\{}^]{2,}", text)
    return bigrams + latin


def _get_ctx(ctx: Any):
    pc = getattr(ctx, "page_context", None)
    if pc is None or not getattr(pc, "has_content", False):
        return None
    return pc


def search_in_page(page_text: str, query: str, top_k: int = 4) -> list[dict[str, Any]]:
    """页内检索：按 query 与 chunk 的词重叠打分。"""
    chunks = chunk_text(page_text)
    if not chunks:
        return []
    q = set(_grams(query))
    if not q:
        return [{"index": i, "content": c, "score": 0.0} for i, c in enumerate(chunks[:top_k])]

    scored: list[tuple[float, int, str]] = []
    for i, c in enumerate(chunks):
        grams = set(_grams(c))
        if not grams:
            continue
        hit = len(q & grams)
        if hit == 0:
            continue
        # 用 chunk 长度归一，避免长块天然占优
        score = hit / (len(grams) ** 0.5)
        scored.append((score, i, c))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [
        {"index": i, "content": c, "score": round(s, 4)} for s, i, c in scored[:top_k]
    ]


@tool(
    "page_search",
    "页内检索",
    "在学生当前正在浏览的课程页面正文中检索相关段落。回答'这段/这一页'类问题时应优先用它。",
    owner="R1",
)
async def page_search(*, ctx: Any = None, query: str, top_k: int = 4) -> dict[str, Any]:
    pc = _get_ctx(ctx)
    if pc is None:
        return {
            "available": False,
            "reason": "当前没有页面上下文（助手的页面读取未启用或该页面无正文）",
            "chunks": [],
        }
    top_k = max(1, min(int(top_k), 8))
    hits = search_in_page(pc.text, query, top_k=top_k)
    return {
        "available": True,
        "page_title": pc.title,
        "page_url": pc.url,
        "total_chars": pc.char_count,
        "hit_count": len(hits),
        "chunks": hits,
    }


@tool(
    "page_outline",
    "页面大纲",
    "返回当前课程页面的标题层级结构，用于回答'这一页讲了什么/结构是什么'。",
    owner="R1",
)
async def page_outline(*, ctx: Any = None) -> dict[str, Any]:
    pc = _get_ctx(ctx)
    if pc is None:
        return {"available": False, "headings": []}
    return {
        "available": True,
        "title": pc.title,
        "url": pc.url,
        "headings": (pc.headings or [])[:30],
        "outline_text": pc.outline(30),
        "char_count": pc.char_count,
        "formula_count": len(pc.formulas or []),
    }


@tool(
    "page_selection",
    "取选中文字",
    "返回学生在页面上划选的那段文字。当用户说'这段/这里'时用它确认指代对象。",
    owner="R1",
)
async def page_selection(*, ctx: Any = None) -> dict[str, Any]:
    pc = _get_ctx(ctx)
    if pc is None or not pc.has_selection:
        return {"available": False, "selection": ""}
    sel = pc.selection.strip()
    return {
        "available": True,
        "selection": sel[:3000],
        "char_count": len(sel),
        "page_title": pc.title,
    }

"""知识库目录 API —— 把"系统里到底有什么内容"摆出来。

背景：前端「知识讲解」页原本只有一个空输入框，用户不知道知识库里有什么，
自然也不知道该问什么。这个接口把知识库的章节结构吐出来，
前端渲染成可点击的课程目录，点一下就直接提问。

内容来源是 `backend/knowledge_base/probstat.md`（P2 阶段会换成 Qdrant 检索，
但这个"目录"接口的形态不变）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..tools import kb_search

router = APIRouter(tags=["knowledge"])


@router.get("/api/knowledge/chapters", summary="课程章节目录（含知识点）")
async def chapters() -> dict[str, Any]:
    chapters = kb_search.outline()
    stats = await kb_search.kb_stats(ctx=None)
    return {
        "chapter_count": len(chapters),
        "section_count": sum(c["section_count"] for c in chapters),
        "source": stats.get("path"),
        "chapters": chapters,
        "note": "demo 阶段为本地 Markdown 知识库；P2 阶段换成 Qdrant 混合检索，接口形态不变。",
    }

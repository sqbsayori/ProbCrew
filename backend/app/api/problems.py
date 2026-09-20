"""例题库 API —— 给「题目讲解」页提供可一键加载的题目。

内容文件：`backend/knowledge_base/examples.json`（由内容负责人维护，
数值都必须独立核算过 —— 当前 10 道题的答案已用程序复算一致）。

为什么要有它：题目讲解页原本是空输入框，演示时只能现场编一道题。
有了例题库，学生（和演示者）可以按章节/难度/标签挑题，点一下就开始讲解。
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..kernel import auth as A

from ..config import PROJECT_ROOT

router = APIRouter(tags=["problems"])

EXAMPLES_PATH = PROJECT_ROOT / "backend" / "knowledge_base" / "examples.json"


@lru_cache(maxsize=1)
def load_examples() -> dict[str, Any]:
    if not EXAMPLES_PATH.exists():
        return {"version": 0, "examples": [], "error": "examples.json 不存在"}
    try:
        return json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"version": 0, "examples": [], "error": f"examples.json 解析失败：{exc}"}


@router.get("/api/problems/examples", summary="典型例题库")
async def list_examples(
    user: A.CurrentUser,
    chapter: str | None = Query(default=None, description="按章节过滤，如 ch01"),
    level: str | None = Query(default=None, description="基础 / 进阶"),
    tag: str | None = Query(default=None, description="按知识点标签过滤"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    data = load_examples()
    items = list(data.get("examples", []))

    if chapter:
        items = [e for e in items if e.get("chapter") == chapter]
    if level:
        items = [e for e in items if e.get("level") == level]
    if tag:
        items = [e for e in items if tag in (e.get("tags") or [])]

    # 汇总可用的过滤维度，便于前端渲染筛选器
    all_items = data.get("examples", [])
    chapters = sorted({e.get("chapter", "") for e in all_items if e.get("chapter")})
    levels = sorted({e.get("level", "") for e in all_items if e.get("level")})
    tags: list[str] = []
    for e in all_items:
        for t in e.get("tags") or []:
            if t not in tags:
                tags.append(t)

    return {
        "count": len(items[:limit]),
        "total": len(all_items),
        "filters": {"chapters": chapters, "levels": levels, "tags": tags},
        "items": items[:limit],
        "note": data.get("note", ""),
        "error": data.get("error"),
    }


@router.get("/api/problems/examples/{example_id}", summary="单道例题详情")
async def get_example(example_id: str, user: A.CurrentUser) -> dict[str, Any]:
    for e in load_examples().get("examples", []):
        if e.get("id") == example_id:
            return e
    raise HTTPException(status_code=404, detail=f"未找到例题：{example_id}")

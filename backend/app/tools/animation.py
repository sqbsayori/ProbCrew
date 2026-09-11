"""动画资产工具 —— 把 8 个 HTML 交互动画变成 Agent 可调用的"可视化工具"。

这是本项目**建立在既有 HTML 动画之上**的关键接缝：
动画本身不动（保持自包含、可离线），由本工具负责
「自然语言 / 知识点 → 动画 id → 前端 artifact 事件 → iframe 播放」。

数据来源：`frontend/assets/animations/manifest.json`（由动画勘测生成）。
若 manifest 缺失，工具会退化为"空目录"，不会让服务启动失败。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import ANIMATIONS_DIR
from ..kernel.specs import tool

MANIFEST_PATH = ANIMATIONS_DIR / "manifest.json"


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    """读取动画清单。用 lru_cache 避免每次请求都读盘。"""
    if not MANIFEST_PATH.exists():
        return {"version": 1, "basePath": "/animations/_raw/", "animations": []}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "version": 1,
            "basePath": "/animations/_raw/",
            "animations": [],
            "error": f"manifest.json 解析失败：{exc}",
        }


def all_animations() -> list[dict[str, Any]]:
    return list(load_manifest().get("animations", []))


def _tokens(text: str) -> set[str]:
    """中文按字 + 英文/数字按词切分，够用且无需分词库。"""
    text = text.lower()
    words = set(re.findall(r"[a-z0-9_]+", text))
    chars = set(re.findall(r"[\u4e00-\u9fff]", text))
    return words | chars


def score_animation(query: str, item: dict[str, Any]) -> float:
    """关键字打分：概念命中权重最高，其次标题，再次描述。"""
    q = _tokens(query)
    if not q:
        return 0.0

    concept_tokens: set[str] = set()
    for concept in item.get("concepts", []) or []:
        concept_tokens |= _tokens(concept)
    title_tokens = _tokens(item.get("title", ""))
    desc_tokens = _tokens(item.get("description", ""))

    def overlap(target: set[str]) -> float:
        if not target:
            return 0.0
        hit = len(q & target)
        return hit / max(len(target), 1) + hit * 0.05

    return (
        overlap(concept_tokens) * 3.0
        + overlap(title_tokens) * 2.0
        + overlap(desc_tokens) * 1.0
    )


def recommend(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """按知识点关键词推荐最相关的动画。"""
    scored = [(score_animation(query, a), a) for a in all_animations()]
    scored = [(s, a) for s, a in scored if s > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "id": a.get("id"),
            "title": a.get("title"),
            "file": a.get("file"),
            "category": a.get("category"),
            "description": a.get("description"),
            "url": f"{load_manifest().get('basePath', '/animations/_raw/')}{a.get('file')}",
            "score": round(s, 3),
        }
        for s, a in scored[:top_k]
    ]


@tool(
    "list_animations",
    "列出交互动画",
    "列出全部可用的概率论交互动画及其分类，用于构建资源导航。",
    owner="R1",
)
async def list_animations(*, ctx: Any = None, category: str | None = None) -> dict[str, Any]:
    items = all_animations()
    if category and category != "全部":
        items = [a for a in items if a.get("category") == category]
    return {
        "count": len(items),
        "categories": load_manifest().get("categories", ["全部"]),
        "items": [
            {
                "id": a.get("id"),
                "title": a.get("title"),
                "category": a.get("category"),
                "description": a.get("description"),
                "icon": a.get("icon"),
                "accent": a.get("accent"),
                "url": f"{load_manifest().get('basePath', '/animations/_raw/')}{a.get('file')}",
                "controls": a.get("controls", {}),
            }
            for a in items
        ],
    }


@tool(
    "recommend_animation",
    "推荐交互动画",
    "根据用户问题或知识点关键词，推荐最相关的 1-3 个交互动画并返回可播放 URL。",
    owner="R1",
)
async def recommend_animation(
    *, ctx: Any = None, query: str, top_k: int = 2
) -> dict[str, Any]:
    matches = recommend(query, top_k=top_k)
    primary = matches[0] if matches else None
    return {"query": query, "matches": matches, "primary": primary}

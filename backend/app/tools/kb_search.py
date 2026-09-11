"""知识库检索工具（轻量 RAG）。

定位
----
这是 **RAG 的接缝（seam）**，不是最终实现。
demo 阶段用「本地 Markdown + 中文 bigram TF-IDF」跑通全链路；
迭代阶段把本文件换成 Qdrant 混合检索即可，**调用方（Agent）完全不用改**。

为什么先用本地实现：R5 的 Qdrant 起好之前，其他人不能干等。
接口先冻结，实现后替换 —— 这就是契约优先的价值。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT
from ..kernel.specs import tool

KB_PATH = PROJECT_ROOT / "backend" / "knowledge_base" / "probstat.md"


def _split_sections(md: str) -> list[dict[str, str]]:
    """按二级标题切块，并记录所属一级标题作为章节目录。"""
    sections: list[dict[str, str]] = []
    chapter = ""
    current: dict[str, str] | None = None
    for line in md.splitlines():
        if line.startswith("## "):
            if current:
                sections.append(current)
            title = line[3:].strip()
            if title.startswith("ch") or re.match(r"^ch\d", title):
                chapter = title
            current = {"heading": title, "chapter": chapter, "body": ""}
        elif line.startswith("# "):
            chapter = line[2:].strip()
        elif current is not None:
            current["body"] += line + "\n"
    if current:
        sections.append(current)
    return [s for s in sections if s["body"].strip()]


def _grams(text: str) -> list[str]:
    """中文 bigram + 英文单词。中文 bigram 让"条件概率"能命中"条件/概率"。"""
    text = text.lower()
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = ["".join(chars[i : i + 2]) for i in range(max(len(chars) - 1, 0))]
    latin = re.findall(r"[a-z0-9_]{2,}", text)
    return bigrams + latin


@lru_cache(maxsize=1)
def _index() -> tuple[list[dict[str, Any]], dict[str, float]]:
    """构建倒排索引与 IDF。首次调用时建，之后缓存。"""
    if not KB_PATH.exists():
        return [], {}
    sections = _split_sections(KB_PATH.read_text(encoding="utf-8"))
    docs: list[dict[str, Any]] = []
    df: Counter[str] = Counter()
    for i, sec in enumerate(sections):
        grams = _grams(sec["heading"] + "\n" + sec["body"])
        tf = Counter(grams)
        docs.append({**sec, "idx": i, "tf": tf, "len": max(len(grams), 1)})
        df.update(set(grams))
    total = max(len(docs), 1)
    idf = {g: math.log((total + 1) / (c + 1)) + 1.0 for g, c in df.items()}
    return docs, idf


def search(query: str, top_k: int = 4) -> list[dict[str, Any]]:
    docs, idf = _index()
    if not docs:
        return []
    q_grams = Counter(_grams(query))
    scored: list[tuple[float, dict[str, Any]]] = []
    for doc in docs:
        score = 0.0
        for gram, qn in q_grams.items():
            if gram in doc["tf"]:
                tf = doc["tf"][gram] / doc["len"]
                score += qn * tf * idf.get(gram, 1.0)
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda p: p[0], reverse=True)
    return [
        {
            "chapter": d["chapter"],
            "heading": d["heading"],
            "content": d["body"].strip()[:1200],
            "score": round(s, 4),
        }
        for s, d in scored[:top_k]
    ]


@tool(
    "kb_search",
    "知识库检索",
    "在概率论与数理统计教材知识库中做混合检索，返回相关章节片段（含 LaTeX 公式）。",
    owner="R3",
)
async def kb_search(*, ctx: Any = None, query: str, top_k: int = 4) -> dict[str, Any]:
    hits = search(query, top_k=top_k)
    return {
        "query": query,
        "hit_count": len(hits),
        "chunks": hits,
        "empty": len(hits) == 0,
    }


@tool(
    "kb_stats",
    "知识库统计",
    "返回本地知识库的规模（章节/片段数），用于健康检查与演示。",
    owner="R3",
)
async def kb_stats(*, ctx: Any = None) -> dict[str, Any]:
    docs, _ = _index()
    chapters = sorted({d["chapter"] for d in docs if d["chapter"]})
    return {
        "path": str(KB_PATH),
        "exists": KB_PATH.exists(),
        "section_count": len(docs),
        "chapters": chapters,
    }


def outline() -> list[dict[str, Any]]:
    """返回知识库的章节结构（供前端渲染"课程目录"，点击即可提问）。

    这是把"知识库里有 5 章 18 节"这件事实实在在地展示出来 ——
    否则用户看到的是一个空输入框，不知道系统里到底有什么内容。
    """
    docs, _ = _index()
    chapters: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for d in docs:
        raw = d["chapter"] or "未分类"
        # "ch01 随机事件与概率" -> id="ch01", title="随机事件与概率"
        parts = raw.split(" ", 1)
        cid = parts[0] if len(parts) == 2 else raw
        ctitle = parts[1] if len(parts) == 2 else raw
        if cid not in chapters:
            chapters[cid] = {"id": cid, "title": ctitle, "sections": []}
            order.append(cid)

        body = re.sub(r"\s+", " ", d["body"]).strip()
        # 抓该节里第一条公式，作为"这节有什么"的提示
        formula = ""
        fm = re.search(r"\$\$(.+?)\$\$", d["body"], re.S)
        if fm:
            formula = re.sub(r"\s+", " ", fm.group(1)).strip()[:90]

        chapters[cid]["sections"].append(
            {
                "title": d["heading"],
                "summary": body[:70],
                "formula": formula,
                "question": f"{d['heading']}讲的是什么？",
                "chars": len(body),
            }
        )

    result = [chapters[cid] for cid in order]
    for ch in result:
        ch["section_count"] = len(ch["sections"])
    return result

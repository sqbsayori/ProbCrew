"""知识库检索工具（混合检索：BM25 + 向量 + 重排）。

定位
----
这是 **RAG 的接缝（seam）**。M2 检索升级后，它从"本地 bigram TF-IDF"升级为
**混合检索**，但**调用方（Agent）完全不用改** —— 返回结构只增字段、不改字段。

为什么必须保留 BM25（docs/12 M2）
----------------------------------
我们语料里全是 LaTeX 公式（`P(A\\mid B)`、`\\sum`、上下标）。
嵌入模型对这类符号几乎不敏感，纯向量检索会把"条件概率"和"贝叶斯公式"排乱；
BM25 精确匹配反而稳。所以是 **BM25 + 向量**融合，不是二选一。

失败必须显式
------------
模型权重不在本地 / 推理失败时，检索**照常返回结果**（走 BM25），
同时在 `trace` 里写明"这轮没有向量 / 没有重排"及原因。
绝不出现"看起来做了向量检索、其实只是关键词匹配"这种沉默降级。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT, settings
from ..kernel.specs import tool
from . import embedding, reranker

KB_PATH = PROJECT_ROOT / "backend" / "knowledge_base" / "probstat.md"

#: 融合权重。BM25 占 0.5 是有意的：公式密集语料里精确匹配很值钱。
_W_BM25 = 0.5
_W_VECTOR = 0.5
_K1 = 1.5  # BM25 参数（标准取值）
_B = 0.75
_RRF_K = 10  # RRF 平滑常数。K=60 是"网页级"取值，小语料上过于平滑（实测掉分）
_RRF_EPS = 0.05  # 同路内的幅度加成：让"都是第 1 名"里分数更高的那个胜出


# --------------------------------------------------------------------------
# 语料切分
# --------------------------------------------------------------------------


def _split_sections(md: str) -> list[dict[str, Any]]:
    """切分语料并记录章节目录与**原文行号区间**。

    两级都切成可检索片段：
      * `## 小节` → 片段（章 = 最近的一级标题）
      * 一级标题下**没有**任何二级小节的正文 → 自成一个片段（ch06–ch09 就是这样）

    第二条是必要的：真实教材里"统计量及其分布""参数估计"这类章可能没有二级标题，
    如果只认 `##`，这些章的正文会**整章检索不到**（体感就是"问了它说知识库没有"）。
    行号是"出处可点开"的基础：前端要能说清那句话在第几行，而不是只给个标题。
    """
    sections: list[dict[str, Any]] = []
    chapter = ""
    current: dict[str, Any] | None = None
    chapter_header: dict[str, Any] | None = None
    lines = md.splitlines()

    def new_block(title: str, lineno: int, level: int) -> dict[str, Any]:
        return {
            "heading": title,
            "chapter": chapter,
            "body": "",
            "level": level,
            "start_line": lineno,
            "end_line": lineno,
            "line_map": [],  # (原文行号, 行内容)
        }

    for lineno, line in enumerate(lines, 1):
        if line.startswith("## "):
            if current:
                sections.append(current)
            if chapter_header and chapter_header["body"].strip():
                sections.append(chapter_header)  # 章首正文先落地，再进小节
            chapter_header = None  # 本章已有二级小节，一级标题不再单独成段
            title = line[3:].strip()
            if title.startswith("ch") or re.match(r"^ch\d", title):
                chapter = title
            current = new_block(title, lineno, 2)
        elif line.startswith("# "):
            if current:
                sections.append(current)
                current = None
            if chapter_header:
                sections.append(chapter_header)
            chapter = line[2:].strip()
            chapter_header = new_block(chapter, lineno, 1)
        elif current is not None:
            current["body"] += line + "\n"
            current["end_line"] = lineno
            if line.strip():
                current["line_map"].append((lineno, line))
        elif chapter_header is not None:
            chapter_header["body"] += line + "\n"
            chapter_header["end_line"] = lineno
            if line.strip():
                chapter_header["line_map"].append((lineno, line))

    if current:
        sections.append(current)
    if chapter_header:
        sections.append(chapter_header)
    return [s for s in sections if s["body"].strip()]


def _grams(text: str) -> list[str]:
    """中文 bigram + 英文单词。中文 bigram 让"条件概率"能命中"条件/概率"。"""
    text = text.lower()
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = ["".join(chars[i : i + 2]) for i in range(max(len(chars) - 1, 0))]
    latin = re.findall(r"[a-z0-9_]{2,}", text)
    return bigrams + latin


# --------------------------------------------------------------------------
# 索引（词法 BM25 + 向量），按语料内容缓存
# --------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _index_for(signature: tuple[str, int]) -> dict[str, Any]:
    """构建 BM25 统计量（词法部分，便宜）。

    `signature` 是 (语料路径, mtime_ns)：文件没动就直接复用缓存，
    文件一动就自动重建 —— 不需要任何人记得"改完语料要重启"。

    **向量部分不在这里**：编码整个语料要几百毫秒（CPU 上 BGE-M3 更慢），
    而每次查询都会调 `_index()`；把编码放进这个缓存会导致
    "每问一次就重编码一遍语料"（实测让评测从 20s 涨到 2min）。
    所以向量单独用 `_doc_vectors()` 按同一签名缓存。
    """
    path_str, _mtime = signature
    path = Path(path_str)
    if not path.exists():
        return {"docs": [], "idf": {}, "avg_len": 1.0, "signature": signature}

    sections = _split_sections(path.read_text(encoding="utf-8"))
    docs: list[dict[str, Any]] = []
    df: Counter[str] = Counter()
    for i, sec in enumerate(sections):
        grams = _grams(sec["heading"] + "\n" + sec["body"])
        tf = Counter(grams)
        docs.append({**sec, "idx": i, "tf": tf, "len": max(len(grams), 1)})
        df.update(set(grams))

    total = max(len(docs), 1)
    idf = {g: math.log((total + 1) / (c + 1)) + 1.0 for g, c in df.items()}
    avg_len = sum(d["len"] for d in docs) / total

    return {"docs": docs, "idf": idf, "avg_len": avg_len, "signature": signature}


def _index() -> dict[str, Any]:
    """取当前语料对应的索引。文件 mtime 变了就自动重建（无需重启）。"""
    if not KB_PATH.exists():
        return _index_for((str(KB_PATH), -1))
    return _index_for((str(KB_PATH), KB_PATH.stat().st_mtime_ns))


_doc_vectors: tuple[tuple[str, int], list[list[float]]] | None = None


def _doc_vector_cache() -> tuple[tuple[str, int], list[list[float]]]:
    """语料向量索引（按语料签名缓存，避免每次查询重编码全语料）。"""
    global _doc_vectors
    idx = _index()
    signature = idx["signature"]
    if _doc_vectors is not None and _doc_vectors[0] == signature:
        return _doc_vectors

    docs = idx["docs"]
    vectors: list[list[float]] = []
    if docs:
        # 标题重复两次：让标题在向量里权重更高（BM25 那边由 tf 自然体现）
        payload = [f"{d['heading']}\n{d['heading']}\n{d['body']}" for d in docs]
        vectors = embedding.encode_many(payload)
    _doc_vectors = (signature, vectors)
    return _doc_vectors


def _lexical_scores(query: str) -> dict[int, float]:
    """BM25。返回 {doc_idx: 原始分数}（>0 才算候选）。"""
    idx = _index()
    docs, idf, avg_len = idx["docs"], idx["idf"], idx["avg_len"]
    if not docs:
        return {}
    q_grams = [g for g in _grams(query) if g in idf]
    if not q_grams:
        return {}

    scores: dict[int, float] = {}
    for doc in docs:
        s = 0.0
        for gram in q_grams:
            f = doc["tf"].get(gram, 0)
            if not f:
                continue
            denom = f + _K1 * (1 - _B + _B * doc["len"] / max(avg_len, 1e-9))
            s += idf[gram] * (f * (_K1 + 1)) / denom
        if s > 0:
            scores[doc["idx"]] = s
    return scores


def _vector_scores(query: str) -> tuple[dict[int, float], str]:
    """余弦相似度。返回 ({doc_idx: 相似度}, 说明)。"""
    idx = _index()
    docs = idx["docs"]
    if not docs:
        return {}, "向量索引为空（语料为空）"
    signature, vectors = _doc_vector_cache()
    if len(vectors) != len(docs):
        return {}, "向量索引与语料不同步（编码失败？）"
    try:
        qv = embedding.encode(query)
    except Exception as exc:  # noqa: BLE001
        return {}, f"查询编码失败：{type(exc).__name__}: {exc}"
    sims = {d["idx"]: embedding.similarity(qv, vectors[d["idx"]]) for d in docs}
    return sims, ""


def _normalize(scores: dict[int, float]) -> dict[int, float]:
    """把一路分数线性压到 [0,1]（**仅用于展示**，不用于融合）。

    注意：min-max 归一化会把"排名第二但分数很接近"的片段压成接近 0，
    两路加权平均时反而**伤害**召回（实测：融合后 top-3 比单路还低）。
    所以融合改用 RRF（只看排名），这个函数只留给前端展示归一化分数。
    """
    if not scores:
        return {}
    lo = min(scores.values())
    hi = max(scores.values())
    if hi - lo < 1e-12:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def _rrf(scores: dict[int, float], weight: float) -> dict[int, float]:
    """加权 Reciprocal Rank Fusion：`weight · [1/(K+rank) + ε·score]`。

    为什么是混合式（排名 + 少量幅度），而不是纯 RRF 或纯加权求和：
      * 纯加权求和：BM25 分值能到 20+，余弦只有 0.1~0.4，量纲不可比 → BM25 单方面决定结果；
      * 纯 RRF（K=60）：对 22 个片段的语料过于平滑 —— 第 1 名与第 2 名的差只有 0.4%，
        结果由 ε 噪声决定（实测 top-1 反而比 BM25 低）；
      * 混合式：名次决定主序（鲁棒），**同一路里分数更高的片段再拿一点加成**
        （恢复名次内部的分辨力），K 调到 10 让"靠前"这件事本身有足够分量。

    参考：Cormack et al. 2009 (RRF)；工业界常见的 weighted-rank + score-tiebreak 变体。
    """
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return {}
    span = max(scores.values()) - min(scores.values())
    scale = span if span > 1e-12 else 1.0
    return {
        idx: weight * (1.0 / (_RRF_K + rank) + _RRF_EPS * (s / scale))
        for rank, (idx, s) in enumerate(ranked, 1)
    }


# --------------------------------------------------------------------------
# 出处与片段
# --------------------------------------------------------------------------


def _snippet(doc: dict[str, Any], query: str) -> tuple[str, int]:
    """在片段里定位与查询最贴近的那几行。

    出处要"可点开"，就必须给出**能定位的位置**；只给标题的话，
    一节课件几十页，学生还是找不到那句原话。
    """
    line_map: list[tuple[int, str]] = doc.get("line_map") or []
    if not line_map:
        return "", doc.get("start_line", 0)
    q = set(_grams(query))
    best_line, best_score = line_map[0][0], -1
    for lineno, text in line_map:
        score = len(q & set(_grams(text)))
        if score > best_score:
            best_line, best_score = lineno, score

    window: list[tuple[int, str]] = []
    for i, (lineno, text) in enumerate(line_map):
        if lineno == best_line:
            window = line_map[max(0, i - 1) : i + 3]
            break
    snippet = "\n".join(t.strip() for _, t in window).strip()
    if len(snippet) > 320:
        snippet = snippet[:320] + "…"
    return snippet, best_line


def _provenance(doc: dict[str, Any], query: str) -> dict[str, Any]:
    snippet, line = _snippet(doc, query)
    return {
        "chapter": doc.get("chapter", ""),
        "heading": doc.get("heading", ""),
        "start_line": doc.get("start_line", 0),
        "end_line": doc.get("end_line", 0),
        "hit_line": line,
        "snippet": snippet,
    }


# --------------------------------------------------------------------------
# 检索主入口
# --------------------------------------------------------------------------


def search_with_trace(
    query: str, top_k: int = 4, rerank: bool = True
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """混合检索。返回 (命中列表, trace)。

    trace 里写清楚**这一轮实际跑了哪几层**、没跑的原因是什么 ——
    评估脚本与前端都靠它，避免"看起来在跑向量"。
    `rerank=False` 用于评估"只融合、不重排"的中间态。
    """
    idx = _index()
    docs = idx["docs"]
    emb_status = embedding.status()
    rer_status = reranker.status()
    trace: dict[str, Any] = {
        "query": query,
        "top_k": top_k,
        "corpus_sections": len(docs),
        "corpus_path": str(KB_PATH),
        "stages": [],
        "degraded": [],
        "embedding": emb_status,
        "reranker": rer_status,
    }
    if not docs:
        trace["degraded"].append("语料为空：没有可检索的内容")
        return [], trace

    effective_backend = (settings.kb_backend or "auto").lower()
    use_vector = effective_backend != "bm25"
    use_rerank = use_vector and rerank

    # ---- ① 词法 BM25（永远跑：公式密集语料的地基）----
    bm25_raw = _lexical_scores(query)
    trace["stages"].append(f"bm25（{len(bm25_raw)} 个候选）")

    # ---- ② 向量 ----
    vec_raw: dict[int, float] = {}
    if use_vector:
        vec_all, vec_err = _vector_scores(query)
        if vec_err:
            trace["degraded"].append(f"向量检索未生效：{vec_err}")
        else:
            # 候选选择两步走：
            #   ① 绝对阈值（默认 0.08）挡掉"跟谁都有点像"的噪声；
            #   ② 排名截断，且**上限跟词法候选数挂钩** —— 词法只找到 3 条时，
            #      向量不该塞 12 条进来，否则融合会被稀释成"一半噪声"（实测会掉分）。
            over = {k: v for k, v in vec_all.items() if v >= settings.embedding_min_score}
            ranked = sorted(over.items(), key=lambda kv: kv[1], reverse=True)
            cap = min(settings.vector_candidates, max(len(bm25_raw), top_k, 3))
            vec_raw = dict(ranked[:cap])
            trace["stages"].append(
                f"vector·{emb_status['backend']}（{len(vec_all)} 条过阈值 → top-{len(vec_raw)} 入融合）"
            )
        if not emb_status["available"]:
            trace["degraded"].append(
                "向量层跑的是**离线降级实现**（hash-bigram），不是 "
                f"{emb_status['model']}；命中率数字不代表 BGE 的效果。原因：{emb_status['detail']}"
            )
    else:
        trace["degraded"].append("配置 KB_BACKEND=bm25：本轮禁用向量与重排")

    # ---- ③ 融合：RRF（只看排名，避免两路分数量纲不可比）----
    if use_vector:
        fused: dict[int, float] = {}
        for idx_, s in _rrf(bm25_raw, _W_BM25).items():
            fused[idx_] = fused.get(idx_, 0.0) + s
        for idx_, s in _rrf(vec_raw, _W_VECTOR).items():
            fused[idx_] = fused.get(idx_, 0.0) + s
        trace["fusion"] = f"RRF({_W_BM25:g}×bm25, {_W_VECTOR:g}×vector, K={_RRF_K})"
    else:
        fused = {i: s for i, s in bm25_raw.items()}
        trace["fusion"] = "1×bm25（仅词法）"
    bm25_norm, vec_norm = _normalize(bm25_raw), _normalize(vec_raw)  # 仅展示用

    # ---- ④ 粗排收窄 → 重排精选 ----
    candidates = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    cand_n = max(settings.rerank_candidates, top_k)
    candidates = candidates[:cand_n]

    rerank_map: dict[int, float] = {}
    if use_rerank and candidates:
        docs_text = []
        for doc_idx, _ in candidates:
            d = docs[doc_idx]
            snippet, _line = _snippet(d, query)
            docs_text.append(f"{d['heading']}\n{snippet or d['body'][:400]}")
        reranked, rerank_err = reranker.rerank(query, docs_text, top_k=None)
        if reranked is None:
            trace["degraded"].append(
                f"重排未生效（这轮是粗排顺序）：{rerank_err}"
            )
        else:
            rerank_map = {candidates[r["index"]][0]: r["score"] for r in reranked}
            trace["stages"].append(f"rerank·{rer_status['model']}（{len(reranked)} 条重排）")

    # ---- ⑤ 定序与产出 ----
    if rerank_map:
        ordered = sorted(
            candidates,
            key=lambda kv: (rerank_map.get(kv[0], 0.0), kv[1]),
            reverse=True,
        )
        score_view = lambda i, f: rerank_map.get(i, f)  # noqa: E731
    else:
        ordered = candidates
        score_view = lambda i, f: f  # noqa: E731

    hits: list[dict[str, Any]] = []
    for rank, (doc_idx, fused_score) in enumerate(ordered[:top_k], 1):
        doc = docs[doc_idx]
        prov = _provenance(doc, query)
        hits.append(
            {
                # ---- 原有字段（只增不改，调用方零改动）----
                "chapter": doc["chapter"],
                "heading": doc["heading"],
                "content": doc["body"].strip()[:1200],
                "score": round(float(score_view(doc_idx, fused_score)), 4),
                # ---- 新增字段 ----
                "rank": rank,
                "provenance": prov,
                "scores": {
                    "bm25": round(float(bm25_raw.get(doc_idx, 0.0)), 4),
                    "bm25_norm": round(float(bm25_norm.get(doc_idx, 0.0)), 4),
                    "vector": round(float(vec_raw.get(doc_idx, 0.0)), 4),
                    "vector_norm": round(float(vec_norm.get(doc_idx, 0.0)), 4),
                    "fused": round(float(fused_score), 4),
                    "rerank": round(float(rerank_map[doc_idx]), 4) if doc_idx in rerank_map else None,
                },
                "source": "hybrid" if use_vector else "bm25",
            }
        )

    trace["returned"] = len(hits)
    trace["empty"] = len(hits) == 0
    return hits, trace


def search(query: str, top_k: int = 4) -> list[dict[str, Any]]:
    """兼容入口：只要命中列表（老调用方与测试用这个签名）。"""
    hits, _trace = search_with_trace(query, top_k=top_k)
    return hits


@tool(
    "kb_search",
    "知识库检索",
    "在概率论与数理统计教材知识库中做混合检索（BM25 + 向量 + 重排），返回相关章节片段（含 LaTeX 公式与出处）。",
    owner="R3",
)
async def kb_search(*, ctx: Any = None, query: str, top_k: int = 4) -> dict[str, Any]:
    hits, trace = search_with_trace(query, top_k=top_k)
    return {
        "query": query,
        "hit_count": len(hits),
        "chunks": hits,
        "empty": len(hits) == 0,
        # 三态之外补一条：这一轮检索实际用了哪几层（前端/评估脚本据此如实展示）
        "retrieval": {
            "fusion": trace.get("fusion", ""),
            "stages": trace.get("stages", []),
            "degraded": trace.get("degraded", []),
            "embedding_backend": trace.get("embedding", {}).get("backend", ""),
            "embedding_available": trace.get("embedding", {}).get("available", False),
            "reranker_available": trace.get("reranker", {}).get("available", False),
        },
    }


@tool(
    "kb_stats",
    "知识库统计",
    "返回本地知识库的规模（章节/片段数）与检索层状态，用于健康检查与演示。",
    owner="R3",
)
async def kb_stats(*, ctx: Any = None) -> dict[str, Any]:
    docs = _index()["docs"]
    chapters = sorted({d["chapter"] for d in docs if d["chapter"]})
    return {
        "path": str(KB_PATH),
        "exists": KB_PATH.exists(),
        "section_count": len(docs),
        "chapters": chapters,
        "retrieval": {
            "embedding": embedding.status(),
            "reranker": reranker.status(),
            "fusion": f"{_W_BM25:g}×bm25 + {_W_VECTOR:g}×vector",
        },
    }


def outline() -> list[dict[str, Any]]:
    """返回知识库的章节结构（供前端渲染"课程目录"，点击即可提问）。

    这是把"知识库里有 5 章 18 节"这件事实在地展示出来 ——
    否则用户看到的是一个空输入框，不知道系统里到底有什么内容。
    """
    docs = _index()["docs"]
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
                "start_line": d.get("start_line", 0),
            }
        )

    result = [chapters[cid] for cid in order]
    for ch in result:
        ch["section_count"] = len(ch["sections"])
    return result


def reset_index() -> None:
    """测试用：丢掉**语料索引**缓存（改了语料或想强制重建时）。

    只清索引、**不清嵌入模型**：模型装配要十几秒（BGE-M3 CPU），
    而索引重建跟模型没关系；早先两者一起清，导致跑一次单测要重载好几次模型。
    """
    global _doc_vectors
    _index_for.cache_clear()
    _doc_vectors = None

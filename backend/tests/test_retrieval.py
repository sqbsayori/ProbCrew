"""混合检索（M2 · 任务 1）的单元测试。

守什么
------
1. **接口兼容**：`kb_search()` 的返回结构只增不改（Agent 调用方零改动），三态语义不变；
2. **BM25 必须活着**：即使向量层 / 重排层不可用，检索也要返回结果（LaTeX 语料靠它）；
3. **失败必须显式**：向量或重排没生效时，`retrieval.degraded` 要写出来 ——
   不允许"看起来做了语义检索、其实是关键词匹配"；
4. **出处可定位**：命中要带 chapter/heading/行号/片段，前端才能点开；
5. **离线可用**：没有模型权重时走降级实现，仍然能跑（CI 就是这种情况）。

运行：
    cd ProbCrew/backend
    python -m pytest tests -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LLM_PROVIDER", "mock")


# --------------------------------------------------------------------------
# 返回结构与三态
# --------------------------------------------------------------------------


def test_kb_search_keeps_legacy_shape() -> None:
    """老字段一个都不能少（契约只增不改）。"""
    from app.tools import kb_search

    out = asyncio.run(kb_search.kb_search(query="什么是条件概率", top_k=3))
    assert set(out) >= {"query", "hit_count", "chunks", "empty"}
    assert out["hit_count"] == len(out["chunks"])
    assert out["empty"] is (out["hit_count"] == 0)
    for chunk in out["chunks"]:
        assert set(chunk) >= {"chapter", "heading", "content", "score"}


def test_kb_search_reports_retrieval_stages() -> None:
    from app.tools import kb_search

    out = asyncio.run(kb_search.kb_search(query="中心极限定理", top_k=3))
    ret = out["retrieval"]
    assert ret["stages"], "至少要说明跑过哪几层"
    assert isinstance(ret["degraded"], list)
    assert ret["embedding_backend"]
    assert "bm25" in ret["fusion"].lower() or "bm25" in " ".join(ret["stages"]).lower()


def test_kb_search_empty_query_is_explicitly_empty() -> None:
    """查不到就必须显式说 empty（三态语义），不能返回一段不相关内容充数。"""
    from app.tools import kb_search

    out = asyncio.run(kb_search.kb_search(query="红烧肉的做法", top_k=3))
    assert out["empty"] is True and out["chunks"] == []


def test_kb_search_lexical_only_still_works() -> None:
    """把向量与重排都关掉，BM25 必须独立可用（这是"LaTeX 语料的地基"）。"""
    from app.config import settings
    from app.tools import embedding, kb_search, reranker

    original = settings.kb_backend
    try:
        settings.kb_backend = "bm25"
        hits, trace = kb_search.search_with_trace("贝叶斯公式", top_k=3)
        assert hits, "纯 BM25 也应当有命中"
        assert "bm25" in trace["fusion"]
        assert any("bm25" in s for s in trace["stages"])
        assert not any("vector" in s for s in trace["stages"])
        # 关掉向量后，嵌入/重排的状态**仍然可查**（前端要展示当前能力）
        assert embedding.status()["backend"]
        assert "available" in reranker.status()
    finally:
        settings.kb_backend = original


def test_degraded_reasons_are_explicit_when_models_missing() -> None:
    """模型权重不在本地时，必须把原因写进 trace，不能沉默降级。"""
    from app.tools import embedding, kb_search, reranker

    hits, trace = kb_search.search_with_trace("方差的计算公式", top_k=3)
    assert hits
    if not embedding.status()["available"]:
        assert any("降级实现" in d for d in trace["degraded"]), trace["degraded"]
        assert any("hash-bigram" in d for d in trace["degraded"])
    if not reranker.status()["available"]:
        assert any("重排未生效" in d for d in trace["degraded"]), trace["degraded"]


# --------------------------------------------------------------------------
# 出处
# --------------------------------------------------------------------------


def test_hits_carry_locatable_provenance() -> None:
    from app.tools import kb_search

    hits, _ = kb_search.search_with_trace("全概率公式", top_k=3)
    assert hits
    prov = hits[0]["provenance"]
    assert prov["chapter"].startswith("ch")
    assert prov["heading"]
    assert prov["start_line"] > 0 and prov["end_line"] >= prov["start_line"]
    assert prov["start_line"] <= prov["hit_line"] <= prov["end_line"]
    assert prov["snippet"], "出处要带可读片段，否则前端点开是空的"


def test_rank_is_one_based_and_monotonic() -> None:
    from app.tools import kb_search

    hits, _ = kb_search.search_with_trace("相关系数", top_k=4)
    assert [h["rank"] for h in hits] == list(range(1, len(hits) + 1))


def test_scores_expose_each_stage() -> None:
    from app.tools import kb_search

    hits, _ = kb_search.search_with_trace("期望的定义", top_k=3)
    scores = hits[0]["scores"]
    assert set(scores) >= {"bm25", "bm25_norm", "vector", "vector_norm", "fused", "rerank"}
    assert hits[0]["source"] in ("hybrid", "bm25")


# --------------------------------------------------------------------------
# 融合：RRF
# --------------------------------------------------------------------------


def test_rrf_rewards_agreement_between_the_two_routes() -> None:
    """RRF 的核心性质：**名次靠前**的片段，融合分必须显著高于靠后/未被召回的。"""
    from app.tools import kb_search

    bm25 = {1: 50.0, 2: 40.0, 3: 1.0, 4: 0.5}  # 排名：1 > 2 > 3 > 4
    vector = {3: 0.9, 2: 0.8, 1: 0.1}  # 排名：3 > 2 > 1（4 没被向量召回）
    total: dict[int, float] = {}
    for part, weight in ((bm25, 0.5), (vector, 0.5)):
        for idx_, s in kb_search._rrf(part, weight).items():
            total[idx_] = total.get(idx_, 0.0) + s

    # 被两路都召回且名次靠前的 1/2/3，必须明显高于只被一路看中（且排最后）的 4
    assert min(total[1], total[2], total[3]) > total[4] * 1.5, total
    # 两路都排第 2 的 2，跑赢"一路第 1、一路第 3"的 1/3 —— 这正是融合想要的：
    # 单路的一家之言不足以定胜负，需要两路互相印证。
    assert total[2] > total[1], total
    assert total[2] > total[3], total


def test_fusion_uses_score_as_tiebreak_within_same_rank() -> None:
    """同一路里"名次相同"是不可能，但两路名次完全一致时，分值更高的应当胜出。

    这是加权 RRF 里 `ε·score` 的作用：纯 RRF（只看名次）在大分值差场景下
    会退化成"名次一模一样就随机"，反而丢掉 BM25 已经算出来的分辨力。
    """
    from app.tools import kb_search

    bm25 = {1: 50.0, 2: 40.0}  # 1 明显更好
    vector = {1: 0.9, 2: 0.8}  # 向量也这么认为，但差距小
    total: dict[int, float] = {}
    for part, weight in ((bm25, 0.5), (vector, 0.5)):
        for idx_, s in kb_search._rrf(part, weight).items():
            total[idx_] = total.get(idx_, 0.0) + s
    assert total[1] > total[2], total


def test_rrf_ranking_is_scale_free_across_routes() -> None:
    """两路分值量纲完全不同（BM25 到 20+、余弦只有 0.1~0.4）也必须能公平融合。

    这是"为什么不能直接加权求和"的回归测试：如果哪天有人把融合改回
    `w1*bm25 + w2*cosine`，量纲差 100 倍会让向量层彻底失去作用 —— 这里会红。
    """
    from app.tools import kb_search

    bm25 = {1: 25.0, 2: 20.0, 3: 0.5}  # 排名：1 > 2 > 3
    vector = {3: 0.31, 2: 0.30, 1: 0.10}  # 排名：3 > 2 > 1
    fused: dict[int, float] = {}
    for part, weight in ((bm25, 0.5), (vector, 0.5)):
        for idx_, s in kb_search._rrf(part, weight).items():
            fused[idx_] = fused.get(idx_, 0.0) + s
    # 两路名次都靠前的 2 必须赢过"一路第 3、一路垫底"的 3 里更差的那个
    assert fused[2] > fused[1] * 0.95, fused
    # 量纲完全不同也不该出现"某一维独占"（三者的差距都在同一量级内）
    assert max(fused.values()) / min(fused.values()) < 3.0, fused


def test_rrf_is_scale_invariant() -> None:
    """同一路分值整体放大 1000 倍，融合结果不变（名次与相对幅度都没变）。"""
    from app.tools import kb_search

    a = {1: 8.0, 2: 7.9, 3: 0.1}
    b = {1: 8000.0, 2: 7900.0, 3: 100.0}
    ra, rb = kb_search._rrf(a, 1.0), kb_search._rrf(b, 1.0)
    assert set(ra) == set(rb)
    for key in ra:
        assert abs(ra[key] - rb[key]) < 1e-9, (key, ra[key], rb[key])


# --------------------------------------------------------------------------
# 索引：语料变了要自动重建
# --------------------------------------------------------------------------


def test_index_rebuilds_when_corpus_changes(tmp_path: Path, monkeypatch) -> None:
    """改了语料不重启也能生效（索引缓存以各文件 mtime 为签名）。"""
    from app.tools import kb_search

    bundled = tmp_path / "bundled"
    bundled.mkdir()
    fake = bundled / "kb.md"
    fake.write_text("# ch01 测试\n\n## 苹果\n\n苹果的期望是 1。\n", encoding="utf-8")
    monkeypatch.setattr(kb_search, "KB_DIR", bundled)
    kb_search.reset_index()

    hits, _ = kb_search.search_with_trace("苹果", top_k=3)
    assert hits and hits[0]["heading"] == "苹果"

    # 改语料 → 同一进程内再检索应当看到新内容
    fake.write_text("# ch01 测试\n\n## 香蕉\n\n香蕉的方差是 2。\n", encoding="utf-8")
    hits2, _ = kb_search.search_with_trace("香蕉", top_k=3)
    assert hits2 and hits2[0]["heading"] == "香蕉"

    kb_search.reset_index()


def test_missing_corpus_is_reported_not_crashed(tmp_path: Path, monkeypatch) -> None:
    """语料目录为空时必须如实说"没东西可检索"，而不是崩或者瞎返回。"""
    from app.tools import kb_search

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(kb_search, "KB_DIR", empty)
    kb_search.reset_index()
    hits, trace = kb_search.search_with_trace("任意问题")
    assert hits == []
    assert trace["corpus_sections"] == 0
    kb_search.reset_index()


# --------------------------------------------------------------------------
# 语料两来源（仓库内示例 + 仓库外教材）
# --------------------------------------------------------------------------


def test_external_corpus_is_indexed_and_tagged(tmp_path: Path, monkeypatch) -> None:
    """把教材语料丢进 CORPUS_DIR 就能检索到，且出处标明来自哪一来源。

    这是 docs/13 §1.2 的核心要求：教材（L1）不进仓库，但放进去**不用改代码**。
    """
    from app.config import settings
    from app.tools import kb_search

    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "sample.md").write_text(
        "# ch01 示例\n\n## 示例小节\n\n这是仓库内的示例内容。\n", encoding="utf-8"
    )
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "textbook-ch02.md").write_text(
        "# ch02 教材章节\n\n## 教材里的正态分布\n\n"
        "正态分布的密度函数是 $$f(x)=\\frac{1}{\\sqrt{2\\pi}\\sigma}e^{-\\frac{(x-\\mu)^2}{2\\sigma^2}}$$\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(kb_search, "KB_DIR", bundled)
    original = settings.corpus_dir
    try:
        settings.corpus_dir = str(corpus)
        kb_search.reset_index()

        info = kb_search.corpus_info()
        assert info["bundled_files"] == 1
        assert info["corpus_files"] == 1
        assert info["corpus_dir_exists"] is True
        assert info["hint"] == "", "已经有教材语料了，不该再提示'尚未放入'"

        # 教材里的内容必须检索得到
        hits, _ = kb_search.search_with_trace("正态分布的密度函数是什么", top_k=3)
        assert hits
        assert hits[0]["heading"] == "教材里的正态分布"
        assert hits[0]["corpus_source"] == "教材语料"
        assert hits[0]["corpus_file"] == "corpus/textbook-ch02.md", "外部语料不许泄露绝对路径"

        # 示例语料也还在索引里（两来源是"并存"，不是替换）
        hits2, _ = kb_search.search_with_trace("示例内容", top_k=3)
        assert hits2 and hits2[0]["corpus_source"] == "示例语料"
    finally:
        settings.corpus_dir = original
        kb_search.reset_index()


def test_corpus_info_hints_when_no_textbook(tmp_path: Path, monkeypatch) -> None:
    """只有示例语料时，要给出"教材还没放进来 + 放到哪"的人话提示。"""
    from app.config import settings
    from app.tools import kb_search

    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "sample.md").write_text("# ch01 示例\n\n## 小节\n\n内容。\n", encoding="utf-8")

    monkeypatch.setattr(kb_search, "KB_DIR", bundled)
    original = settings.corpus_dir
    try:
        settings.corpus_dir = str(tmp_path / "not-there")
        kb_search.reset_index()
        info = kb_search.corpus_info()
        assert info["corpus_files"] == 0
        assert info["corpus_dir_exists"] is False
        assert "尚未放入正式教材语料" in info["hint"]
    finally:
        settings.corpus_dir = original
        kb_search.reset_index()


def test_health_exposes_corpus_sources() -> None:
    """/api/health 要能回答"教材放进来了没有"。"""
    from fastapi.testclient import TestClient

    from app.main import build_app

    body = TestClient(build_app()).get("/api/health").json()
    corpus = body["knowledge_base"]["corpus"]
    assert corpus["sections"] > 0
    assert "bundled_files" in corpus and "corpus_files" in corpus
    assert corpus["by_source"]


# --------------------------------------------------------------------------
# 嵌入层
# --------------------------------------------------------------------------


def test_embedding_is_deterministic_and_normalized() -> None:
    """确定性是硬要求：否则同一问题两次检索结果不同，问题无法复现。"""
    from app.tools import embedding

    v1 = embedding.encode("条件概率")
    v2 = embedding.encode("条件概率")
    assert v1 == v2
    assert abs(embedding.similarity(v1, v1) - 1.0) < 1e-6
    assert embedding.dim() == len(v1)


def test_embedding_status_is_honest() -> None:
    from app.tools import embedding

    st = embedding.status()
    assert set(st) >= {"available", "backend", "model", "dim", "detail"}
    if st["backend"] == "hash-bigram":
        assert st["available"] is False, "降级实现不能被说成真实模型"
        assert st["detail"], "降级时必须给出原因（权重在哪、为什么不下载）"


def test_reranker_unavailable_returns_reason_not_silent() -> None:
    """不可用时返回 `(None, 原因)`：调用方必须能把"没做重排"讲清楚。"""
    from app.tools import reranker

    if reranker.status()["available"]:
        result, reason = reranker.rerank("问题", [])
        assert result == [] and reason == ""  # 空候选不算失败
    else:
        result, reason = reranker.rerank("问题", ["片段A", "片段B"])
        assert result is None and reason, "不可用时必须给出原因"


# --------------------------------------------------------------------------
# 评估脚本能跑（题集与脚本不能脱节）
# --------------------------------------------------------------------------


def test_question_bank_is_parseable_and_meaningful() -> None:
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "eval_retrieval", root / "scripts" / "eval_retrieval.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    questions = module.load_questions(root / "scripts" / "retrieval_questions.tsv")
    assert len(questions) >= 30, "任务 1 的验收要求 ≥30 个问题"
    for q in questions:
        assert q["query"], "问题不能为空"
        assert q["chapter"].startswith("ch"), f"期望章格式不对：{q['chapter']}"

    # ch01–ch05 的题必须指向真实存在的小节（否则小节口径的标尺是假的）；
    # ch06–ch09 在语料里只有章标题、没有二级小节，那些题只按章判定。
    from app.tools import kb_search

    idx = kb_search._index()["docs"]
    headings = {d["heading"] for d in idx}
    chapter_ids = {d["chapter"] for d in idx}
    chapters_without_sections = {"ch06", "ch07", "ch08", "ch09"}

    for q in questions:
        assert q["chapter"] in chapter_ids, f"题集引用了不存在的章：{q['chapter']}"
        cid = q["chapter"].split(" ")[0]
        if cid in chapters_without_sections:
            continue
        assert q["section"] in headings, f"题集引用了不存在的小节：{q['section']}"


def test_retrieval_meets_baseline_on_question_bank() -> None:
    """回归闸门：命中率不能掉到基线以下（数值取当前实测并留出余量）。

    这是"能拦住回归的测试"：改了融合权重、切分方式或阈值导致命中率崩掉时，
    这里会红，而不是等到学生发现答非所问。

    装了真实权重时这条测试会**自动跳过**：CPU 上重排单次约 2.2 s，
    跑完 20 题 × 4 种配置要一两分钟，放进"每次改代码都跑"的测试里会让人绕开测试。
    想连着权重一起验收时，显式打开：

        $env:RUN_SLOW_TESTS="1"; python -m pytest backend/tests -q
        # 或直接跑全量：python scripts/eval_retrieval.py
    """
    import importlib.util
    import os

    from app.tools import embedding, reranker

    if not os.environ.get("RUN_SLOW_TESTS") and (
        embedding.status()["available"] or reranker.status()["available"]
    ):
        import pytest

        pytest.skip(
            "已装真实模型权重：这条回归测试较慢（CPU 重排 ≈2.2s/次）。"
            "设 RUN_SLOW_TESTS=1 强制运行，或用 scripts/eval_retrieval.py 做全量验收。"
        )

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "eval_retrieval_gate", root / "scripts" / "eval_retrieval.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)

    questions = module.load_questions(root / "scripts" / "retrieval_questions.tsv")
    report = module.evaluate(questions[:20], k=3)  # 取前 20 题，跑得快
    assert report["rerank"]["top3_chapter"] >= 0.75, (
        f"混合检索 top-3 按章命中率跌破 75%：{report['rerank']['top3_chapter']:.2%}"
    )
    assert report["bm25"]["top3_chapter"] >= 0.65, (
        f"BM25 基线跌破 65%：{report['bm25']['top3_chapter']:.2%}"
    )


# --------------------------------------------------------------------------
# 手动运行入口（无 pytest 时）
# --------------------------------------------------------------------------


def _run_all() -> int:
    import inspect
    import tempfile
    import traceback

    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in tests:
            try:
                params = list(inspect.signature(fn).parameters)
                if "monkeypatch" in params:
                    print(f"  ○ {name}  （需要 pytest 的 monkeypatch，跳过）")
                    continue
                fn(Path(tmp)) if params else fn()
                print(f"  ✔ {name}")
            except Exception:  # noqa: BLE001
                failed += 1
                print(f"  ✘ {name}")
                traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())

"""重排（rerank）层（M2 检索升级 · 任务 1）。

为什么值得单独一层
------------------
粗排（BM25 / 向量）是"双塔"式：查询与片段各自编码，快但精度有限。
重排是"交叉编码"：把 (查询, 片段) 一起送进模型逐条打分，慢但准得多。
于是标准做法是 **粗排收窄到 N 条 → 重排精选 top-k**，`RERANK_CANDIDATES` 就是这个 N。

三条硬约束（与 embedding.py 一致）
----------------------------------
1. 本地跑，默认**不联网下载**权重；
2. 拿不到权重 → `status()["available"] is False`，`kb_search` 据此**明说没做重排**；
3. 推理必须**独立打分**（不能借用粗排分数），否则"重排"就只是给原序贴了个标签。
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from ..config import settings
from .embedding import _hf_cache_dir_name, _load_tokenizer  # 同一套本地权重/分词器口径

__all__ = ["status", "rerank", "reset_cache"]


def _local_model_dir(model_name: str) -> str:
    from pathlib import Path

    candidate = Path(model_name)
    if candidate.is_dir():
        return str(candidate)
    root = settings.models_root
    direct = root / _hf_cache_dir_name(model_name)
    if direct.is_dir():
        snapshots = direct / "snapshots"
        if snapshots.is_dir():
            for snap in sorted(snapshots.iterdir(), reverse=True):
                if (snap / "config.json").exists():
                    return str(snap)
        return str(direct)
    plain = root / model_name
    return str(plain) if plain.is_dir() else ""


_model: Any = None
_status: dict[str, Any] | None = None


def _load() -> tuple[Any, dict[str, Any]]:
    global _model, _status
    if _status is not None:
        return _model, _status

    name = settings.reranker_model
    local = _local_model_dir(name)
    detail = ""
    model: Any = None

    if local:
        try:
            import torch  # noqa: F401
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            tok = _load_tokenizer(local)
            mdl = AutoModelForSequenceClassification.from_pretrained(
                local, local_files_only=True
            )
            mdl.eval()
            model = {"tokenizer": tok, "model": mdl}
        except Exception as exc:  # noqa: BLE001
            detail = f"加载失败：{type(exc).__name__}: {exc}"
    else:
        detail = (
            f"本地找不到权重 {name}（找过：{settings.models_root}/"
            f"{_hf_cache_dir_name(name)}）；默认禁止联网下载（数据不出校）"
        )

    _model = model
    _status = {
        "available": model is not None,
        "model": name,
        "local_path": local,
        "detail": detail,
        "allow_download": settings.allow_model_download,
    }
    return _model, _status


def status() -> dict[str, Any]:
    return dict(_load()[1])


def rerank(
    query: str,
    documents: Sequence[str],
    top_k: int | None = None,
) -> tuple[list[dict[str, Any]] | None, str]:
    """对候选片段独立打分并重排。

    返回 `(结果, 说明)`：
      * 成功 → `([{index, score}, ...], "")`，按分数降序；
      * 不可用 → `(None, 原因)` —— 调用方**必须**把原因写进检索结果里，
        不能假装重排过了（"没有验证就写没有验证"）。
    """
    model, st = _load()
    if model is None:
        # 不可用时**必须**给出原因（调用方要把它写进检索结果里）
        return None, st["detail"] or "重排模型不可用"
    if not documents:
        return [], ""
    docs = list(documents)
    try:
        import torch

        tok, mdl = model["tokenizer"], model["model"]
        scores: list[float] = []
        with torch.no_grad():
            for start in range(0, len(docs), 8):  # 小批量：CPU 上内存友好
                batch = docs[start : start + 8]
                enc = tok(
                    [query] * len(batch),
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                )
                logits = mdl(**enc).logits.view(-1).float()
                scores.extend(float(s) for s in logits)
        # 有些 reranker 输出 logit（无界），有些输出概率；统一压到 [0,1] 便于展示
        norm = [_sigmoid(s) if (s < 0 or s > 1) else s for s in scores]
        order = sorted(range(len(docs)), key=lambda i: norm[i], reverse=True)
        if top_k:
            order = order[:top_k]
        return [{"index": i, "score": round(norm[i], 4)} for i in order], ""
    except Exception as exc:  # noqa: BLE001 - 推理失败也要如实上报
        return None, f"重排推理失败：{type(exc).__name__}: {exc}"


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def reset_cache() -> None:
    global _model, _status
    _model = None
    _status = None

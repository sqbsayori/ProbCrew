"""向量检索的嵌入层（M2 检索升级 · 任务 1）。

定位
----
`kb_search` 是"检索的接缝"，本文件是接缝后面的**向量那一半**：
把查询与语料片段编码成同一空间的向量，供 `kb_search` 做混合打分。

三条硬约束（来自 docs/12 M2 与 docs/13）
----------------------------------------
1. **本地跑，数据不出校**：默认**禁止联网下载权重**（`ALLOW_MODEL_DOWNLOAD=false`），
   模型必须已经在本机（HF 缓存或 `MODELS_DIR` 指向的目录）。
2. **失败必须显式**：拿不到权重就 `status()["available"] is False` + 给出原因，
   `kb_search` 会据此**明说"这轮只有 BM25"**，绝不静默假装在跑向量。
3. **不允许"看起来在跑 BGE"**：没权重时用一个**离线降级实现**（中文 bigram + 稳定哈希
   投影，即 hashing 向量化）顶上，并在 `status()["backend"]` 里如实标注是
   `hash-bigram` 而不是 `bge-m3`。降级实现的命中率**不代表 BGE 的效果**。

为什么必须有降级实现：本仓库要能在断网机器 / CI 上跑通，
并且要让"混合检索 + 出处 + 评估脚本"这条链路现在就能被测试。
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any, Iterable, Sequence

from ..config import settings

__all__ = ["status", "encode", "encode_many", "similarity", "dim", "reset_cache"]

# 中文按字 + 英文/数字按词，与 kb_search 的切分口径保持一致
_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[a-zA-Z0-9_]{2,}")


def _grams(text: str) -> list[str]:
    """中文 bigram + 英文词。保留 bigram 是因为语料里全是术语与公式，
    单字切分会把"条件概率"和"概率条件"混为一谈。"""
    low = (text or "").lower()
    chars = _CJK.findall(low)
    bigrams = ["".join(chars[i : i + 2]) for i in range(max(len(chars) - 1, 0))]
    return bigrams + _LATIN.findall(low)


def _stable_hash(token: str, dim: int) -> int:
    """用 md5 而不是内置 hash()：内置 hash 对 str 每个进程都不同，
    会让"同一份语料两次检索结果不一样"，也让测试无法复现。"""
    return int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:4], "big") % dim


class _HashBigramEmbedder:
    """离线降级实现：hashing 向量化（hashing trick + 次线性 TF + L2 归一化）。

    它**不是**语义模型：只是把 bigram 词表投到固定维度上，
    好处是零依赖、零权重、确定性、跨机器一致，能在断网环境跑通全链路。
    """

    backend = "hash-bigram"

    def __init__(self, dim: int) -> None:
        self.dim = max(64, int(dim))

    def encode(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        grams = _grams(text)
        if not grams:
            return vec
        for token, count in Counter(grams).items():
            weight = 1.0 + math.log(count)  # 次线性 TF：重复不无限加分
            idx = _stable_hash(token, self.dim)
            # 符号哈希：不同 token 撞到同一维时相互抵消一部分，减少系统性偏置
            sign = 1.0 if int.from_bytes(hashlib.md5(token.encode()).digest()[4:5], "big") % 2 else -1.0
            vec[idx] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


def read_pooling_mode(local: str) -> str:
    """从 sentence-transformers 的 `1_Pooling/config.json` 读池化方式。

    这一步不是可选的细节：**BGE-M3 官方配置是 CLS pooling**，
    如果按"常识"用 mean pooling，语义区分度会明显变差
    （实测：相关句与无关句的余弦只差 0.06，排序几乎没有分辨力）。
    读不到配置时退回 mean（对多数 BERT 类模型是合理默认）。
    """
    import json
    from pathlib import Path

    cfg = Path(local) / "1_Pooling" / "config.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 没有配置就用默认
        return "mean"
    if data.get("pooling_mode_cls_token"):
        return "cls"
    if data.get("pooling_mode_mean_tokens") or data.get("pooling_mode_mean_sqrt_len_tokens"):
        return "mean"
    if data.get("pooling_mode_max_tokens"):
        return "max"
    return "mean"


class _RealEmbedder:
    """真正的语义嵌入（BGE-M3 / bge-large-zh-v1.5 之类），要求权重已在本机。"""

    def __init__(
        self,
        model: Any,
        backend: str,
        dim: int,
        name: str,
        pooling: str = "mean",
        max_length: int = 512,
    ) -> None:
        self._model = model
        self.backend = backend
        self.dim = dim
        self.name = name
        self.pooling = pooling
        self.max_length = max_length

    def encode(self, text: str) -> list[float]:
        return self.encode_many([text])[0]

    def encode_many(self, texts: Sequence[str]) -> list[list[float]]:
        if self.backend == "sentence-transformers":
            vecs = self._model.encode(
                list(texts), normalize_embeddings=True, show_progress_bar=False
            )
            return [list(map(float, v)) for v in vecs]

        import torch

        with torch.no_grad():
            batch = self._model["tokenizer"](
                list(texts),
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            out = self._model["model"](**batch)
            last = out.last_hidden_state
            if self.pooling == "cls":
                pooled = last[:, 0]
            elif self.pooling == "max":
                mask = batch["attention_mask"].unsqueeze(-1).float()
                pooled = (last * mask + (mask - 1) * 1e9).max(dim=1).values
            else:  # mean
                mask = batch["attention_mask"].unsqueeze(-1).float()
                pooled = (last * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            return [list(map(float, v)) for v in pooled]


# --------------------------------------------------------------------------
# 权重解析（只找本地，不联网）
# --------------------------------------------------------------------------


def _hf_cache_dir_name(model_name: str) -> str:
    return "models--" + model_name.replace("/", "--")


def _load_tokenizer(local: str) -> Any:
    """加载分词器，**必须拿到 fast 版**。

    为什么单独封装：BGE-M3 仓库里既有 `sentencepiece.bpe.model` 又有 `tokenizer.json`。
    `AutoTokenizer` 不稳时（缺少 sentencepiece 等）会**静默回退**到慢速
    `XLMRobertaTokenizer`，而慢速版读不到 BGE 的中文词表 —— 结果是**所有中文都被
    编码成 `<unk>`**（`input_ids=[0,3,2]`），于是任意两句话的向量完全相同、
    余弦相似度恒等于 1.0。这个 bug 不会报错，只会让检索"看起来在跑、其实全错"。
    （真踩过：先下载权重、后测相似度才发现。）

    所以这里：**优先 fast** → 校验中文没有退化成 `<unk>` → 不合格就显式报错。
    """
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(local, local_files_only=True, use_fast=True)

    probe = tok("条件概率")
    if len(probe["input_ids"]) <= 3:  # [CLS, <unk>, SEP] —— 中文全丢了
        raise RuntimeError(
            "分词器把中文编码成了 <unk>（拿到的是慢速 tokenizer，缺少 sentencepiece/tokenizer.json）。"
            "请确认模型目录里有 tokenizer.json；必要时 pip install sentencepiece。"
        )
    return tok


def _local_model_dir(model_name: str) -> str:
    """把配置里的模型名解析成一个**本地**目录；找不到返回空串。"""
    from pathlib import Path

    candidate = Path(model_name)
    if candidate.is_dir():
        return str(candidate)

    root = settings.models_root
    direct = root / _hf_cache_dir_name(model_name)
    if direct.is_dir():
        snapshots = direct / "snapshots"
        if snapshots.is_dir():
            # 有 download 标记才算完整（避免加载到下载了一半的权重）
            for snap in sorted(snapshots.iterdir(), reverse=True):
                if (snap / "config.json").exists():
                    return str(snap)
        return str(direct)
    # 允许直接放 <MODELS_DIR>/<模型名> 这种朴素布局
    plain = root / model_name
    if plain.is_dir():
        return str(plain)
    return ""


_embedder: Any = None
_status: dict[str, Any] | None = None


def _load() -> tuple[Any, dict[str, Any]]:
    """装配嵌入器：真模型 → 降级实现。**只尝试本地权重**。"""
    global _embedder, _status
    if _embedder is not None and _status is not None:
        return _embedder, _status

    name = settings.embedding_model
    local = _local_model_dir(name)
    detail = ""
    backend = ""
    embedder: Any = None

    if local:
        try:  # ① sentence-transformers（最省事，装了就用）
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(local)
            real_dim = len(model.encode(["探针"], normalize_embeddings=True)[0])
            embedder = _RealEmbedder(model, "sentence-transformers", real_dim, name)
            backend = "sentence-transformers"
        except ImportError as exc:  # 没装 sentence-transformers
            detail = f"sentence-transformers 未安装（{exc}）"
        except Exception as exc:  # noqa: BLE001 - 权重坏了也要说清楚
            detail = f"加载失败：{type(exc).__name__}: {exc}"

        if embedder is None:
            try:  # ② transformers 原生（torch 已在依赖里）
                import torch  # noqa: F401
                from transformers import AutoModel

                tok = _load_tokenizer(local)
                # 权重格式让 transformers 自己挑（优先 safetensors，其次 pytorch_model.bin）。
                # 不写死 use_safetensors=True：有些镜像的快照只拉到 .bin，
                # 写死会把"权重明明在本地"误判成"模型不可用"（踩过）。
                mdl = AutoModel.from_pretrained(local, local_files_only=True)
                mdl.eval()
                with torch.no_grad():
                    probe = tok(["探针"], return_tensors="pt")
                    real_dim = int(mdl(**probe).last_hidden_state.shape[-1])
                embedder = _RealEmbedder(
                    {"tokenizer": tok, "model": mdl},
                    "transformers",
                    real_dim,
                    name,
                    pooling=read_pooling_mode(local),
                )
                backend = "transformers"
            except Exception as exc:  # noqa: BLE001
                detail = (detail + "；" if detail else "") + f"transformers 加载失败：{exc}"
    else:
        detail = (
            f"本地找不到权重 {name}（找过：{settings.models_root}/"
            f"{_hf_cache_dir_name(name)}）；默认禁止联网下载（数据不出校）"
        )

    if embedder is None:
        embedder = _HashBigramEmbedder(settings.embedding_dim)
        backend = "hash-bigram"

    _embedder = embedder
    _status = {
        "available": backend != "hash-bigram",
        "backend": backend,
        "model": name,
        "dim": int(embedder.dim),
        "pooling": getattr(embedder, "pooling", ""),
        "local_path": local,
        "detail": detail,
        "allow_download": settings.allow_model_download,
    }
    return _embedder, _status


def status() -> dict[str, Any]:
    """当前嵌入能力。`available=False` 表示跑的是离线降级实现，**不是 BGE-M3**。"""
    return dict(_load()[1])


def dim() -> int:
    return int(_load()[0].dim)


def encode(text: str) -> list[float]:
    return _load()[0].encode(text)


def encode_many(texts: Iterable[str]) -> list[list[float]]:
    items = list(texts)
    embedder = _load()[0]
    if hasattr(embedder, "encode_many"):
        return embedder.encode_many(items)
    return [embedder.encode(t) for t in items]


def similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """余弦相似度（两边都已归一化时就是点积）。"""
    n = min(len(a), len(b))
    return float(sum(a[i] * b[i] for i in range(n)))


def reset_cache() -> None:
    """测试用：清掉已装配的嵌入器。"""
    global _embedder, _status
    _embedder = None
    _status = None

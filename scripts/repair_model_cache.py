#!/usr/bin/env python
"""补齐模型快照里缺的文件（镜像 403 / 断流后用）。

为什么需要它
------------
`hf-mirror.com` 会对仓库里的**图片等非权重文件**返回 403，
导致 `snapshot_download` 半途失败；而 Windows 上不能建符号链接，
快照是"真副本"，缺一个文件就是永久缺（配置里 `local_files_only=True`
不会去补）。

这个脚本做一件很窄的事：把某个仓库**缺的文件列表**逐个 `hf_hub_download`，
哪个通道能下就用哪个，下到已存在的文件会直接跳过。

用法
----
    cd ProbCrew
    python scripts/repair_model_cache.py --repo BAAI/bge-m3
    python scripts/repair_model_cache.py --repo BAAI/bge-m3 --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "backend" / "data" / "models"

ENDPOINTS = (
    ("hf-mirror", "https://hf-mirror.com", None),
    ("huggingface", "https://huggingface.co", "http://127.0.0.1:7890"),
)


def _install_proxy(proxy: str | None) -> None:
    if not proxy:
        return
    os.environ["HTTPS_PROXY"] = proxy
    os.environ["HTTP_PROXY"] = proxy
    import urllib.request

    urllib.request.install_opener(
        urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    )


def _cache_name(repo: str) -> str:
    return "models--" + repo.replace("/", "--")


def _snapshot_dir(cache: Path, repo: str) -> Path:
    base = cache / _cache_name(repo) / "snapshots"
    if not base.is_dir():
        raise SystemExit(f"[错误] 找不到快照目录：{base}（先跑 scripts/setup_models.py）")
    snaps = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)
    if not snaps:
        raise SystemExit(f"[错误] 快照目录为空：{base}")
    return snaps[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="补齐模型快照里缺的文件")
    ap.add_argument("--repo", required=True, help="例如 BAAI/bge-m3")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="权重根目录")
    ap.add_argument("--dry-run", action="store_true", help="只列出缺哪些文件")
    args = ap.parse_args()

    cache = Path(args.cache)
    snap = _snapshot_dir(cache, args.repo)

    from huggingface_hub import HfApi, snapshot_download

    _install_proxy("http://127.0.0.1:7890")
    os.environ["HF_ENDPOINT"] = "https://huggingface.co"

    info = HfApi(endpoint="https://huggingface.co").model_info(args.repo, files_metadata=True)
    wanted = []
    for sib in info.siblings or []:
        name = sib.rfilename
        if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")):
            continue  # 文档配图，下载失败也不影响推理
        target = snap / name
        if target.exists() and target.stat().st_size > 0:
            continue
        wanted.append(name)

    print(f"  仓库 {args.repo}")
    print(f"  快照 {snap}")
    print(f"  缺失 {len(wanted)} 个文件" + (f"：{wanted}" if wanted else "（无需补齐）"))
    if args.dry_run or not wanted:
        return 0

    for name in wanted:
        ok = False
        for label, endpoint, proxy in ENDPOINTS:
            _install_proxy(proxy)
            os.environ["HF_ENDPOINT"] = endpoint
            for attempt in (1, 2):
                try:
                    t0 = time.time()
                    # 关键：用 snapshot_download + allow_patterns，而不是 hf_hub_download。
                    # `hf_hub_download(local_dir=...)` 会把文件平铺到目录根，
                    # 丢掉 tokenizer 等子目录结构；而 allow_patterns 会正确落到 snapshots/。
                    path = snapshot_download(
                        repo_id=args.repo,
                        cache_dir=str(cache),
                        allow_patterns=[name],
                        endpoint=endpoint,
                        max_workers=2,
                    )
                    print(f"    ✔ {name}（{label}，{time.time() - t0:.0f}s）")
                    ok = True
                    break
                except Exception as exc:  # noqa: BLE001
                    last = f"{type(exc).__name__}: {str(exc)[:120]}"
            if ok:
                break
        if not ok:
            print(f"    ✘ {name} 两个通道都失败：{last}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

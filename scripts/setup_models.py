#!/usr/bin/env python
"""一次性把检索模型权重装到**本机**（不进仓库、不进分发物）。

为什么需要它
------------
`docs/12` M2 / `docs/14` 任务 1 要求「嵌入与重排模型全部本地跑，数据不出校」。
本项目默认 `ALLOW_MODEL_DOWNLOAD=false`，也就是**运行时不联网**；
权重必须由人显式下载一次，放在本机缓存或 `MODELS_DIR` 指向的目录里。

下载到哪
--------
默认落到 **`backend/data/models`**（仓库内、但整目录已 gitignore）：
这样既不会把数 GB 权重提交进仓库，也不要求用户有 `~/.cache` 的写权限
（受限环境 / 受控机器上很常见）。装完脚本会告诉你 `.env` 里该写什么。

也可以用 `--target D:\models` 指定别处，然后 `.env` 里写 `MODELS_DIR=D:\models`。
`--write-env` 可以帮你把这一行写进 `.env`（没装过权重时最省事）。

网络说明
--------
本脚本会**按顺序尝试**三种通道，任一成功即继续（切模型时会再试一遍）：
  1. `https://hf-mirror.com`（国内镜像，直连）；
  2. `https://huggingface.co`（官方；若本机有代理会自动挂上）；
  3. 上面都失败 → 报错并给出替代方案（手动下载 + `--from-dir`）。

用法
----
    cd ProbCrew
    python scripts/setup_models.py                      # 装 bge-m3 + bge-reranker-v2-m3
    python scripts/setup_models.py --only embedding      # 只装嵌入
    python scripts/setup_models.py --target D:\\models
    python scripts/setup_models.py --list                # 只看当前状态，不下载
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

DEFAULT_MODELS = {
    "embedding": "BAAI/bge-m3",
    "reranker": "BAAI/bge-reranker-v2-m3",
}

#: 镜像优先（直连可用），官方兜底（需要代理）
ENDPOINTS = (
    ("hf-mirror", "https://hf-mirror.com", None),
    ("huggingface", "https://huggingface.co", "http://127.0.0.1:7890"),
)

#: 这些文件是训练/多格式副本，推理用不到 —— 不下能省下 1~2 GB
#: 注意**不能**忽略 tokenizer.json：缺了它 AutoTokenizer 会静默回退到慢速实现，
#: 把中文全编码成 <unk>（向量恒等），是个不报错的坑。见 embedding._load_tokenizer。
IGNORE_PATTERNS = ["*.onnx", "onnx/*", "*.h5", "*.msgpack", "*.tflite", "openvino/*", "*.ot"]


def _install_proxy(proxy: str | None) -> None:
    """让本次进程的 HTTPS 走代理（httpx 读环境变量；顺便给 urllib 也挂上）。"""
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


def _reachable(endpoint: str) -> bool:
    import urllib.error
    import urllib.request

    url = endpoint.rstrip("/") + "/api/models/BAAI/bge-m3"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code in (200, 401, 403)  # 有响应就算通
    except Exception:  # noqa: BLE001
        return False


def _local_dir(model: str, root: Path | None) -> str:
    from app.tools.embedding import _hf_cache_dir_name

    base = root or (Path.home() / ".cache" / "huggingface" / "hub")
    direct = base / _hf_cache_dir_name(model)
    snapshots = direct / "snapshots"
    if snapshots.is_dir():
        for snap in sorted(snapshots.iterdir(), reverse=True):
            if (snap / "config.json").exists():
                return str(snap)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="下载检索模型权重到本机")
    ap.add_argument("--only", choices=["embedding", "reranker"], help="只装一个")
    ap.add_argument(
        "--target",
        default=str(ROOT / "backend" / "data" / "models"),
        help="权重根目录（默认 backend/data/models，已 gitignore）",
    )
    ap.add_argument("--list", action="store_true", help="只看状态，不下载")
    ap.add_argument("--write-env", action="store_true", help="把 MODELS_DIR 写进 .env")
    ap.add_argument("--retries", type=int, default=2, help="每个通道的重试次数")
    args = ap.parse_args()

    root = Path(args.target).expanduser()
    wanted = (
        {args.only: DEFAULT_MODELS[args.only]} if args.only else dict(DEFAULT_MODELS)
    )
    root.mkdir(parents=True, exist_ok=True)

    print("=" * 66)
    print("  检索模型权重安装（本机，不进仓库）")
    print("=" * 66)
    print(f"  目标目录：{root}")
    print()

    from app.tools import embedding, reranker

    print("  [当前状态]")
    print(f"    嵌入  {embedding.status()['backend']:<20} available={embedding.status()['available']}")
    print(f"    重排  {'loaded' if reranker.status()['available'] else '未加载':<20} available={reranker.status()['available']}")
    print()
    if args.list:
        return 0

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("  [错误] 缺少 huggingface_hub。请先：pip install huggingface_hub")
        return 1

    failures: list[str] = []
    # 让复核与后续运行都用同一个权重根目录（也提醒用户 .env 该写什么）
    os.environ["MODELS_DIR"] = str(root)
    for kind, model in wanted.items():
        print(f"  [{kind}] {model}")
        done = False
        for name, endpoint, proxy in ENDPOINTS:
            _install_proxy(proxy)
            os.environ["HF_ENDPOINT"] = endpoint
            if not _reachable(endpoint):
                print(f"    - {name:<12} 不可达，跳过")
                continue
            for attempt in range(1, args.retries + 1):
                try:
                    t0 = time.time()
                    path = snapshot_download(
                        repo_id=model,
                        endpoint=endpoint,
                        cache_dir=str(root),
                        ignore_patterns=IGNORE_PATTERNS,
                        max_workers=4,
                    )
                    print(
                        f"    ✔ {name} 下载完成（{time.time() - t0:.0f}s）：{path}"
                    )
                    done = True
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"    ✘ {name} 第 {attempt} 次失败：{type(exc).__name__}: {str(exc)[:160]}")
            if done:
                break
        if not done:
            failures.append(model)
        print()

    # ---- 复核：装完必须能被项目真的用起来 ----
    embedding.reset_cache()
    reranker.reset_cache()
    st = embedding.status()
    rt = reranker.status()
    print("  [复核]")
    print(f"    嵌入  backend={st['backend']}  available={st['available']}  dim={st['dim']}")
    print(f"    重排  available={rt['available']}  path={rt['local_path']}")

    wanted_env = f"MODELS_DIR={root}"
    if args.write_env:
        env_path = ROOT / ".env"
        old = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        if "MODELS_DIR" in old:
            print(f"\n  · .env 里已有 MODELS_DIR，未改动（请确认它等于 {root}）")
        else:
            with env_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n# 由 scripts/setup_models.py 追加：检索模型权重位置\n{wanted_env}\n")
            print(f"\n  ✔ 已把 {wanted_env} 追加到 .env")

    if st["available"] and rt["available"]:
        print("\n  ✔ 两层都是真实模型了。请确认 .env 里有这一行：")
        print(f"      {wanted_env}")
        print("    然后重跑评测拿真实数字：")
        print("      python scripts/eval_retrieval.py --out docs/16-检索升级对比.md")
        return 0

    print("\n  ⚠️ 还有层没就绪：")
    for model in failures:
        print(f"      - {model}")
    print("    替代方案：在别的机器上用 `huggingface-cli download <模型>` 拉好，")
    print("    把整个目录拷到本机，再用 --target 指向它（或设 MODELS_DIR）。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

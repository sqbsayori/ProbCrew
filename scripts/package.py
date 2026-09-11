#!/usr/bin/env python
"""打包为可分发的原型演示包。

用法：
    cd our-system
    python scripts/package.py                    # 默认版本 0.1.0
    python scripts/package.py --version 0.2.0
    python scripts/package.py --no-zip           # 只生成目录，不压缩（便于检查）

产出：
    dist/probstat-assistant-prototype-v<版本>.zip
    dist/probstat-assistant-prototype-v<版本>/    （staging 目录，可直接压缩或拷贝）

设计要点
--------
1. **绝不打包密钥**。脚本会扫描所有待打包的文本文件，命中 API Key 特征就**中止打包**
   而不是警告 —— 因为一旦分发出去就无法收回。这是本脚本最重要的功能。
2. **不打包运行时数据**（learning.sqlite 里是真实的学习记录，属于用户隐私）。
3. **不打包 __pycache__ / .env / dist**，保持包干净、体积小。
4. 附带 `PACKAGE-INFO.txt` 记录构建时间、文件数、逐文件校验和 —— 方便确认双方拿到的是同一份。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

#: 这些目录 / 文件名一律不打包
EXCLUDE_DIRS = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "node_modules",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
}

EXCLUDE_FILES = {
    ".env",  # ★ 密钥
    ".env.local",
    ".deps-installed",
    "package-info.txt",
}

EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".sqlite",  # ★ 学习记录（用户隐私）
    ".sqlite-journal",
    ".db",
    ".log",
    ".zip",
}

EXCLUDE_NAME_PATTERNS = (
    re.compile(r"^\.env\..*$"),  # .env.bak 之类
)

#: 明确要保留的例外（否则上面的后缀规则会误伤 .env.example）
KEEP_OVERRIDES = {".env.example"}

#: 密钥特征。命中即中止。
SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{16,}"), "疑似 OpenAI/DeepSeek 风格密钥 (sk-...)"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "疑似 AWS Access Key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"), "疑似 GitHub Token"),
    (re.compile(
        r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]"
    ), "疑似硬编码的密钥/口令"),
]

#: 只扫这些文本后缀（二进制文件跳过，避免误报）
TEXT_SUFFIXES = {
    ".py", ".js", ".mjs", ".ts", ".json", ".md", ".txt", ".html", ".css",
    ".sh", ".ps1", ".bat", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".env",
    ".example", "",
}

#: 这些文件里出现密钥样式属于「说明文字」，不算泄露
SECRET_SCAN_ALLOWLIST = {
    ".env.example",
    "requirements.txt",
    Path("scripts/package.py").as_posix(),
    Path("docs/07-部署与分发.md").as_posix(),
    Path("原型声明.md").as_posix(),
}


def should_skip(path: Path, rel: Path) -> bool:
    """判断是否跳过某个文件/目录。"""
    if path.is_dir():
        return path.name in EXCLUDE_DIRS or path.name.startswith(".")

    if path.name in KEEP_OVERRIDES:
        return False
    if path.name in EXCLUDE_FILES:
        return True
    if any(p.match(path.name) for p in EXCLUDE_NAME_PATTERNS):
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    # 隐藏文件默认跳过（.gitignore 例外，分发时要带上）
    if path.name.startswith(".") and path.name != ".gitignore":
        return True
    return any(part in EXCLUDE_DIRS for part in rel.parts)


def collect_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if should_skip(path, rel):
            continue
        if path.is_file():
            files.append(rel)
    return files


def scan_secrets(files: list[Path]) -> list[tuple[str, int, str]]:
    """扫描密钥。返回 [(文件, 行号, 命中的描述)]。"""
    hits: list[tuple[str, int, str]] = []
    for rel in files:
        if rel.as_posix() in SECRET_SCAN_ALLOWLIST:
            continue
        if rel.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            # 明显的占位符放行
            if any(
                ph in line
                for ph in ("your-api-key", "sk-your", "sk-xxx", "xxx", "example", "占位")
            ):
                continue
            for pattern, desc in SECRET_PATTERNS:
                if pattern.search(line):
                    hits.append((rel.as_posix(), lineno, desc))
                    break
    return hits


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def build_staging(files: list[Path], stage: Path) -> None:
    if stage.exists():
        shutil.rmtree(stage)
    for rel in files:
        dest = stage / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)


def write_info(stage: Path, files: list[Path], version: str) -> Path:
    lines = [
        "概率论伴学助手 · 多智能体原型演示包",
        "=" * 60,
        f"版本      : v{version}",
        f"构建时间  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"文件数    : {len(files)}",
        "",
        "这个包是什么",
        "-" * 60,
        "一个可注入到在线课程页面上的 AI 伴学助手原型（悬浮球 / 虚拟页宠），",
        "由 LangGraph 编排多个 Agent 协作答疑，能读取学生当前页面的内容。",
        "",
        "怎么跑",
        "-" * 60,
        "Windows : 双击 启动.bat",
        "Linux/mac: bash start.sh",
        "手动    : pip install -r requirements.txt",
        "          python scripts/gen_registry.py",
        "          cd backend && python -m uvicorn app.main:app --port 8000",
        "然后打开 http://127.0.0.1:8000/course/",
        "",
        "★ 这是原型，不是成品。请务必先读《原型声明.md》，",
        "  里面写清了已知限制、数据流向与合规注意事项。",
        "",
        "文件校验和（SHA256 前 16 位）",
        "-" * 60,
    ]
    for rel in files:
        lines.append(f"{sha256(stage / rel)}  {rel.as_posix()}")

    out = stage / "PACKAGE-INFO.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="打包原型演示包")
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--no-zip", action="store_true", help="只生成目录，不压缩")
    ap.add_argument(
        "--allow-secrets",
        action="store_true",
        help="跳过密钥扫描（仅在你确认误报时使用；默认不允许）",
    )
    args = ap.parse_args()

    print("=" * 64)
    print("  打包原型演示包")
    print("=" * 64)

    files = collect_files()
    total = sum((ROOT / f).stat().st_size for f in files)
    print(f"  待打包文件 : {len(files)} 个，{human(total)}")

    # ---- ★ 密钥扫描 ----
    print("\n  [安全检查] 扫描密钥 …")
    if args.allow_secrets:
        print("    ⚠️  已用 --allow-secrets 跳过（请确认你知道自己在做什么）")
    else:
        hits = scan_secrets(files)
        if hits:
            print(f"\n    ✘ 发现 {len(hits)} 处疑似密钥，**已中止打包**：\n")
            for rel, lineno, desc in hits[:20]:
                print(f"      {rel}:{lineno}  {desc}")
            if len(hits) > 20:
                print(f"      …还有 {len(hits) - 20} 处")
            print(
                "\n    密钥一旦分发出去就无法收回。请先清理这些内容再重新打包。\n"
                "    如果确认是误报，可加 --allow-secrets 跳过（不推荐）。"
            )
            return 1
        print("    ✔ 未发现密钥")

    # ---- 组装 ----
    name = f"probstat-assistant-prototype-v{args.version}"
    stage = DIST / name
    print(f"\n  [组装] {stage.relative_to(ROOT)}")
    build_staging(files, stage)
    info = write_info(stage, files, args.version)
    print(f"    ✔ 已写入 {info.name}")

    # ---- 压缩 ----
    if args.no_zip:
        print("\n  [压缩] 已跳过（--no-zip）")
        zip_path = None
    else:
        zip_path = DIST / f"{name}.zip"
        if zip_path.exists():
            zip_path.unlink()
        print(f"\n  [压缩] {zip_path.name}")
        packed = 0
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zf.write(path, arcname=str(path.relative_to(DIST)))
                    packed += 1
        print(f"    ✔ {packed} 个文件，{human(zip_path.stat().st_size)}")

    # ---- 汇总 ----
    print("\n" + "=" * 64)
    print("  完成")
    print("=" * 64)
    print(f"  分发目录 : {stage}")
    if zip_path:
        print(f"  分发包   : {zip_path}")
        print(f"  包大小   : {human(zip_path.stat().st_size)}（原始 {human(total)}）")
    print("\n  收到包的人只需要：")
    print("    1. 解压")
    print("    2. 双击 启动.bat（或 bash start.sh）")
    print("    3. 浏览器打开 http://127.0.0.1:8000/course/")
    print("\n  未配置 API Key 会自动用 Mock 模式，断网也能完整演示。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

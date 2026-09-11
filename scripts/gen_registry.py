#!/usr/bin/env python
"""生成前端 feature 注册表。

为什么需要它
-----------
前端要"新增页面不改共享文件"，就必然需要一个"目录清单"。
我们不让任何人手写这个清单（那又变成冲突点），而是**扫描生成**：

    app/features/<dir>/feature.json   ->   app/features.registry.js

用法：
    cd our-system
    python scripts/gen_registry.py

在 CI 里跑 `--check` 可以校验注册表是否与目录一致（防止有人忘了生成）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURES_DIR = ROOT / "frontend" / "app" / "features"
OUT = ROOT / "frontend" / "app" / "features.registry.js"

HEADER = """/**
 * 本文件由 `scripts/gen_registry.py` 自动生成，请勿手工编辑。
 *
 * 新增页面：在 app/features/ 下新建目录，放入 feature.json 与 index.js，
 * 然后重新运行生成脚本即可。这样多人并行开发不会在同一份清单上冲突。
 */
export const FEATURES = """


def collect() -> list[dict]:
    items: list[dict] = []
    if not FEATURES_DIR.exists():
        return items
    for folder in sorted(FEATURES_DIR.iterdir()):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        meta_file = folder / "feature.json"
        entry_file = folder / "index.js"
        if not meta_file.exists():
            print(f"  ! 跳过 {folder.name}：缺少 feature.json")
            continue
        if not entry_file.exists():
            print(f"  ! 跳过 {folder.name}：缺少 index.js")
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"  ! 跳过 {folder.name}：feature.json 不是合法 JSON（{exc}）")
            continue
        meta.setdefault("id", folder.name)
        meta.setdefault("dir", folder.name)
        meta.setdefault("title", folder.name)
        meta.setdefault("route", meta["id"])
        items.append(meta)

    items.sort(key=lambda m: (m.get("order", 100), str(m.get("id", ""))))
    return items


def main() -> int:
    check = "--check" in sys.argv
    items = collect()
    payload = "[\n" + ",\n".join(
        "  " + json.dumps(m, ensure_ascii=False) for m in items
    ) + "\n];\n"
    content = HEADER + payload

    if check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        # 比较前统一换行符，避免 CRLF/LF 差异造成假失败
        norm = lambda s: s.replace("\r\n", "\n")
        if norm(current) != norm(content):
            print("✖ features.registry.js 与 features/ 目录不一致，请运行：python scripts/gen_registry.py")
            return 1
        print(f"✔ 注册表一致（{len(items)} 个 feature）")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" 是必须的：默认行为在 Windows 上会把 \n 翻译成 \r\n，
    # 于是 Windows 组员生成的注册表与 Linux 组员生成的**字节不同**，
    # CI 里的 `--check` 必然误报，git 里也会出现"只有换行符变了"的假 diff。
    OUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"✔ 已生成 {OUT.relative_to(ROOT)}（{len(items)} 个 feature）")
    for m in items:
        print(f"    [{m.get('order', 100):>3}] {m.get('icon', '•')} {m.get('route'):<14} {m.get('title')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

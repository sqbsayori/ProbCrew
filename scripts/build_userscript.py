#!/usr/bin/env python
"""生成"发布用"的油猴脚本 —— 部署时**不改源码**。

为什么需要它
------------
`frontend/widget/probstat-assistant.user.js` 里**没有任何写死的后端地址**：
地址是靠"从哪安装就连哪"（`location.origin` → 本页同源）自动推断的，
所以绝大多数情况下**不需要这个脚本**，学生直接从后端地址安装即可。

但有两种情况必须显式指定地址，这时才用它生成一份发布物：
  1. 前后端**分域**部署（前端在 A 域、后端在 B 域）；
  2. 目标页面是 `file://`（opaque origin，推断不出后端）。

这个脚本做三件事（都是"只增不改"）：
  * 把 `API_BASE_PIN` 填成发布地址；
  * 补上 `@downloadURL` / `@updateURL`（学生装了以后能自动更新）；
  * 输出到 `dist/`，**仓库里的源码保持通用**。

用法
----
    cd ProbCrew
    python scripts/build_userscript.py --base https://probstat.example.edu
    python scripts/build_userscript.py --base http://192.168.1.20:8000   # 局域网演示
    python scripts/build_userscript.py --base https://x.edu --check       # 只校验不写文件

产出
----
    dist/probstat-assistant.user.js      ← 直接发这个文件的链接给学生/老师
"""
from __future__ import annotations

from _console import utf8_output

utf8_output()

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "widget" / "probstat-assistant.user.js"
OUT_DIR = ROOT / "dist"
OUT_NAME = "probstat-assistant.user.js"

#: 源码里必须保持"通用"的东西 —— 一旦有人把地址写死，这里直接红灯
PIN_RE = re.compile(r"var API_BASE_PIN = '(?P<value>[^']*)';")
META_END = "// ==/UserScript=="
REQUIRE_RE = re.compile(r"^\s*//\s*@require\s+(\S+)\s*$", re.M)


def check_source(text: str) -> list[str]:
    """守住"源码里不许有写死的后端地址"。返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    if PIN_RE.search(text) is None:
        problems.append("找不到 `var API_BASE_PIN = '...';` 配置块（模板结构变了？）")
    else:
        pin = PIN_RE.search(text).group("value")  # type: ignore[union-attr]
        if pin:
            problems.append(f"源码里的 API_BASE_PIN 不是空的（当前 {pin!r}）—— 源码必须保持通用")
    if "127.0.0.1" in text or "localhost" in text:
        # 允许出现在注释里说明用法，但不允许出现在 `@match`/`@require`/可执行代码里
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            if "127.0.0.1" in line or "localhost" in line:
                problems.append(f"第 {lineno} 行出现写死的本机地址：{stripped[:80]}")
    for req in REQUIRE_RE.findall(text):
        if re.match(r"^[a-z]+://", req, re.I):
            problems.append(f"@require 应当是相对路径（由 Tampermonkey 按安装来源解析），实际是 {req}")
    return problems


def render(base: str, src_text: str) -> str:
    """把源码渲染成发布物。只改配置块与元数据块，其余逐字保留。"""
    origin = base.rstrip("/")
    out = PIN_RE.sub(f"var API_BASE_PIN = '{origin}';", src_text, count=1)

    extra_meta = (
        f"// @downloadURL  {origin}/widget/{OUT_NAME}\n"
        f"// @updateURL    {origin}/widget/{OUT_NAME}\n"
    )
    out = out.replace(META_END, extra_meta + META_END, 1)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    banner = (
        "// ---------------------------------------------------------------------------\n"
        f"// ★ 发布物（由 scripts/build_userscript.py 生成，{stamp}）\n"
        f"//   后端地址已固定为 {origin}；仓库源码不含任何写死地址。\n"
        "//   要改地址：重新跑一次生成脚本并覆盖安装，**不要手改这份文件**。\n"
        "// ---------------------------------------------------------------------------\n"
    )
    return banner + out


def main() -> int:
    ap = argparse.ArgumentParser(description="生成发布用油猴脚本（不改源码）")
    ap.add_argument("--base", default="", help="后端发布地址，例如 https://probstat.example.edu")
    ap.add_argument("--out", default="", help="输出路径（默认 dist/probstat-assistant.user.js）")
    ap.add_argument("--check", action="store_true", help="只校验源码是通用的，不生成文件")
    args = ap.parse_args()

    if not SRC.exists():
        print(f"[错误] 找不到源文件：{SRC}")
        return 1
    src_text = SRC.read_text(encoding="utf-8")

    problems = check_source(src_text)
    print("[校验] 源码通用性检查（不许写死后端地址）")
    if problems:
        for p in problems:
            print(f"  ✘ {p}")
        print("\n  源码一旦写死地址，部署到服务器后每个学生都要改源码重装 —— 这正是任务 3 要消掉的代价。")
        return 1
    print("  ✔ 未发现写死的后端地址；@require 全部是相对路径")

    if args.check:
        return 0

    if not args.base:
        print("\n[提示] 未提供 --base：源码本身已经能用（自动按安装来源推断地址）。")
        print("       只有「前后端分域」或 file:// 场景才需要显式指定：")
        print("         python scripts/build_userscript.py --base https://<你们的域名>")
        return 0

    if not re.match(r"^https?://", args.base):
        print(f"[错误] --base 必须是 http(s) 地址，实际：{args.base}")
        return 1

    out_text = render(args.base, src_text)
    out_path = Path(args.out) if args.out else (OUT_DIR / OUT_NAME)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out_text, encoding="utf-8")

    print("\n[生成] 发布物")
    print(f"  ✔ {out_path}")
    print(f"    安装地址：{args.base.rstrip('/')}/widget/{OUT_NAME}")
    print(f"    （把上面这个链接发出去即可；script 会自动更新）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

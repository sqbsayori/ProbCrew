#!/usr/bin/env python
"""从契约生成前端事件常量 —— `frontend/shared/events.js`。

为什么必须生成（而不是手写）
--------------------------
事件的唯一权威是 `contracts/events.schema.json`（14 种）。前端有两处分发：
`app/components/trace.js`（覆盖 13 种）与 `widget/assistant.js`（覆盖 11 种）——
**三者不一致**，而新增事件类型时只能靠人记得两边都改（`docs/23` §六）。

改成生成之后：契约里加一种事件 → CI 立刻红灯提醒重新生成 → 前端常量自动跟上。

用法
----
    python scripts/gen_events_js.py            # 生成
    python scripts/gen_events_js.py --check    # 只校验是否过期（CI 用）
"""
from __future__ import annotations

from _console import utf8_output

utf8_output()

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "contracts" / "events.schema.json"
OUT = ROOT / "frontend" / "shared" / "events.js"

HEADER = """/**
 * 事件类型常量 —— **本文件由 `scripts/gen_events_js.py` 自动生成，请勿手工编辑。**
 *
 * 唯一来源：`contracts/events.schema.json`（契约层）。
 * 主站与悬浮窗都必须用这里的常量，不许再手写事件名 —— 否则契约新增一种事件时，
 * 两处分发会各自漏掉（这正是生成它的原因，见 `docs/23` §六）。
 *
 * 重新生成：`python scripts/gen_events_js.py`
 */

/** 契约里的全部事件类型（{count} 种） */
export const EVENT_TYPES = """


def render() -> str:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    types = schema["properties"]["type"]["enum"]
    lines = [HEADER.format(count=len(types))]
    lines.append("[\n")
    for t in types:
        lines.append(f"  '{t}',\n")
    lines.append("];\n\n")
    lines.append("/** 事件类型 → 常量名（`EVENT.AGENT_DELTA` 这种写法靠它） */\n")
    lines.append("export const EVENT = Object.freeze(\n")
    lines.append("  Object.fromEntries(EVENT_TYPES.map((t) => [t.toUpperCase().replace(/\\./g, '_'), t]))\n")
    lines.append(");\n\n")
    lines.append("/** 判断某事件类型是否在契约里（分发处用它兜住「未处理类型」） */\n")
    lines.append("export const isKnownEventType = (t) => EVENT_TYPES.includes(t);\n")
    return "".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成前端事件常量（源：contracts/events.schema.json）")
    ap.add_argument("--check", action="store_true", help="只校验是否与契约一致（不写文件）")
    args = ap.parse_args()

    content = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != content:
            print("✘ frontend/shared/events.js 与契约不一致（或尚未生成）")
            print("  跑一次：python scripts/gen_events_js.py")
            return 1
        print(f"✔ 事件常量与契约一致（{content.count(chr(39)) // 2 - 0} 项左右）")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content, encoding="utf-8")
    n = content.count("\n  '")
    print(f"✔ 已生成 {OUT.relative_to(ROOT)}（{n} 种事件类型）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

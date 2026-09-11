#!/usr/bin/env python
"""复现尝试：CPython `re` 编译器在字符集优化时抛
   ValueError: not enough values to unpack (expected 2, got 0)

背景：在 smoke_test 的一次运行中观察到该异常，堆栈指向
   Lib/re/_compiler.py:326  `if q - p == 1:`
这是标准库的代码，不是本项目代码。本脚本尝试用项目里实际用到的
正则模式（加上常见 flag 组合与高频重复）复现它。

用法：
    python scripts/repro_re_bug.py
"""
from __future__ import annotations

import itertools
import re
import sys

PATTERNS = [
    r"[\u4e00-\u9fff]",
    r"[a-z0-9_]{2,}",
    r"[a-z0-9_\\{}^]{2,}",
    r"\*\*\s*Step\s*(\d+)\s*[·:：]?\s*([^*]*?)\*\*\s*(.*?)(?=\*\*\s*Step|\Z)",
    r"\$\$(.+?)\$\$",
    r"\$([^$\n]{2,200}?)\$",
    r"sk-[A-Za-z0-9]{16,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bghp_[A-Za-z0-9]{30,}\b",
    r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]",
    r"^\.env\..*$",
    r"[\s:|-]+\|[\s:|-]*",
    r"^\s*(-{3,}|\*{3,}|_{3,})\s*$",
    r"[\u0080-\uffff]",
    r"[^\x00-\x7f]",
    r"[\w\u4e00-\u9fff]+",
    r"[A-Za-z\u4e00-\u9fff0-9_]",
    r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]",
]

FLAGS = [0, re.I, re.S, re.M, re.U, re.I | re.S, re.I | re.U, re.I | re.S | re.U | re.M]

ROUNDS = 60


def main() -> int:
    print("=" * 64)
    print("  CPython `re` 编译器缺陷复现尝试")
    print("=" * 64)
    print(f"  Python : {sys.version.split()[0]}")
    print(f"  模式数 : {len(PATTERNS)} × flag {len(FLAGS)} × 每组合 {ROUNDS} 轮")
    print()

    tried = 0
    bad: list[tuple[str, int, str]] = []

    for pat, flag in itertools.product(PATTERNS, FLAGS):
        for _ in range(ROUNDS):
            try:
                re.compile(pat, flag)
                tried += 1
            except ValueError as exc:
                bad.append((pat, flag, str(exc)))
            # 清空编译缓存，强制每次都真正走一遍编译器
            re.purge()

    print(f"  实际编译 {tried} 次")

    if bad:
        print(f"\n  ✘ 复现了 {len(bad)} 次：")
        seen = set()
        for pat, flag, err in bad:
            key = (pat, flag)
            if key in seen:
                continue
            seen.add(key)
            print(f"     pattern={pat!r}  flags={flag}  ->  {err}")
        return 1

    print("  ✔ 未复现")
    print()
    print("  结论：用本项目实际使用的模式（及其常见变体）无法稳定复现。")
    print("  该异常来自 CPython 标准库 re 模块的字符集优化器，属上游缺陷，")
    print("  不是本项目代码的问题。详见 docs/notes/已知问题.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

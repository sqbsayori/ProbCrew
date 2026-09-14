#!/usr/bin/env python
"""Windows 控制台编码兜底 —— 让脚本里的 ✔ / → / ⚠ 不炸。

为什么需要
----------
中文 Windows 的默认控制台编码是 GBK，Python 的 `sys.stdout` 会跟着用 GBK。
一旦脚本打印 `✔`(U+2714)、`→`(U+2192) 这类字符，就抛：

    UnicodeEncodeError: 'gbk' codec can't encode character '\\u2714'

这个错误**只在本地出现**：CI 跑在 ubuntu-latest，默认 UTF-8，所以 CI 永远是绿的，
本地却会在跑完一半时崩掉 —— 新人第一天就会踩，且很容易误判成"代码有问题"。

用法
----
    from _console import utf8_output
    utf8_output()          # 在脚本入口尽早调用（import 之后、第一个 print 之前）

说明
----
- 只改**输出编码**，不改文件读写编码，也不改任何业务逻辑。
- `errors="replace"`：万一终端连替换字符都放不下，也不会再抛异常。
- 终端不支持 `reconfigure`（被重定向到非文本流）时静默跳过。
"""
from __future__ import annotations

import sys


def utf8_output() -> None:
    """把 stdout / stderr 切成 UTF-8（不可用时静默跳过）。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # 流已被关闭或不支持切换编码 —— 不值得为一个日志字符中断脚本
            continue

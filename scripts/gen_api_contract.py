#!/usr/bin/env python
"""从 FastAPI 应用生成 HTTP API 契约（contracts/api.md）。

为什么自动生成
-------------
手写的 API 文档一定会过期 —— 这是软件工程里最确定的规律之一。
本脚本直接从运行中的 FastAPI 应用读取 OpenAPI，渲染成人类可读的 Markdown。

`scripts/check_contracts.py` 会比对「重新生成的」与「仓库里的」是否一致，
不一致就报错 —— 于是"忘了更新文档"变成 CI 里的红灯。

用法
----
    python scripts/gen_api_contract.py            # 写入 contracts/api.md
    python scripts/gen_api_contract.py --stdout    # 打印到屏幕（不写文件）
"""
from __future__ import annotations

from _console import utf8_output

utf8_output()

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "contracts" / "api.md"
sys.path.insert(0, str(ROOT / "backend"))

# 生成文档不该花钱、不该联网 —— 强制 mock
os.environ.setdefault("LLM_PROVIDER", "mock")

#: 分组标题。按路径前缀归类，让文档读起来像"模块清单"而不是"一堆端点"。
GROUPS: list[tuple[str, str]] = [
    ("/api/chat", "对话与编排"),
    ("/api/hitl", "人机协同（HITL）"),
    ("/api/runs", "运行轨迹"),
    ("/api/knowledge", "知识库"),
    ("/api/problems", "题库与例题"),
    ("/api/distributions", "分布计算"),
    ("/api/animations", "交互动画"),
    ("/api/raw-live", "原始动画注入"),
    ("/api/agents", "Agent 目录"),
    ("/api/tools", "工具目录"),
    ("/api/health", "系统"),
    ("/api/stats", "学习统计"),
]

HEADER = """# contracts/api.md · HTTP API 契约

> **本文件由 `scripts/gen_api_contract.py` 自动生成，请勿手工编辑。**
> 修改 API 后运行 `python scripts/gen_api_contract.py` 重新生成。
> `scripts/check_contracts.py` 会校验本文件与实现是否一致。

## 约定

| 项 | 约定 |
|----|------|
| 基础路径 | 无前缀，直接挂在根上（`/api/...`） |
| 编码 | 请求与响应统一 UTF-8；中文不转义 |
| 内容类型 | `application/json`；流式端点为 `text/event-stream` |
| 错误格式 | FastAPI 默认：`{"detail": "..."}`；校验失败为 422 |
| 流式协议 | 见 `contracts/events.schema.json`（SSE 每帧 `data: <json>`） |
| 版本策略 | 只增不改；破坏性变更走 ADR（见 `contracts/README.md`） |

## 端点总览

"""


def group_of(path: str) -> str:
    for prefix, title in GROUPS:
        if path.startswith(prefix):
            return title
    return "其他"


def render() -> str:
    from app.main import build_app

    app = build_app()
    spec = app.openapi()
    paths = spec.get("paths", {})

    buckets: dict[str, list[tuple[str, str, dict]]] = {}
    order: list[str] = []
    for path, methods in paths.items():
        for method, op in methods.items():
            g = group_of(path)
            if g not in buckets:
                buckets[g] = []
                order.append(g)
            buckets[g].append((path, method.upper(), op))

    lines: list[str] = [HEADER]

    # 总览表
    lines.append("| 方法 | 路径 | 说明 |")
    lines.append("|------|------|------|")
    for g in order:
        for path, method, op in sorted(buckets[g], key=lambda x: (x[0], x[1])):
            summary = (op.get("summary") or "").replace("|", "\\|")
            lines.append(f"| `{method}` | `{path}` | {summary} |")
    lines.append("")

    # 分组明细
    for g in order:
        lines.append(f"## {g}")
        lines.append("")
        for path, method, op in sorted(buckets[g], key=lambda x: (x[0], x[1])):
            lines.append(f"### `{method} {path}`")
            lines.append("")
            if op.get("summary"):
                lines.append(f"**{op['summary']}**")
                lines.append("")
            if op.get("description"):
                lines.append(op["description"].strip())
                lines.append("")

            # 请求体
            body = op.get("requestBody")
            if body:
                content = (body.get("content") or {}).get("application/json") or {}
                ref = content.get("schema", {}).get("$ref", "")
                name = ref.rsplit("/", 1)[-1] if ref else ""
                lines.append(f"请求体：`{name or '(inline)'}`" + ("（必填）" if body.get("required") else "（可选）"))
                if name and name in spec.get("components", {}).get("schemas", {}):
                    schema = spec["components"]["schemas"][name]
                    props = schema.get("properties") or {}
                    required = set(schema.get("required") or [])
                    if props:
                        lines.append("")
                        lines.append("| 字段 | 类型 | 必填 | 说明 |")
                        lines.append("|------|------|------|------|")
                        for fname, fschema in props.items():
                            ftype = fschema.get("type") or fschema.get("anyOf") or "?"
                            if isinstance(ftype, list):
                                ftype = " / ".join(
                                    (x.get("type") if isinstance(x, dict) else str(x)) for x in ftype
                                )
                            desc = (fschema.get("description") or "").replace("|", "\\|").replace("\n", " ")
                            lines.append(
                                f"| `{fname}` | `{ftype}` | {'✓' if fname in required else ''} | {desc} |"
                            )
                lines.append("")

            # 响应
            responses = op.get("responses") or {}
            if responses:
                codes = ", ".join(f"`{c}`" for c in sorted(responses))
                lines.append(f"响应：{codes}")
                lines.append("")

    lines.append("---")
    lines.append("")
    # 注意：这里**刻意不写生成时间**。
    # 写了时间戳的话每次生成结果都不同，check_contracts.py 的"新鲜度比对"
    # 就永远失败 —— 那种检查等于没有。"什么时候生成的"由 git 历史回答。
    lines.append(
        f"*共 {len(paths)} 条路径 · "
        f"{sum(len(v) for v in paths.values())} 个端点*"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdout", action="store_true", help="打印到屏幕，不写文件")
    args = ap.parse_args()

    content = render()

    if args.stdout:
        print(content)
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" 保证跨平台一致，否则 Windows 生成 CRLF、Linux 生成 LF，
    # check_contracts.py 会误报"文件过期"
    OUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"✔ 已生成 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

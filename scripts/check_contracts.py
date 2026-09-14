#!/usr/bin/env python
"""契约校验 —— 让「契约 ↔ 实现一致」不靠自觉。

跑什么
------
1. **schema 自洽**：JSON 合法、符合 Draft-07 元 schema、$ref 能解析
2. **示例有效**：每份 schema 里的 examples 必须能通过它自己的校验
   （根级 examples 对自己的根；definitions 下的 examples 对各自的 definition）
3. **事件枚举一致**：`events.py::EventType` 与 `events.schema.json` 逐项比对
4. **Agent / 工具规格一致**：运行时发现的每个 AgentSpec / ToolSpec
   必须符合 `agent.schema.json` / `tool.schema.json`

为什么必须自动化
---------------
契约腐化的典型方式是「加了个字段，忘了改 schema」——
这种错误不会报错，只会在几周后以"前端说字段不对"的形式爆发。
本脚本把它变成 CI 里的红灯。

用法
----
    python scripts/check_contracts.py
    python scripts/check_contracts.py --quiet     # 只输出失败项

依赖
----
    pip install -r requirements-dev.txt   （需要 jsonschema）
    未安装时前三项仍会执行，第 2 项会跳过并提示。
"""
from __future__ import annotations

from _console import utf8_output

utf8_output()

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
sys.path.insert(0, str(ROOT / "backend"))

PASS, FAIL, SKIP = "✔", "✘", "○"
results: list[tuple[bool, str, str]] = []
quiet = False


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((ok, name, detail))
    if not quiet or not ok:
        print(f"  {PASS if ok else FAIL} {name}" + (f"  — {detail}" if detail else ""))
    return ok


def skip(name: str, detail: str = "") -> None:
    print(f"  {SKIP} {name}  — {detail}")


def section(title: str) -> None:
    if not quiet:
        print(f"\n=== {title} ===")


# ---------------------------------------------------------------------------
# 1. schema 自洽
# ---------------------------------------------------------------------------


def load_schemas() -> dict[str, dict]:
    schemas: dict[str, dict] = {}
    for path in sorted(CONTRACTS.glob("*.schema.json")):
        try:
            schemas[path.name] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            check(False, f"{path.name} 是合法 JSON", str(exc))
    return schemas


def check_meta(schemas: dict[str, dict]) -> object:
    """用 Draft-07 元 schema 校验每份 schema。返回 Draft7Validator 类（或 None）。"""
    try:
        from jsonschema import Draft7Validator
    except ImportError:
        skip("Draft-07 元校验与示例校验", "未安装 jsonschema，请 pip install -r requirements-dev.txt")
        return None

    for name, schema in schemas.items():
        try:
            Draft7Validator.check_schema(schema)
            check(True, f"{name} 符合 Draft-07")
        except Exception as exc:  # noqa: BLE001
            check(False, f"{name} 符合 Draft-07", str(exc)[:160])
    return Draft7Validator


# ---------------------------------------------------------------------------
# 2. 示例有效
# ---------------------------------------------------------------------------


def check_examples(schemas: dict[str, dict], validator_cls: object) -> None:
    if validator_cls is None:
        return
    total = 0
    bad = 0
    for name, schema in schemas.items():
        targets: list[tuple[str, dict, list]] = []

        # 根级 examples 对根 schema
        if schema.get("examples"):
            targets.append((f"{name} 根示例", schema, schema["examples"]))

        # definitions 下的 examples 对各自的 definition
        for def_name, def_schema in (schema.get("definitions") or {}).items():
            if isinstance(def_schema, dict) and def_schema.get("examples"):
                # 关键：单独拿一个 definition 当根 schema 时，它内部的
                # `$ref: #/definitions/X` 会断链（新根的 definitions 是空的）。
                # 所以要把父级的 definitions 一起带上，让引用仍能解析。
                wrapper = {
                    "$schema": schema.get("$schema"),
                    "definitions": schema.get("definitions", {}),
                }
                wrapper.update(def_schema)
                targets.append((f"{name}#{def_name} 示例", wrapper, def_schema["examples"]))

        for label, target_schema, examples in targets:
            v = validator_cls(target_schema)
            for i, ex in enumerate(examples):
                total += 1
                errors = sorted(v.iter_errors(ex), key=lambda e: e.path)
                if errors:
                    bad += 1
                    first = errors[0]
                    loc = "/".join(str(p) for p in first.path) or "(根)"
                    check(
                        False,
                        f"{label}[{i}] 通过校验",
                        f"字段 {loc}: {first.message[:120]}",
                    )
                else:
                    check(True, f"{label}[{i}] 通过校验")

        # 校验器能解析所有 $ref（悬空引用会在实例化时报错）
        try:
            validator_cls(schema)
        except Exception as exc:  # noqa: BLE001
            check(False, f"{name} 的 $ref 可解析", str(exc)[:160])

    if total:
        check(bad == 0, f"全部 {total} 个示例有效", "" if bad == 0 else f"{bad} 个失败")


# ---------------------------------------------------------------------------
# 3. 事件枚举一致
# ---------------------------------------------------------------------------


def check_event_enum(schemas: dict[str, dict]) -> None:
    schema = schemas.get("events.schema.json")
    if not schema:
        check(False, "events.schema.json 存在")
        return
    try:
        allowed = set(schema["properties"]["type"]["enum"])
    except KeyError:
        check(False, "events.schema.json 有 type.enum")
        return

    try:
        from app.kernel import events as E
    except Exception as exc:  # noqa: BLE001
        check(False, "能导入 app.kernel.events", str(exc)[:160])
        return

    declared = set(getattr(E.EventType, "__args__", ()))
    check(
        declared == allowed,
        "EventType 与 events.schema.json 枚举一致",
        "" if declared == allowed else f"仅在代码：{declared - allowed}  仅在契约：{allowed - declared}",
    )

    # 便捷构造器覆盖检查：每个事件类型都应有构造器（避免手拼 JSON）
    #
    # 注意：函数名**由事件类型动态派生**（`tool.result` → `tool_result`），
    # 不再硬编码清单 —— 硬编码会漏项，而漏项时这条检查会**假绿**：
    # 曾经它只列了 13 项、漏掉 `hitl.resolved`，于是 14 种事件里缺一个构造器也照样报"全部通过"。
    expected = {event_type: event_type.replace(".", "_") for event_type in sorted(allowed)}
    missing = {
        event_type: fn
        for event_type, fn in expected.items()
        if not callable(getattr(E, fn, None))
    }
    check(
        not missing,
        "每种事件都有便捷构造器",
        "; ".join(f"{t} → 缺 {fn}()" for t, fn in sorted(missing.items())) if missing else "",
    )


# ---------------------------------------------------------------------------
# 4. Agent / 工具规格一致
# ---------------------------------------------------------------------------


def check_registries(schemas: dict[str, dict], validator_cls: object) -> None:
    if validator_cls is None:
        return
    try:
        from app.main import build_app
    except Exception as exc:  # noqa: BLE001
        check(False, "能装配 FastAPI 应用（用于取注册表）", str(exc)[:160])
        return

    import os

    os.environ.setdefault("LLM_PROVIDER", "mock")  # 校验不该花钱、不该联网
    app = build_app()

    # --- Agent ---
    spec_schema = (schemas.get("agent.schema.json") or {}).get("definitions", {}).get("agentSpec")
    if spec_schema:
        v = validator_cls(spec_schema)
        bad = []
        for item in app.state.agents.describe():
            errors = list(v.iter_errors(item))
            if errors:
                loc = "/".join(str(p) for p in errors[0].path) or "(根)"
                bad.append(f"{item.get('id')}: {loc} {errors[0].message[:80]}")
        check(not bad, f"{len(app.state.agents.all())} 个 AgentSpec 符合契约", "; ".join(bad)[:200])

    # --- Tool ---
    tool_schema = (schemas.get("tool.schema.json") or {}).get("definitions", {}).get("toolSpec")
    if tool_schema:
        v = validator_cls(tool_schema)
        bad = []
        for item in app.state.tools.describe():
            errors = list(v.iter_errors(item))
            if errors:
                loc = "/".join(str(p) for p in errors[0].path) or "(根)"
                bad.append(f"{item.get('id')}: {loc} {errors[0].message[:80]}")
        check(not bad, f"{len(app.state.tools.all())} 个 ToolSpec 符合契约", "; ".join(bad)[:200])

    # --- 角色门控：Agent 声明的工具必须真实存在（契约里的 tools 字段是强约束）---
    tool_ids = {t.id for t in app.state.tools.all()}
    dangling = [
        f"{e.spec.id}->{t}"
        for e in app.state.agents.all()
        for t in e.spec.tools
        if t not in tool_ids
    ]
    check(not dangling, "Agent 声明的工具都真实存在", f"悬空：{dangling}" if dangling else "")


# ---------------------------------------------------------------------------
# 5. api.md 新鲜度
# ---------------------------------------------------------------------------


def check_api_contract() -> None:
    api_md = CONTRACTS / "api.md"
    if not api_md.exists():
        check(False, "contracts/api.md 存在", "运行 python scripts/gen_api_contract.py 生成")
        return
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from gen_api_contract import render  # type: ignore

        expected = render()
        actual = api_md.read_text(encoding="utf-8")
        check(
            expected == actual,
            "contracts/api.md 与当前实现一致",
            "" if expected == actual else "已过期，运行 python scripts/gen_api_contract.py 重新生成",
        )
    except Exception as exc:  # noqa: BLE001
        skip("api.md 新鲜度", f"无法比对：{str(exc)[:120]}")


# ---------------------------------------------------------------------------
# 6. 部署无关化（前端不许写死后端地址）
# ---------------------------------------------------------------------------


def check_deployment_agnostic() -> None:
    """守住「换服务器不用改源码」（docs/13 §2.2 / 任务 3）。

    这里校验的是**交付层**：油猴脚本、loader、SPA 的 api 客户端。
    它们一旦写死 `http://某台机器:8000`，部署到服务器后每个学生都得改源码重装，
    而这个错误在本地**永远测不出来**（本地恰好就是那个地址）。
    """
    import re

    targets = [
        ROOT / "frontend" / "widget" / "probstat-assistant.user.js",
        ROOT / "frontend" / "widget" / "loader.js",
        ROOT / "frontend" / "app" / "core" / "api.js",
    ]
    missing = [str(p.relative_to(ROOT)) for p in targets if not p.exists()]
    if missing:
        check(False, "交付层文件齐全", f"缺失：{missing}")
        return

    # 油猴脚本另有一份更细的检查（配置块留空、@require 相对路径）
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from build_userscript import check_source  # type: ignore

        problems = check_source(targets[0].read_text(encoding="utf-8"))
        check(not problems, "油猴脚本不含写死的后端地址", "; ".join(problems)[:200])
    except Exception as exc:  # noqa: BLE001
        skip("油猴脚本地址检查", f"无法执行：{str(exc)[:120]}")

    bad: list[str] = []
    for path in targets[1:]:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
                continue
            if re.search(r"https?://\d{1,3}(\.\d{1,3}){3}|https?://localhost", line, re.I):
                bad.append(f"{path.relative_to(ROOT)}:{lineno}")
    check(not bad, "loader / SPA 客户端不含写死的后端地址", ", ".join(bad)[:200])


# ---------------------------------------------------------------------------


def main() -> int:
    global quiet
    ap = argparse.ArgumentParser(description="契约校验")
    ap.add_argument("--quiet", action="store_true", help="只输出失败项")
    args = ap.parse_args()
    quiet = args.quiet

    if not quiet:
        print("=" * 66)
        print("  ProbCrew 契约校验")
        print("=" * 66)

    section("1. schema 自洽")
    schemas = load_schemas()
    check(bool(schemas), f"发现 {len(schemas)} 份 schema", ", ".join(sorted(schemas)))
    validator_cls = check_meta(schemas)

    section("2. 示例有效性")
    check_examples(schemas, validator_cls)

    section("3. 事件枚举与构造器")
    check_event_enum(schemas)

    section("4. Agent / 工具规格一致")
    check_registries(schemas, validator_cls)

    section("5. API 契约新鲜度")
    check_api_contract()

    section("6. 部署无关化（前端不许写死后端地址）")
    check_deployment_agnostic()

    failed = [r for r in results if not r[0]]
    print()
    if failed:
        print("=" * 66)
        print(f"  {FAIL} {len(failed)}/{len(results)} 项失败：")
        for _, name, detail in failed:
            print(f"     {name}" + (f"  — {detail}" if detail else ""))
        print("=" * 66)
        print("\n  契约与实现不一致时，**不要改契约去迁就代码**，先想清楚哪个是对的。")
        print("  破坏性变更需要 ADR，见 contracts/README.md 第三节。")
        return 1
    print("=" * 66)
    print(f"  {PASS} 全部通过（{len(results)} 项）")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

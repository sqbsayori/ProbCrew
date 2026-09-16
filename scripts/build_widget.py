#!/usr/bin/env python
"""把 `frontend/shared/`（ESM）拼成悬浮窗能用的**经典脚本产物**。

为什么需要它（`docs/23` §四）
----------------------------
共享内核是 ESM，而悬浮窗必须是经典脚本 —— 因为油猴 `@require` 只吃经典脚本，
而它"安装期抓取、运行时不受目标站点 CSP 限制"的能力，是我们能在第三方课程平台上工作的前提。
于是：**一份源码（shared/）+ 一次确定性拼接（本脚本）**，而不是两份实现。

产物（都提交进仓库，CI 用 `--check` 校验新鲜度 —— 与 gen_api_contract / gen_registry 同一套做法）
    frontend/widget/_shared.js      经典脚本包，挂到 window.__PSA.shared
    frontend/widget/_modules.json   模块加载清单（loader.js 与油猴 @require 共用）

严格到什么程度
--------------
拼接器是手写的，所以它**只接受它看得懂的输入**，遇到任何不确定的写法直接报错退出，
绝不产出一个"看起来能跑"的半成品：
  · 只允许相对导入（`./x.js`）与具名导出
  · 禁止 default export、禁止顶层 await、禁止循环依赖
  · 禁止在 shared/ 里触碰 document / window / localStorage / fetch / location
    （`globalThis` 允许 —— 仅用于读取注入进来的渲染引擎）
  · 禁止跨模块的重名顶层声明（拼接后会互相覆盖）

用法
----
    python scripts/build_widget.py            # 生成
    python scripts/build_widget.py --check    # 只校验产物是否过期（CI 用）
"""
from __future__ import annotations

from _console import utf8_output

utf8_output()

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "frontend" / "shared"
OUT_BUNDLE = ROOT / "frontend" / "widget" / "_shared.js"
OUT_MANIFEST = ROOT / "frontend" / "widget" / "_modules.json"

#: 悬浮窗的模块清单。`_shared.js` 永远排第一（后面的模块要用 __PSA.shared）。
#: UI = 顶层页面需要的全部；FRAME = iframe 里那点最小集合（省内存）。
MODULES_UI = [
    "/widget/_shared.js",
    "/widget/api.js",
    "/widget/pet.js",
    "/widget/render.js",
    "/widget/anim-bridge.js",
    "/widget/extractor.js",
    "/widget/frames.js",
    "/widget/assistant.js",
]
MODULES_FRAME = [
    "/widget/_shared.js",
    "/widget/render.js",
    "/widget/anim-bridge.js",
    "/widget/extractor.js",
    "/widget/frames.js",
]

#: 共享内核里禁止出现的东西（R2：纯逻辑，环境能力靠注入）
FORBIDDEN = {
    r"\bdocument\b": "触碰了 document —— shared/ 必须保持纯逻辑，DOM 操作放调用方",
    r"\bwindow\b": "触碰了 window —— 同上（需要全局能力时由调用方注入）",
    r"\blocalStorage\b": "触碰了 localStorage —— 存储由调用方负责",
    r"\bfetch\s*\(": "直接调用了 fetch —— 请用 createRequester 注入",
    r"\blocation\b": "触碰了 location —— 地址解析由调用方负责",
}

IMPORT_RE = re.compile(r"^\s*import\s+([^;]+?)\s+from\s+['\"]([^'\"]+)['\"]\s*;?\s*$", re.M)
EXPORT_DECL_RE = re.compile(r"^(\s*)export\s+(?=(const|let|var|function|async function|class)\b)", re.M)
EXPORT_LIST_RE = re.compile(r"^\s*export\s*\{[^}]*\}\s*;?\s*$", re.M)
TOPLEVEL_DECL_RE = re.compile(r"^(?:const|let|var|function|async function|class)\s+([A-Za-z_$][\w$]*)", re.M)
#: `export const x = 1` / `export function f(){}` —— 取被导出的名字
EXPORT_NAMED_RE = re.compile(
    r"^\s*export\s+(?:async\s+)?(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)", re.M
)
#: `export { a, b as c }` —— 取花括号里的名字
EXPORT_BRACE_RE = re.compile(r"^\s*export\s*\{([^}]*)\}\s*;?\s*$", re.M)


def _strip_comments(text: str) -> str:
    """粗略剥掉块注释与行注释（只用于违禁用法扫描，不用于产物输出）。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    text = re.sub(r"\s//\s.*$", "", text, flags=re.M)
    return text


class BuildError(RuntimeError):
    pass


def read_modules() -> dict[str, dict]:
    """读出 shared/ 下所有模块：正文、相对依赖、导出名、顶层声明名。"""
    mods: dict[str, dict] = {}
    for path in sorted(SHARED.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        deps = []
        for _clause, target in IMPORT_RE.findall(text):
            if not target.startswith("./"):
                raise BuildError(f"{path.name}: 只允许相对导入，发现 {target!r}")
            deps.append(target[2:])
        if "export default" in text:
            raise BuildError(f"{path.name}: 禁止 default export（拼接后无法可靠区分命名空间）")
        if re.search(r"^\s*await\s", text, re.M) and "async function" not in text:
            raise BuildError(f"{path.name}: 疑似顶层 await —— shared/ 必须是可同步拼接的模块")
        # 先在**去掉注释**的副本上查违禁用法：注释里会正当地提到这些词
        # （比如"本文件不碰 document/window"这种说明），不剥掉就会误报。
        code = _strip_comments(text)
        for pattern, why in FORBIDDEN.items():
            if re.search(pattern, code):
                raise BuildError(f"{path.name}: {why}")
        decls = TOPLEVEL_DECL_RE.findall(EXPORT_DECL_RE.sub(r"\1", text))
        # 导出名：ESM 的 export 被去掉之后，必须显式挂到 shared 对象上，否则产物是空壳
        exports = EXPORT_NAMED_RE.findall(text)
        for block in EXPORT_BRACE_RE.findall(text):
            for item in block.split(","):
                piece = item.strip()
                if not piece:
                    continue
                # `a as b` → 对外名字是 b
                name = piece.split(" as ")[-1].strip() if " as " in piece else piece
                exports.append(name)
        mods[path.name] = {
            "path": path, "text": text, "deps": deps, "decls": decls, "exports": exports,
        }
    return mods


def topo_order(mods: dict[str, dict]) -> list[str]:
    """依赖优先的拓扑序；有环就报错（拼接后环无法表达）。"""
    order: list[str] = []
    state: dict[str, int] = {}  # 0=未访问 1=在栈上 2=完成

    def visit(name: str, stack: list[str]) -> None:
        if name not in mods:
            raise BuildError(f"导入了不存在的模块：{name}")
        if state.get(name) == 2:
            return
        if state.get(name) == 1:
            raise BuildError("发现循环依赖：" + " → ".join([*stack, name]))
        state[name] = 1
        for dep in mods[name]["deps"]:
            visit(dep, [*stack, name])
        state[name] = 2
        order.append(name)

    for name in mods:
        visit(name, [])
    return order


def strip_module_syntax(text: str) -> str:
    """去掉 import 与 export 关键字，其余原样保留（包括注释 —— 它们是文档）。"""
    text = IMPORT_RE.sub("", text)
    text = EXPORT_LIST_RE.sub("", text)
    text = EXPORT_DECL_RE.sub(r"\1", text)
    return text.strip("\n")


def bundle(mods: dict[str, dict]) -> str:
    order = topo_order(mods)

    # 跨模块重名检查：拼接后同名会互相覆盖，必须提前拦住
    seen: dict[str, str] = {}
    for name in order:
        for decl in mods[name]["decls"]:
            if decl in seen:
                raise BuildError(
                    f"顶层声明重名：`{decl}` 同时出现在 {seen[decl]} 与 {name} —— "
                    "拼接后会互相覆盖，请改名"
                )
            seen[decl] = name

    parts = [
        "/**",
        " * 共享内核（经典脚本产物）—— **本文件由 `scripts/build_widget.py` 自动生成，请勿手工编辑。**",
        " *",
        " * 源码：`frontend/shared/*.js`（ESM，主站直接 import 那一份）。",
        " * 为什么有这份产物：油猴 `@require` 只吃经典脚本，而它安装期抓取、运行时不受目标站点",
        " * CSP 限制 —— 那是悬浮窗能在第三方课程平台上工作的前提（见 docs/23 §1.1）。",
        " *",
        " * 模块顺序（依赖优先）：" + " → ".join(order),
        " */",
        "(function (global) {",
        "  'use strict';",
        "  var shared = {};",
        "",
    ]
    for name in order:
        parts.append(f"  /* ===== shared/{name} ===== */")
        body = strip_module_syntax(mods[name]["text"])
        parts.extend("  " + line if line else "" for line in body.split("\n"))
        for export in mods[name]["exports"]:
            parts.append(f"  shared.{export} = {export};")
        parts.append("")
    parts.append("  global.__PSA = global.__PSA || {};")
    parts.append("  global.__PSA.shared = shared;")
    parts.append("})(typeof window !== 'undefined' ? window : globalThis);")
    parts.append("")
    return "\n".join(parts)


def manifest() -> str:
    return json.dumps(
        {
            "_generated_by": "scripts/build_widget.py",
            "_note": "模块加载清单。loader.js 与油猴脚本的 @require 都以它为准（CI 会校验一致性）。",
            "shared": "/widget/_shared.js",
            "ui": MODULES_UI,
            "frame": MODULES_FRAME,
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="把 frontend/shared/ 拼成悬浮窗的经典脚本产物")
    ap.add_argument("--check", action="store_true", help="只校验产物是否过期")
    args = ap.parse_args()

    try:
        mods = read_modules()
        content = bundle(mods)
    except BuildError as exc:
        print(f"✘ 生成失败：{exc}")
        return 1

    man = manifest()
    if args.check:
        stale = []
        if not OUT_BUNDLE.exists() or OUT_BUNDLE.read_text(encoding="utf-8") != content:
            stale.append(OUT_BUNDLE.relative_to(ROOT))
        if not OUT_MANIFEST.exists() or OUT_MANIFEST.read_text(encoding="utf-8") != man:
            stale.append(OUT_MANIFEST.relative_to(ROOT))
        if stale:
            print("✘ 悬浮窗共享产物已过期：" + "、".join(str(s) for s in stale))
            print("  跑一次：python scripts/build_widget.py")
            return 1
        # 结构性断言：同一件事不许在 widget 里再出现第二份实现。
        # 这是"统一技术栈"从"说过了"变成"守得住"的那道闸（docs/23 §七）。
        dupes = []
        for path in sorted((ROOT / "frontend" / "widget").glob("*.js")):
            if path.name.startswith("_"):
                continue  # _shared.js 就是产物本身，跳过
            body = _strip_comments(path.read_text(encoding="utf-8"))
            # 按"实现特征"判断，而不是按函数名 —— 适配层里可以有
            # `function consumeSSE(...)` 这种**转发**壳（3 行），那不算重复实现。
            for marker, where in (
                (r"indexOf\('\\n\\n'\)", "SSE 帧解析"),
                ("isTableSep", "Markdown 表格解析"),
                ("function normalizeMath", "公式定界符归一化"),
                ('<table class="data">', "Markdown 输出"),
            ):
                if re.search(marker, body):
                    dupes.append(f"{path.name} 里还有第二份{where} —— 应改用 __PSA.shared")
        if dupes:
            print("✘ 仍有重复实现：")
            for d in dupes:
                print(f"   · {d}")
            return 1

        print(f"✔ 产物新鲜（{len(mods)} 个共享模块，{len(content.splitlines())} 行）")
        print("✔ 悬浮窗内无重复实现（SSE / 公式归一化 / Markdown 都只有共享内核一份）")
        return 0

    OUT_BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    OUT_BUNDLE.write_text(content, encoding="utf-8")
    OUT_MANIFEST.write_text(man, encoding="utf-8")
    print(f"✔ 已生成 {OUT_BUNDLE.relative_to(ROOT)}（{len(content.splitlines())} 行）")
    print(f"✔ 已生成 {OUT_MANIFEST.relative_to(ROOT)}（UI {len(MODULES_UI)} 个 / FRAME {len(MODULES_FRAME)} 个）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

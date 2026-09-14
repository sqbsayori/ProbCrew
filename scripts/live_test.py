#!/usr/bin/env python
"""真模型端到端联调（页面伴学）。

用途：服务起来之后，验证"页宠上报的跨 frame 上下文"能否驱动真模型正确作答。
同时检查 LaTeX 定界符是否规范（`$...$` / `$$...$$`，不出现 `\\(...\\)` / `\\[...\\]`）。

用法：
    python scripts/live_test.py                 # 默认 http://127.0.0.1:8000
    python scripts/live_test.py --base http://127.0.0.1:8011
"""
from __future__ import annotations

from _console import utf8_output

utf8_output()

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = chr(36)  # 避免在源码里写死美元符号造成转义混乱

# 模拟页宠在真实课程页上抽取、并经 postMessage 汇总后的上报内容
PAGE = {
    "source": "userscript",
    "selection": "贝叶斯公式则是在已知结果 B 已发生的条件下，反过来推断某个成因 A_i 的概率。",
    "frames": [
        {  # 顶层：只有导航，内容很少
            "url": "https://mooc.example.edu/course/1",
            "title": "课程学习页",
            "text": "首页 课程 我的 学习进度 62% 上一节 下一节",
            "headings": [{"level": 1, "text": "课程导航"}],
        },
        {  # 课件 iframe：正文在这里
            "url": "https://mooc.example.edu/courseware/ch1-4.html",
            "title": "1.4 全概率公式与贝叶斯公式",
            "headings": [
                {"level": 1, "text": "1.4 全概率公式与贝叶斯公式"},
                {"level": 2, "text": "一、完备事件组"},
                {"level": 2, "text": "二、全概率公式"},
                {"level": 2, "text": "三、贝叶斯公式"},
                {"level": 2, "text": "四、例题：三条生产线"},
            ],
            "text": (
                "完备事件组：A1..An 两两互不相容，并集为样本空间 Ω，且每个概率大于零。"
                "全概率公式把结果 B 的概率按成因分解：P(B)=Σ P(Ai)P(B|Ai)。"
                "贝叶斯公式则是在已知结果 B 已发生的条件下，反过来推断某个成因 Ai 的概率："
                "P(Ai|B)=P(Ai)P(B|Ai)/Σj P(Aj)P(B|Aj)，分子是先验×似然，分母就是全概率公式。"
                "例题：某工厂甲乙丙三条生产线产量占比 25%/35%/40%，次品率分别为 5%/4%/2%。"
                "任取一件是次品的概率 P(D)=0.0345；已知是次品时来自乙线的概率最大，为 28/69≈40.58%。"
            ),
            "formulas": [
                "P(B)=\\sum_{i=1}^{n}P(A_i)P(B\\mid A_i)",
                "P(A_i\\mid B)=\\frac{P(A_i)P(B\\mid A_i)}{\\sum_{j}P(A_j)P(B\\mid A_j)}",
            ],
            "media": {
                "kind": "video",
                "currentTime": 318,
                "duration": 900,
                "title": "全概率公式与贝叶斯公式",
            },
            "scroll_pct": 0.46,
        },
    ],
}


def post_sse(base: str, path: str, payload: dict, timeout: int = 180) -> list[dict]:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    events: list[dict] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body and body != "{}":
                events.append(json.loads(body))
    return events


def run_case(base: str, tag: str, query: str, page: dict | None) -> dict:
    payload: dict = {"query": query, "session_id": "live-test"}
    if page is not None:
        payload["page_context"] = page

    t0 = time.time()
    events = post_sse(base, "/api/chat/stream", payload)
    elapsed = time.time() - t0

    plan = next((e for e in events if e["type"] == "plan"), {})
    ctx = next((e for e in events if e["type"] == "context.received"), None)
    answer = next((e.get("final_answer") or "" for e in events if e["type"] == "run.end"), "")

    print("=" * 74)
    print(f"{tag}    ({elapsed:.1f}s)")
    print("=" * 74)
    print(f"  上下文 : {ctx['summary'] if ctx else '—（未上报页面）'}")
    print(f"  路由   : {plan.get('intent')} -> {[s['agent'] for s in plan.get('steps', [])]}")
    print(f"  理由   : {plan.get('reason')}")
    tools = sorted({e["tool"] for e in events if e["type"] == "tool.call"})
    print(f"  工具   : {tools}")
    print(f"  产物   : {[e['kind'] for e in events if e['type'] == 'artifact']}")

    # ---- 定界符体检 ----
    inline_open = len(re.findall(r"\\\(", answer))
    block_open = len(re.findall(r"\\\[", answer))
    good_inline = len(re.findall(r"(?<!" + re.escape(D) + r")" + re.escape(D) + r"(?!"
                                 + re.escape(D) + r")[^" + re.escape(D) + r"\n]{1,200}?"
                                 + re.escape(D) + r"(?!" + re.escape(D) + r")", answer))
    good_block = answer.count(D * 2) // 2
    print()
    print(f"  定界符 : {D}...{D} 行内 {good_inline} 个 | {D}{D}...{D}{D} 独立 {good_block} 个"
          f" | 残留 \\( {inline_open} 个 | 残留 \\[ {block_open} 个")
    if inline_open or block_open:
        print("  ⚠️ 仍有非标准定界符残留，前端会显示成源码")

    print()
    print("  回答（前 12 行）：")
    for line in answer.split("\n")[:12]:
        if line.strip():
            print("    " + line[:90])
    print()

    return {
        "tag": tag,
        "elapsed": elapsed,
        "intent": plan.get("intent"),
        "agents": [s["agent"] for s in plan.get("steps", [])],
        "answer_len": len(answer),
        "bad_delims": inline_open + block_open,
        "context_summary": ctx["summary"] if ctx else None,
    }


def animation_page_context(steps: int = 3) -> dict | None:
    """构造"悬浮窗注入在动画页面上"的上下文。

    直接读**原始动画文件**并粗剥标签，尽量贴近真实上报内容。
    找不到文件时返回 None，对应场景会自动跳过。
    """
    import re

    raw_dir = ROOT.parent.parent / "动画"
    if not raw_dir.is_dir():
        raw_dir = ROOT.parent / "动画"
    target = None
    for cand in raw_dir.glob("*贝叶斯*.html"):
        target = cand
        break
    if target is None:
        return None

    html = target.read_text(encoding="utf-8", errors="replace")
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", body)
    text = re.sub(r"\s+", " ", text).strip()[:2500]

    return {
        "source": "userscript",
        "frames": [
            {
                "url": "http://127.0.0.1:8000/raw-live/" + target.name,
                "title": "贝叶斯公式可视化动画",
                "headings": [{"level": 1, "text": "贝叶斯公式"}],
                "text": text,
                "formulas": [],
                "animation": {
                    "id": "bayes",
                    "title": "贝叶斯公式",
                    "file": target.name,
                    "concepts": ["贝叶斯公式", "先验概率", "似然", "后验概率", "条件概率"],
                    "state": f"已暂停（已单步 {steps} 次）",
                    "steps": steps,
                    "playing": False,
                },
                "scroll_pct": 0.2,
            }
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    # 健康检查
    try:
        health = json.load(urllib.request.urlopen(base + "/api/health", timeout=15))
    except Exception as exc:  # noqa: BLE001
        print(f"✘ 无法连接后端 {base}：{exc}")
        print("  请先启动：.\\scripts\\dev.ps1")
        return 2

    print("=" * 74)
    print("  概率论伴学助手 · 真模型联调")
    print("=" * 74)
    print(f"  后端      : {base}")
    print(f"  Provider  : {health['provider']['resolved']} ({health['provider']['model']})")
    print(f"  Agents    : {health['registry']['agents']}  Tools: {health['registry']['tools']}")
    print(f"  HITL      : {health['collaboration']['hitl_enabled']}")
    print()

    results = [
        run_case(base, "① 划词追问（页宠核心能力）", "这段什么意思？", PAGE),
        run_case(
            base,
            "② 页面级提问（跨 frame 汇总）",
            "这一页的例题里，为什么乙线的后验概率最大？",
            {k: v for k, v in PAGE.items() if k != "selection"},
        ),
        run_case(
            base,
            "③ 视频进度感知",
            "我学到哪了？",
            {k: v for k, v in PAGE.items() if k != "selection"},
        ),
    ]

    anim_page = animation_page_context(steps=3)
    if anim_page:
        results.append(
            run_case(
                base,
                "④ 交互动画页 + 单步并讲解",
                "我刚才把动画单步推进到了第 3 步。请告诉我：这一步在演示什么？"
                "和上一步相比发生了什么变化？为什么这个变化在概率论上是重要的？",
                anim_page,
            )
        )
    else:
        print("  （跳过动画场景：未找到原始动画文件夹）\n")

    results.append(
        run_case(base, "⑤ 无页面上下文（回归，应走教材知识库）", "什么是贝叶斯公式？", None)
    )

    print("=" * 74)
    print("  汇总")
    print("=" * 74)
    print(f"  {'场景':<34}{'意图':<20}{'耗时':>7}{'答案':>7}{'坏定界符':>9}")
    for r in results:
        print(
            f"  {r['tag']:<34}{str(r['intent']):<20}{r['elapsed']:>6.1f}s"
            f"{r['answer_len']:>6}字{r['bad_delims']:>9}"
        )

    bad = [r for r in results if r["bad_delims"]]
    wrong = []
    if results[0]["intent"] != "explain_selection":
        wrong.append("划词应路由到 explain_selection")
    if results[1]["intent"] != "explain_page":
        wrong.append("页面级提问应路由到 explain_page")
    last = results[-1]
    if last["intent"] != "knowledge":
        wrong.append("无页面上下文应回归 knowledge")
    if last["context_summary"] is not None:
        wrong.append("无页面上下文时不应发 context.received")

    print()
    if bad:
        print(f"  ⚠️ {len(bad)} 个场景存在非标准 LaTeX 定界符")
    if wrong:
        print("  ✘ 路由异常：")
        for w in wrong:
            print("     - " + w)
    if not bad and not wrong:
        print("  ✔ 全部场景通过：路由正确、无坏定界符")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

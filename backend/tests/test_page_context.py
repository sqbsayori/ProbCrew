"""页面伴学（Page Tutor）的单元测试。

这一组测试守护的是"在线课程学习助手"的核心能力：
**助手必须理解学生当前在看什么，并且把指代词正确接住。**

运行：
    cd our-system/backend
    python tests/test_page_context.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LLM_PROVIDER", "mock")


def _frame(**kw):
    from app.kernel.page_context import FrameContext

    return FrameContext(**kw)


def _sample_page():
    """模拟超星那种"顶层壳 + 课件 iframe"的结构。"""
    from app.kernel.page_context import merge_frames

    return merge_frames(
        [
            _frame(  # 顶层：只有导航，内容很少
                url="https://mooc.example.edu/course/1",
                title="课程学习页",
                text="首页 课程 我的 学习进度 62% 上一节 下一节",
                headings=[{"level": 1, "text": "导航"}],
            ),
            _frame(  # 课件 iframe：正文在这里
                url="https://mooc.example.edu/courseware/ch01-4.html",
                title="1.4 全概率公式与贝叶斯公式",
                headings=[
                    {"level": 1, "text": "1.4 全概率公式与贝叶斯公式"},
                    {"level": 2, "text": "全概率公式"},
                    {"level": 2, "text": "贝叶斯公式"},
                    {"level": 2, "text": "例题：三条生产线"},
                ],
                text=(
                    "设 B1,B2,...,Bn 为完备事件组，即两两互斥且并为样本空间。"
                    "则对任意事件 A，有全概率公式 P(A)=ΣP(Bi)P(A|Bi)。"
                    "贝叶斯公式则是在已知 A 发生的条件下反推原因 Bi 的概率。"
                    "$$P(B_i|A)=\\frac{P(B_i)P(A|B_i)}{\\sum_j P(B_j)P(A|B_j)}$$"
                    "例题：某工厂三条生产线产量占比 25%%/35%%/40%%，次品率分别为 5%%/4%%/2%%。"
                ),
                formulas=[
                    "P(A)=\\sum_{i=1}^{n}P(B_i)P(A\\mid B_i)",
                    "P(B_i\\mid A)=\\frac{P(B_i)P(A\\mid B_i)}{\\sum_j P(B_j)P(A\\mid B_j)}",
                ],
                media={"kind": "video", "currentTime": 318, "duration": 900, "title": "全概率公式"},
                scroll_pct=0.42,
            ),
        ],
        source="test",
    )


# --------------------------------------------------------------------------


def test_merge_frames_picks_the_richest_frame() -> None:
    """顶层只有导航，正文在 iframe —— 必须选出 iframe 那份作为主上下文。"""
    pc = _sample_page()
    assert "全概率公式" in pc.title
    assert pc.char_count > 100
    assert "完备事件组" in pc.text
    assert len(pc.frames) == 2


def test_merge_frames_uses_top_level_selection() -> None:
    """用户在任意 frame 里划词，都应被归并到主上下文。"""
    from app.kernel.page_context import merge_frames

    pc = merge_frames(
        [
            _frame(url="top", title="壳", text="导航", selection=""),
            _frame(url="inner", title="课件", text="正文" * 50, selection="全概率公式把复杂事件按原因分解"),
        ]
    )
    assert pc.has_selection
    assert "按原因分解" in pc.selection


def test_summary_line_and_outline() -> None:
    pc = _sample_page()
    line = pc.summary_line()
    assert "字" in line and "公式" in line
    assert "全概率公式" in pc.outline()


def test_to_prompt_includes_selection_and_media() -> None:
    pc = _sample_page()
    pc.selection = "这段我看不懂"
    block = pc.to_prompt()
    assert "当前选中的文字" in block
    assert "这段我看不懂" in block
    assert "视频进度" in block
    assert "318" in block


def test_from_payload_tolerates_garbage() -> None:
    from app.kernel.page_context import from_payload

    assert from_payload(None) is None
    assert from_payload({}) is None
    # 结构不对不能抛异常
    assert from_payload({"frames": ["不是字典"]}) is None
    # 简单形态要能用
    pc = from_payload({"text": "一些正文内容", "title": "标题", "selection": "选中"})
    assert pc is not None and pc.has_content and pc.has_selection


# --------------------------------------------------------------------------
# 路由：这是本功能最关键的行为
# --------------------------------------------------------------------------


def test_router_prefers_selection_explanation() -> None:
    from app.agents import _router

    pc = _sample_page()
    pc.selection = "贝叶斯公式则是在已知 A 发生的条件下反推原因"
    intent, agents, reason = _router.route("这段什么意思", pc)
    assert intent == "explain_selection"
    assert agents == ["page_tutor"]
    assert "划选" in reason


def test_router_handles_short_question_with_selection() -> None:
    """学生划完词常常只打两个字。"""
    from app.agents import _router

    pc = _sample_page()
    pc.selection = "完备事件组"
    assert _router.route("看不懂", pc)[0] == "explain_selection"
    assert _router.route("解释", pc)[0] == "explain_selection"


def test_router_routes_page_reference_to_page_tutor() -> None:
    from app.agents import _router

    pc = _sample_page()
    for q in ("这一页讲了什么", "这段推导为什么成立", "本节的例子能再讲一遍吗"):
        intent, agents, _ = _router.route(q, pc)
        assert intent == "explain_page", q
        assert agents == ["page_tutor"], q


def test_router_falls_back_to_page_tutor_when_nothing_matches() -> None:
    """在课程页上，一个没有任何特征词的问题也该由页面伴学接住。"""
    from app.agents import _router

    pc = _sample_page()
    intent, agents, _ = _router.route("嗯……那个有点绕", pc)
    assert intent == "explain_page"


def test_router_without_page_context_keeps_old_behaviour() -> None:
    """没有页面上下文时，行为必须和以前一致（不能回归）。"""
    from app.agents import _router

    assert _router.route("什么是贝叶斯公式")[0] == "knowledge"
    assert _router.route("求解这道题")[0] == "solve"
    assert _router.route("这一页讲了什么")[0] in ("knowledge", "explain_page")
    # 关键：没有页面时不应路由到 page_tutor
    assert "page_tutor" not in _router.route("这一页讲了什么")[1]


def test_solve_intent_still_wins_over_page_when_explicit() -> None:
    """学生明确贴出一道题要解，仍应走 solver —— 页面上下文不该吞掉明确意图。"""
    from app.agents import _router

    pc = _sample_page()
    intent, agents, _ = _router.route("求解：已知 P(B1)=0.5，求 P(A)", pc)
    assert "solver" in agents


# --------------------------------------------------------------------------
# 页内检索
# --------------------------------------------------------------------------


def test_page_search_finds_relevant_chunk() -> None:
    from app.tools.page_tools import search_in_page

    pc = _sample_page()
    hits = search_in_page(pc.text, "完完备事件组是什么", top_k=2)
    assert hits, "页内检索不应为空"
    assert "完备事件组" in hits[0]["content"]


def test_page_search_returns_empty_for_irrelevant_query() -> None:
    from app.tools.page_tools import search_in_page

    assert search_in_page("今天天气很好我想吃火锅", "完全无关的词组xyzzy") == []


# --------------------------------------------------------------------------
# 端到端：带页面上下文跑一次图
# --------------------------------------------------------------------------


def test_page_tutor_agent_end_to_end() -> None:
    from app.config import settings
    from app.kernel.registry import discover_agents, discover_tools
    from app.kernel.runs import RUNS
    from app.main import build_app
    from app.providers import get_provider

    app = build_app()
    assert "page_tutor" in {e.spec.id for e in app.state.agents.all()}, "page_tutor 应被自动发现"

    pc = _sample_page()
    pc.selection = "全概率公式 P(A)=ΣP(Bi)P(A|Bi)"

    run = RUNS.create("t", "这段什么意思")
    run.runtime = {
        "llm": app.state.llm,
        "tools": app.state.tools,
        "settings": app.state.settings,
        "page_context": pc,
    }

    from app.kernel import runner

    async def go():
        events = []
        async for line in runner.stream_run(
            run, app.state.graph, query="这段什么意思", session_id="t"
        ):
            import json

            events.append(json.loads(line))
        return events

    events = asyncio.run(go())
    types = [e["type"] for e in events]
    assert "context.received" in types, "应发出 context.received 事件"
    plan = next(e for e in events if e["type"] == "plan")
    assert plan["intent"] == "explain_selection"
    assert [s["agent"] for s in plan["steps"]] == ["page_tutor"]
    assert next(e for e in events if e["type"] == "run.end").get("final_answer")


def test_context_received_event_is_in_schema() -> None:
    import json

    from app.kernel import events as E

    schema_path = Path(__file__).resolve().parents[2] / "contracts" / "events.schema.json"
    allowed = set(
        json.loads(schema_path.read_text(encoding="utf-8"))["properties"]["type"]["enum"]
    )
    declared = set(E.EventType.__args__)  # type: ignore[attr-defined]
    assert declared == allowed, f"代码与契约不一致：{declared ^ allowed}"


def _run_all() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✔ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✘ {name}\n      {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✘ {name}\n      {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())

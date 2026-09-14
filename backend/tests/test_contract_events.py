"""契约一致性：**真实运行产物**必须符合契约（不只校验 schema 里内嵌的 examples）。

守护什么
--------
`scripts/check_contracts.py` 已经会校验"每份 schema 的内嵌 examples 能过自己的校验"，
但它**从不校验真实运行产物** —— 于是出现过这些它抓不到的腐化：

- 验证报告缺 `level`、每条 check 缺 `method`，还多出 `additionalProperties:false` 禁止的字段；
- `tool.result` 的 `ok` 被写死成 `True`，前端失败分支永远不触发。

这类问题的共同点是：**schema 是对的，跑出来的东西不符合它**。
所以本测试不看 examples，而是真跑一次问答、把线上会发出去的每一条事件拿去校验。

跑法
----
    python -m pytest backend/tests/test_contract_events.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
os.environ.setdefault("LLM_PROVIDER", "mock")

from _console import utf8_output  # noqa: E402

utf8_output()

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts" / "events.schema.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _run_once(query: str) -> list[dict]:
    """真跑一次问答，返回这次运行发出去的全部事件（SSE 逐条解析）。"""
    from fastapi.testclient import TestClient

    from app.main import app

    events: list[dict] = []
    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"query": query, "session_id": "contract-conformance"},
        ) as resp:
            assert resp.status_code == 200, f"问答接口未成功：{resp.status_code}"
            for line in resp.iter_lines():
                if not line:
                    continue
                text = line.decode("utf-8") if isinstance(line, bytes) else line
                if not text.startswith("data:"):
                    continue
                payload = text[len("data:") :].strip()
                if not payload or payload == "[DONE]":
                    continue
                event = json.loads(payload)
                # SSE 收尾是 `event: end` + `data: {}`（见 api/chat.py）——
                # `{}` 是终止哨兵，不是事件，不能拿去按事件 schema 校验。
                if not isinstance(event, dict) or "type" not in event:
                    continue
                events.append(event)
    return events


def test_real_event_stream_conforms_to_events_schema() -> None:
    """线上真实发出的事件，逐条必须通过 `contracts/events.schema.json`。"""
    jsonschema = __import__("jsonschema")
    schema = _load_schema()
    validator = jsonschema.Draft7Validator(schema)

    events = _run_once("什么是全概率公式？")
    assert events, "这次运行没有产生任何事件 —— 链路可能断了"

    problems: list[str] = []
    for i, event in enumerate(events):
        for err in validator.iter_errors(event):
            where = "/".join(str(p) for p in err.absolute_path) or "(根)"
            problems.append(f"#{i} {event.get('type')} @ {where}: {err.message}")

    assert not problems, "真实事件流违反 events.schema.json：\n  " + "\n  ".join(problems[:20])


def test_stream_covers_the_core_event_types() -> None:
    """普通问答（不触发 HITL）必须覆盖核心事件；缺了说明编排断了。"""
    events = _run_once("什么是全概率公式？")
    kinds = {e.get("type") for e in events}

    required = {
        "run.start",
        "agent.start",
        "agent.end",
        "tool.call",
        "tool.result",
        # 验证闭环的权威出口：A1 之前这个事件**从未发出过**（构造器零调用），
        # 前端因此没有验证级别可展示。这条断言把它钉住。
        "verification.report",
        "run.end",
    }
    missing = required - kinds
    assert not missing, f"真实事件流缺少核心事件类型：{sorted(missing)}；实际出现：{sorted(kinds)}"


def test_solve_query_pauses_for_hitl_without_run_end() -> None:
    """解题类（高风险）提问走 HITL 挂起：出现 `hitl.request`，且**不发** `run.end`。

    依据 `kernel/runner.py`：命中 HITL 时发 `PAUSE` 哨兵收尾（run 仍存活，等
    `/api/hitl/{run_id}/resolve`），`run.end` 在恢复后才发。所以这条不是"缺事件"，
    而是**正确行为** —— 把它固定下来，避免以后有人顺手改成"挂起也发 run.end"。
    """
    events = _run_once("解一下：抛两枚硬币，至少一个正面的概率")
    kinds = {e.get("type") for e in events}

    assert "hitl.request" in kinds, f"解题类提问没有触发 HITL；实际事件：{sorted(kinds)}"
    assert "run.end" not in kinds, (
        "HITL 挂起的 run 不应发 run.end（恢复后才发）；"
        f"实际事件：{sorted(kinds)}"
    )


def test_tool_result_ok_is_a_real_boolean() -> None:
    """`tool.result.ok` 必须是真实布尔值，不能是 None。

    契约 `tool.schema.json` 说明这个字段决定前端轨迹的红/绿。
    它曾经被硬编码成 True（后端），使前端失败分支永远不触发 ——
    这里只钉"它是布尔且非 None"，因为"失败时为 false"依赖 A3 任务的实现。
    """
    events = _run_once("什么是条件概率？")
    results = [e for e in events if e.get("type") == "tool.result"]
    assert results, "这次运行没有产生 tool.result 事件"

    bad = [e for e in results if not isinstance(e.get("ok"), bool)]
    assert not bad, f"tool.result.ok 不是布尔：{bad[:3]}"

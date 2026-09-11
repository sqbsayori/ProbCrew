"""学习记录工具（SQLite）。

demo 阶段用内置 sqlite3（零依赖、零运维），接口即契约：
迭代阶段换 PostgreSQL 时，**只改本文件**，Analytics Agent 不用动。

写入的两张表：
- `qa_log`：问答流水（谁在什么时候问了什么、路由到哪个 Agent）
- `mastery`：知识点掌握度（按 知识点 -> 正确率 聚合，供薄弱诊断）
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT
from ..kernel.specs import tool

DB_PATH = PROJECT_ROOT / "backend" / "data" / "learning.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS qa_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    run_id      TEXT,
    query       TEXT NOT NULL,
    intent      TEXT,
    agents      TEXT,
    answer      TEXT,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS mastery (
    session_id  TEXT NOT NULL,
    topic       TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    correct     INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (session_id, topic)
);
CREATE INDEX IF NOT EXISTS idx_qa_session ON qa_log(session_id, created_at);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


@tool(
    "log_qa",
    "记录问答",
    "把一次问答写入学习记录，用于后续的进度统计与薄弱点诊断。",
    owner="R4",
)
async def log_qa(
    *,
    ctx: Any = None,
    session_id: str,
    query: str,
    intent: str = "",
    agents: list[str] | None = None,
    answer: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO qa_log (session_id, run_id, query, intent, agents, answer, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                session_id,
                run_id,
                query,
                intent,
                json.dumps(agents or [], ensure_ascii=False),
                answer[:4000],
                time.time(),
            ),
        )
    return {"ok": True}


@tool(
    "log_mastery",
    "记录掌握度",
    "记录某知识点的作答结果，累加正确率（薄弱诊断的数据基础）。",
    owner="R4",
)
async def log_mastery(
    *,
    ctx: Any = None,
    session_id: str,
    topic: str,
    correct: bool,
) -> dict[str, Any]:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO mastery (session_id, topic, attempts, correct, updated_at)"
            " VALUES (?,?,1,?,?)"
            " ON CONFLICT(session_id, topic) DO UPDATE SET"
            " attempts = attempts + 1,"
            " correct  = correct + excluded.correct,"
            " updated_at = excluded.updated_at",
            (session_id, topic, 1 if correct else 0, time.time()),
        )
    return {"ok": True}


@tool(
    "learning_stats",
    "学习统计",
    "汇总学习记录：问答总数、最近记录、各知识点薄弱排序（简易诊断，不做级联定位）。",
    owner="R4",
)
async def learning_stats(*, ctx: Any = None, session_id: str, limit: int = 10) -> dict[str, Any]:
    limit = max(1, min(int(limit), 50))
    with _conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM qa_log WHERE session_id=?", (session_id,)
        ).fetchone()["c"]
        recent = conn.execute(
            "SELECT query, intent, created_at FROM qa_log WHERE session_id=?"
            " ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        mastery = conn.execute(
            "SELECT topic, attempts, correct FROM mastery WHERE session_id=?"
            " AND attempts > 0 ORDER BY CAST(correct AS REAL)/attempts ASC",
            (session_id,),
        ).fetchall()

    weak = [
        {
            "topic": row["topic"],
            "attempts": row["attempts"],
            "correct": row["correct"],
            "accuracy": round(row["correct"] / row["attempts"], 3),
        }
        for row in mastery
    ]
    return {
        "session_id": session_id,
        "total_qa": total,
        "recent": [
            {"query": r["query"], "intent": r["intent"], "at": r["created_at"]} for r in recent
        ],
        "weak_topics": weak[:5],
        "note": "demo 阶段为单点正确率排序；迭代二接入知识点依赖图后做级联定位。",
    }

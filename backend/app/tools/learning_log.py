"""学习记录工具（SQLite）—— 账号时代的**业务数据**读写。

demo 阶段用内置 sqlite3（零依赖、零运维），接口即契约：
迭代阶段换 PostgreSQL 时，**只改本文件**，Analytics Agent 不用动。

## 从"匿名 session"迁到"账号"改了什么
| | 改造前 | 现在 |
|---|---|---|
| 表名 | `qa_log` / `attempt` / `mastery` | `student_qa_log` / `student_attempt` / `student_mastery` |
| 归属 | 浏览器匿名 `session_id` | **`user_id`（账号）**；`session_id` 仍记，只作匿名追踪 |
| 掌握度主键 | `(session_id, topic)` | `(user_id, topic)` |
| 建表 | 本文件 `_SCHEMA` + 每次调用重建 | `tools/accounts.py` 统一建（一个库只能有一个建表入口） |

为什么表名必须带 `student_` 前缀：`docs/13 §1.1 约束 2` 要求"哪些表敏感"可机械判定，
导出/备份/日志脚本靠 `LIKE 'student_%'` 一次性排除全部 L2 数据。这三张表里
`student_qa_log` 存**提问原文**，是全库最敏感的一张。

⚠️ `mastery` 主键改 `(user_id, topic)` 的依据：同一个人换浏览器就是另一个 session，
按 session 聚合会把一个人的掌握度拆成几份。口径修正见 `docs/21 §5.3`。
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT
from ..kernel.specs import tool
from . import accounts

#: 保留模块级常量只为兼容旧引用（脚本里可能 import 它）；运行时一律走 accounts.db_path()。
DB_PATH = PROJECT_ROOT / "backend" / "data" / "learning.sqlite"


def _db_path() -> Path:
    """当前配置下的库文件绝对路径（改配置无需改代码）。"""
    return accounts.db_path()


def _conn():
    """连接由 `accounts.connect()` 统一提供。

    顺带解决两个老问题：① 每次调用都 `executescript` 重建表；②
    `with sqlite3.connect(...)` 是**事务**上下文而非资源上下文，连接靠引用计数释放。
    现在统一：进程内只建一次表、每调用一个连接、用完显式关闭（`closing()`）、
    并开启 WAL + busy_timeout 以扛住多线程并发写。
    """
    return accounts.connect()


@tool(
    "log_qa",
    "记录问答",
    "把一次问答写入学习记录，用于后续的进度统计与薄弱点诊断。",
    owner="R4",
)
async def log_qa(
    *,
    ctx: Any = None,
    user_id: str,
    session_id: str = "",
    query: str,
    intent: str = "",
    agents: list[str] | None = None,
    answer: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """记一次问答。`user_id` 必填 —— 统计与"我的数据"全按账号聚合。

    `session_id` 仍然记，但只作匿名追踪（同一账号换设备/换浏览器时的线索），
    **不再参与任何归属判断**。
    """
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO student_qa_log"
            " (user_id, session_id, run_id, query, intent, agents, answer, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                user_id,
                session_id,
                run_id,
                query,
                intent,
                json.dumps(agents or [], ensure_ascii=False),
                answer[:4000],
                time.time(),
            ),
        )
        conn.commit()
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
    user_id: str,
    topic: str,
    correct: bool,
    session_id: str = "",
) -> dict[str, Any]:
    """累加某知识点的作答次数与正确次数。

    口径（`docs/21 §5.3`）：进来计的 `correct` 只应是**独立答对**
    （`hint_used=0` 且答对）；提示后答对进 `attempts` 但不进 `correct`。
    判断由调用方做（见 `api/practice.py`），本函数只负责累加。
    """
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO student_mastery (user_id, topic, attempts, correct, updated_at)"
            " VALUES (?,?,1,?,?)"
            " ON CONFLICT(user_id, topic) DO UPDATE SET"
            " attempts = attempts + 1,"
            " correct  = correct + excluded.correct,"
            " updated_at = excluded.updated_at",
            (user_id, topic, 1 if correct else 0, time.time()),
        )
        conn.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# 作答记录（Attempt）—— 契约见 contracts/attempt.schema.json「记录层」
# --------------------------------------------------------------------------


def next_attempt_no(user_id: str, item_id: str) -> int:
    """**同一账号**对同一道题的第几次尝试（BKT 的学习效应靠它区分首刷/重做）。

    按账号而不是按 session 计数：否则"换个浏览器重做同一题"会被算成第一次，
    重做次数与学习效应分析全部失真。
    """
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(attempt_no), 0) AS n FROM student_attempt"
            " WHERE user_id=? AND item_id=? AND deleted=0",
            (user_id, item_id),
        ).fetchone()
    return int(row["n"] or 0) + 1


def write_attempt(
    *,
    user_id: str,
    item_id: str,
    session_id: str = "",
    student_id: str = "",
    kc_ids: list[str] | None = None,
    correct: bool,
    score: float | None = None,
    answer_raw: str = "",
    answer_normalized: str = "",
    expected: str = "",
    hint_used: int = 0,
    duration_ms: int = 0,
    attempt_no: int | None = None,
    source: str = "practice",
    grader: str = "sympy",
    grader_confidence: float | None = 1.0,
) -> dict[str, Any]:
    """写一条作答记录。**由服务端调用**（不让前端上报，防篡改/防漏记）。

    只写 `correct` 已确定的记录：解析失败 / 未作答由调用方拦掉（docs/21 §6.4 ①），
    否则会把「没看懂学生的写法」污染成「答错」，直接失真掌握度。

    `student_id` 保留是为了对齐 `contracts/attempt.schema.json` 的历史字段名，
    默认与 `user_id` 同值（该字段语义已随账号体系变成"账号 id"）。
    """
    attempt_id = f"att_{uuid.uuid4().hex[:12]}"
    no = attempt_no if attempt_no is not None else next_attempt_no(user_id, item_id)
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO student_attempt (attempt_id, user_id, student_id, item_id, session_id,"
            " kc_ids, correct, score, answer_raw, answer_normalized, expected, hint_used,"
            " duration_ms, attempt_no, source, grader, grader_confidence, created_at, deleted)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (
                attempt_id,
                user_id,
                student_id or user_id,
                item_id,
                session_id,
                json.dumps(kc_ids or [], ensure_ascii=False),
                1 if correct else 0,
                score,
                (answer_raw or "")[:500],
                (answer_normalized or "")[:500],
                (expected or "")[:500],
                int(hint_used or 0),
                int(duration_ms or 0),
                no,
                source,
                grader,
                grader_confidence,
                time.time(),
            ),
        )
        # ⚠️ 必须显式 commit：`closing()` 只负责关闭连接，不像
        # `with sqlite3.connect(...)` 那样在退出时提交事务。
        # 漏掉这一行会让作答记录**静默消失**（曾实测：批改返回 200、错题本却是空的）。
        conn.commit()
    return {"ok": True, "attempt_id": attempt_id, "attempt_no": no}


def attempts_for_user(user_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """取**一个账号**的全部作答记录（错题本 / 掌握度的唯一数据源）。

    原来的 `attempts_for_session()` 已删除：按浏览器 session 取数据在账号体系下
    就是越权读写（同一台电脑换个浏览器就等于换个人）。**身份只能来自令牌。**
    """
    limit = max(1, min(int(limit), 1000))
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM student_attempt WHERE user_id=? AND deleted=0"
            " ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        try:
            d["kc_ids"] = json.loads(d.get("kc_ids") or "[]")
        except (TypeError, ValueError):
            d["kc_ids"] = []
        d["correct"] = bool(d.get("correct"))
        out.append(d)
    return out


@tool(
    "learning_stats",
    "学习统计",
    "汇总学习记录：问答总数、最近记录、各知识点薄弱排序（简易诊断，不做级联定位）。",
    owner="R4",
)
async def learning_stats(
    *, ctx: Any = None, user_id: str, limit: int = 10, session_id: str = ""
) -> dict[str, Any]:
    """一个账号的学习统计（`/api/me/stats` 与 analytics Agent 共用）。"""
    limit = max(1, min(int(limit), 50))
    with closing(_conn()) as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM student_qa_log WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
        recent = conn.execute(
            "SELECT query, intent, created_at FROM student_qa_log WHERE user_id=?"
            " ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        mastery = conn.execute(
            "SELECT topic, attempts, correct FROM student_mastery WHERE user_id=?"
            " AND attempts > 0 ORDER BY CAST(correct AS REAL)/attempts ASC",
            (user_id,),
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
        "user_id": user_id,
        "session_id": session_id,
        "total_qa": total,
        "recent": [
            {"query": r["query"], "intent": r["intent"], "at": r["created_at"]} for r in recent
        ],
        "weak_topics": weak[:5],
        "note": "demo 阶段为单点正确率排序；迭代二接入知识点依赖图后做级联定位。",
    }

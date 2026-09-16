"""迁移脚本单元测试（匿名老表 → student_* 账号表）。

守什么
------
迁移是本轮唯一**动真实数据**的一次性动作，一旦搬漏或搬重，
学生的历史作答就永久错位。所以这里钉两件事：

1. **行数守恒**：每张表迁移前后的行数必须一致；
2. **幂等**：重复执行不会把老数据重复灌进去。

测试在临时库上跑（`tmp_path`），不碰真实数据。

运行：
    cd ProbCrew
    python -m pytest backend/tests/test_migration.py -q
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from app.config import settings  # noqa: E402
from app.tools import accounts  # noqa: E402

import migrate_to_accounts as M  # noqa: E402


def _make_legacy_db(path: Path, *, qa: int = 3, att: int = 2, mastery: int = 1) -> None:
    """造一个"改造前"的库：老表名、老列名。"""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE qa_log (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            run_id TEXT, query TEXT NOT NULL, intent TEXT, agents TEXT, answer TEXT,
            created_at REAL NOT NULL);
        CREATE TABLE mastery (session_id TEXT NOT NULL, topic TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, correct INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL, PRIMARY KEY (session_id, topic));
        CREATE TABLE attempt (attempt_id TEXT PRIMARY KEY, student_id TEXT NOT NULL,
            item_id TEXT NOT NULL, session_id TEXT, kc_ids TEXT NOT NULL DEFAULT '[]',
            correct INTEGER NOT NULL, score REAL, answer_raw TEXT, answer_normalized TEXT,
            expected TEXT, hint_used INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0, attempt_no INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'practice', grader TEXT NOT NULL DEFAULT 'sympy',
            grader_confidence REAL, created_at REAL NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
        """
    )
    for i in range(qa):
        conn.execute(
            "INSERT INTO qa_log (session_id, query, intent, created_at) VALUES (?,?,?,?)",
            (f"s{i}", f"问题 {i}", "knowledge", float(i)),
        )
    for i in range(att):
        conn.execute(
            "INSERT INTO attempt (attempt_id, student_id, item_id, session_id, correct, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (f"att{i}", f"s{i}", "ex-total-prob-01", f"s{i}", 1, float(i)),
        )
    for i in range(mastery):
        conn.execute(
            "INSERT INTO mastery (session_id, topic, attempts, correct, updated_at)"
            " VALUES (?,?,?,?,?)",
            (f"s{i}", "kc_x", 2, 1, float(i)),
        )
    conn.commit()
    conn.close()


def _use_db(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(settings, "db_path", str(path), raising=False)
    accounts.reset_schema_cache()


def test_migration_preserves_row_counts(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "legacy.sqlite"
    _make_legacy_db(db)
    _use_db(monkeypatch, db)

    assert M.migrate(backup=True) == 0

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    for old, new, _ in M.MIGRATIONS:
        assert conn.execute(
            f"SELECT COUNT(*) c FROM legacy_{old}"
        ).fetchone()["c"] >= 0, f"legacy_{old} 应存在"
        assert conn.execute(f"SELECT COUNT(*) c FROM {new}").fetchone()["c"] == (
            conn.execute(f"SELECT COUNT(*) c FROM legacy_{old}").fetchone()["c"]
        ), f"{new} 行数与 legacy_{old} 不一致"
    # 老数据必须归属到不可登录的历史账号
    rows = conn.execute("SELECT DISTINCT user_id FROM student_qa_log").fetchall()
    assert {r["user_id"] for r in rows} == {accounts.HISTORY_USER_ID}
    conn.close()

    assert accounts.get_user(accounts.HISTORY_USER_ID) is not None
    assert accounts.get_by_username("history", with_hash=True)["password_hash"] == ""


def test_migration_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    """跑第二次：没有老表可迁 → 直接返回，且**不重复灌数据**。"""
    db = tmp_path / "legacy2.sqlite"
    _make_legacy_db(db, qa=4, att=2, mastery=0)
    _use_db(monkeypatch, db)

    assert M.migrate(backup=False) == 0
    before = sqlite3.connect(db).execute("SELECT COUNT(*) FROM student_qa_log").fetchone()[0]
    assert M.migrate(backup=False) == 0
    after = sqlite3.connect(db).execute("SELECT COUNT(*) FROM student_qa_log").fetchone()[0]
    assert before == after == 4, f"重复迁移把数据搬重了：{before} → {after}"


def test_migration_refuses_when_target_has_data(tmp_path: Path, monkeypatch) -> None:
    """目标表已有数据时**拒绝执行**（返回 2）—— 否则会把老数据重复插一遍。"""
    db = tmp_path / "legacy3.sqlite"
    _make_legacy_db(db, qa=1, att=0, mastery=0)
    _use_db(monkeypatch, db)
    # 先在目标表里放一条（模拟"已经迁移过、又有人写了新数据"）
    conn = accounts.connect()
    conn.execute(
        "INSERT INTO student_qa_log (user_id, session_id, query, created_at) VALUES (?,?,?,?)",
        ("usr_x", "s", "已存在的新数据", 1.0),
    )
    conn.commit()
    conn.close()

    assert M.migrate(backup=True) == 2, "目标表非空时应拒绝迁移"
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM qa_log").fetchone()[0] == 1, "老表不应被改名"

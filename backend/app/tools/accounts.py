"""账号数据层（L2）—— 账号、令牌、审计三张表 + 业务表的读写。

为什么单独一个文件
----------------
`learning_log.py` 管的是"学习记录"（问答、作答、掌握度），本文件管的是"**谁在用**"。
两者都是 L2 敏感数据，共用一个 SQLite 库（`settings.resolved_db_path`），
但混在一个文件里会让"账号"和"学生行为"的边界糊掉 —— 而这个边界正是
导出 / 备份 / 删除脚本要按 `student_` 前缀机械识别的依据（`docs/13 §1.1 约束 2`）。

三条工程约定（都是踩过坑才写下来的）
----------------------------------
1. **表名一律 `student_` 前缀**。`/api/health` 就是靠 `LIKE 'student_%'` 报出
   "这台机器上有哪些敏感表"，所以前缀不是命名风格，是可机械判定的合规标记。
2. **连接每次新建、用完必关**。sqlite3 的连接不能跨线程共享，而 FastAPI 的同步
   依赖跑在线程池里 —— 模块级全局连接会随机报 "SQLite objects created in a thread
   can only be used in that same thread"。所以照 `learning_log.py` 的做法每调用一次
   建一次连接；但**这次用 closing() 显式关闭**（`with sqlite3.connect(...)` 是事务
   上下文，不是资源上下文，靠引用计数释放太脆）。
3. **建表只在进程内做一次**（`_ensure_schema`）。旧代码每次调用都
   `executescript(_SCHEMA)`，等于每个接口调用都重建一遍表与索引。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Optional

from ..config import settings

#: 角色与状态是**封闭枚举**（契约 contracts/user.schema.json）：写错一个字就是脏数据，
#: 所以在这一层就拦住，而不是指望每个调用方都传对。
ROLE_STUDENT = "student"
ROLE_ADMIN = "admin"
ROLES = (ROLE_STUDENT, ROLE_ADMIN)

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
STATUS_DELETED = "deleted"
STATUSES = (STATUS_ACTIVE, STATUS_DISABLED, STATUS_DELETED)

#: 历史匿名数据所属的账号（迁移脚本建的，不可登录）
HISTORY_USER_ID = "usr_history"

_SCHEMA = """
-- 账号（L2）
CREATE TABLE IF NOT EXISTS student_user (
    user_id       TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL CHECK (role IN ('student','admin')),
    password_hash TEXT NOT NULL DEFAULT '',   -- bcrypt；空串 = 不可登录（历史账号）
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','disabled','deleted')),
    must_change_pw INTEGER NOT NULL DEFAULT 0,
    failed_count  INTEGER NOT NULL DEFAULT 0,
    locked_until  REAL NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    created_by    TEXT NOT NULL DEFAULT '',
    last_login_at REAL
);
CREATE INDEX IF NOT EXISTS idx_user_role ON student_user(role, status);

-- 会话令牌：库里只存 sha256(明文)，明文只在登录响应里返回一次
CREATE TABLE IF NOT EXISTS student_token (
    token_id     TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    issued_at    REAL NOT NULL,
    expires_at   REAL NOT NULL,
    last_used_at REAL,
    revoked      INTEGER NOT NULL DEFAULT 0,
    user_agent   TEXT NOT NULL DEFAULT '',
    ip           TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_token_user ON student_token(user_id, revoked);

-- 审计：谁在什么时候对谁做了什么（管理员看学生数据必须留痕）
CREATE TABLE IF NOT EXISTS student_audit (
    audit_id   TEXT PRIMARY KEY,
    actor_id   TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    action     TEXT NOT NULL,
    target_id  TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON student_audit(actor_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_target ON student_audit(target_id, created_at);
"""

#: 业务表（同样是 L2）。**放在这里而不是 learning_log.py**，是因为一个 SQLite 文件
#: 只能有一个建表入口：分两处 do `CREATE TABLE`，迟早会出现"某一个入口漏建了表"，
#: 而症状是运行时的 `no such table`，很难查。改表结构只需改这一处。
_SCHEMA_LEARNING = """
-- 问答流水（含**提问原文**，是 L2 里最敏感的一张）
CREATE TABLE IF NOT EXISTS student_qa_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL DEFAULT '',
    session_id  TEXT NOT NULL,
    run_id      TEXT,
    query       TEXT NOT NULL,
    intent      TEXT,
    agents      TEXT,
    answer      TEXT,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qa_user ON student_qa_log(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_qa_session ON student_qa_log(session_id, created_at);

-- 作答记录（契约：contracts/attempt.schema.json「记录层」）
-- 字段名与契约逐字一致；`student_id` 与 `user_id` 同值（契约里的历史命名保留）
CREATE TABLE IF NOT EXISTS student_attempt (
    attempt_id        TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL DEFAULT '',
    student_id        TEXT NOT NULL,
    item_id           TEXT NOT NULL,
    session_id        TEXT,
    kc_ids            TEXT NOT NULL DEFAULT '[]',
    correct           INTEGER NOT NULL,
    score             REAL,
    answer_raw        TEXT,
    answer_normalized TEXT,
    expected          TEXT,
    hint_used         INTEGER NOT NULL DEFAULT 0,
    duration_ms       INTEGER NOT NULL DEFAULT 0,
    attempt_no        INTEGER NOT NULL DEFAULT 1,
    source            TEXT NOT NULL DEFAULT 'practice',
    grader            TEXT NOT NULL DEFAULT 'sympy',
    grader_confidence REAL,
    created_at        REAL NOT NULL,
    deleted           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_attempt_user ON student_attempt(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_attempt_item ON student_attempt(user_id, item_id);

-- 掌握度：★ 主键从 (session_id, topic) 改为 (user_id, topic) ——
-- 有了账号之后，同一个人换浏览器就是另一个 session，"按 session 聚合"会把
-- 一个人的掌握度拆成好几份。这条口径修正记在 docs/21 §5.3 与 contracts/CHANGELOG.md。
CREATE TABLE IF NOT EXISTS student_mastery (
    user_id     TEXT NOT NULL,
    topic       TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    correct     INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (user_id, topic)
);
"""

#: 已经建过表的库文件（进程内一次）。键是绝对路径字符串，测试里换库也不会串。
_initialized: set[str] = set()
_init_lock = threading.Lock()


# --------------------------------------------------------------------------
# 连接与初始化
# --------------------------------------------------------------------------


def db_path() -> Path:
    return settings.resolved_db_path


def connect() -> sqlite3.Connection:
    """建一个连接（调用方负责关闭；请用 `closing()`）。

    WAL + busy_timeout：FastAPI 是多线程的，多个请求同时写会撞 "database is locked"。
    WAL 让读写不互相阻塞，busy_timeout 让写锁等待而不是立刻报错。
    """
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn, path)
    return conn


def _ensure_schema(conn: sqlite3.Connection, path: Path) -> None:
    """建表建索引，每个进程只对同一个库做一次。"""
    key = str(path.resolve())
    if key in _initialized:
        return
    with _init_lock:
        if key in _initialized:
            return
        conn.executescript(_SCHEMA)
        conn.executescript(_SCHEMA_LEARNING)
        conn.commit()
        _initialized.add(key)


def reset_schema_cache() -> None:
    """测试用：让下一次连接重新建表（换库文件后调用）。"""
    _initialized.clear()


# --------------------------------------------------------------------------
# 账号
# --------------------------------------------------------------------------


def new_user_id() -> str:
    return f"usr_{uuid.uuid4().hex[:12]}"


def _row_to_user(row: sqlite3.Row | None, *, with_hash: bool = False) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    user = {
        "user_id": row["user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "status": row["status"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "last_login_at": row["last_login_at"],
    }
    if with_hash:
        # 只给登录逻辑用：**绝不允许**出现在任何 HTTP 响应里
        user["password_hash"] = row["password_hash"]
        user["failed_count"] = row["failed_count"]
        user["locked_until"] = row["locked_until"]
        user["must_change_pw"] = bool(row["must_change_pw"])
    return user


def create_user(
    *,
    username: str,
    password_hash: str,
    role: str = ROLE_STUDENT,
    display_name: str = "",
    created_by: str = "",
    user_id: str | None = None,
    status: str = STATUS_ACTIVE,
) -> dict[str, Any]:
    """建一个账号。用户名重复抛 `sqlite3.IntegrityError`（调用方转 409）。"""
    if role not in ROLES:
        raise ValueError(f"角色只能是 {ROLES}，收到 {role!r}")
    if status not in STATUSES:
        raise ValueError(f"状态只能是 {STATUSES}，收到 {status!r}")
    uid = user_id or new_user_id()
    with closing(connect()) as conn:
        conn.execute(
            "INSERT INTO student_user (user_id, username, display_name, role, password_hash,"
            " status, created_at, created_by) VALUES (?,?,?,?,?,?,?,?)",
            (uid, username, display_name or username, role, password_hash, status, time.time(), created_by),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM student_user WHERE user_id=?", (uid,)).fetchone()
    return _row_to_user(row)  # type: ignore[return-value]


def get_user(user_id: str) -> Optional[dict[str, Any]]:
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM student_user WHERE user_id=?", (user_id,)).fetchone()
    return _row_to_user(row)


def get_by_username(username: str, *, with_hash: bool = False) -> Optional[dict[str, Any]]:
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT * FROM student_user WHERE username=? COLLATE NOCASE", (username,)
        ).fetchone()
    return _row_to_user(row, with_hash=with_hash)


def count_admins() -> int:
    with closing(connect()) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM student_user WHERE role='admin' AND status<>'deleted'"
            ).fetchone()["c"]
        )


def list_users(
    *, role: str | None = None, include_deleted: bool = False
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM student_user WHERE 1=1"
    args: list[Any] = []
    if role:
        sql += " AND role=?"
        args.append(role)
    if not include_deleted:
        sql += " AND status<>'deleted'"
    sql += " ORDER BY created_at"
    with closing(connect()) as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_user(r) for r in rows]  # type: ignore[misc]


def set_password(user_id: str, password_hash: str) -> None:
    with closing(connect()) as conn:
        conn.execute(
            "UPDATE student_user SET password_hash=?, must_change_pw=0, failed_count=0,"
            " locked_until=0 WHERE user_id=?",
            (password_hash, user_id),
        )
        conn.commit()


def set_status(user_id: str, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"状态只能是 {STATUSES}，收到 {status!r}")
    with closing(connect()) as conn:
        conn.execute("UPDATE student_user SET status=? WHERE user_id=?", (status, user_id))
        conn.commit()


def note_login_success(user_id: str) -> None:
    with closing(connect()) as conn:
        conn.execute(
            "UPDATE student_user SET failed_count=0, locked_until=0, last_login_at=?"
            " WHERE user_id=?",
            (time.time(), user_id),
        )
        conn.commit()


def note_login_failure(user_id: str, *, max_failed: int, lock_seconds: int) -> dict[str, Any]:
    """记一次失败。达到上限就锁定，并**清零计数**（锁定期满后重新计数）。"""
    now = time.time()
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT failed_count FROM student_user WHERE user_id=?", (user_id,)
        ).fetchone()
        failed = int(row["failed_count"] if row else 0) + 1
        if failed >= max_failed:
            conn.execute(
                "UPDATE student_user SET failed_count=0, locked_until=? WHERE user_id=?",
                (now + lock_seconds, user_id),
            )
            locked = True
        else:
            conn.execute(
                "UPDATE student_user SET failed_count=? WHERE user_id=?",
                (failed, user_id),
            )
            locked = False
        conn.commit()
    return {"failed_count": 0 if locked else failed, "locked": locked}


# --------------------------------------------------------------------------
# 令牌（服务端会话令牌：库里只存 sha256）
# --------------------------------------------------------------------------


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_token(
    user_id: str, *, ttl_days: int, user_agent: str = "", ip: str = ""
) -> dict[str, Any]:
    """发一个令牌。**明文只在这里返回一次**，库里存 sha256。"""
    raw = secrets.token_urlsafe(32)
    now = time.time()
    expires = now + ttl_days * 86400
    with closing(connect()) as conn:
        conn.execute(
            "INSERT INTO student_token (token_id, user_id, token_hash, issued_at, expires_at,"
            " revoked, user_agent, ip) VALUES (?,?,?,?,?,0,?,?)",
            (f"tok_{uuid.uuid4().hex[:12]}", user_id, _hash_token(raw), now, expires,
             user_agent[:200], ip[:64]),
        )
        conn.commit()
    return {"token": raw, "expires_at": expires}


def resolve_token(raw: str) -> Optional[dict[str, Any]]:
    """校验令牌 → 返回账号；无效/过期/已撤销/账号不可用一律 None。

    同时刷新 `last_used_at`（排查"令牌到底在哪儿被用了"的唯一线索）。
    """
    if not raw:
        return None
    digest = _hash_token(raw)
    now = time.time()
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT t.token_id, t.user_id, t.expires_at, t.revoked, u.*"
            " FROM student_token t JOIN student_user u ON u.user_id = t.user_id"
            " WHERE t.token_hash=?",
            (digest,),
        ).fetchone()
        if row is None:
            return None
        if row["revoked"] or float(row["expires_at"]) < now:
            return None
        if row["status"] != STATUS_ACTIVE:
            return None
        conn.execute(
            "UPDATE student_token SET last_used_at=? WHERE token_id=?", (now, row["token_id"])
        )
        conn.commit()
    return _row_to_user(row)


def revoke_token(raw: str) -> None:
    with closing(connect()) as conn:
        conn.execute(
            "UPDATE student_token SET revoked=1 WHERE token_hash=?", (_hash_token(raw),)
        )
        conn.commit()


def revoke_user_tokens(user_id: str) -> int:
    """撤销某人的全部令牌。改密 / 重置 / 禁用 / 删数据都要调它 —— 
    "改了密码旧设备还能用"是最常见的权限漏洞。"""
    with closing(connect()) as conn:
        cur = conn.execute(
            "UPDATE student_token SET revoked=1 WHERE user_id=? AND revoked=0", (user_id,)
        )
        conn.commit()
        return int(cur.rowcount)


def purge_expired_tokens(older_than_days: int = 30) -> int:
    """清理过期很久的令牌行（顺手做，避免表无限增长）。"""
    cutoff = time.time() - older_than_days * 86400
    with closing(connect()) as conn:
        cur = conn.execute("DELETE FROM student_token WHERE expires_at < ?", (cutoff,))
        conn.commit()
        return int(cur.rowcount)


# --------------------------------------------------------------------------
# 审计
# --------------------------------------------------------------------------


def write_audit(
    *,
    actor_id: str,
    actor_role: str,
    action: str,
    target_id: str = "",
    detail: dict[str, Any] | None = None,
) -> str:
    audit_id = f"aud_{uuid.uuid4().hex[:12]}"
    with closing(connect()) as conn:
        conn.execute(
            "INSERT INTO student_audit (audit_id, actor_id, actor_role, action, target_id,"
            " detail, created_at) VALUES (?,?,?,?,?,?,?)",
            (audit_id, actor_id, actor_role, action, target_id,
             json.dumps(detail or {}, ensure_ascii=False), time.time()),
        )
        conn.commit()
    return audit_id


def list_audit(
    *, page: int = 1, page_size: int = 50, action: str = "", actor_id: str = ""
) -> dict[str, Any]:
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 200))
    where = " WHERE 1=1"
    args: list[Any] = []
    if action:
        where += " AND a.action=?"
        args.append(action)
    if actor_id:
        where += " AND a.actor_id=?"
        args.append(actor_id)

    with closing(connect()) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) AS c FROM student_audit a{where}", args).fetchone()["c"])
        rows = conn.execute(
            f"""SELECT a.*, au.username AS actor_username, tu.username AS target_username
                FROM student_audit a
                LEFT JOIN student_user au ON au.user_id = a.actor_id
                LEFT JOIN student_user tu ON tu.user_id = a.target_id
                {where}
                ORDER BY a.created_at DESC LIMIT ? OFFSET ?""",
            [*args, page_size, (page - 1) * page_size],
        ).fetchall()

    items = []
    for r in rows:
        try:
            detail = json.loads(r["detail"] or "{}")
        except (TypeError, ValueError):
            detail = {}
        items.append(
            {
                "audit_id": r["audit_id"],
                "actor_id": r["actor_id"],
                "actor_username": r["actor_username"] or "",
                "actor_role": r["actor_role"],
                "action": r["action"],
                "target_id": r["target_id"],
                "target_username": r["target_username"] or "",
                "detail": detail,
                "created_at": r["created_at"],
            }
        )
    return {"items": items, "page": page, "page_size": page_size, "total": total}


# --------------------------------------------------------------------------
# 历史账号（迁移后老数据的归属）
# --------------------------------------------------------------------------


def ensure_history_user() -> str:
    """确保"历史匿名数据"账号存在。

    `password_hash=''` + `status='disabled'` → **任何密码都登不进去**，
    登录逻辑也显式拒绝空哈希（双保险）。它的唯一用途是给迁移过来的老数据一个 user_id。
    """
    existing = get_user(HISTORY_USER_ID)
    if existing:
        return HISTORY_USER_ID
    try:
        create_user(
            user_id=HISTORY_USER_ID,
            username="history",
            display_name="历史匿名数据",
            role=ROLE_STUDENT,
            password_hash="",
            created_by="migration",
            status=STATUS_DISABLED,
        )
    except sqlite3.IntegrityError:
        pass  # 并发下另一个进程刚建好
    return HISTORY_USER_ID


# --------------------------------------------------------------------------
# 删除学生数据（隐私承诺的兑现口）
# --------------------------------------------------------------------------

#: 一个学生的"业务数据"分布在这三张表里。删除时必须一起删干净 ——
#: 只删一张、留着 qa_log 里的**提问原文**，等于没删（那是 L2 里最敏感的部分）。
BUSINESS_TABLES = ("student_attempt", "student_qa_log", "student_mastery")


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def delete_user_data(user_id: str) -> dict[str, int]:
    """删除某学生的全部业务数据 + 账号脱敏。**不可逆，调用方必须先二次确认。**

    账号行**不物理删除**，而是脱敏保留（`status='deleted'`、用户名改成
    `deleted_<8hex>`、清空密码与显示名）。原因：审计日志里引用了 `user_id` 与用户名，
    把行删掉会让"谁在什么时候删了这个人的数据"变成一条查不下去的死链。
    留一行壳、抹掉所有可识别信息，既满足隐私要求也保住了审计可追溯性。
    """
    counts: dict[str, int] = {}
    with closing(connect()) as conn:
        for table in BUSINESS_TABLES:
            if not table_exists(conn, table):
                counts[table] = 0
                continue
            cur = conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            counts[table] = int(cur.rowcount)

        scrubbed = f"deleted_{secrets.token_hex(4)}"
        conn.execute(
            "UPDATE student_user SET status=?, username=?, display_name='', password_hash='',"
            " failed_count=0, locked_until=0 WHERE user_id=?",
            (STATUS_DELETED, scrubbed, user_id),
        )
        conn.execute(
            "UPDATE student_token SET revoked=1 WHERE user_id=? AND revoked=0", (user_id,)
        )
        conn.commit()
    return counts


def student_stats(
    user_ids: list[str] | None = None, *, include_history: bool = False
) -> list[dict[str, Any]]:
    """按账号聚合学习数据（管理端列表与学生列表共用）。

    口径（`docs/21 §5.3`）：`correct` 只算 attempt 里判对的次数，
    `accuracy = correct / attempts`；没有作答记录时是 0 而不是 null（前端少一个分支）。

    `usr_history`（迁移过来的匿名老数据）**默认排除**：它是合成的归属壳，
    把它算进"班级平均正确率"会误导（76 条历史记录会盖过真实学生的 3 条）。
    需要看它时传 `include_history=True`。
    """
    with closing(connect()) as conn:
        if not table_exists(conn, "student_attempt"):
            return []
        sql = """
            SELECT u.user_id, u.username, u.display_name, u.status, u.created_at, u.last_login_at,
                   COUNT(a.attempt_id)                                   AS attempts,
                   COALESCE(SUM(a.correct), 0)                           AS correct,
                   COALESCE(SUM(CASE WHEN a.correct=0 THEN 1 ELSE 0 END), 0) AS wrong,
                   COALESCE(SUM(CASE WHEN a.hint_used > 0 THEN 1 ELSE 0 END), 0) AS hinted
              FROM student_user u
              LEFT JOIN student_attempt a ON a.user_id = u.user_id AND a.deleted = 0
             WHERE u.role='student' AND u.status<>'deleted'
        """
        args: list[Any] = []
        if not include_history:
            sql += " AND u.user_id <> ?"
            args.append(HISTORY_USER_ID)
        if user_ids:
            sql += " AND u.user_id IN (" + ",".join("?" * len(user_ids)) + ")"
            args.extend(user_ids)
        sql += " GROUP BY u.user_id ORDER BY u.created_at"
        rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        attempts = int(r["attempts"] or 0)
        correct = int(r["correct"] or 0)
        out.append(
            {
                "user_id": r["user_id"],
                "username": r["username"],
                "display_name": r["display_name"],
                "status": r["status"],
                "created_at": r["created_at"],
                "last_login_at": r["last_login_at"],
                "attempts": attempts,
                "correct": correct,
                "wrong_items": int(r["wrong"] or 0),
                "hint_used_total": int(r["hinted"] or 0),
                "accuracy": round(correct / attempts, 4) if attempts else 0.0,
            }
        )
    return out


def recent_attempts(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """某个学生的逐题作答明细（管理端"学生详情"用）。"""
    limit = max(1, min(int(limit), 500))
    with closing(connect()) as conn:
        if not table_exists(conn, "student_attempt"):
            return []
        rows = conn.execute(
            "SELECT attempt_id, item_id, correct, hint_used, attempt_no, duration_ms,"
            " answer_raw, expected, kc_ids, created_at FROM student_attempt"
            " WHERE user_id=? AND deleted=0 ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["kc_ids"] = json.loads(d.get("kc_ids") or "[]")
        except (TypeError, ValueError):
            d["kc_ids"] = []
        d["correct"] = bool(d.get("correct"))
        out.append(d)
    return out


__all__ = [
    "BUSINESS_TABLES",
    "HISTORY_USER_ID",
    "ROLES",
    "ROLE_ADMIN",
    "ROLE_STUDENT",
    "STATUS_ACTIVE",
    "STATUS_DELETED",
    "STATUS_DISABLED",
    "STATUSES",
    "connect",
    "count_admins",
    "create_user",
    "db_path",
    "delete_user_data",
    "ensure_history_user",
    "get_by_username",
    "get_user",
    "issue_token",
    "list_audit",
    "list_users",
    "new_user_id",
    "note_login_failure",
    "note_login_success",
    "purge_expired_tokens",
    "recent_attempts",
    "reset_schema_cache",
    "resolve_token",
    "revoke_token",
    "revoke_user_tokens",
    "set_password",
    "set_status",
    "student_stats",
    "table_exists",
    "write_audit",
]

#!/usr/bin/env python
"""把"匿名 session 时代"的老表迁移到"账号时代"的 `student_*` 表。

为什么要迁移（而不是清库重来）
----------------------------
1. **`docs/13 §1.1 约束 2` 是硬约束**：L2 表必须以 `student_` 前缀命名，
   这样导出/备份/日志脚本一条 `LIKE 'student_%'` 就能把所有敏感表挑出来。
   老表 `qa_log`（含**提问原文**）、`attempt`、`mastery` 都违反这条。
2. 库里已有真实记录（本机迁移前 37 条问答 + 76 条作答）—— 直接删掉太粗暴，
   而且老师那份真实使用记录是结项材料的一部分。

迁移做了什么
-----------
    qa_log   → student_qa_log    (加 user_id)
    attempt  → student_attempt   (加 user_id)
    mastery  → student_mastery   (主键 session_id → user_id)

老数据全部归属到一个**不可登录**的账号 `history`（`password_hash=''` + `status='disabled'`），
所以它们不会混进任何真实学生的统计里，但也没有被丢掉。
老表**重命名为 `legacy_*`**（不删），确认一周没问题后再人工 DROP。

四道保险
-------
1. 迁移前**先备份**库文件（`learning.sqlite.bak-<时间戳>`）；
2. 整个过程在**一个事务**里，出错整体回滚，库保持原样；
3. **行数守恒断言**：逐表比对"迁移前后行数"，不等就回滚 —— 这是判断"有没有搬漏"的唯一硬标准；
4. **幂等 + 防重复灌入**：目标表已有数据就拒绝执行（否则会把老数据重复插一遍）。

用法
----
    cd ProbCrew
    python scripts/migrate_to_accounts.py --check    # 只看现状，不动数据
    python scripts/migrate_to_accounts.py            # 真迁移（会先备份）
"""
from __future__ import annotations

from _console import utf8_output

utf8_output()

import argparse
import shutil
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.tools import accounts  # noqa: E402

#: 老表 → 新表。列名差异只在 user_id 上，其余逐列照搬。
MIGRATIONS: list[tuple[str, str, str]] = [
    # (老表, 新表, 新表里显式补的列)
    ("qa_log", "student_qa_log", "user_id"),
    ("attempt", "student_attempt", "user_id"),
    ("mastery", "student_mastery", "user_id"),
]


def _count(conn: sqlite3.Connection, table: str) -> int | None:
    if not accounts.table_exists(conn, table):
        return None
    return int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not accounts.table_exists(conn, table):
        return []
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def survey() -> dict:
    """只看现状：哪些老表还在、有多少行、新表建了没有。"""
    with closing(accounts.connect()) as conn:
        info = {}
        for old, new, _extra in MIGRATIONS:
            info[old] = _count(conn, old)
            info[new] = _count(conn, new)
            info[f"legacy_{old}"] = _count(conn, f"legacy_{old}")
        info["db"] = str(accounts.db_path())
        info["history_user"] = accounts.get_user(accounts.HISTORY_USER_ID) is not None
    return info


def print_survey(info: dict) -> None:
    print(f"库文件：{info['db']}")
    print(f"{'表':<24}{'行数':>8}")
    for old, new, _extra in MIGRATIONS:
        for name in (old, new, f"legacy_{old}"):
            n = info[name]
            if n is None:
                print(f"  {name:<22}{'不存在':>8}")
            else:
                print(f"  {name:<22}{n:>8}")
    print(f"  历史账号 usr_history：{'已存在' if info['history_user'] else '未建'}")


def migrate(*, backup: bool = True, dry_run: bool = False) -> int:
    info = survey()
    print_survey(info)
    print()

    pending = [m for m in MIGRATIONS if info[m[0]] is not None]
    if not pending:
        print("✔ 没有需要迁移的老表（可能已经迁移过）。")
        return 0

    # ---- 防重复灌入：目标表非空就停手 ----
    risky = [new for _old, new, _e in pending if (info[new] or 0) > 0]
    if risky:
        print("✗ 这些目标表里已经有数据：" + "、".join(risky))
        print("  继续迁移会把老数据重复插一遍。请先人工确认：")
        print("    · 若迁移已经做过，直接跑 --check；")
        print("    · 若确实要合并，请先把目标表清空或改名。")
        return 2

    if dry_run:
        print("（--dry-run：以上是计划，未改任何数据）")
        return 0

    # ---- 备份 ----
    backup_path = None
    if backup:
        src = accounts.db_path()
        if src.exists():
            backup_path = src.with_suffix(src.suffix + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(src, backup_path)
            print(f"① 已备份：{backup_path}")
        else:
            print(f"① 库文件还不存在（{src}），这次迁移会新建它")

    accounts.ensure_history_user()
    print(f"② 历史账号就绪：{accounts.HISTORY_USER_ID}（不可登录，只作老数据归属）")

    # ---- 单事务搬迁 ----
    conn = sqlite3.connect(accounts.db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        moved: dict[str, tuple[int, int]] = {}
        for old, new, extra in pending:
            before = _count(conn, old) or 0
            cols = [c for c in _columns(conn, new) if c != extra]
            shared = [c for c in cols if c in _columns(conn, old)]
            col_list = ", ".join([extra, *shared])
            placeholders = ", ".join(["?"] * (len(shared) + 1))
            select_list = ", ".join(shared)
            conn.execute(
                f"INSERT INTO {new} ({col_list}) SELECT ?, {select_list} FROM {old}",
                (accounts.HISTORY_USER_ID,),
            )
            after = _count(conn, new) or 0
            moved[new] = (before, after)
            if after - (info[new] or 0) != before:
                raise RuntimeError(
                    f"行数守恒断言失败：{old} 有 {before} 行，{new} 只多了 "
                    f"{after - (info[new] or 0)} 行 —— 已回滚"
                )
            conn.execute(f"ALTER TABLE {old} RENAME TO legacy_{old}")
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        conn.close()
        print(f"✗ 迁移失败，已整体回滚：{exc}")
        if backup_path:
            print(f"  备份仍在：{backup_path}")
        return 1
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    print("③ 搬迁完成（行数守恒已校验）：")
    for new, (old_n, new_n) in moved.items():
        print(f"   {new:<22} 老表 {old_n} 行 → 新表 {new_n} 行 ✔")
    print("④ 老表已重命名为 legacy_*（未删除；确认一周后人工 DROP）")
    print()
    print_survey(survey())
    print("\n✔ 迁移完成。下一步：")
    print("   python scripts/manage_users.py list      # 确认 history 账号存在且不可登录")
    return 0


def check() -> int:
    """给 CI / 验收用：断言"老表都已搬完、新表行数对得上"。"""
    info = survey()
    print_survey(info)
    # 全新库（老表、新表都没有）→ 没有可迁移的东西，不算失败。
    # 这条分支很关键：CI 是全新 checkout，库里什么表都没有 —— 没有它，--check 在 CI 上必红。
    fresh = all(info[m[0]] is None and (info[m[1]] or 0) == 0 and info[f"legacy_{m[0]}"] is None
                for m in MIGRATIONS)
    if fresh:
        print("✔ 这是个全新的库：没有老表、也没有业务数据，无需迁移。")
        return 0

    problems = []
    for old, new, _extra in MIGRATIONS:
        if info[old] is not None:
            problems.append(f"老表 {old} 还在（{info[old]} 行），说明没迁移")
        if info[new] is None:
            problems.append(f"新表 {new} 不存在")
        if info[f"legacy_{old}"] is not None and info[new] is not None:
            if info[f"legacy_{old}"] != info[new]:
                problems.append(
                    f"{new} 行数 {info[new]} 与 legacy_{old} 的 {info[f'legacy_{old}']} 不等"
                )
    if not info["history_user"]:
        problems.append("历史账号 usr_history 不存在")
    print()
    if problems:
        print("✘ 迁移检查未通过：")
        for p in problems:
            print(f"   · {p}")
        return 1
    print("✔ 迁移检查通过：老表已清空、新表行数一致、历史账号在。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="匿名 session 老表 → student_* 账号表")
    ap.add_argument("--check", action="store_true", help="只检查是否已迁移完成（CI 用）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不改数据")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份（不推荐）")
    args = ap.parse_args()

    if args.check:
        return check()
    return migrate(backup=not args.no_backup, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

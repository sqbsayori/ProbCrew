#!/usr/bin/env python
"""账号管理 CLI —— 不依赖网页就能建号、改密、停用、删数据。

为什么要有命令行入口
------------------
1. **冷启动**：库里没有管理员时，总得有个地方建第一个账号。种子管理员由启动
   流程自动创建（见 `app/main.py:_bootstrap_accounts`），但"再建一个管理员"
   只能靠命令 —— 界面刻意不做（管理端只有只读的管理员列表）。
2. **演示兜底**：管理页还没做完、或演示现场网页出问题时，一条命令就能建号。
3. **合规**：`delete-data` 是隐私承诺的兑现口。即使网页上的删除按钮坏了，
   也必须有一条能真正删掉学生数据的路。

用法
----
    cd ProbCrew
    python scripts/manage_users.py list
    python scripts/manage_users.py create --username s01 --display-name 张三
    python scripts/manage_users.py create --username teacher --role admin --password 'StrongPass123'
    python scripts/manage_users.py reset-password --username s01
    python scripts/manage_users.py disable --username s01
    python scripts/manage_users.py enable  --username s01
    python scripts/manage_users.py delete-data --username s01 --yes

    # 换库（默认 backend/data/learning.sqlite，由 .env 的 DB_PATH / DB_URL 决定）
    DB_PATH=/tmp/demo.sqlite python scripts/manage_users.py list
"""
from __future__ import annotations

from _console import utf8_output

utf8_output()

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.kernel import auth as A  # noqa: E402
from app.tools import accounts  # noqa: E402


def _find(username: str) -> dict:
    user = accounts.get_by_username(username)
    if user is None:
        print(f"✗ 找不到账号：{username}")
        raise SystemExit(1)
    return user


def _print_user(u: dict, *, password: str = "") -> None:
    tag = "管理员" if u["role"] == accounts.ROLE_ADMIN else "学生"
    line = f"  {u['username']:<20} {tag:<5} {u['status']:<9} {u['display_name']}"
    if password:
        line += f"   密码：{password}"
    print(line)


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    users = accounts.list_users(include_deleted=args.all)
    if not users:
        print("（库里还没有账号。启动一次服务会自动创建种子管理员，")
        print("  或用 `create --role admin` 手工建一个。）")
        return 0
    print(f"库文件：{accounts.db_path()}")
    print(f"共 {len(users)} 个账号：")
    for u in users:
        _print_user(u)
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    username = args.username.strip()
    try:
        A.validate_username(username)
    except ValueError as exc:
        print(f"✗ {exc}")
        return 1

    if accounts.get_by_username(username):
        print(f"✗ 用户名已存在：{username}")
        return 1

    password = args.password or A.new_random_password()
    try:
        A.validate_password(password, username=username)
    except ValueError as exc:
        print(f"✗ {exc}")
        return 1

    user = accounts.create_user(
        username=username,
        password_hash=A.hash_password(password),
        role=args.role,
        display_name=args.display_name or username,
        created_by="cli",
    )
    accounts.write_audit(
        actor_id="cli", actor_role=accounts.ROLE_ADMIN, action="user_create",
        target_id=user["user_id"], detail={"role": args.role, "via": "cli"},
    )
    print("✔ 已创建：")
    _print_user(user, password=password)
    if not args.password:
        print("  （密码是自动生成的，只显示这一次；请立刻抄走）")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    user = _find(args.username)
    password = args.password or A.new_random_password()
    try:
        A.validate_password(password, username=user["username"])
    except ValueError as exc:
        print(f"✗ {exc}")
        return 1
    accounts.set_password(user["user_id"], A.hash_password(password))
    revoked = accounts.revoke_user_tokens(user["user_id"])
    accounts.write_audit(
        actor_id="cli", actor_role=accounts.ROLE_ADMIN, action="password_reset",
        target_id=user["user_id"], detail={"via": "cli", "revoked_tokens": revoked},
    )
    print(f"✔ 已重置 {user['username']} 的密码（同时撤销了 {revoked} 张令牌）")
    print(f"  新密码：{password}")
    return 0


def cmd_set_status(args: argparse.Namespace) -> int:
    user = _find(args.username)
    status = accounts.STATUS_DISABLED if args.command == "disable" else accounts.STATUS_ACTIVE
    accounts.set_status(user["user_id"], status)
    revoked = accounts.revoke_user_tokens(user["user_id"]) if status == accounts.STATUS_DISABLED else 0
    accounts.write_audit(
        actor_id="cli", actor_role=accounts.ROLE_ADMIN,
        action="user_disable" if status == accounts.STATUS_DISABLED else "user_enable",
        target_id=user["user_id"], detail={"via": "cli"},
    )
    extra = f"，并撤销了 {revoked} 张令牌" if revoked else ""
    print(f"✔ {user['username']} 现在是 {status}{extra}")
    return 0


def cmd_delete_data(args: argparse.Namespace) -> int:
    """删除某个学生的**全部业务数据**（隐私承诺的兑现口）。不可逆。"""
    user = _find(args.username)
    if user["role"] == accounts.ROLE_ADMIN:
        print("✗ 不做管理员数据删除：管理员账号请用 disable（保留审计链）")
        return 1

    if not args.yes:
        print(f"即将**永久删除** {user['username']} 的全部作答/问答/掌握度记录，")
        print("并把这个账号脱敏（用户名改为 deleted_xxxx、密码清空）。此操作不可逆。")
        print("确认请加 --yes")
        return 1

    result = accounts.delete_user_data(user["user_id"])
    accounts.write_audit(
        actor_id="cli", actor_role=accounts.ROLE_ADMIN, action="data_delete",
        target_id=user["user_id"], detail={**result, "via": "cli"},
    )
    print("✔ 已删除：" + "、".join(f"{k} {v} 行" for k, v in result.items()))
    print("  账号已脱敏，审计记录保留（审计里不含学生作答内容）")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    created = A.ensure_seed_admin()
    if created is None:
        print("（已有管理员，未做任何改动）")
        return 0
    print("✔ 已创建种子管理员：")
    _print_user(created, password=created.get("_initial_password", ""))
    return 0


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="ProbCrew 账号管理（建号 / 改密 / 停用 / 删除学生数据）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("list", help="列出账号")
    s.add_argument("--all", action="store_true", help="连已删除的账号一起列")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("create", help="新建账号")
    s.add_argument("--username", required=True)
    s.add_argument("--role", choices=list(accounts.ROLES), default=accounts.ROLE_STUDENT)
    s.add_argument("--display-name", default="")
    s.add_argument("--password", default="", help="不填则自动生成并打印一次")
    s.set_defaults(func=cmd_create)

    s = sub.add_parser("reset-password", help="重置密码（并撤销其全部令牌）")
    s.add_argument("--username", required=True)
    s.add_argument("--password", default="")
    s.set_defaults(func=cmd_reset_password)

    s = sub.add_parser("disable", help="停用账号（并撤销其全部令牌）")
    s.add_argument("--username", required=True)
    s.set_defaults(func=cmd_set_status)

    s = sub.add_parser("enable", help="启用账号")
    s.add_argument("--username", required=True)
    s.set_defaults(func=cmd_set_status)

    s = sub.add_parser("delete-data", help="删除某学生的全部数据（不可逆，隐私合规用）")
    s.add_argument("--username", required=True)
    s.add_argument("--yes", action="store_true", help="确认执行")
    s.set_defaults(func=cmd_delete_data)

    s = sub.add_parser("seed", help="确保存在种子管理员")
    s.set_defaults(func=cmd_seed)

    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

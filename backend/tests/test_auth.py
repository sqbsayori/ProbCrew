"""账号与认证单元测试（Sprint 1 地基）。

守什么
------
账号是**权限的唯一来源**，所以这里的重点全部是"越权与绕过"：

1. 未登录访问受保护接口 → 401；学生访问管理端 → 403（前端藏菜单不是权限）；
2. 密码**只存 bcrypt 哈希**，明文在任何响应与任何列里都不出现；
3. 令牌在库里**只存 sha256**（库被拿走也不能直接当令牌用）；
4. 改密 / 重置 / 禁用 / 删数据之后，**旧令牌立即失效**；
5. 连续失败锁定（标准档：5 次 / 60 秒），且锁定期间连正确密码也拒绝；
6. 历史账号（空哈希 + disabled）**登不进去**；
7. 登录失败不泄露"用户名是否存在"（错误文案与耗时都要一致）。

运行：
    cd ProbCrew
    python -m pytest backend/tests/test_auth.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _auth import ADMIN, STUDENT, ensure_account, login_client, login_fresh  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.kernel import auth as A  # noqa: E402
from app.main import build_app  # noqa: E402
from app.tools import accounts  # noqa: E402

#: 需要登录才能访问的端点样本（覆盖各模块，防止漏挂依赖）
PROTECTED = [
    "/api/me/stats",
    "/api/me/wrong",
    "/api/me/mastery",
    "/api/practice/questions",
    "/api/problems/examples",
    "/api/knowledge/chapters",
    "/api/distributions",
    "/api/animations",
    "/api/agents",
    "/api/tools",
    "/api/runs",
    "/api/admin/overview",
    "/api/admin/students",
    "/api/admin/audit",
]


def _client():
    return TestClient(build_app())


# --------------------------------------------------------------------------
# 1. 认证边界
# --------------------------------------------------------------------------


def test_everything_needs_login() -> None:
    """未登录 → 一律 401，且**不泄露任何业务数据**。"""
    c = _client()
    for path in PROTECTED:
        r = c.get(path)
        assert r.status_code == 401, f"{path} 未登录竟返回 {r.status_code}"
        assert "detail" in r.json()


def test_health_and_login_stay_public() -> None:
    """健康检查与登录本身必须匿名可达 —— 否则前端连状态都显示不出来。"""
    c = _client()
    assert c.get("/api/health").status_code == 200
    assert c.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code in (401, 423)


def test_student_cannot_touch_admin_endpoints() -> None:
    """学生拿到管理员接口 → 403（不是 401：他确实登录了，只是没权限）。"""
    c = login_client(_client(), "student")
    for path in ("/api/admin/overview", "/api/admin/students", "/api/admin/audit"):
        assert c.get(path).status_code == 403, path
    assert c.get("/api/admin/export/students.csv").status_code == 403


def test_admin_can_touch_admin_endpoints() -> None:
    c = login_client(_client(), "admin")
    assert c.get("/api/admin/overview").status_code == 200
    assert c.get("/api/admin/students").status_code == 200


# --------------------------------------------------------------------------
# 2. 登录失败的三套语义
# --------------------------------------------------------------------------


def test_login_wrong_password_is_401() -> None:
    username, _pw = ensure_account("student")
    c = _client()
    r = c.post("/api/auth/login", json={"username": username, "password": "definitely-wrong"})
    assert r.status_code == 401
    assert r.json()["detail"] == "用户名或密码不正确"


def test_login_unknown_user_gives_the_same_message() -> None:
    """不存在的用户名与密码错**文案必须一致** —— 否则就是一份用户名单探测接口。"""
    c = _client()
    a = c.post("/api/auth/login", json={"username": "no_such_user_xyz", "password": "whatever"})
    b = c.post("/api/auth/login", json={"username": ensure_account()[0], "password": "wrong-pass"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_login_disabled_account_is_403() -> None:
    """被禁用的账号：**密码对**也要 403，前端才能给出"请联系管理员"而不是"密码错"。"""
    from app.kernel import auth as A

    username = "t_disabled_case"
    if accounts.get_by_username(username) is None:
        accounts.create_user(
            username=username, password_hash=A.hash_password("good-pass-123"),
            role="student", created_by="tests",
        )
    user = accounts.get_by_username(username)
    accounts.set_password(user["user_id"], A.hash_password("good-pass-123"))
    accounts.set_status(user["user_id"], accounts.STATUS_DISABLED)
    try:
        r = _client().post("/api/auth/login", json={"username": username, "password": "good-pass-123"})
        assert r.status_code == 403
        assert "禁用" in r.json()["detail"]
    finally:
        accounts.set_status(user["user_id"], accounts.STATUS_ACTIVE)


def test_login_locks_after_five_failures() -> None:
    """★ 标准档：连续 5 次失败锁 60 秒；锁定期间**正确密码也被拒**（423）。"""
    from app.config import settings

    username, password = ensure_account("student")
    user = accounts.get_by_username(username)
    accounts.set_password(user["user_id"], A.hash_password(password))

    c = _client()
    # 先制造 max_failed 次失败
    for _ in range(settings.auth_max_failed):
        c.post("/api/auth/login", json={"username": username, "password": "wrong-pass"})
    locked = c.post("/api/auth/login", json={"username": username, "password": password})
    assert locked.status_code == 423, f"应被锁定，实际 {locked.status_code}"
    assert "秒后再试" in locked.json()["detail"]

    # 收尾：解锁，避免影响后面的用例（set_password 会清 failed_count / locked_until）
    accounts.set_password(user["user_id"], A.hash_password(password))
    assert _client().post(
        "/api/auth/login", json={"username": username, "password": password}
    ).status_code == 200, "解锁后应能正常登录"


def test_history_account_cannot_login() -> None:
    """`usr_history`（空哈希 + disabled）是老数据的归属壳，**任何密码都不该进去**。"""
    accounts.ensure_history_user()
    r = _client().post("/api/auth/login", json={"username": "history", "password": "anything-123"})
    assert r.status_code == 401


# --------------------------------------------------------------------------
# 3. 存储安全：哈希与令牌
# --------------------------------------------------------------------------


def test_password_is_hashed_not_stored() -> None:
    """库里必须是 bcrypt 哈希，且**明文不出现在任何列**。"""
    username, password = ensure_account("student")
    row = accounts.get_by_username(username, with_hash=True)
    assert row is not None
    assert row["password_hash"].startswith("$2b$"), row["password_hash"][:10]
    assert password not in row["password_hash"]

    # 全表扫一遍：明文不能出现在任何账号的任何列里
    for u in accounts.list_users():
        assert u.get("password_hash") is None, "对外视图不应带出哈希"
        assert password not in str(u)


def test_token_is_stored_hashed() -> None:
    """★ 令牌明文**只存在于响应里**，库里只有 sha256 —— 库被拷走也不能直接用。"""
    from contextlib import closing

    username, password = ensure_account("student")
    raw = _client().post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["token"]
    assert raw and len(raw) > 20

    with closing(accounts.connect()) as conn:
        rows = conn.execute("SELECT token_hash FROM student_token").fetchall()
    hashes = [r["token_hash"] for r in rows]
    assert raw not in hashes, "令牌明文被存进库了"
    import hashlib

    assert hashlib.sha256(raw.encode()).hexdigest() in hashes, "应存 sha256(令牌)"


def test_api_never_returns_password_hash() -> None:
    """所有返回账号的接口都不得含 password_hash。"""
    c = login_client(_client(), "admin")
    payloads = [
        c.get("/api/auth/me").text,
        c.get("/api/admin/students").text,
        c.get("/api/admin/overview").text,
    ]
    for p in payloads:
        assert "password_hash" not in p
        assert "$2b$" not in p


# --------------------------------------------------------------------------
# 4. 令牌生命周期
# --------------------------------------------------------------------------


def test_logout_revokes_token() -> None:
    c = login_client(_client(), "student")
    assert c.get("/api/auth/me").status_code == 200
    assert c.post("/api/auth/logout").status_code == 200
    # logout 之后同一个客户端再请求 → 401（令牌已撤销）
    assert c.get("/api/auth/me").status_code == 401


def test_change_password_kills_old_tokens() -> None:
    """★ 改密必须让**其他设备下线**，而当前设备拿到新令牌直接继续用。"""
    username, password = ensure_account("student")
    client = _client()
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.get("/api/auth/me").status_code == 200

    new_password = "changed-pass-456"
    r = client.post("/api/auth/password", json={"old_password": password, "new_password": new_password})
    assert r.status_code == 200, r.text
    new_token = r.json()["token"]
    assert new_token and new_token != token

    old_device = _client()
    old_device.headers["Authorization"] = f"Bearer {token}"
    assert old_device.get("/api/auth/me").status_code == 401, "旧令牌没有失效"

    current_device = _client()
    current_device.headers["Authorization"] = f"Bearer {new_token}"
    assert current_device.get("/api/auth/me").status_code == 200, "当前设备应无需重新登录"

    # 新密码能登录、旧密码不能
    assert _client().post(
        "/api/auth/login", json={"username": username, "password": new_password}
    ).status_code == 200
    assert _client().post(
        "/api/auth/login", json={"username": username, "password": password}
    ).status_code == 401

    # 收尾：改回固定密码（后面的用例依赖它）
    accounts.set_password(accounts.get_by_username(username)["user_id"], A.hash_password(password))


def test_disable_account_revokes_tokens_immediately() -> None:
    """★ 禁用之后，**已经发出去的令牌立刻失效**（否则他刷新一下还能继续用）。"""
    c, uid = login_fresh(_client())
    assert c.get("/api/auth/me").status_code == 200
    accounts.set_status(uid, accounts.STATUS_DISABLED)
    try:
        assert c.get("/api/auth/me").status_code == 401
    finally:
        accounts.set_status(uid, accounts.STATUS_ACTIVE)


def test_garbage_token_is_401() -> None:
    c = _client()
    for bad in ("", "abc", "Bearer", "x" * 100):
        c.headers["Authorization"] = f"Bearer {bad}"
        assert c.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------
# 5. 输入校验
# --------------------------------------------------------------------------


def test_login_input_validation() -> None:
    c = _client()
    assert c.post("/api/auth/login", json={"username": "", "password": "x"}).status_code == 422
    assert c.post("/api/auth/login", json={"password": "x"}).status_code == 422
    assert c.post("/api/auth/login", json={"username": "a" * 200, "password": "x"}).status_code == 422


def test_weak_password_rejected_on_change() -> None:
    """密码策略：太短 / 与用户名相同都要拒。"""
    username, password = ensure_account("student")
    c = login_client(_client(), "student")
    short = c.post("/api/auth/password", json={"old_password": password, "new_password": "123"})
    assert short.status_code == 422
    same = c.post(
        "/api/auth/password", json={"old_password": password, "new_password": username}
    )
    assert same.status_code == 422


def test_password_longer_than_bcrypt_limit_rejected() -> None:
    """bcrypt 上限 72 字节：**必须明确拒绝，不能静默截断**。"""
    from app.kernel import auth as A

    try:
        A.validate_password("x" * 100, username="t_student")
        raise AssertionError("超长密码没有被拒绝")
    except ValueError as exc:
        assert "72" in str(exc)


def test_username_rules() -> None:
    from app.kernel import auth as A

    for bad in ("ab", "a" * 40, "张三", "has space", "emoji😀"):
        try:
            A.validate_username(bad)
            raise AssertionError(f"非法用户名被接受：{bad!r}")
        except ValueError:
            pass
    A.validate_username("s01")
    A.validate_username("zhang_san-1.x")

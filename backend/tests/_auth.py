"""测试用的登录夹具。

为什么要有它
-----------
接口收紧成"必须登录"之后，所有原本匿名调用的测试都会拿到 401。
与其在每个用例里手写登录，不如：

    with TestClient(app) as client:
        login_client(client)          # ← 一行，之后所有请求自动带令牌
        client.get("/api/me/stats")   # 不用改任何既有调用

原理：`TestClient` 继承自 httpx.Client，`client.headers` 是**默认请求头**，
改一次就作用于这个客户端发出的每个请求。

凭证是固定的（`t_student` / `t_admin`），密码写在下方常量里 ——
它们只存在于测试库里（conftest.py 把 DB_PATH 指到临时文件）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: 测试账号（固定用户名 + 固定密码，便于重复运行）
STUDENT = ("t_student", "test-pass-123")
ADMIN = ("t_admin", "test-pass-123")


def ensure_account(role: str = "student") -> tuple[str, str]:
    """确保测试账号存在且状态正常，返回 `(username, password)`。

    - 不存在就建；
    - 存在就**重置密码并解除锁定** —— 否则上一次跑测试时"连续错 5 次"的锁定
      会让这次整组用例莫名其妙地 423。
    """
    from app.kernel import auth as A
    from app.tools import accounts

    username, password = ADMIN if role == "admin" else STUDENT
    existing = accounts.get_by_username(username)
    if existing is None:
        accounts.create_user(
            username=username,
            password_hash=A.hash_password(password),
            role=role,
            display_name=f"测试{'管理员' if role == 'admin' else '学生'}",
            created_by="tests",
        )
    else:
        accounts.set_password(existing["user_id"], A.hash_password(password))
        accounts.set_status(existing["user_id"], accounts.STATUS_ACTIVE)
    return username, password


def login_client(client, role: str = "student"):
    """登录并把令牌装到客户端默认头上。返回同一个 client。"""
    username, password = ensure_account(role)
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"测试登录失败：{resp.status_code} {resp.text[:200]}"
    client.headers["Authorization"] = f"Bearer {resp.json()['token']}"
    return client


def login_fresh(client, *, role: str = "student"):
    """登录为一个**全新学生**，返回 `(client, user_id)`。

    需要"这个用例的作答只属于它自己"时用它 —— 账号体系之后，隔离维度从
    `session_id`（浏览器）换成了 `user_id`（账号），所以旧的 `_sid()` 隔离法失效了。
    """
    import uuid

    from app.kernel import auth as A
    from app.tools import accounts

    username = f"t_{uuid.uuid4().hex[:10]}"
    password = "test-pass-123"
    user = accounts.create_user(
        username=username,
        password_hash=A.hash_password(password),
        role=role,
        display_name=username,
        created_by="tests",
    )
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"一次性测试账号登录失败：{resp.text[:200]}"
    client.headers["Authorization"] = f"Bearer {resp.json()['token']}"
    return client, user["user_id"]

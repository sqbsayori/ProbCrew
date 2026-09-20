"""管理端 API 单元测试（Sprint 1 标准档）。

守什么
------
管理端能**看学生的学习数据、能删数据**，所以这里的红线是：

1. **不能提权**：接口与 CSV 都不能创建管理员账号；
2. **不能自锁**：管理员不能禁用/删除自己，也不能通过管理端删管理员；
3. **敏感操作必须留痕**：看明细 / 导出 / 删数据 / 重置 / 禁用，都要在审计表里查到；
4. **删除是真删**：作答、问答、掌握度三张表里该账号的行必须归零，且账号被脱敏。

运行：
    cd ProbCrew
    python -m pytest backend/tests/test_admin_api.py -q
"""
from __future__ import annotations

import sys
import uuid
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _auth import login_client, login_fresh  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.kernel import auth as A  # noqa: E402
from app.main import build_app  # noqa: E402
from app.tools import accounts  # noqa: E402


def _admin_client():
    return login_client(TestClient(build_app()), "admin")


def _new_student(prefix: str = "t_a") -> tuple[str, str]:
    """直接在库里建一个学生（走 CLI 那条路），返回 (username, user_id)。"""
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    password = "student-pass-123"
    user = accounts.create_user(
        username=username,
        password_hash=A.hash_password(password),
        role="student",
        display_name=f"学生{username[-4:]}",
        created_by="tests",
    )
    return username, user["user_id"]


def _actions(c, **params) -> list[str]:
    return [i["action"] for i in c.get("/api/admin/audit", params=params).json()["items"]]


# --------------------------------------------------------------------------
# 1. 概览与列表
# --------------------------------------------------------------------------


def test_overview_counts_only_real_students() -> None:
    """★ `usr_history`（迁移过来的匿名老数据）默认**不算进班级统计** ——
    否则 76 条历史记录会把真实学生的数字淹没。

    ⚠️ **必须先 `ensure_history_user()`**（与本文件其它用例一视同仁）：
    `conftest.py` 把 `DB_PATH` 指到一个**空的临时库**，所以
    `usr_history` 在干净环境里**并不存在**（CI / 新 clone 都是如此）。
    少了这一行，`assert "history" in names2` 会永远失败 ——
    它此前只在"作者本机跑过迁移"的机器上偶然通过。
    对照组：`test_auth.py::test_history_account_cannot_login` 就是这么写的。
    """
    accounts.ensure_history_user()
    c = _admin_client()
    default = c.get("/api/admin/overview").json()
    with_history = c.get("/api/admin/overview?include_history=true").json()
    assert default["student_count"] <= with_history["student_count"]
    assert default["total_attempts"] <= with_history["total_attempts"]
    names = [s["username"] for s in c.get("/api/admin/students").json()["items"]]
    assert "history" not in names
    names2 = [s["username"] for s in c.get("/api/admin/students?include_history=true").json()["items"]]
    assert "history" in names2


def test_student_list_pagination_and_search() -> None:
    c = _admin_client()
    username, _uid = _new_student("t_page")
    body = c.get("/api/admin/students", params={"q": username, "page_size": 5}).json()
    assert body["total"] == 1
    assert body["items"][0]["username"] == username
    assert {"page", "page_size", "total", "items"} <= set(body)
    # 列表里不得出现哈希
    assert "password_hash" not in str(body)


def test_student_list_rejects_bad_params() -> None:
    c = _admin_client()
    assert c.get("/api/admin/students", params={"page": 0}).status_code == 422
    assert c.get("/api/admin/students", params={"page_size": 999}).status_code == 422
    assert c.get("/api/admin/students", params={"order": "sideways"}).status_code == 422


# --------------------------------------------------------------------------
# 2. 建号：不能提权
# --------------------------------------------------------------------------


def test_create_student_and_reject_duplicate() -> None:
    c = _admin_client()
    username = f"t_mk_{uuid.uuid4().hex[:8]}"
    r = c.post("/api/admin/students", json={"username": username, "display_name": "测试学生"})
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "student"
    assert r.json()["initial_password"], "应返回一次性初始密码"

    dup = c.post("/api/admin/students", json={"username": username})
    assert dup.status_code == 409

    # 新账号能登录（初始密码可用）
    fresh = TestClient(build_app())
    assert fresh.post(
        "/api/auth/login", json={"username": username, "password": r.json()["initial_password"]}
    ).status_code == 200


def test_create_student_validation() -> None:
    c = _admin_client()
    assert c.post("/api/admin/students", json={"username": "ab"}).status_code == 422
    assert c.post("/api/admin/students", json={"username": "张三"}).status_code == 422
    assert c.post("/api/admin/students", json={"username": "t_weak", "password": "123"}).status_code == 422


def test_api_cannot_create_admin() -> None:
    """★ 提权防线：请求体里塞 `role` 也没用（接口写死 student）。"""
    c = _admin_client()
    username = f"t_esc_{uuid.uuid4().hex[:8]}"
    r = c.post("/api/admin/students", json={"username": username, "role": "admin"})
    assert r.status_code == 201
    created = accounts.get_by_username(username)
    assert created["role"] == "student", "接口竟然能创建管理员"


# --------------------------------------------------------------------------
# 3. CSV 导入
# --------------------------------------------------------------------------


def test_csv_import_reports_each_row() -> None:
    c = _admin_client()
    a = f"t_csv_{uuid.uuid4().hex[:6]}"
    b = f"t_csv_{uuid.uuid4().hex[:6]}"
    csv_text = (
        "username,display_name,password\n"
        f"{a},甲,\n"                      # 自动生成密码
        f"{b},乙,Passw0rd123\n"            # 指定密码
        f"{a},重复,Passw0rd123\n"          # 重复 → skipped
        ",空用户名,x\n"                    # 空 → failed
    )
    body = c.post("/api/admin/students/import", json={"csv_text": csv_text}).json()
    assert body["created"] == 2
    assert len(body["skipped"]) == 1 and body["skipped"][0]["reason"] == "用户名已存在"
    assert len(body["failed"]) == 1 and "为空" in body["failed"][0]["reason"]
    assert {p["username"] for p in body["initial_passwords"]} == {a, b}


def test_csv_import_cannot_create_admin() -> None:
    """★ 提权防线 2：CSV 里冒出来的 role=admin 行必须失败，而不是被静默当学生建。"""
    c = _admin_client()
    csv_text = "username,role\nhack_admin_1,admin\n"
    body = c.post("/api/admin/students/import", json={"csv_text": csv_text}).json()
    assert body["created"] == 0
    assert any("管理员" in f["reason"] for f in body["failed"])
    assert accounts.get_by_username("hack_admin_1") is None


def test_csv_import_rejects_bad_header_and_oversize() -> None:
    c = _admin_client()
    assert c.post("/api/admin/students/import", json={"csv_text": "name,x\n1,2\n"}).status_code == 422
    huge = "username\n" + "\n".join(f"t_huge_{i}" for i in range(600))
    body = c.post("/api/admin/students/import", json={"csv_text": huge}).json()
    assert body["created"] <= 500
    assert any("上限" in f["reason"] for f in body["failed"])


def test_csv_bom_is_accepted() -> None:
    """Excel 导出的 CSV 常带 BOM，不去掉的话表头会变成 '\\ufeffusername'。"""
    c = _admin_client()
    username = f"t_bom_{uuid.uuid4().hex[:6]}"
    body = c.post(
        "/api/admin/students/import", json={"csv_text": f"\ufeffusername,display_name\n{username},BOM\n"}
    ).json()
    assert body["created"] == 1


# --------------------------------------------------------------------------
# 4. 详情 / 重置 / 禁用：留痕 + 立刻生效
# --------------------------------------------------------------------------


def test_view_detail_is_audited() -> None:
    c = _admin_client()
    _username, uid = _new_student("t_det")
    r = c.get(f"/api/admin/students/{uid}")
    assert r.status_code == 200
    assert {"user", "stats", "recent_attempts"} <= set(r.json())
    entries = c.get("/api/admin/audit", params={"action": "view_detail"}).json()["items"]
    assert any(e["target_id"] == uid for e in entries), "查看明细没有留下审计"


def test_reset_password_revokes_tokens() -> None:
    c = _admin_client()
    username, uid = _new_student("t_rst")
    student = login_client(TestClient(build_app()), "student")
    # 用这个学生的身份登录（ensure_account 创建的是公共测试学生，这里直接用库里那个）
    token = TestClient(build_app()).post(
        "/api/auth/login", json={"username": username, "password": "student-pass-123"}
    ).json()["token"]
    student.headers["Authorization"] = f"Bearer {token}"
    assert student.get("/api/auth/me").status_code == 200

    r = c.post(f"/api/admin/students/{uid}/reset-password")
    assert r.status_code == 200
    new_password = r.json()["new_password"]
    assert r.json()["revoked_tokens"] >= 1
    assert student.get("/api/auth/me").status_code == 401, "重置密码后旧令牌应失效"
    assert TestClient(build_app()).post(
        "/api/auth/login", json={"username": username, "password": new_password}
    ).status_code == 200
    assert "password_reset" in _actions(c, action="password_reset")


def test_disable_and_enable_student() -> None:
    c = _admin_client()
    _username, uid = _new_student("t_dis")
    assert c.post(f"/api/admin/students/{uid}/status", json={"status": "disabled"}).status_code == 200
    assert accounts.get_user(uid)["status"] == "disabled"
    assert c.post(f"/api/admin/students/{uid}/status", json={"status": "active"}).status_code == 200
    assert accounts.get_user(uid)["status"] == "active"
    assert c.post(f"/api/admin/students/{uid}/status", json={"status": "hacked"}).status_code == 422
    assert "user_disable" in _actions(c, action="user_disable")


def test_admin_cannot_disable_or_delete_self() -> None:
    """★ 防自锁：对自己做这两件事会把系统锁死（没人能再进来）。"""
    c = _admin_client()
    me = c.get("/api/auth/me").json()["user"]
    if me["role"] != "admin":
        raise AssertionError("测试管理员角色不对")
    r = c.post(f"/api/admin/students/{me['user_id']}/status", json={"status": "disabled"})
    assert r.status_code == 400
    r2 = c.delete(f"/api/admin/students/{me['user_id']}/data")
    assert r2.status_code == 400


def test_admin_cannot_manage_admins() -> None:
    """★ 管理端只能碰学生：对管理员账号做任何操作都要被拒。"""
    c = _admin_client()
    other_admin = accounts.get_by_username("t_admin") or accounts.get_by_username("admin")
    uid = other_admin["user_id"]
    assert c.post(f"/api/admin/students/{uid}/reset-password").status_code == 400
    assert c.post(f"/api/admin/students/{uid}/status", json={"status": "disabled"}).status_code == 400
    assert c.delete(f"/api/admin/students/{uid}/data").status_code == 400


# --------------------------------------------------------------------------
# 5. 删除数据：真删 + 脱敏 + 留痕
# --------------------------------------------------------------------------


def test_delete_data_removes_everything_and_scrubs_account() -> None:
    """★ 隐私承诺的兑现：三张表里该账号的行归零、账号脱敏、审计保留。"""
    c = _admin_client()
    username, uid = _new_student("t_del")

    # 制造数据：一次问答 + 一次作答
    from app.tools import learning_log as L

    L.write_attempt(user_id=uid, item_id="ex-total-prob-01", correct=False, hint_used=1)
    with closing(accounts.connect()) as conn:
        conn.execute(
            "INSERT INTO student_qa_log (user_id, session_id, query, intent, created_at)"
            " VALUES (?,?,?,?,?)",
            (uid, "s_probe", "测试提问原文", "knowledge", 1.0),
        )
        conn.execute(
            "INSERT INTO student_mastery (user_id, topic, attempts, correct, updated_at)"
            " VALUES (?,?,?,?,?)",
            (uid, "kc_probe", 1, 0, 1.0),
        )
        conn.commit()

    r = c.delete(f"/api/admin/students/{uid}/data")
    assert r.status_code == 200, r.text
    deleted = r.json()["deleted"]
    assert deleted["student_attempt"] >= 1
    assert deleted["student_qa_log"] >= 1
    assert deleted["student_mastery"] >= 1

    with closing(accounts.connect()) as conn:
        for table in ("student_attempt", "student_qa_log", "student_mastery"):
            left = conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE user_id=?", (uid,)).fetchone()["c"]
            assert left == 0, f"{table} 还有 {left} 行"

    scrubbed = accounts.get_user(uid)
    assert scrubbed["status"] == "deleted"
    assert scrubbed["username"].startswith("deleted_")
    assert scrubbed["display_name"] == ""

    # 审计必须留着（否则"谁删了数据"就查不到了）
    data_delete = c.get("/api/admin/audit", params={"action": "data_delete"}).json()["items"]
    assert any(e["target_id"] == uid for e in data_delete)


# --------------------------------------------------------------------------
# 6. 导出与审计
# --------------------------------------------------------------------------


def test_export_csv_is_audited_and_excel_friendly() -> None:
    c = _admin_client()
    r = c.get("/api/admin/export/students.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")
    text = r.content.decode("utf-8")
    assert text.startswith("\ufeff"), "缺 BOM，Excel 打开会乱码"
    assert "username,display_name,status" in text
    assert "export_csv" in _actions(c, action="export_csv")


def test_audit_list_shape_and_filters() -> None:
    c = _admin_client()
    body = c.get("/api/admin/audit", params={"page": 1, "page_size": 5}).json()
    assert {"items", "page", "page_size", "total"} <= set(body)
    assert len(body["items"]) <= 5
    one = body["items"][0]
    assert {"audit_id", "actor_id", "action", "target_id", "created_at"} <= set(one)
    filtered = c.get("/api/admin/audit", params={"action": "login"}).json()
    assert all(i["action"] == "login" for i in filtered["items"])


def test_export_csv_headers_are_not_leaked_to_students() -> None:
    """学生连导出都拿不到（403），更不会看到别人的数据。"""
    c = login_client(TestClient(build_app()), "student")
    assert c.get("/api/admin/export/students.csv").status_code == 403
    assert c.get("/api/admin/audit").status_code == 403

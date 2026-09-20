"""「我的数据」接口单元测试（`/api/me/*`）。

守什么
------
`/api/me/*` 是学生看自己数据的新口径，它同时承担两件事：

1. **统计口径正确**：`accuracy` / `hint_used_total` / `wrong_items` 的含义必须与
   `docs/21 §5.3` 一致 —— 这些数字会直接显示给学生，算错就是误导。
2. **★ 越权防护（本文件最重要的一组）**：身份只能来自令牌。
   旧路径 `/api/wrong/{session_id}`、`/api/stats/{session_id}` 保留 URL 形状，
   但**必须忽略路径里的 id** —— 否则"改一个参数就能读别人的错题本"
   （上一轮审计实测到的真实泄漏）会以兼容之名活下来。

运行：
    cd ProbCrew
    python -m pytest backend/tests/test_me_api.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _auth import login_fresh  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.main import build_app  # noqa: E402


def _student():
    """返回 `(client, user_id)`：一个全新学生（账号级隔离）。"""
    return login_fresh(TestClient(build_app()), role="student")


def _answer(c, item_id: str, answer: str, *, hint: int = 0, ms: int = 0) -> None:
    r = c.post(
        "/api/practice/grade",
        json={"item_id": item_id, "student_answer": answer, "hint_used": hint, "duration_ms": ms},
    )
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------
# 1. 统计口径
# --------------------------------------------------------------------------


def test_stats_shape_and_semantics() -> None:
    """统计卡的四个数必须各自都对：作答数 / 答对数 / 错题数 / 用提示次数。"""
    c, _uid = _student()
    _answer(c, "ex-total-prob-01", "0.05")            # 错
    _answer(c, "ex-total-prob-01", "0.026", hint=1)   # 用提示后答对
    _answer(c, "ex-bayes-01", "0.0194")               # 独立答对

    d = c.get("/api/me/stats").json()
    assert d["attempts"] == 3
    assert d["correct"] == 2
    assert d["wrong_items"] == 1                      # 只有第一题错过
    assert d["hint_used_total"] == 1                  # 只有一次用了提示
    assert abs(d["accuracy"] - 2 / 3) < 1e-3
    assert d["total_qa"] == 0                         # 没问过问题（问答与作答是两个指标）
    assert "user" in d and d["user"]["role"] == "student"


def test_stats_empty_state_is_zero_not_null() -> None:
    """0 数据的账号要返回 0 而不是 null —— 前端少一个分支，也少一次崩溃。"""
    c, _uid = _student()
    d = c.get("/api/me/stats").json()
    assert d["attempts"] == 0 and d["correct"] == 0
    assert d["accuracy"] == 0.0 and d["wrong_items"] == 0
    assert d["weak_topics"] == [] and d["recent"] == []


def test_stats_recent_is_newest_first_and_bounded() -> None:
    c, _uid = _student()
    for i in range(3):
        _answer(c, "ex-total-prob-01", str(i + 1))
    recent = c.get("/api/me/stats").json()["recent"]
    assert len(recent) == 3
    assert recent[0]["at"] >= recent[-1]["at"], "最近作答应排在前面"
    assert {"item_id", "correct", "hint_used", "attempt_no", "at"} <= set(recent[0])


def test_attempt_no_counts_per_account_not_per_session() -> None:
    """★ 重做次数要按**账号**累计：换个浏览器重做不该被算成第一次。"""
    c, _uid = _student()
    _answer(c, "ex-bayes-01", "0.0194")
    again = c.post(
        "/api/practice/grade",
        json={"item_id": "ex-bayes-01", "student_answer": "0.0194", "session_id": "另一个浏览器"},
    ).json()
    assert again["attempt_no"] == 2, "换 session 后 attempt_no 被重置了 —— 聚合维度没换成账号"


# --------------------------------------------------------------------------
# 2. 错题本
# --------------------------------------------------------------------------


def test_wrong_book_aggregates_by_item_and_kc() -> None:
    c, _uid = _student()
    _answer(c, "ex-bayes-01", "0.99", hint=2)
    _answer(c, "ex-total-prob-01", "0.026")

    book = c.get("/api/me/wrong").json()
    assert book["total_attempts"] == 2
    assert book["wrong_count"] == 1
    assert book["hinted_wrong_count"] == 1
    item = book["wrong_items"][0]
    assert item["item_id"] == "ex-bayes-01"
    # ★ 标题要给人话标题，不是 ex-bayes-01
    assert item["title"] and item["title"] != "ex-bayes-01"
    assert item["wrong"] == 1 and item["last_correct"] is False
    assert {"by_kc", "wrong_items", "hinted_wrong_count"} <= set(book)


def test_wrong_book_empty_state() -> None:
    c, _uid = _student()
    book = c.get("/api/me/wrong").json()
    assert book["total_attempts"] == 0 and book["wrong_count"] == 0
    assert book["wrong_items"] == [] and book["by_kc"] == []


def test_wrong_book_limit_is_bounded() -> None:
    c, _uid = _student()
    assert c.get("/api/me/wrong", params={"limit": 0}).status_code == 422
    assert c.get("/api/me/wrong", params={"limit": 100000}).status_code == 422


def test_wrong_item_disappears_after_correct_retry() -> None:
    """重做答对之后，`last_correct` 要变成 True（前端据此显示"已订正"）。"""
    c, _uid = _student()
    _answer(c, "ex-total-prob-01", "0.05")
    _answer(c, "ex-total-prob-01", "0.026")
    item = c.get("/api/me/wrong").json()["wrong_items"][0]
    assert item["attempts"] == 2 and item["wrong"] == 1
    assert item["last_correct"] is True


def test_mastery_endpoint_shape() -> None:
    """kc_ids 尚未标注时返回空列表（内容任务），但**字段结构必须在**。"""
    c, _uid = _student()
    _answer(c, "ex-total-prob-01", "0.026")
    d = c.get("/api/me/mastery").json()
    assert "topics" in d and isinstance(d["topics"], list)
    for t in d["topics"]:
        assert {"topic", "attempts", "correct", "accuracy"} <= set(t)


# --------------------------------------------------------------------------
# 3. ★ 越权防护：身份只能来自令牌
# --------------------------------------------------------------------------


def test_two_students_are_isolated() -> None:
    """最基础的一条：A 的作答不会出现在 B 的统计里。"""
    a, _aid = _student()
    b, _bid = _student()
    _answer(a, "ex-total-prob-01", "0.026")

    assert a.get("/api/me/stats").json()["attempts"] == 1
    assert b.get("/api/me/stats").json()["attempts"] == 0
    assert b.get("/api/me/wrong").json()["total_attempts"] == 0


def test_legacy_wrong_path_ignores_the_session_id_in_url() -> None:
    """★★ 计划的负向用例 #2：拿自己的令牌去读**别人的旧路径**，只能拿到自己的数据。

    旧实现把路径里的 `session_id` 当身份 → `GET /api/wrong/随便一个人` 返回 200
    并给出那个人的错题本（实测过的真实泄漏）。现在这个参数**不参与取数**。
    """
    a, _aid = _student()
    _answer(a, "ex-bayes-01", "0.99")  # A 有一条错题

    b, _bid = _student()
    stolen = b.get("/api/wrong/A的session_id")
    assert stolen.status_code == 200
    body = stolen.json()
    assert body["wrong_count"] == 0, "★ 越权：B 读到了 A 的错题本"
    assert body["total_attempts"] == 0
    assert body.get("deprecated"), "旧路径应显式标注已被取代"

    # A 自己走同一条路径，拿到的才是自己那份
    own = a.get("/api/wrong/A的session_id").json()
    assert own["wrong_count"] == 1


def test_legacy_stats_path_ignores_the_session_id_in_url() -> None:
    """同上的统计版本：`/api/stats/{sid}` 也必须只看令牌。"""
    a, _aid = _student()
    _answer(a, "ex-total-prob-01", "0.026")

    b, _bid = _student()
    body = b.get("/api/stats/别人的session").json()
    assert body["attempts"] == 0, "★ 越权：B 通过旧统计路径读到了 A 的数据"
    assert body.get("deprecated")

    assert a.get("/api/stats/别人的session").json()["attempts"] == 1


def test_me_endpoints_require_login() -> None:
    c = TestClient(build_app())
    for path in ("/api/me/stats", "/api/me/wrong", "/api/me/mastery"):
        assert c.get(path).status_code == 401, path


def test_a_students_token_cannot_be_replayed_as_another() -> None:
    """令牌与账号强绑定：拿 A 的令牌只能看到 A。"""
    a, aid = _student()
    _answer(a, "ex-bayes-01", "0.99")
    token = a.headers["Authorization"].split()[-1]

    replay = TestClient(build_app())
    replay.headers["Authorization"] = f"Bearer {token}"
    me = replay.get("/api/auth/me").json()["user"]
    assert me["user_id"] == aid
    assert replay.get("/api/me/wrong").json()["wrong_count"] == 1

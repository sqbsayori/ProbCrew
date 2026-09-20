"""共享读模型（以 `_` 开头 → 不会被 main.py 当路由模块自动挂载）。

为什么单独一个文件
----------------
`/api/me/wrong`（学生看自己的错题本）与 `/api/wrong/{session_id}`（旧路径，
保留兼容）返回的**字段必须逐字一致** —— 否则错题本页要写两套渲染逻辑，
而"旧路径以后删掉"这件事就永远做不成。所以聚合逻辑只写一份，两处都调它。

聚合口径（`docs/21 §2.4` / §5.3）：
* **唯一数据源是 `student_attempt`**，不是 `student_qa_log` ——
  qa_log 只记"他问过什么"，答不出"他答得对不对"；
* 错题 = 有过 `correct=0` 的题；`last_*` 取最近一次；
* 按知识点分组是**主维度**（错题本要沿着知识点找根源，不是按时间翻）；
* `hinted_wrong_count` = 最近一次作答用过提示的错题数 —— 这是"是否在抄"的信号，
  也是 `docs/22` 缺口 3 里唯一不需要真实学生数据就能给老师看的东西。
"""
from __future__ import annotations

from typing import Any

from ..tools import learning_log as L


def wrong_book(user_id: str, *, limit: int = 200) -> dict[str, Any]:
    """按题目 + 按知识点两个维度聚合错题。"""
    rows = L.attempts_for_user(user_id, limit=limit)

    by_item: dict[str, dict[str, Any]] = {}
    for r in rows:  # rows 已按 created_at 倒序
        it = by_item.setdefault(
            r["item_id"],
            {
                "item_id": r["item_id"],
                "title": r["item_id"],  # 题库标题在接口层补（见 _with_titles）
                "attempts": 0,
                "wrong": 0,
                "last_correct": None,
                "last_at": r["created_at"],
                "hint_used_last": r["hint_used"],
                "kc_ids": list(r.get("kc_ids") or []),
            },
        )
        it["attempts"] += 1
        if not r["correct"]:
            it["wrong"] += 1
        if it["last_correct"] is None:  # 倒序遍历 → 第一条即最近一次
            it["last_correct"] = r["correct"]
            it["last_at"] = r["created_at"]
            it["hint_used_last"] = r["hint_used"]
        for k in r.get("kc_ids") or []:
            if k not in it["kc_ids"]:
                it["kc_ids"].append(k)

    wrong_items = [v for v in by_item.values() if v["wrong"] > 0]

    # 按知识点聚合（错题本的主维度，不是时间序）
    by_kc: dict[str, dict[str, Any]] = {}
    for it in by_item.values():
        for k in it["kc_ids"]:
            d = by_kc.setdefault(k, {"kc_id": k, "attempts": 0, "wrong": 0, "items": []})
            d["attempts"] += it["attempts"]
            d["wrong"] += it["wrong"]
            d["items"].append(it["item_id"])
    kc_list = sorted(by_kc.values(), key=lambda d: (-d["wrong"], d["kc_id"]))

    hinted = sum(1 for it in wrong_items if (it.get("hint_used_last") or 0) > 0)
    return {
        "total_attempts": len(rows),
        "wrong_items": wrong_items,
        "by_kc": kc_list,
        "wrong_count": len(wrong_items),
        "hinted_wrong_count": hinted,
    }


def with_titles(result: dict[str, Any], title_of: dict[str, str]) -> dict[str, Any]:
    """给错题补上题干短标题（前端列表要显示"贝叶斯公式 · 疾病检测"而不是 ex-bayes-01）。

    `title_of` 由调用方从题库现取（题库可能改，所以不在答题时冗余存标题）。
    """
    for it in result.get("wrong_items", []):
        it["title"] = title_of.get(it["item_id"], it["item_id"])
    for kc in result.get("by_kc", []):
        kc["titles"] = [title_of.get(i, i) for i in kc["items"]]
    return result


def mastery_list(user_id: str) -> list[dict[str, Any]]:
    """知识点掌握度列表（按正确率升序 —— 最薄弱的排在最前）。"""
    from contextlib import closing

    from ..tools import accounts

    with closing(accounts.connect()) as conn:
        rows = conn.execute(
            "SELECT topic, attempts, correct FROM student_mastery WHERE user_id=?"
            " AND attempts > 0 ORDER BY CAST(correct AS REAL)/attempts ASC",
            (user_id,),
        ).fetchall()
    return [
        {
            "topic": r["topic"],
            "attempts": int(r["attempts"]),
            "correct": int(r["correct"]),
            "accuracy": round(int(r["correct"]) / int(r["attempts"]), 4)
            if r["attempts"]
            else 0.0,
        }
        for r in rows
    ]


def my_stats(user_id: str, *, recent_limit: int = 10) -> dict[str, Any]:
    """主页四张统计卡 + 薄弱点 + 最近作答。

    与旧的 `learning_stats` 工具的区别：这里**同时**给出"问答量"和"作答量" ——
    主页要区分"问了 10 次"和"答对了 7 题"，这是两个完全不同的指标，
    混在一起会让人以为"问得多 = 学得好"。
    """
    from contextlib import closing

    from ..tools import accounts

    with closing(accounts.connect()) as conn:
        total_qa = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM student_qa_log WHERE user_id=?", (user_id,)
            ).fetchone()["c"]
        )
        agg = conn.execute(
            "SELECT COUNT(*) AS attempts, COALESCE(SUM(correct),0) AS correct,"
            " COALESCE(SUM(CASE WHEN correct=0 THEN 1 ELSE 0 END),0) AS wrong,"
            " COALESCE(SUM(CASE WHEN hint_used>0 THEN 1 ELSE 0 END),0) AS hinted"
            " FROM student_attempt WHERE user_id=? AND deleted=0",
            (user_id,),
        ).fetchone()
        recent = conn.execute(
            "SELECT item_id, correct, hint_used, attempt_no, created_at"
            "  FROM student_attempt WHERE user_id=? AND deleted=0"
            " ORDER BY created_at DESC LIMIT ?",
            (user_id, recent_limit),
        ).fetchall()

    attempts = int(agg["attempts"] or 0)
    correct = int(agg["correct"] or 0)
    return {
        "total_qa": total_qa,
        "attempts": attempts,
        "correct": correct,
        "wrong_items": int(agg["wrong"] or 0),
        "hint_used_total": int(agg["hinted"] or 0),
        "accuracy": round(correct / attempts, 4) if attempts else 0.0,
        "weak_topics": mastery_list(user_id)[:5],
        "recent": [
            {
                "item_id": r["item_id"],
                "correct": bool(r["correct"]),
                "hint_used": int(r["hint_used"] or 0),
                "attempt_no": int(r["attempt_no"] or 1),
                "at": r["created_at"],
            }
            for r in recent
        ],
    }

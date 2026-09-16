"""刷题 API —— 主站核心链路的服务端出口（`docs/21` §6，任务 `X5`）。

为什么单独一个模块而不是并进 `problems.py`
----------------------------------------
`problems.py` 服务的是「**题目讲解**」（把题交给 LLM Agent 去讲），
本模块服务的是「**刷题**」（确定性判定 + 记录作答）。两者对"答案"的暴露策略**相反**：

    problems.py   → 讲题，可以把答案给 Agent
    本模块         → 做题，**绝不能**把答案下发给前端

所以拆开，让"不许泄题"这条红线只在一个文件里守。

三条红线（`docs/21` §6.2 / §6.4）
--------------------------------
1. **不下发答案**：`final` / `steps` / `pitfalls` / `distractors` 只在
   **答对**或**显式 `reveal=true`** 时返回。实测 `grader.grade()` 是**无条件**
   返回这些字段的（哪怕答错），所以裁剪必须在这一层做，不能指望 grader。
2. **服务端判定**：前端不持有标准答案、不做本地比对。
3. **服务端记录**：`attempt` 由服务端写，前端不上报，防篡改与漏记。

批改为什么不走 LLM（`docs/21` §6.2）
-----------------------------------
`grader.grade()` 是纯确定性 SymPy 代码，答案比较用符号等价
（`0.026` = `2.6%` = `13/500`）。用概率模型解确定性问题会引入本可避免的误差，
且一次 LLM 协作实测 192 帧 / 31.4 KB，远慢于本地判定。项目的核心卖点是
「生成 / 验证分权」——让 LLM 既出题又批改会把「验证」降级为模型自述。
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..kernel import auth as A
from ..tools import grader
from ..tools import learning_log as L
from . import _aggregate

router = APIRouter(tags=["practice"])

#: ★ 泄题红线：这些键**绝不允许**出现在题目下发接口里，且**答错时不随判定下发**。
#:
#: 注意 `pitfalls`（易错点）与 `diagnosis`（错因诊断）**不在**此列 ——
#: 它们是教学信息而非答案，答错时正是最该给的东西（`docs/22` F5）。
#: 真正要守的是"答案本身"：`final`（标准答案）与 `steps`（逐步数值）。
ANSWER_KEYS = ("final", "steps")


def _public_problem(p: dict[str, Any]) -> dict[str, Any]:
    """把内部题库条目裁成可下发的题目（去掉一切答案相关字段）。"""
    return {
        "id": p.get("id", ""),
        "title": p.get("title", ""),
        "chapter": p.get("chapter", ""),
        "level": p.get("level", ""),
        "problem": p.get("problem", ""),
        "kc_ids": list(p.get("kc_ids") or []),
        "tags": list(p.get("tags") or []),
        "gradable": bool((p.get("final") or {}).get("expr")),
    }


def _hint_payload(p: dict[str, Any], level: int) -> dict[str, Any]:
    """提示阶梯（`docs/21` §4.2，口径唯一权威在那里）。

    L0 = 无提示；L1 = 一句话方向（无数值）；L2 = 步骤骨架（**不含 expr 数值**）。
    """
    level = max(0, min(int(level), 2))
    steps = list(p.get("steps") or [])
    out: dict[str, Any] = {"level": level, "has_hint": bool(p.get("hint"))}
    if level == 0:
        return out
    if level == 1:
        # 缺 hint 时降级拿第一步标题，并**显式标注**（诚实原则，不许静默跳过）
        if p.get("hint"):
            out["text"] = p["hint"]
            out["degraded"] = False
        elif steps:
            out["text"] = f"试着从「{steps[0].get('title', '第一步')}」入手。"
            out["degraded"] = True
            out["note"] = "本题未配置方向提示，已降级为第一步的标题。"
        return out
    # L2：只给 title，**绝不给 expr / display**（那是答案）
    out["steps"] = [{"index": s.get("index"), "title": s.get("title", "")} for s in steps]
    out["note"] = "以上只给步骤名，不给数值 —— 自己算出来再提交。"
    return out


def _redacted_verdict(raw: dict[str, Any], *, reveal: bool) -> dict[str, Any]:
    """裁剪 `grader.grade()` 的返回（`docs/21` §6.4 ②）。

    `grade()` 只要答案能被解析就会返回 `final` 与全部 `steps`（含期望数值），
    因此**答错时也必须裁掉** —— 否则学生提交一个 `0` 就能拿到标准答案，
    提示阶梯形同虚设。
    """
    graded = raw.get("graded")
    out: dict[str, Any] = {
        "ok": bool(raw.get("ok")),
        "available": bool(raw.get("available")),
        "graded": graded,                      # True / False / None（None=未解析出答案）
        "verdict": raw.get("verdict"),          # 中文结论（"正确"/"不正确"）
        "message": raw.get("message", ""),
        "basis": raw.get("basis", ""),          # 判定依据（符号等价 / 数值比较+容差）
        "problem": raw.get("problem", {}),
        "revealed": bool(reveal),
    }
    if raw.get("gradable"):
        out["gradable"] = raw["gradable"]
    if raw.get("error"):
        out["error"] = raw["error"]

    # 错因诊断与易错点：**始终下发**（教学信息，不是答案）。
    # `diagnosis.kind` 实测为 "distractor"（命中干扰项，带针对性解释）
    # 或 "mismatch"（未命中，定位到第几步）。
    if raw.get("diagnosis") is not None:
        out["diagnosis"] = raw["diagnosis"]
    if raw.get("pitfalls") is not None:
        out["pitfalls"] = raw["pitfalls"]

    # ★ 只有答对、或学生显式要求看解析时，才给答案本身
    if graded is True or reveal:
        for k in ANSWER_KEYS:
            if raw.get(k) is not None:
                out[k] = raw[k]
    return out


@router.get("/api/practice/questions", summary="题库列表（不含答案）")
async def list_questions(
    user: A.CurrentUser,
    chapter: str | None = Query(default=None),
    level: str | None = Query(default=None),
    kc: str | None = Query(default=None, description="按知识点 id 过滤"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """列出可做的题。**响应中不含任何答案相关字段**（红线 1）。"""
    items = [p for p in grader.load_bank(strict=False)]

    if chapter:
        items = [p for p in items if p.get("chapter") == chapter]
    if level:
        items = [p for p in items if p.get("level") == level]
    if kc:
        items = [p for p in items if kc in (p.get("kc_ids") or [])]

    all_items = grader.load_bank(strict=False)
    chapters = sorted({p.get("chapter", "") for p in all_items if p.get("chapter")})
    levels = sorted({p.get("level", "") for p in all_items if p.get("level")})
    kcs: list[str] = []
    for p in all_items:
        for k in p.get("kc_ids") or []:
            if k not in kcs:
                kcs.append(k)

    return {
        "count": len(items[:limit]),
        "total": len(items),
        "filters": {"chapters": chapters, "levels": levels, "kc_ids": kcs},
        "items": [_public_problem(p) for p in items[:limit]],
        "note": "不含答案；做题请走 POST /api/practice/grade。",
    }


@router.get("/api/practice/questions/{item_id}", summary="单题题干（可含提示）")
async def get_question(
    item_id: str,
    user: A.CurrentUser,
    hint: int = Query(default=0, ge=0, le=2, description="提示层级 0/1/2，见 docs/21 §4.2"),
) -> dict[str, Any]:
    p = grader._find_problem(item_id)  # noqa: SLF001 —— 同包内复用，避免重复实现
    if p is None:
        raise HTTPException(status_code=404, detail=f"题目 {item_id} 不在题库里")
    return {"problem": _public_problem(p), "hint": _hint_payload(p, hint)}


class GradeRequest(BaseModel):
    item_id: str
    student_answer: str = Field(default="", max_length=200)
    #: ⚠️ 已废弃：身份来自令牌，服务端**不再使用**这个字段。
    #: 保留只是为了让还没改的前端不报 422。有上限是为了不让它成为攻击面。
    session_id: str = Field(default="", max_length=64)
    #: 学生本次答题已用掉的提示次数（0/1/2）。由前端 `hint` 状态传入，服务端只做记录。
    hint_used: int = Field(default=0, ge=0, le=2)
    #: 作答耗时，服务端只在客户端没给时兜底（正常应由前端计时上报）
    duration_ms: int = Field(default=0, ge=0, le=86_400_000)
    #: 显式要求看解析（"我要看解析"按钮）。答错且未 reveal 时**不下发答案**。
    reveal: bool = False


@router.post("/api/practice/grade", summary="判定作答（确定性批改 + 记录 attempt）")
async def grade_answer(req: GradeRequest, user: A.CurrentUser) -> dict[str, Any]:
    """判定一次作答。

    三态语义（`docs/21` §6.4 ①）：
      * `graded=true`  → 正确
      * `graded=false` → 错误（含错因定位）
      * `graded=null`  → **没能解析出答案**，不算错，**不写 attempt**，请学生换个写法

    ⚠️ 两条加固（上一轮审计的实测缺陷，这里必须守住）：
      1. `student_answer` 有长度上限（200 字）。旧版无上限，实测一个 10 万位的
         数字答案会让 `normalize_answer` 里的正则**平方级回溯**，把整个进程卡死两分钟；
         再加上 `9**9**9` 这种短但会算爆的表达式，一个请求就能让全站不可用。
      2. `grader.grade()` 是**纯 CPU 同步调用**，放在 `async def` 里会独占事件循环
         （实测：一个慢请求期间连 `/api/health` 都超时）。所以丢到线程池跑。
    """
    import anyio

    raw = await anyio.to_thread.run_sync(  # type: ignore[attr-defined]
        lambda: grader.grade(problem_id=req.item_id, student_answer=req.student_answer)
    )
    out = _redacted_verdict(raw, reveal=req.reveal)

    if not raw.get("available"):
        # 题目不在题库：不写记录，也不猜答案
        return out

    graded = raw.get("graded")
    if graded is None:
        # ★ 不许把"没看懂写法"记成"答错" —— 否则掌握度直接失真
        out["recorded"] = False
        out["hint_for_user"] = "直接写结果即可，例如 0.026 / 13/500 / 2.6%"
        return out

    problem = grader._find_problem(req.item_id) or {}  # noqa: SLF001
    correct = bool(graded)
    rec = L.write_attempt(
        user_id=user["user_id"],            # ★ 身份只来自令牌
        item_id=req.item_id,
        session_id=req.session_id,          # 仅匿名追踪
        kc_ids=list(problem.get("kc_ids") or []),
        correct=correct,
        score=1.0 if correct else 0.0,
        answer_raw=req.student_answer,
        answer_normalized=str(raw.get("student", {}).get("parsed", "")) or "",
        expected=str((problem.get("final") or {}).get("expr", "")),
        hint_used=req.hint_used,
        duration_ms=req.duration_ms,
        source="practice",
        grader="sympy",
        grader_confidence=1.0,
    )
    out["recorded"] = True
    out["attempt_id"] = rec["attempt_id"]
    out["attempt_no"] = rec["attempt_no"]

    # 掌握度：只把「独立答对」（hint_used=0）计入 correct（docs/21 §5.3 口径）
    topics = list(problem.get("kc_ids") or [])
    if topics:
        independent = correct and req.hint_used == 0
        for t in topics:
            await L.log_mastery(user_id=user["user_id"], topic=t, correct=independent)
    return out


@router.get("/api/wrong/{session_id}", summary="错题本（旧路径，保留兼容）")
async def wrong_book(
    session_id: str,
    user: A.CurrentUser,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    """错题本。**身份以令牌为准**，路径里的 `session_id` 只作日志对照。

    ⚠️ 为什么必须这样：旧实现用路径参数当身份 → 改一个参数就能读别人的错题本
    （上一轮审计实测：`GET /api/wrong/随便一个人` 返回 200）。
    现在这个参数**不参与取数**，只保留在 URL 里让旧前端不 404。
    新前端请用 `/api/me/wrong`。
    """
    result = _aggregate.with_titles(
        _aggregate.wrong_book(user["user_id"], limit=limit),
        {p["id"]: p.get("title", p["id"]) for p in grader.load_bank(strict=False)},
    )
    result["session_id"] = session_id
    result["deprecated"] = "旧路径：身份已改为以令牌为准，请改用 /api/me/wrong"
    result["note"] = "数据源为 student_attempt（本地、按账号归属、不出校）。"
    return result

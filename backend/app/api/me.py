"""我的数据 API —— 学生的"自己这一摊"。

为什么和 `/api/wrong/{session_id}` 并存
------------------------------------
旧路径以**路径参数里的 session_id** 作为身份，在账号体系下等于把身份交给了调用方：
改一个参数就能读别人的数据（这正是上一轮审计里实测到的越权）。
新路径 `/api/me/*` 的身份**只来自令牌**，路径里没有任何可以伪造的标识。

旧路径暂时保留（前端还在用），但服务端会**忽略路径里的 id、强制用自己的身份**，
所以它不再是漏洞；等页面全部切到 `/api/me/*` 后删掉。

字段约定：`/api/me/wrong` 与旧接口**逐字一致**（共用 `_aggregate.wrong_book`），
错题本页不用写两套渲染。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ..kernel import auth as A
from ..tools import grader
from . import _aggregate

router = APIRouter(tags=["me"])


def _title_map() -> dict[str, str]:
    """`{题目 id: 标题}`，给错题本列表显示人话标题用。"""
    return {p["id"]: p.get("title", p["id"]) for p in grader.load_bank(strict=False)}


@router.get("/api/me/stats", summary="我的学习统计（主页用）")
async def my_stats(user: A.CurrentUser) -> dict[str, Any]:
    data = _aggregate.my_stats(user["user_id"])
    data["user"] = user
    return data


@router.get("/api/me/wrong", summary="我的错题本（按知识点聚合）")
async def my_wrong(
    user: A.CurrentUser, limit: int = Query(default=200, ge=1, le=1000)
) -> dict[str, Any]:
    result = _aggregate.with_titles(_aggregate.wrong_book(user["user_id"], limit=limit), _title_map())
    result["user_id"] = user["user_id"]
    result["note"] = "数据源为 student_attempt（本地、按账号归属、不出校）。"
    return result


@router.get("/api/me/mastery", summary="我的知识点掌握度")
async def my_mastery(user: A.CurrentUser) -> dict[str, Any]:
    return {"user_id": user["user_id"], "topics": _aggregate.mastery_list(user["user_id"])}

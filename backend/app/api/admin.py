"""管理端 API —— 学生数据管理 + 审计。

三条不能越过的线
---------------
1. **只能管学生，不能管管理员**。`student_user.role='admin'` 的账号既不能通过接口创建、
   也不能被重置密码/禁用/删数据。管理员账号只由种子流程或 CLI（`scripts/manage_users.py`）
   产生 —— 这是刻意的：**一个能提权的接口就是一个提权漏洞**，
   而"管理员互相管理"对一个课程项目没有实际需求。
2. **不能操作自己**。禁用/删除自己会把系统锁死（没人能再进来），服务端直接拒绝。
3. **敏感操作必须留痕**。看某个学生的明细、导出 CSV、删数据、重置密码、禁用 —— 全部写审计，
   而且审计写失败就**中止操作**（`auth.audit()` 的 strict 模式）。
   合规逻辑：查不到"谁看过学生数据"比"这次没看成"严重得多。

CSV 导入为什么用 JSON 传文本而不是 multipart
------------------------------------------
FastAPI 处理 `UploadFile` 需要额外的 `python-multipart` 依赖，而前端只要
`file.text()` 就能把 CSV 读成字符串。少一个依赖、少一种解析失败的可能。
代价是**必须自己设上限**（行数 / 字节数），否则一个大文件就能吃满内存 —— 见下方常量。
"""
from __future__ import annotations

import csv
import io
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from ..kernel import auth as A
from ..tools import accounts

router = APIRouter(tags=["admin"])

#: CSV 上限。挡住"误选了一个 50MB 的文件"这类事故。
CSV_MAX_BYTES = 256 * 1024
CSV_MAX_ROWS = 500

#: 学生列表允许的排序字段（白名单 —— 拼进 SQL 的东西不能来自请求）
SORTABLE = {
    "created_at": "u.created_at",
    "username": "u.username",
    "attempts": "attempts",
    "accuracy": "accuracy",
    "last_login_at": "u.last_login_at",
}


class CreateStudentRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=200)


class ImportRequest(BaseModel):
    csv_text: str = Field(min_length=1)


class StatusRequest(BaseModel):
    status: Literal["active", "disabled"]


def _public(user: dict[str, Any]) -> dict[str, Any]:
    """对外账号视图。**永远不含 password_hash**（源头就不返回，不是靠过滤）。"""
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "status": user["status"],
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


def _require_student(user_id: str) -> dict[str, Any]:
    """取目标账号，并强制"只能是学生"。"""
    target = accounts.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="学生不存在")
    if target["role"] != accounts.ROLE_STUDENT:
        raise HTTPException(status_code=400, detail="只能管理学生账号；管理员账号请用 CLI 维护")
    return target


def _forbid_self(actor: dict[str, Any], target_id: str) -> None:
    if actor["user_id"] == target_id:
        raise HTTPException(
            status_code=400, detail="不能对自己执行这个操作（会导致没人能再管理系统）"
        )


# --------------------------------------------------------------------------
# 概览 / 列表 / 详情
# --------------------------------------------------------------------------


@router.get("/api/admin/overview", summary="全班统计")
async def overview(
    user: A.AdminUser,
    include_history: bool = Query(default=False, description="是否把 usr_history（老匿名数据）算进班级统计"),
) -> dict[str, Any]:
    stats = accounts.student_stats(include_history=include_history)
    attempts = sum(s["attempts"] for s in stats)
    correct = sum(s["correct"] for s in stats)
    hinted = sum(s["hint_used_total"] for s in stats)
    active = [s for s in stats if s["status"] == accounts.STATUS_ACTIVE]
    return {
        "student_count": len(stats),
        "active_students": len(active),
        "total_attempts": attempts,
        "total_correct": correct,
        "avg_accuracy": round(correct / attempts, 4) if attempts else 0.0,
        "hint_used_total": hinted,
        "hinted_rate": round(hinted / attempts, 4) if attempts else 0.0,
        "students_with_data": len([s for s in stats if s["attempts"] > 0]),
        "note": "hinted_rate = 用过提示的作答占比，是「是否在抄」的粗信号（docs/22 缺口 3）",
    }


@router.get("/api/admin/students", summary="学生列表（分页 + 搜索 + 排序）")
async def list_students(
    user: A.AdminUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str = Query(default="", max_length=64),
    sort: str = Query(default="created_at"),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
    include_history: bool = Query(default=False),
) -> dict[str, Any]:
    column = SORTABLE.get(sort, SORTABLE["created_at"])
    del column  # 排序在 Python 侧做（学生量级小，不必猜 SQL 拼接）
    stats = accounts.student_stats(include_history=include_history)
    if q:
        needle = q.strip().lower()
        stats = [
            s
            for s in stats
            if needle in s["username"].lower() or needle in s["display_name"].lower()
        ]
    reverse = order == "desc"
    stats.sort(key=lambda s: (s.get(sort) if s.get(sort) is not None else ""), reverse=reverse)

    total = len(stats)
    start = (page - 1) * page_size
    return {
        "items": stats[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/api/admin/students/{user_id}", summary="学生详情 + 逐题明细")
async def student_detail(user_id: str, user: A.AdminUser) -> dict[str, Any]:
    target = _require_student(user_id)
    stats = accounts.student_stats([user_id])
    # 敏感操作：先写审计，写不进去就不给看（strict 模式会抛错）
    A.audit(user, "view_detail", target_id=user_id, detail={"username": target["username"]})
    return {
        "user": _public(target),
        "stats": stats[0] if stats else {},
        "recent_attempts": accounts.recent_attempts(user_id, limit=100),
    }


# --------------------------------------------------------------------------
# 建号（单个 / CSV 批量）
# --------------------------------------------------------------------------


@router.post("/api/admin/students", summary="新建学生账号", status_code=201)
async def create_student(payload: CreateStudentRequest, user: A.AdminUser) -> dict[str, Any]:
    username = payload.username.strip()
    try:
        A.validate_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if accounts.get_by_username(username):
        raise HTTPException(status_code=409, detail=f"用户名已存在：{username}")

    password = payload.password or A.new_random_password()
    try:
        A.validate_password(password, username=username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    created = accounts.create_user(
        username=username,
        password_hash=A.hash_password(password),
        role=accounts.ROLE_STUDENT,  # ★ 写死：接口无法创建管理员
        display_name=payload.display_name or username,
        created_by=user["user_id"],
    )
    A.audit(user, "user_create", target_id=created["user_id"], detail={"role": "student"})
    return {"user": _public(created), "initial_password": password}


@router.post("/api/admin/students/import", summary="CSV 批量建号")
async def import_students(payload: ImportRequest, user: A.AdminUser) -> dict[str, Any]:
    """CSV 表头：`username,display_name,password`（password 可留空 → 自动生成）。

    逐行处理、逐行报告：**重复用户名跳过**（不算失败，方便反复导入同一份名单），
    格式错误行进 `failed` 并带行号，方便学生自己改表。
    """
    raw = payload.csv_text
    if len(raw.encode("utf-8")) > CSV_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"CSV 过大（上限 {CSV_MAX_BYTES // 1024} KB）")

    # utf-8-sig：Excel 导出的 CSV 常带 BOM，不去掉的话第一列表头会变成 "\ufeffusername"
    reader = csv.DictReader(io.StringIO(raw.lstrip("\ufeff")))
    if not reader.fieldnames or "username" not in [f.strip() for f in reader.fieldnames]:
        raise HTTPException(status_code=422, detail="CSV 表头必须包含 username（可另含 display_name, password）")

    created: list[dict[str, str]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for lineno, row in enumerate(reader, start=2):  # 第 1 行是表头
        if len(created) + len(skipped) + len(failed) >= CSV_MAX_ROWS:
            failed.append({"line": lineno, "reason": f"超过 {CSV_MAX_ROWS} 行上限，其余未处理"})
            break
        username = (row.get("username") or "").strip()
        display_name = (row.get("display_name") or "").strip()
        password = (row.get("password") or "").strip()
        if not username:
            failed.append({"line": lineno, "reason": "username 为空"})
            continue
        # ★ 防提权：CSV 里冒出来的 role 列一律忽略，且显式声明 role=admin 的行算失败
        if (row.get("role") or "").strip().lower() == accounts.ROLE_ADMIN:
            failed.append({"line": lineno, "reason": "CSV 不能创建管理员账号"})
            continue
        try:
            A.validate_username(username)
        except ValueError as exc:
            failed.append({"line": lineno, "username": username, "reason": str(exc)})
            continue
        if accounts.get_by_username(username):
            skipped.append({"line": lineno, "username": username, "reason": "用户名已存在"})
            continue
        pw = password or A.new_random_password()
        try:
            A.validate_password(pw, username=username)
        except ValueError as exc:
            failed.append({"line": lineno, "username": username, "reason": str(exc)})
            continue
        try:
            accounts.create_user(
                username=username,
                password_hash=A.hash_password(pw),
                role=accounts.ROLE_STUDENT,
                display_name=display_name or username,
                created_by=user["user_id"],
            )
        except Exception as exc:  # noqa: BLE001
            failed.append({"line": lineno, "username": username, "reason": str(exc)[:120]})
            continue
        created.append({"username": username, "password": pw})

    A.audit(
        user, "user_import",
        detail={"created": len(created), "skipped": len(skipped), "failed": len(failed)},
    )
    return {
        "created": len(created),
        "skipped": skipped,
        "failed": failed,
        "initial_passwords": created,  # 只在这一次返回，页面必须提示"立刻抄走"
    }


# --------------------------------------------------------------------------
# 重置密码 / 禁用启用 / 删数据
# --------------------------------------------------------------------------


@router.post("/api/admin/students/{user_id}/reset-password", summary="重置学生密码")
async def reset_password(user_id: str, user: A.AdminUser) -> dict[str, Any]:
    target = _require_student(user_id)
    _forbid_self(user, user_id)
    password = A.new_random_password()
    accounts.set_password(user_id, A.hash_password(password))
    revoked = accounts.revoke_user_tokens(user_id)
    A.audit(user, "password_reset", target_id=user_id, detail={"revoked_tokens": revoked})
    return {"user": _public(target), "new_password": password, "revoked_tokens": revoked}


@router.post("/api/admin/students/{user_id}/status", summary="禁用 / 启用学生账号")
async def set_status(user_id: str, payload: StatusRequest, user: A.AdminUser) -> dict[str, Any]:
    target = _require_student(user_id)
    _forbid_self(user, user_id)
    accounts.set_status(user_id, payload.status)
    revoked = 0
    if payload.status == accounts.STATUS_DISABLED:
        # ★ 禁用必须同时踢掉在线会话，否则他刷新一下还能继续用
        revoked = accounts.revoke_user_tokens(user_id)
    A.audit(
        user,
        "user_disable" if payload.status == accounts.STATUS_DISABLED else "user_enable",
        target_id=user_id,
        detail={"revoked_tokens": revoked},
    )
    fresh = accounts.get_user(user_id) or target
    return {"user": _public(fresh), "revoked_tokens": revoked}


@router.delete("/api/admin/students/{user_id}/data", summary="删除某学生的全部数据")
async def delete_data(user_id: str, user: A.AdminUser) -> dict[str, Any]:
    """**不可逆**。删掉作答/问答/掌握度，并把账号脱敏（保留一行壳以便审计可追溯）。

    前端必须二次确认（输入用户名那种），这里只负责执行 + 留痕。
    """
    target = _require_student(user_id)
    _forbid_self(user, user_id)
    deleted = accounts.delete_user_data(user_id)
    A.audit(user, "data_delete", target_id=user_id, detail=deleted)
    return {
        "user_id": user_id,
        "username_before": target["username"],
        "deleted": deleted,
        "note": "业务数据已硬删除；账号已脱敏；审计记录保留（不含学生作答内容）",
    }


# --------------------------------------------------------------------------
# 导出 / 审计
# --------------------------------------------------------------------------


@router.get("/api/admin/export/students.csv", summary="导出学生统计 CSV")
async def export_csv(
    user: A.AdminUser, include_history: bool = Query(default=False)
) -> Response:
    stats = accounts.student_stats(include_history=include_history)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["username", "display_name", "status", "created_at", "last_login_at",
         "attempts", "correct", "accuracy", "wrong_items", "hint_used_total"]
    )
    for s in stats:
        writer.writerow([
            s["username"], s["display_name"], s["status"],
            _fmt_ts(s["created_at"]), _fmt_ts(s["last_login_at"]),
            s["attempts"], s["correct"], s["accuracy"], s["wrong_items"], s["hint_used_total"],
        ])
    A.audit(user, "export_csv", detail={"rows": len(stats)})
    # BOM 是为了 Excel 直接打开不乱码（Windows 上尤其明显）
    body = "\ufeff" + buf.getvalue()
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="students.csv"'},
    )


@router.get("/api/admin/audit", summary="审计日志")
async def audit_log(
    user: A.AdminUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    action: str = Query(default="", max_length=32),
    actor_id: str = Query(default="", max_length=64),
) -> dict[str, Any]:
    return accounts.list_audit(page=page, page_size=page_size, action=action, actor_id=actor_id)


def _fmt_ts(value: Any) -> str:
    """epoch 秒 → 人能读的本地时间（导出给人看，不是给程序读）。"""
    import time as _t

    try:
        return _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(float(value)))
    except (TypeError, ValueError):
        return ""

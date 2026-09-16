"""认证 API —— 登录 / 当前用户 / 登出 / 改密。

四个端点都在这里，因为它们是**同一件事的四个动作**（拿到身份、确认身份、
交还身份、换凭证）。业务逻辑在 `kernel/auth.py`，本文件只做 HTTP 包装
（参数校验 + 状态码 + 审计），这样 CLI 与测试也能复用同一套逻辑。

前端约定（契约见 `contracts/api.md`）：
    POST /api/auth/login      {username, password} → {token, expires_at, user}
    GET  /api/auth/me         → {user}
    POST /api/auth/logout     → {ok}
    POST /api/auth/password   {old_password, new_password} → {token, expires_at, user}

错误码（前端要分别给文案，别笼统写"登录失败"）：
    401 用户名或密码不正确 · 403 账号已被禁用 · 423 尝试次数过多（附剩余秒数）· 422 参数格式错
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..config import settings
from ..kernel import auth as A
from ..tools import accounts

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class PasswordChangeRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


def _client_ip(request: Request) -> str:
    """取客户端 IP。

    ⚠️ 只用于审计与排查，**不作为任何安全判据**：`X-Forwarded-For` 是客户端可伪造的，
    真正的部署环境要在 Nginx 层覆盖它（见 `deployment/nginx.conf`）。
    """
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.post("/api/auth/login", summary="登录（返回服务端会话令牌）")
async def login(req: LoginRequest, request: Request) -> dict[str, Any]:
    return A.login(
        username=req.username,
        password=req.password,
        user_agent=request.headers.get("user-agent", ""),
        ip=_client_ip(request),
    )


@router.get("/api/auth/me", summary="当前登录用户")
async def me(user: A.CurrentUser) -> dict[str, Any]:
    return {"user": user}


@router.post("/api/auth/logout", summary="登出（撤销当前令牌）")
async def logout(request: Request, user: A.CurrentUser) -> dict[str, Any]:
    A.audit(user, "logout", target_id=user["user_id"])
    accounts.revoke_token(A.bearer_token(request))
    return {"ok": True}


@router.post("/api/auth/password", summary="修改自己的密码")
async def change_password(
    req: PasswordChangeRequest, request: Request, user: A.CurrentUser
) -> dict[str, Any]:
    """改密 → **撤销该用户全部令牌** → 给当前设备发一张新的。

    这样"我在别处登录过"的会话会立刻失效，而我自己不用重新登录。
    """
    row = accounts.get_by_username(user["username"], with_hash=True)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")

    if not A.verify_password(req.old_password, row.get("password_hash", "")):
        # 旧密码错也要留痕：这是"有人拿到了别人的电脑"的典型信号
        A._audit_safe(  # noqa: SLF001 —— 同包内的审计助手
            actor_id=user["user_id"], actor_role=user["role"],
            action="password_change_failed", target_id=user["user_id"], strict=False,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="原密码不正确")

    try:
        A.validate_password(req.new_password, username=user["username"])
    except ValueError as exc:
        # 用字面量 422 而不是 status.HTTP_422_UNPROCESSABLE_ENTITY：
        # 后者在 FastAPI 0.141 起已更名（HTTP_422_UNPROCESSABLE_CONTENT），
        # 用常量会在新版本上发 DeprecationWarning、在旧版本上不存在，字面量两边都稳。
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if A.verify_password(req.new_password, row.get("password_hash", "")):
        raise HTTPException(status_code=422, detail="新密码不能与原密码相同")

    accounts.set_password(user["user_id"], A.hash_password(req.new_password))
    accounts.revoke_user_tokens(user["user_id"])
    token = accounts.issue_token(
        user["user_id"],
        ttl_days=settings.auth_token_ttl_days,
        user_agent=request.headers.get("user-agent", ""),
        ip=_client_ip(request),
    )
    A.audit(user, "password_change", target_id=user["user_id"])
    fresh = accounts.get_user(user["user_id"]) or {}
    return {"token": token["token"], "expires_at": token["expires_at"], "user": fresh}

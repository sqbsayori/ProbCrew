"""认证核心 —— 密码哈希、令牌、FastAPI 身份依赖、种子管理员。

为什么放在 `kernel/` 而不是 `tools/`
----------------------------------
工具（tools）是"Agent 可以调用的能力"；认证是**每个请求的前置条件**，
和 `specs.py` / `registry.py` 一样属于内核。而且它必须能被 api 层与测试直接依赖，
不应该绕一圈经过 ToolRegistry。

三条安全约定
-----------
1. **密码只以 bcrypt 哈希落库**，任何响应里都不出现 `password_hash`。
2. **登录失败不区分"用户名不存在"与"密码错"**，且用户名不存在时也要做一次
   dummy 哈希校验 —— 否则响应时间会泄露"这个用户名存在"，等于送人脸识别名单。
3. **改密 / 重置 / 禁用 / 删数据一律撤销该用户全部令牌** ——
   "改了密码但旧设备还能用"是最常见的越权漏洞。
"""
from __future__ import annotations

import logging
import secrets
import time
from typing import Annotated, Any, Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status

from ..config import settings
from ..tools import accounts

log = logging.getLogger("probcrew.auth")

#: bcrypt 的硬上限是 72 字节。**超过必须拒绝，不能悄悄截断** ——
#: 截断意味着 "abc...(72字节)...xyz" 与 "abc...(72字节)" 是同一个密码。
MIN_PASSWORD_BYTES = 8
MAX_PASSWORD_BYTES = 72

#: 用户名允许的字符：留白很窄是有意的 —— 用户名是**登录标识**，不是昵称。
#: 中文显示名请放 display_name，避免全角/半角、大小写、空格的歧义。
USERNAME_MIN = 3
USERNAME_MAX = 32

#: 用户名不存在时用来消耗时间的固定哈希（明文是 "dummy-password-for-timing"）。
#: 生成一次即可：它的唯一作用是让"用户不存在"和"密码错"耗时接近。
#: 惰性生成 —— 强度来自配置，测试里会调低（见 config.auth_bcrypt_rounds）。
_DUMMY_HASH: bytes | None = None


def _rounds() -> int:
    """bcrypt 强度。允许 4–15（4 只给测试用）。"""
    try:
        return max(4, min(int(settings.auth_bcrypt_rounds), 15))
    except (TypeError, ValueError):
        return 12


def _dummy_hash() -> bytes:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt(rounds=_rounds()))
    return _DUMMY_HASH


# --------------------------------------------------------------------------
# 密码
# --------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_rounds())).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码。哈希为空（历史账号）直接 False —— 空哈希 = 不可登录。"""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def burn_time() -> None:
    """用户名不存在时调用：做一次等价开销的哈希校验，抹平响应时间差。"""
    bcrypt.checkpw(b"dummy-password-for-timing", _dummy_hash())


def validate_password(password: str, *, username: str = "") -> None:
    """密码策略（标准档）。不合格抛 `ValueError`，调用方转 422。"""
    raw = (password or "").encode("utf-8")
    if len(raw) < MIN_PASSWORD_BYTES:
        raise ValueError(f"密码至少 {MIN_PASSWORD_BYTES} 位")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError(f"密码过长（bcrypt 上限 {MAX_PASSWORD_BYTES} 字节），请缩短")
    if username and password.strip().lower() == username.strip().lower():
        raise ValueError("密码不能与用户名相同")


def validate_username(username: str) -> None:
    name = (username or "").strip()
    if not (USERNAME_MIN <= len(name) <= USERNAME_MAX):
        raise ValueError(f"用户名长度需 {USERNAME_MIN}–{USERNAME_MAX} 位")
    if not all(c.isascii() and (c.isalnum() or c in "_.-") for c in name):
        raise ValueError("用户名只能包含字母、数字、下划线、点、连字符（显示名请填 display_name）")


def new_random_password() -> str:
    """给"批量建号"用的可读随机密码：3 段词 + 数字，方便口头传达。"""
    return f"pc-{secrets.token_hex(3)}-{secrets.randbelow(9000) + 1000}"


# --------------------------------------------------------------------------
# 令牌 / 请求身份
# --------------------------------------------------------------------------

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="未登录或登录已过期，请重新登录",
    headers={"WWW-Authenticate": "Bearer"},
)


def bearer_token(request: Request) -> str:
    """从 `Authorization: Bearer <token>` 取令牌；没有则空串。"""
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def current_user(request: Request) -> dict[str, Any]:
    """FastAPI 依赖：解析登录态。无效一律 401。

    同步函数 → FastAPI 会把它丢进线程池跑，因此这里的 sqlite 调用
    **不会阻塞事件循环**（这是上一个版本用 `async def` 直接跑 SymPy 把全站卡死
    的教训，见 `docs/notes/已知问题.md` 待补一条）。
    """
    user = accounts.resolve_token(bearer_token(request))
    if user is None:
        raise UNAUTHORIZED
    return user


def require_admin(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    """FastAPI 依赖：必须是管理员。

    ⚠️ 前端把菜单藏起来**不是**权限控制；这里是唯一的权限判定点。
    """
    if user.get("role") != accounts.ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


CurrentUser = Annotated[dict[str, Any], Depends(current_user)]
AdminUser = Annotated[dict[str, Any], Depends(require_admin)]


# --------------------------------------------------------------------------
# 登录（业务逻辑放这里，api 层只做 HTTP 包装）
# --------------------------------------------------------------------------

#: 登录失败的返回体。**不区分"用户名不存在"与"密码错"** —— 见文件头约定 2。
BAD_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码不正确"
)


def login(*, username: str, password: str, user_agent: str = "", ip: str = "") -> dict[str, Any]:
    """登录 → `{token, expires_at, user}`；失败抛 HTTPException。

    判定顺序是有讲究的：先抹平时间差 → 再查锁定 → 再验密码，
    这样"被锁定的账号"和"密码错的账号"也给出不同的错误码（423 vs 401），
    前端才能给出"再等 N 秒"而不是笼统的"登录失败"。
    """
    name = (username or "").strip()
    row = accounts.get_by_username(name, with_hash=True)

    if row is None:
        burn_time()
        _audit_login_failure(None, name, "no_such_user")
        raise BAD_CREDENTIALS

    user_id = row["user_id"]

    # 历史账号（空哈希）与已删除账号：一律当作凭证错误，且不透露原因
    if row["status"] == accounts.STATUS_DELETED or not row.get("password_hash"):
        burn_time()
        _audit_login_failure(user_id, name, "unusable_account")
        raise BAD_CREDENTIALS

    locked_until = float(row.get("locked_until") or 0)
    now = time.time()
    if locked_until > now:
        _audit_login_failure(user_id, name, "locked")
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"尝试次数过多，请 {int(locked_until - now) + 1} 秒后再试",
        )

    if not verify_password(password, row["password_hash"]):
        result = accounts.note_login_failure(
            user_id,
            max_failed=settings.auth_max_failed,
            lock_seconds=settings.auth_lock_seconds,
        )
        _audit_login_failure(user_id, name, "bad_password" if not result["locked"] else "now_locked")
        if result["locked"]:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"尝试次数过多，请 {settings.auth_lock_seconds} 秒后再试",
            )
        raise BAD_CREDENTIALS

    if row["status"] == accounts.STATUS_DISABLED:
        _audit_login_failure(user_id, name, "disabled")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用，请联系管理员"
        )

    token = accounts.issue_token(
        user_id, ttl_days=settings.auth_token_ttl_days, user_agent=user_agent, ip=ip
    )
    accounts.note_login_success(user_id)
    fresh = accounts.get_user(user_id) or {}
    _audit_safe(
        actor_id=user_id, actor_role=fresh.get("role", ""), action="login", target_id=user_id
    )
    return {"token": token["token"], "expires_at": token["expires_at"], "user": fresh}


def _audit_login_failure(user_id: Optional[str], username: str, reason: str) -> None:
    """登录失败也留痕（限速与排查都靠它）。**写失败不阻断登录流程**。"""
    _audit_safe(
        actor_id=user_id or "",
        actor_role="",
        action="login_failed",
        target_id=user_id or "",
        detail={"username": username, "reason": reason},
        strict=False,
    )


def _audit_safe(
    *,
    actor_id: str,
    actor_role: str,
    action: str,
    target_id: str = "",
    detail: dict[str, Any] | None = None,
    strict: bool = True,
) -> None:
    """写审计。

    `strict=True`（默认）用于**敏感操作**（看学生明细 / 导出 / 删数据 / 重置 / 禁用）：
    写不进去就抛错、让业务一起回滚 —— 合规优先，"查不到谁看过数据"比"这次没看成"更糟。
    `strict=False` 用于登录事件：审计失败不该妨碍学生登录。
    """
    try:
        accounts.write_audit(
            actor_id=actor_id, actor_role=actor_role, action=action,
            target_id=target_id, detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("审计写入失败 action=%s actor=%s: %s", action, actor_id, exc)
        if strict:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="审计日志写入失败，操作已中止（请联系管理员）",
            ) from exc


def audit(
    actor: dict[str, Any],
    action: str,
    *,
    target_id: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    """给 api 层用的便捷入口（自动带 actor 信息）。"""
    _audit_safe(
        actor_id=actor.get("user_id", ""),
        actor_role=actor.get("role", ""),
        action=action,
        target_id=target_id,
        detail=detail,
    )


# --------------------------------------------------------------------------
# 种子管理员
# --------------------------------------------------------------------------


def ensure_seed_admin() -> Optional[dict[str, Any]]:
    """库里一个管理员都没有时，用 `ADMIN_INIT_*` 建一个。

    - 配了 `ADMIN_INIT_PASSWORD` 就用它；没配则生成随机密码并**打印到启动日志**。
    - 已经有管理员 → 什么都不做（绝不在每次启动时重置管理员密码）。

    返回新建的账号（含明文密码字段 `_initial_password`，仅供启动日志打印），
    或 None 表示"已存在，无需处理"。
    """
    try:
        if accounts.count_admins() > 0:
            return None
    except Exception as exc:  # noqa: BLE001 —— 库坏了也要让服务起来，由 /api/health 报出来
        log.warning("检查管理员账号失败：%s", exc)
        return None

    username = (settings.admin_init_username or "admin").strip()
    password = settings.admin_init_password.strip() or new_random_password()
    try:
        validate_username(username)
        validate_password(password, username=username)
        user = accounts.create_user(
            username=username,
            password_hash=hash_password(password),
            role=accounts.ROLE_ADMIN,
            display_name="管理员",
            created_by="seed",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("种子管理员创建失败：%s", exc)
        return None

    user["_initial_password"] = password
    try:
        accounts.write_audit(
            actor_id="seed", actor_role=accounts.ROLE_ADMIN,
            action="user_create", target_id=user["user_id"], detail={"role": "admin", "seed": True},
        )
    except Exception:  # noqa: BLE001
        pass
    return user

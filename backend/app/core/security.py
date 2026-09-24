"""密码哈希与 JWT。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

settings = get_settings()

# 封号响应体：只回传机器码，不回传任何可读文案。
# 前端据此静默拦截（不渲染任何提示），避免被封用户从提示中反推封禁原因或绕过方式。
BANNED_DETAIL: dict[str, str] = {"code": "banned"}
# 会话被顶替（同一账号在其它端登录，见 `users.session_epoch`）。前端据此提示并要求重新登录。
SESSION_REPLACED_DETAIL: dict[str, str] = {"code": "session_replaced"}
# 同一设备并发在线超限（见 services/devices.enforce_online_limit）。前端据此暂停本账号活动。
DEVICE_LIMIT_DETAIL: dict[str, str] = {"code": "device_limit"}

# 服务端签发的设备 Cookie：前端清 localStorage 换不掉它，抬高「换指纹绕过注册上限」的成本。
DEVICE_COOKIE_NAME = "eorzea_device"
DEVICE_COOKIE_MAX_AGE = 365 * 24 * 3600


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, epoch: int = 0) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        # 会话纪元：与 `users.session_epoch` 比较，不一致即视为已过期（单端登录）。
        "ep": int(epoch),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> tuple[int, int] | None:
    """解析访问令牌，返回 (user_id, session_epoch)；无效 / 过期返回 None。

    旧令牌无 `ep` 声明时按 0 处理，因此升级后存量会话不会立即失效。
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return int(payload["sub"]), int(payload.get("ep", 0))
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None


def sign_device_cookie(device_id: str) -> str:
    """签发设备 Cookie（服务端签名，含有效期）。"""
    payload = {
        "did": device_id,
        "exp": int((datetime.now(timezone.utc) + timedelta(seconds=DEVICE_COOKIE_MAX_AGE)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_device_cookie(token: str | None) -> str | None:
    """校验设备 Cookie，返回其中的设备标识；无效 / 过期返回 None。"""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        did = payload.get("did")
        return str(did)[:64] if did else None
    except (jwt.PyJWTError, KeyError, ValueError):
        return None

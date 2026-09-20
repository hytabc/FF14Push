"""管理员账号：账号名与密码来自环境变量。

管理员用于协助用户找回密码（见 `api/v1/admin.py`）：
- 密码以环境变量为准：启动时若账号不存在则创建，若密码不一致则覆盖；
- 不创建初始英雄，因此不会出现在任何排行榜上（另见 `ranking.refresh_all_rankings` 的显式跳过）；
- 不能用改密接口修改管理员自己的密码，避免被环境变量覆盖回去。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models import User

ADMIN_NICKNAME = "管理员"


def admin_username() -> str:
    return get_settings().admin_username.strip()


def admin_enabled() -> bool:
    """账号名与密码都配置了才启用管理员。"""
    settings = get_settings()
    return bool(settings.admin_username.strip()) and bool(settings.admin_password)


def is_admin(user: Any) -> bool:
    name = admin_username()
    return bool(name) and user is not None and getattr(user, "username", None) == name


async def ensure_admin_user(db: AsyncSession) -> str:
    """启动时同步管理员账号。返回对账号做的操作，便于日志。"""
    settings = get_settings()
    username = settings.admin_username.strip()
    password = settings.admin_password
    if not username or not password:
        return "disabled"

    user = (
        await db.execute(
            select(User).options(selectinload(User.hero)).where(User.username == username)
        )
    ).scalar_one_or_none()
    if user is None:
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                nickname=ADMIN_NICKNAME,
                gold=0,
            )
        )
        await db.commit()
        return "created"

    # 该账号名已被普通玩家占用（有英雄）：不要顶掉对方密码，仅记录冲突
    if user.hero is not None:
        return "username-taken"

    if not verify_password(password, user.password_hash):
        user.password_hash = hash_password(password)
        await db.commit()
        return "password-synced"
    return "unchanged"

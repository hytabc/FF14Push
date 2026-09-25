"""管理员账号：账号名与密码来自环境变量。

管理员用于协助用户找回密码与发放补偿（见 `api/v1/admin.py`、`api/v1/grants.py`）：
- 密码以环境变量为准：启动时若账号不存在则创建，若密码不一致则覆盖；
- 不创建初始英雄，因此不会出现在任何排行榜上（另见 `ranking.refresh_all_rankings` 的显式跳过）；
- 不能用改密接口修改管理员自己的密码，避免被环境变量覆盖回去。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models import AdminGrant, User
from app.services.roster import lock_user

ADMIN_NICKNAME = "管理员"

# 单次发放金币上限（与 economy.json 转账 maxAmount 对齐）。
GRANT_MAX_AMOUNT = 2_000_000_000


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


async def grant_gold(
    db: AsyncSession, *, admin: User, target: User, amount: int, reason: str = ""
) -> int:
    """给指定玩家发放金币（管理员补偿）。只增不减，返回发放后的余额。

    金额须为正整数且不超过 `GRANT_MAX_AMOUNT`；改写前对目标账号加行锁，避免与其它结算并发丢更新。
    每次发放都写一条 `AdminGrant`（公示数据源，事由对玩家公开）。
    """
    amount = int(amount)
    if amount <= 0 or amount > GRANT_MAX_AMOUNT:
        raise HTTPException(
            status_code=400,
            detail=f"发放金额需为 1 ~ {GRANT_MAX_AMOUNT} 的整数",
        )

    locked = await lock_user(db, target.id)
    if locked is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    before = int(locked.gold)
    after = before + amount
    locked.gold = after
    db.add(
        AdminGrant(
            user_id=locked.id,
            nickname=locked.nickname,
            amount=amount,
            note=(reason or "").strip()[:200],
            admin_id=admin.id,
        )
    )
    await db.commit()
    return after

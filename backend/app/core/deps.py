"""FastAPI 依赖：当前用户、当前英雄、账号装备。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import BANNED_DETAIL, decode_access_token
from app.models import Hero, Item, User
from app.services import ratelimit

DbSession = Annotated[AsyncSession, Depends(get_db)]


def client_ip(request: Request) -> str:
    """客户端 IP。

    uvicorn 以 `--proxy-headers --forwarded-allow-ips` 启动时，Starlette 已把
    `X-Forwarded-For` 解析进 `request.client`，这里直接读取即可。
    """
    return request.client.host if request.client else "unknown"


async def guard_rate(
    db: AsyncSession,
    scope: str,
    key: str,
    limit: int,
    window_seconds: int,
    detail: str = "操作过于频繁，请稍后再试",
) -> None:
    """滑动窗口限流：超限抛 429。limit <= 0 表示关闭该限制。"""
    if not await ratelimit.hit(db, scope, key, limit, window_seconds):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)


def _extract_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()


async def get_current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    token = _extract_token(authorization)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少访问令牌")
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    # 封号：令牌仍可能有效，因此每个已认证请求都要在这里拦截，实现「强制下线」。
    if user.banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=BANNED_DETAIL)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_hero(db: DbSession, user: CurrentUser) -> Hero:
    hero = (await db.execute(select(Hero).where(Hero.user_id == user.id))).scalar_one_or_none()
    if hero is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="尚未招募英雄")
    return hero


CurrentHero = Annotated[Hero, Depends(get_current_hero)]


async def load_user_items(db: AsyncSession, user_id: int) -> list[Item]:
    return list((await db.execute(select(Item).where(Item.user_id == user_id))).scalars().all())


async def get_current_items(db: DbSession, user: CurrentUser) -> list[Item]:
    return await load_user_items(db, user.id)


CurrentItems = Annotated[list[Item], Depends(get_current_items)]


async def get_optional_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    """排行榜等接口允许未登录访问。"""
    token = _extract_token(authorization)
    if token is None:
        return None
    user_id = decode_access_token(token)
    if user_id is None:
        return None
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    # 封号用户视同未登录：既不参与排行，也不会被回显「我的排名」。
    if user is None or user.banned:
        return None
    return user


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


async def get_optional_hero(db: DbSession, user: CurrentUser) -> Hero | None:
    """解雇英雄后酒馆等入口仍需可用。"""
    return (await db.execute(select(Hero).where(Hero.user_id == user.id))).scalar_one_or_none()


OptionalHero = Annotated[Hero | None, Depends(get_optional_hero)]

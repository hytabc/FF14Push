"""认证：注册 / 登录 / 当前用户。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.models import (
    AutoSellSetting,
    Hero,
    RegionProgress,
    TavernState,
    TutorialProgress,
    User,
)
from app.schemas.game import LoginRequest, RegisterRequest, TokenResponse
from app.services.game_config import CONFIG
from app.services.recruiting import generate_candidate, initial_hero

router = APIRouter(prefix="/auth", tags=["auth"])


async def _bootstrap_new_user(db: DbSession, user: User) -> Hero:
    """新账号初始化：初始英雄 + 地区进度 + 新手指引 + 酒馆候选。"""
    preset = initial_hero()
    hero = Hero(
        user_id=user.id,
        name=preset["name"],
        level=1,
        exp=0,
        talent=preset["talent"],
        attr_bias=preset["attrBias"],
        strength=preset["strength"],
        agility=preset["agility"],
        intellect=preset["intellect"],
        current_region_id=1,
        region_kill_count=0,
        is_initial=True,
    )
    db.add(hero)

    for region in CONFIG.regions["regions"]:
        db.add(
            RegionProgress(
                user_id=user.id,
                region_id=region["id"],
                unlocked=region["id"] == 1,
                cleared=False,
            )
        )

    db.add(TutorialProgress(user_id=user.id, current_step=1))
    db.add(TavernState(user_id=user.id, candidate=generate_candidate(1)))
    db.add(
        AutoSellSetting(
            user_id=user.id,
            enabled=False,
            rarities=list(CONFIG.economy["sell"]["autoSellRarities"]),
        )
    )
    await db.flush()
    return hero


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DbSession) -> TokenResponse:
    exists = (await db.execute(select(User).where(User.username == payload.username))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已被占用")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        nickname=payload.nickname or payload.username,
        gold=0,
    )
    db.add(user)
    await db.flush()
    await _bootstrap_new_user(db, user)
    await db.commit()
    return TokenResponse(accessToken=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = (await db.execute(select(User).where(User.username == payload.username))).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return TokenResponse(accessToken=create_access_token(user.id))


@router.get("/me")
async def me(user: CurrentUser, db: DbSession) -> dict:
    hero = (await db.execute(select(Hero).where(Hero.user_id == user.id))).scalar_one_or_none()
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "gold": int(user.gold),
        "hasHero": hero is not None,
    }

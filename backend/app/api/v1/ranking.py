"""排行榜：等级榜 / 关卡榜 / 战力榜 / 金币榜。来源：PRD 排行榜系统"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, OptionalUser, load_user_items
from app.models import Hero, User
from app.services.admin import is_admin
from app.services.ranking import BOARDS, fetch_board, fetch_user_rank, refresh_all_rankings
from app.services.serialization import hero_to_dict, loadout
from app.services.stats import compute_stats
from app.services.valuation import hero_power

router = APIRouter(prefix="/ranking", tags=["ranking"])


@router.get("")
async def ranking(
    db: DbSession,
    user: OptionalUser,
    board: str = Query("level", pattern="^(level|stage|power|gold)$"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=100),
) -> dict:
    entries = await fetch_board(db, board, page, pageSize)
    mine = await fetch_user_rank(db, board, user.id) if user else None
    return {
        "board": board,
        "boards": list(BOARDS),
        "page": page,
        "pageSize": pageSize,
        "entries": entries,
        "me": mine,
        "loggedIn": user is not None,
    }


@router.post("/refresh")
async def refresh(db: DbSession, user: OptionalUser) -> dict:
    """手动刷新（服务端本应每 5 分钟自动刷新一次）。"""
    counts = await refresh_all_rankings(db)
    await db.commit()
    return {"ok": True, "counts": counts, "message": "排行榜已刷新"}


@router.get("/players/{user_id}")
async def player_profile(user_id: int, db: DbSession, viewer: CurrentUser) -> dict:
    """查看某玩家**当前已装备**的装备（只读）。

    需登录。不存在 / 已封禁 / 无英雄（含管理员）一律 404，不泄露这些账号的数据。
    只返回已装备栏位，不含背包、售价与属于物主私有的标签。
    """
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None or target.banned or is_admin(target):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="玩家不存在")

    hero = (await db.execute(select(Hero).where(Hero.user_id == user_id))).scalar_one_or_none()
    if hero is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="玩家不存在")

    items = await load_user_items(db, user_id)
    stats = compute_stats(hero, items)
    gear = {
        # 标签属于物主私有（id 只在物主账号内有意义），跨账号查看时清空
        slot: {**data, "tagIds": []}
        for slot, data in loadout(items).items()
    }
    return {
        "userId": target.id,
        "nickname": target.nickname,
        "username": target.username,
        "hero": hero_to_dict(hero, stats),
        "power": hero_power(stats),
        "loadout": gear,
    }

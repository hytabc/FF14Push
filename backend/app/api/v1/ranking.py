"""排行榜：等级榜 / 关卡榜 / 战力榜 / 金币榜。来源：PRD 排行榜系统"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, OptionalUser, load_user_items
from app.models import Hero, User
from app.services.admin import is_admin
from app.services.multiplayer_config import DUNGEONS, MULTIPLAYER
from app.services.ranking import (
    BOARDS,
    DOHDOL_BOARDS,
    FISH_BOARDS,
    fetch_board,
    fetch_coop_board,
    fetch_coop_user_rank,
    fetch_dohdol_board,
    fetch_dohdol_user_rank,
    fetch_fish_board,
    fetch_fish_user_rank,
    fetch_user_rank,
    refresh_all_rankings,
)
from app.services.serialization import hero_to_dict, loadout
from app.services.materia import socket_mods
from app.services.stats import compute_stats
from app.services.valuation import hero_power

router = APIRouter(prefix="/ranking", tags=["ranking"])

# 战斗装备 / 生产采集专用装备（跨账号查看时按此拆分）。
_COMBAT_CATEGORIES = {"weapon", "armor", "accessory"}
_DEDICATED_CATEGORIES = {"doh_tool", "doh_gear", "dol_tool", "dol_gear"}


@router.get("")
async def ranking(
    db: DbSession,
    user: OptionalUser,
    board: str = Query(
        "level",
        pattern="^(level|stage|power|gold|playtime|fish_species|fish_count|doh_exp|dol_exp|doh_attr|dol_attr|coop)$",
    ),
    dungeon: str | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=100),
) -> dict:
    # 钓鱼榜 / 生产采集榜 / 远征榜实时聚合（刚完成即可见），其余榜单读 5 分钟缓存
    body: dict = {
        "board": board,
        "boards": list(BOARDS),
        "page": page,
        "pageSize": pageSize,
        "loggedIn": user is not None,
    }
    if board in FISH_BOARDS:
        entries = await fetch_fish_board(db, board, page, pageSize)
        mine = await fetch_fish_user_rank(db, board, user.id) if user else None
    elif board in DOHDOL_BOARDS:
        entries = await fetch_dohdol_board(db, board, page, pageSize)
        mine = await fetch_dohdol_user_rank(db, board, user.id) if user else None
    elif board == "coop":
        # 远征榜按副本筛选；未指定或非法时取配置里的第一个副本
        dungeon_id = dungeon if dungeon in DUNGEONS else next(iter(DUNGEONS))
        entries = await fetch_coop_board(db, dungeon_id, page, pageSize)
        mine = await fetch_coop_user_rank(db, dungeon_id, user.id) if user else None
        body["dungeon"] = dungeon_id
        body["dungeons"] = [
            {"id": d["id"], "name": d["name"], "difficulty": d["difficulty"]}
            for d in MULTIPLAYER["dungeons"]
        ]
    else:
        entries = await fetch_board(db, board, page, pageSize)
        mine = await fetch_user_rank(db, board, user.id) if user else None
    body["entries"] = entries
    body["me"] = mine
    return body


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

    hero = (await db.execute(select(Hero).join(User, User.active_hero_id == Hero.id).where(User.id == user_id))).scalar_one_or_none()
    if hero is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="玩家不存在")

    items = await load_user_items(db, user_id)
    stats = compute_stats(hero, items, await socket_mods(db, user_id))
    # 标签属于物主私有（id 只在物主账号内有意义），跨账号查看时清空
    equipped = {slot: {**data, "tagIds": []} for slot, data in loadout(items, hero.id).items()}
    combat = {s: d for s, d in equipped.items() if d["category"] in _COMBAT_CATEGORIES}
    dedicated = {s: d for s, d in equipped.items() if d["category"] in _DEDICATED_CATEGORIES}
    return {
        "userId": target.id,
        "nickname": target.nickname,
        "username": target.username,
        "hero": hero_to_dict(hero, stats),
        "power": hero_power(stats),
        "maxPower": int(target.max_power or 0),
        "playSeconds": int(target.play_ms or 0) // 1000,
        "loadout": combat,
        "dohdolLoadout": dedicated,
        "activeTitleId": target.active_title_id,
    }

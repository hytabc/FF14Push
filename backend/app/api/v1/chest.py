"""抽箱。来源：PRD 2.8"""

from __future__ import annotations

import random

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentHero, CurrentItems, CurrentUser, DbSession
from app.models import ChestPity
from app.schemas.game import ChestOpenRequest
from app.services.drop_luck import chest_rarity_luck
from app.services.game_config import CONFIG
from app.services.grants import grant_generated_items
from app.services.item_factory import generate_item
from app.services.loot import PityState, chest_by_id
from app.services.stats import compute_stats

router = APIRouter(prefix="/chest", tags=["chest"])

ALLOWED_COUNTS = {1, 10}
LEVEL_BAND_MULTIPLIER = {
    int(band["level"]): float(band["priceMultiplier"]) for band in CONFIG.chests["levelBands"]
}


async def _pity(db: DbSession, user_id: int, chest_id: str) -> ChestPity:
    row = (
        await db.execute(
            select(ChestPity).where(ChestPity.user_id == user_id, ChestPity.chest_type == chest_id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = ChestPity(user_id=user_id, chest_type=chest_id)
        db.add(row)
        await db.flush()
    return row


@router.post("/open")
async def open_chest(
    payload: ChestOpenRequest,
    db: DbSession,
    user: CurrentUser,
    hero: CurrentHero,
    items: CurrentItems,
) -> dict:
    chest = chest_by_id(payload.chestId)
    if chest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="箱子不存在")
    if payload.count not in ALLOWED_COUNTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只支持单抽或十连")

    # 抽箱等级档位：需玩家等级达到档位；省略时按玩家当前等级（等级同步）。
    band = payload.level
    band_multiplier = 1.0
    if band is None:
        band = hero.level
    else:
        if band not in LEVEL_BAND_MULTIPLIER:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知的抽箱等级档位")
        if hero.level < band:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"需要英雄等级 {band} 才能抽取该档位",
            )
        band_multiplier = LEVEL_BAND_MULTIPLIER[band]

    # 品阶概率随「幸运来源」提升（仅影响装备品阶，不含金币）：
    # 通关地区 / 装备品阶幸运 / 料理秘药 / 远征·高难通关 / 彩蛋。
    luck, _ = await chest_rarity_luck(db, user.id, hero, items)

    unit_price = int(chest["price"] * band_multiplier)
    cost = unit_price * payload.count
    if int(user.gold) < cost:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"金币不足，需要 {cost}")

    user.gold = int(user.gold) - cost

    pity_row = await _pity(db, user.id, chest["id"])
    pity = PityState(
        since_rare=int(pity_row.since_rare),
        since_epic=int(pity_row.since_epic),
        since_legendary=int(pity_row.since_legendary),
    )

    rng = random.Random()
    generated = []
    for _ in range(payload.count):
        item, pity = generate_item(
            category=chest["category"],
            level=band,
            box_tier=chest["tier"],
            rng=rng,
            pity=pity,
            luck=luck,
        )
        generated.append(item)

    pity_row.since_rare = pity.since_rare
    pity_row.since_epic = pity.since_epic
    pity_row.since_legendary = pity.since_legendary

    grant = await grant_generated_items(db, user, generated, source=f"chest:{chest['id']}", rng=rng)
    await db.commit()

    return {
        "gold": int(user.gold),
        "cost": cost,
        "items": grant["items"],
        "autoSold": grant["autoSold"],
        "autoGold": grant["autoGold"],
        "pity": {
            "sinceRare": pity.since_rare,
            "sinceEpic": pity.since_epic,
            "sinceLegendary": pity.since_legendary,
        },
        "stats": compute_stats(hero, items).to_dict(),
    }

"""装备穿戴 / 卸载 / 出售。来源：PRD 3.2 / 3.3 / 出售 3.1"""

from __future__ import annotations

import random

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentHero, CurrentItems, CurrentUser, DbSession
from app.models import Item, ItemTag
from app.schemas.game import SellRequest, SetItemTagsRequest, UnequipRequest
from app.services.game_config import CONFIG
from app.services.serialization import item_to_dict
from app.services.slots_util import SLOT_BY_ID, accepts
from app.services.stats import compute_stats
from app.services.valuation import sell_price, sell_price_range

router = APIRouter(prefix="/inventory", tags=["inventory"])


async def _owned_item(db: DbSession, user_id: int, item_id: int) -> Item:
    item = (
        await db.execute(select(Item).where(Item.id == item_id, Item.user_id == user_id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="装备不存在")
    return item


@router.post("/equip")
async def equip(payload: dict, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems) -> dict:
    item_id = int(payload.get("itemId", 0))
    slot = str(payload.get("slot", ""))

    if slot not in SLOT_BY_ID:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知栏位")

    item = await _owned_item(db, user.id, item_id)
    base = CONFIG.base_item_by_id.get(item.base_id)
    if base is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="底材配置缺失")
    if not accepts(slot, base):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该装备不能放入此栏位")

    current = (
        await db.execute(
            select(Item).where(Item.user_id == user.id, Item.equipped_slot == slot)
        )
    ).scalar_one_or_none()
    if current is not None and current.id != item.id:
        current.equipped_slot = None

    if item.equipped_slot and item.equipped_slot != slot:
        item.equipped_slot = None

    item.equipped_slot = slot
    await db.commit()

    stats = compute_stats(hero, items)
    return {"item": item_to_dict(item, sell_price_range(item)), "stats": stats.to_dict()}


@router.post("/unequip")
async def unequip(
    payload: UnequipRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems
) -> dict:
    item = (
        await db.execute(
            select(Item).where(Item.user_id == user.id, Item.equipped_slot == payload.slot)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该栏位没有装备")
    item.equipped_slot = None
    await db.commit()
    stats = compute_stats(hero, items)
    return {"stats": stats.to_dict()}


@router.post("/sell")
async def sell(
    payload: SellRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems
) -> dict:
    """出售装备，已装备的需先卸下。来源：PRD 出售 3.1"""
    if not payload.itemIds:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未选择任何装备")

    items = (
        await db.execute(
            select(Item).where(Item.id.in_(payload.itemIds), Item.user_id == user.id)
        )
    ).scalars().all()
    if not items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有可出售的装备")

    equipped = [i for i in items if i.equipped_slot]
    if equipped:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已装备的装备需先卸下")

    rng = random.Random()
    total = 0
    detail = []
    for item in items:
        price = sell_price(item, rng)
        total += price
        detail.append({"id": item.id, "name": item.name, "rarity": item.rarity, "price": price})
        await db.delete(item)

    user.gold = int(user.gold) + total
    await db.commit()
    return {"gold": int(user.gold), "goldGained": total, "sold": detail}


@router.post("/tags")
async def set_item_tags(
    payload: SetItemTagsRequest, db: DbSession, user: CurrentUser
) -> dict:
    """给装备设置标签（覆盖式）。只接受属于当前用户的标签 id。来源：装备颜色标签。"""
    item = await _owned_item(db, user.id, payload.itemId)

    owned_ids = set(
        (
            await db.execute(select(ItemTag.id).where(ItemTag.user_id == user.id))
        ).scalars().all()
    )
    # 去重并只保留本人标签，避免越权引用他人标签
    item.tag_ids = [tid for tid in dict.fromkeys(payload.tagIds) if tid in owned_ids]
    await db.commit()
    return {"item": item_to_dict(item, sell_price_range(item))}

"""装备穿戴 / 卸载 / 出售。来源：PRD 3.2 / 3.3 / 出售 3.1"""

from __future__ import annotations

import random

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentHero, CurrentItems, CurrentSockets, CurrentUser, DbSession
from app.models import Item, ItemTag
from app.schemas.game import SellRequest, SetItemTagsRequest, UnequipRequest
from app.services.game_config import CONFIG
from app.services.serialization import item_to_dict
from app.services.slots_util import SLOT_BY_ID, accepts, role_name, role_of_base
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


async def _hero_role(db: DbSession, user_id: int, hero_id: int) -> str | None:
    """英雄当前职能：由其已装备的主手武器决定（无武器 → None，不限制穿戴）。"""
    weapon = await db.scalar(
        select(Item).where(
            Item.user_id == user_id, Item.equipped_hero_id == hero_id, Item.equipped_slot == "mainHand"
        )
    )
    base = CONFIG.base_item_by_id.get(weapon.base_id) if weapon is not None else None
    return role_of_base(base) if base is not None else None


async def _unequip_incompatible(
    db: DbSession, user_id: int, hero_id: int, role: str | None, exclude_id: int | None = None
) -> list[dict]:
    """换武器后自动卸下与该武器职能不符的防具 / 饰品（基础型无词缀装备不受限）。"""
    if not role:
        return []
    worn = (
        await db.execute(
            select(Item).where(Item.user_id == user_id, Item.equipped_hero_id == hero_id)
        )
    ).scalars().all()
    out: list[dict] = []
    for item in worn:
        if item.equipped_slot in (None, "mainHand") or item.id == exclude_id:
            continue
        base = CONFIG.base_item_by_id.get(item.base_id)
        item_role = role_of_base(base) if base is not None else None
        if item_role and item_role != role:
            item.equipped_slot = None
            item.equipped_hero_id = None
            out.append({"id": item.id, "name": item.name})
    if out:
        await db.flush()
    return out


@router.post("/equip")
async def equip(payload: dict, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems, sockets: CurrentSockets) -> dict:
    item_id = int(payload.get("itemId", 0))
    slot = str(payload.get("slot", ""))

    if slot not in SLOT_BY_ID:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知栏位")

    item = await _owned_item(db, user.id, item_id)
    if item.equipped_hero_id not in (None, hero.id):
        raise HTTPException(409, "请先从原英雄卸下此装备")
    base = CONFIG.base_item_by_id.get(item.base_id)
    if base is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="底材配置缺失")
    if not accepts(slot, base):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该装备不能放入此栏位")

    item_role = role_of_base(base)
    if slot == "mainHand":
        # 换武器：以新武器职能为准，自动卸下不符职能的防具 / 饰品（卸下永远允许）。
        unequipped = await _unequip_incompatible(db, user.id, hero.id, item_role, exclude_id=item.id)
    else:
        hero_role = await _hero_role(db, user.id, hero.id)
        if hero_role and item_role and item_role != hero_role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"该装备为「{role_name(item_role)}」专用，与英雄当前职能不符",
            )
        unequipped = []

    current = (
        await db.execute(
            select(Item).where(Item.user_id == user.id, Item.equipped_slot == slot, Item.equipped_hero_id == hero.id)
        )
    ).scalar_one_or_none()
    if current is not None and current.id != item.id:
        current.equipped_slot = None
        current.equipped_hero_id = None
        await db.flush()

    if item.equipped_slot and item.equipped_slot != slot:
        item.equipped_slot = None

    item.equipped_slot = slot
    item.equipped_hero_id = hero.id
    await db.commit()

    stats = compute_stats(hero, items, sockets)
    return {
        "item": item_to_dict(item, sell_price_range(item)),
        "stats": stats.to_dict(),
        "unequipped": unequipped,
    }


@router.post("/unequip")
async def unequip(
    payload: UnequipRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems, sockets: CurrentSockets
) -> dict:
    item = (
        await db.execute(
            select(Item).where(Item.user_id == user.id, Item.equipped_slot == payload.slot, Item.equipped_hero_id == hero.id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该栏位没有装备")
    item.equipped_slot = None
    item.equipped_hero_id = None
    await db.commit()
    stats = compute_stats(hero, items, sockets)
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

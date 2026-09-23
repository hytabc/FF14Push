"""发放物品：入库、图鉴解锁、自动出售。"""

from __future__ import annotations

import random
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AutoSellSetting, Item, User
from app.services.codex import unlock_equipment, unlock_terms
from app.services.serialization import item_from_generated, item_to_dict
from app.services.valuation import sell_price, sell_price_range


async def _auto_sell_config(db: AsyncSession, user_id: int) -> AutoSellSetting | None:
    return (
        await db.execute(select(AutoSellSetting).where(AutoSellSetting.user_id == user_id))
    ).scalar_one_or_none()


async def _persist(db: AsyncSession, user: User, generated_item: dict[str, Any], source: str) -> Item:
    item = Item(user_id=user.id, **item_from_generated(generated_item, source))
    db.add(item)
    await db.flush()
    # 词条图鉴同时收录战斗与生产/采集词条，故两类装备都要解锁词条。
    await unlock_terms(db, user.id, item.terms or [])
    # 装备图鉴同时收录战斗装备与生产/采集专用装备（专用装备底材见 dohdol-equipment）。
    await unlock_equipment(db, user.id, item)
    return item


async def grant_generated_items(
    db: AsyncSession,
    user: User,
    generated: Iterable[dict[str, Any]],
    source: str,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """写入背包；按设置自动出售；同步解锁图鉴。"""
    rng = rng or random.Random()
    auto_sell = await _auto_sell_config(db, user.id)
    auto_rarities = set(auto_sell.rarities or []) if auto_sell and auto_sell.enabled else set()

    added: list[dict[str, Any]] = []
    sold: list[dict[str, Any]] = []
    auto_gold = 0

    for generated_item in generated:
        item = await _persist(db, user, generated_item, source)
        if item.rarity in auto_rarities:
            price = sell_price(item, rng)
            auto_gold += price
            sold.append(
                {"baseId": item.base_id, "name": item.name, "rarity": item.rarity, "price": price}
            )
            await db.delete(item)
        else:
            added.append(item_to_dict(item, sell_price_range(item)))

    if auto_gold:
        user.gold = int(user.gold) + auto_gold

    return {"items": added, "autoSold": sold, "autoGold": auto_gold}


async def insert_items(
    db: AsyncSession,
    user: User,
    generated: Iterable[dict[str, Any]],
    source: str,
) -> list[dict[str, Any]]:
    """直接入库（不触发自动出售），用于合成产物。"""
    added: list[dict[str, Any]] = []
    for generated_item in generated:
        item = await _persist(db, user, generated_item, source)
        added.append(item_to_dict(item, sell_price_range(item)))
    return added

"""合成 / 重造 / 附魔。来源：PRD 2.9 / 重造 4 / 附魔 5"""

from __future__ import annotations

import random

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentHero, CurrentItems, CurrentUser, DbSession
from app.models import Item
from app.schemas.game import CraftRequest, EnchantRequest, RefineRequest
from app.services.economy import REQUIRED, build_craft_plan, enchant_cost, refine_cost
from app.services.grants import insert_items
from app.services.item_factory import generate_item, regenerate_attrs, roll_terms_for_enchant
from app.services.loot import RARITY_ORDER
from app.services.serialization import item_to_dict
from app.services.valuation import sell_price_range

router = APIRouter(prefix="/economy", tags=["economy"])

MAX_AUTO_ENCHANT_ATTEMPTS = 100


async def _user_items(db: DbSession, user_id: int) -> list[Item]:
    return list(
        (await db.execute(select(Item).where(Item.user_id == user_id))).scalars().all()
    )


@router.post("/craft/preview")
async def craft_preview(
    payload: CraftRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems
) -> dict:
    plan = build_craft_plan(items, payload.category, auto=payload.auto)
    return {"plan": plan, "gold": int(user.gold), "required": REQUIRED}


@router.post("/craft")
async def craft(
    payload: CraftRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, items: CurrentItems
) -> dict:
    """合成：16 件同品阶同类装备 → 1 件更高品阶。来源：PRD 2.9"""
    if payload.category not in ("weapon", "armor", "accessory"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知装备大类")

    plan = build_craft_plan(items, payload.category, auto=payload.auto)
    steps = [s for s in plan["steps"] if s["crafts"] > 0]
    if not steps:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有可合成的装备")

    total_fee = int(plan["totalFee"])
    if int(user.gold) < total_fee:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"手续费不足，需要 {total_fee}")

    # 可消耗池：未装备的同类装备（含新合成产物）
    pool: list[Item] = [i for i in items if i.category == payload.category and i.equipped_slot is None]
    pool.sort(key=lambda i: (RARITY_ORDER.index(i.rarity), i.level_req))

    rng = random.Random()
    produced: list[dict] = []
    consumed_count = 0

    for step in steps:
        need = int(step["crafts"]) * REQUIRED
        take = [i for i in pool if i.rarity == step["from"]]
        if len(take) < need:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="装备数量不足")
        take = take[:need]
        for item in take:
            pool.remove(item)
            await db.delete(item)
        consumed_count += need

        for _ in range(int(step["crafts"])):
            level = max(t.level_req for t in take) if take else hero.level
            generated = generate_item(payload.category, hero.level, rarity=step["to"], rng=rng)[0]
            generated["levelReq"] = level
            created = await insert_items(db, user, [generated], source="craft")
            produced.extend(created)
            row = (
                await db.execute(select(Item).where(Item.id == created[-1]["id"]))
            ).scalar_one()
            pool.append(row)

    user.gold = int(user.gold) - total_fee
    await db.commit()
    return {
        "gold": int(user.gold),
        "fee": total_fee,
        "consumed": consumed_count,
        "produced": produced,
    }


@router.post("/refine")
async def refine(
    payload: RefineRequest, db: DbSession, user: CurrentUser, hero: CurrentHero
) -> dict:
    """重造：重新随机基础属性与副属性，保留品阶/类型/等级需求/词条。"""
    item = (
        await db.execute(select(Item).where(Item.id == payload.itemId, Item.user_id == user.id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="装备不存在")

    cost = refine_cost(item.rarity, int(item.refine_count), payload.mode)
    if int(user.gold) < cost:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"金币不足，需要 {cost}")

    before = item_to_dict(item, sell_price_range(item))
    rng = random.Random()
    result = regenerate_attrs(item, rng, payload.mode)
    item.base_attrs = result["baseAttrs"]
    item.sub_attrs = result["subAttrs"]
    item.refine_count = int(item.refine_count) + 1
    user.gold = int(user.gold) - cost
    await db.commit()

    after = item_to_dict(item, sell_price_range(item))
    return {"gold": int(user.gold), "cost": cost, "before": before, "after": after}


@router.post("/enchant")
async def enchant(
    payload: EnchantRequest, db: DbSession, user: CurrentUser, hero: CurrentHero
) -> dict:
    """附魔：重新随机全部 Buff/Debuff，含稀有 / 太古词条判定。"""
    item = (
        await db.execute(select(Item).where(Item.id == payload.itemId, Item.user_id == user.id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="装备不存在")

    rng = random.Random()
    before = item_to_dict(item, sell_price_range(item))

    if not payload.autoUntilRare:
        unit_cost = enchant_cost(item.rarity, payload.mode)
        if int(user.gold) < unit_cost:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"金币不足，需要 {unit_cost}")
        item.terms = roll_terms_for_enchant(item, rng, payload.mode)
        item.enchant_count = int(item.enchant_count) + 1
        user.gold = int(user.gold) - unit_cost
        await db.commit()
        return {"gold": int(user.gold), "cost": unit_cost, "attempts": 1, "before": before, "after": item_to_dict(item, sell_price_range(item))}

    # 自动附魔至稀有/太古：始终按彻底随机单价逐次结算
    unit_cost = enchant_cost(item.rarity)
    max_attempts = max(1, min(MAX_AUTO_ENCHANT_ATTEMPTS, int(payload.maxAttempts)))
    affordable = int(user.gold) // unit_cost
    if affordable < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"金币不足，至少需要 {unit_cost}")

    attempts = 0
    best_terms = None
    hit = False
    while attempts < min(max_attempts, affordable):
        attempts += 1
        terms = roll_terms_for_enchant(item, rng)
        if best_terms is None:
            best_terms = terms
        if any(t.get("quality") in ("rare", "ancient") for t in terms):
            best_terms = terms
            hit = True
            break

    item.terms = best_terms or []
    item.enchant_count = int(item.enchant_count) + attempts
    total_cost = unit_cost * attempts
    user.gold = int(user.gold) - total_cost
    await db.commit()

    return {
        "gold": int(user.gold),
        "cost": total_cost,
        "attempts": attempts,
        "hit": hit,
        "before": before,
        "after": item_to_dict(item, sell_price_range(item)),
    }

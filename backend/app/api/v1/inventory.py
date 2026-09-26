"""装备穿戴 / 卸载 / 出售。来源：PRD 3.2 / 3.3 / 出售 3.1"""

from __future__ import annotations

import random

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentHero, CurrentItems, CurrentSockets, CurrentUser, DbSession
from app.models import Item, ItemTag
from app.schemas.game import AutoEquipRequest, SellRequest, SetItemTagsRequest, UnequipRequest
from app.services.auto_equip import hero_job_role, plan_auto_equip
from app.services.game_config import CONFIG
from app.services.serialization import item_to_dict
from app.services.slots_util import SLOT_BY_ID, accepts, all_slot_ids, role_name, role_of_base
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


async def _all_items(db: DbSession, user_id: int) -> list[Item]:
    """账号全部装备（不做英雄过滤）——一键最强需要看到其他英雄身上的装备。"""
    return list((await db.execute(select(Item).where(Item.user_id == user_id))).scalars().all())


def _worn_by_slot(items: list[Item], hero_id: int) -> dict[str, Item]:
    return {i.equipped_slot: i for i in items if i.equipped_hero_id == hero_id and i.equipped_slot}


def _auto_equip_changes(plan: dict, worn: dict[str, Item]) -> list[tuple[str, Item]]:
    """计划中真正发生变化的栏位（已经是最优的栏位不计入）。"""
    changes: list[tuple[str, Item]] = []
    for slot, item in plan.items():
        current = worn.get(slot)
        if current is not None and current.id == item.id:
            continue
        changes.append((slot, item))
    return changes


@router.post("/auto-equip/preview")
async def auto_equip_preview(payload: AutoEquipRequest, db: DbSession, user: CurrentUser, hero: CurrentHero) -> dict:
    """一键最强预览：列出各栏位将更换的装备。主手武器为职业锚点，不参与更换。"""
    items = await _all_items(db, user.id)
    job_id, role = hero_job_role(items, hero.id)
    if job_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先装备一把武器")

    plan = plan_auto_equip(items, hero.id, payload.includeEquipped)
    worn = _worn_by_slot(items, hero.id)
    changes = _auto_equip_changes(plan, worn)
    from_others = sum(1 for _s, it in changes if it.equipped_hero_id not in (None, hero.id))
    weapon = worn.get("mainHand")
    return {
        "jobId": job_id,
        "role": role,
        "weapon": item_to_dict(weapon, sell_price_range(weapon)) if weapon is not None else None,
        "changes": [
            {
                "slot": slot,
                "current": item_to_dict(worn[slot], sell_price_range(worn[slot])) if slot in worn else None,
                "next": item_to_dict(item, sell_price_range(item)),
            }
            for slot, item in changes
        ],
        "fromOthers": from_others,
    }


@router.post("/auto-equip")
async def auto_equip(
    payload: AutoEquipRequest, db: DbSession, user: CurrentUser, hero: CurrentHero, sockets: CurrentSockets
) -> dict:
    """一键最强：保留当前主手武器，把其余栏位换成符合职能、战力最高的装备。

    默认不使用已被其他英雄装备的装备；`includeEquipped=true` 时取用之，并从原英雄卸下。
    """
    items = await _all_items(db, user.id)
    job_id, _role = hero_job_role(items, hero.id)
    if job_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先装备一把武器")

    plan = plan_auto_equip(items, hero.id, payload.includeEquipped)
    worn = _worn_by_slot(items, hero.id)
    changes = _auto_equip_changes(plan, worn)
    from_others = sum(1 for _s, it in changes if it.equipped_hero_id not in (None, hero.id))

    # 先把「被替换的栏位装备」与「计划中要挪用的装备」全部卸下再统一写回，
    # 避免唯一约束 (equipped_hero_id, equipped_slot) 出现瞬时冲突（如换戒指）。
    touched = {item.id for item in plan.values()}
    for slot in plan:
        current = worn.get(slot)
        if current is not None:
            touched.add(current.id)
    for item in items:
        if item.id in touched:
            item.equipped_slot = None
            item.equipped_hero_id = None
    await db.flush()

    for slot, item in plan.items():
        item.equipped_slot = slot
        item.equipped_hero_id = hero.id
    await db.commit()

    stats = compute_stats(hero, items, sockets)
    return {
        "stats": stats.to_dict(),
        "equipped": [
            {"slot": slot, "item": item_to_dict(item, sell_price_range(item))} for slot, item in plan.items()
        ],
        "changes": [
            {"slot": slot, "item": item_to_dict(item, sell_price_range(item))} for slot, item in changes
        ],
        "fromOthers": from_others,
    }


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

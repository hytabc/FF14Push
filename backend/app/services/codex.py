"""图鉴：装备（按底材）、怪物、词条解锁与统计。来源：PRD 图鉴系统"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CodexEquipment, CodexMaterial, CodexMonster, CodexTerm, FishRecord
from app.services.game_config import CONFIG
from app.services.loot import boss_box_for_region
from app.services.slots_util import possible_slots

RARITY_ORDER = list(CONFIG.rarity_order)
# 材料图鉴只收录采集材料与半成品（鱼获单独成册，见 fish_codex_entries）。
MATERIAL_CODEX_KINDS = ("gather", "half")


async def unlock_equipment(db: AsyncSession, user_id: int, item: Any) -> dict[str, Any]:
    """解锁装备图鉴：底材为主条目，品阶为子进度。"""
    row = (
        await db.execute(
            select(CodexEquipment).where(
                CodexEquipment.user_id == user_id, CodexEquipment.base_id == item.base_id
            )
        )
    ).scalar_one_or_none()

    if row is None:
        row = CodexEquipment(
            user_id=user_id,
            base_id=item.base_id,
            unlocked_rarities=[item.rarity],
            total_count=1,
        )
        db.add(row)
        return {"baseId": item.base_id, "newBase": True, "newRarity": True}

    rarities = list(row.unlocked_rarities or [])
    new_rarity = item.rarity not in rarities
    if new_rarity:
        rarities.append(item.rarity)
    row.unlocked_rarities = rarities
    row.total_count = int(row.total_count or 0) + 1
    return {"baseId": item.base_id, "newBase": False, "newRarity": new_rarity}


async def unlock_monster(db: AsyncSession, user_id: int, monster_id: str, count: int = 1) -> dict[str, Any]:
    row = (
        await db.execute(
            select(CodexMonster).where(
                CodexMonster.user_id == user_id, CodexMonster.monster_id == monster_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(CodexMonster(user_id=user_id, monster_id=monster_id, kill_count=count))
        return {"monsterId": monster_id, "new": True}
    row.kill_count = int(row.kill_count or 0) + count
    return {"monsterId": monster_id, "new": False}


async def unlock_terms(db: AsyncSession, user_id: int, terms: Iterable[Any]) -> list[list[str]]:
    """词条图鉴：普通/稀有/太古分别作为独立子项。"""
    unlocked: list[list[str]] = []
    for term in terms:
        term_id = term.get("id")
        quality = term.get("quality", "common")
        if not term_id:
            continue
        row = (
            await db.execute(
                select(CodexTerm).where(
                    CodexTerm.user_id == user_id,
                    CodexTerm.term_id == term_id,
                    CodexTerm.quality == quality,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(CodexTerm(user_id=user_id, term_id=term_id, quality=quality))
            unlocked.append([term_id, quality])
    return unlocked


async def unlock_material(db: AsyncSession, user_id: int, item_id: str, count: int = 1) -> dict[str, Any]:
    """解锁材料图鉴：首次获得即永久记录，累计获得数量随每次入库增长。"""
    row = (
        await db.execute(
            select(CodexMaterial).where(
                CodexMaterial.user_id == user_id, CodexMaterial.item_id == item_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(CodexMaterial(user_id=user_id, item_id=item_id, total_count=int(count)))
        return {"itemId": item_id, "new": True}
    row.total_count = int(row.total_count or 0) + int(count)
    return {"itemId": item_id, "new": False}


def equipment_codex_entries() -> list[dict[str, Any]]:
    """全部装备底材的理论信息（用于图鉴展示，未解锁显示剪影）。"""
    out: list[dict[str, Any]] = []
    for base in CONFIG.base_items:
        category = base.category
        sources = {
            "weapon": ["weaponBox", "advWeaponBox"],
            "armor": ["armorBox", "advArmorBox"],
            "accessory": ["accessoryBox", "advAccessoryBox"],
        }[category]
        out.append(
            {
                "baseId": base.id,
                "name": base.name,
                "category": category,
                "slot": base.slot,
                "equipSlots": possible_slots(base),
                "jobId": base.job_id,
                "weaponType": base.weapon_type,
                "levelReq": base.level_req,
                "tierName": base.tier_name,
                "baseAttrs": base.base_attrs,
                "subAttrPool": base.sub_attr_pool,
                "sources": sources,
            }
        )
    return out


def monster_codex_entries() -> list[dict[str, Any]]:
    """全部怪物条目：小怪按模板，BOSS 按地区。"""
    out: list[dict[str, Any]] = []
    for template in CONFIG.monsters["templates"]:
        regions = sorted({r["id"] for r in CONFIG.regions["regions"]})
        out.append(
            {
                "monsterId": template["id"],
                "name": template["name"],
                "kind": "elite" if template["id"] == "elite" else "normal",
                "examples": template["examples"],
                "regions": regions,
            }
        )
    for region in CONFIG.regions["regions"]:
        out.append(
            {
                "monsterId": f"boss_r{region['id']}",
                "name": region["bossName"],
                "kind": "boss",
                "bossType": region["bossType"],
                "regionId": region["id"],
                "levelMin": region["levelMin"],
                "levelMax": region["levelMax"],
                "boxId": boss_box_for_region(region["id"]),
            }
        )
    return out


def term_codex_entries() -> list[dict[str, Any]]:
    """全部 Buff/Debuff 词条：战斗装备词条 + 生产/采集专用装备词条。

    两套词条池 id 互不重复（见 test_dohdol.test_pool_does_not_overlap_combat_terms），
    但 slot 归属不同，故用 source 标注来源（combat / production）。
    """
    out: list[dict[str, Any]] = []
    pools = (
        ("combat", CONFIG.terms["terms"]),
        ("production", CONFIG.dohdol_equipment.get("terms", [])),
    )
    for source, terms in pools:
        for t in terms:
            out.append(
                {
                    "termId": t["id"],
                    "name": t["name"],
                    "type": t["type"],
                    "stat": t["stat"],
                    "range": t["range"],
                    "slots": t.get("slots", []),
                    "desc": t["desc"],
                    "source": source,
                }
            )
    return out


def material_codex_entries() -> list[dict[str, Any]]:
    """全部采集材料与半成品条目（不含鱼获）。"""
    out: list[dict[str, Any]] = []
    for material in CONFIG.materials["materials"]:
        if material.get("kind") not in MATERIAL_CODEX_KINDS:
            continue
        out.append(
            {
                "itemId": material["id"],
                "name": material["name"],
                "kind": material["kind"],
                "jobId": material.get("jobId"),
                "tier": material.get("tier"),
                "regionId": material.get("regionId"),
                "common": bool(material.get("common", False)),
                "sell": material.get("sell", 0),
            }
        )
    return out


def fish_codex_entries() -> list[dict[str, Any]]:
    """全部鱼获条目：每钓场的普通鱼 + 鱼王 + 鱼皇。"""
    out: list[dict[str, Any]] = []
    for region in CONFIG.fish["regions"]:
        region_id = int(region["regionId"])
        region_name = region["name"]
        for fish in region["normal"]:
            out.append(
                {
                    "fishId": fish["id"],
                    "name": fish["name"],
                    "kind": "normal",
                    "regionId": region_id,
                    "regionName": region_name,
                    "sizeMin": fish["sizeMin"],
                    "sizeMax": fish["sizeMax"],
                    "exp": fish.get("exp", 0),
                    "sell": fish.get("sell", 0),
                    "chance": None,
                }
            )
        for kind, key in (("king", "king"), ("emperor", "emperor")):
            fish = region[key]
            out.append(
                {
                    "fishId": fish["id"],
                    "name": fish["name"],
                    "kind": kind,
                    "regionId": region_id,
                    "regionName": region_name,
                    "sizeMin": fish["sizeMin"],
                    "sizeMax": fish["sizeMax"],
                    "exp": fish.get("exp", 0),
                    "sell": fish.get("sell", 0),
                    "chance": fish.get("chance"),
                }
            )
    return out


async def codex_progress(db: AsyncSession, user_id: int) -> dict[str, Any]:
    equip_count = (
        await db.execute(
            select(func.count()).select_from(CodexEquipment).where(CodexEquipment.user_id == user_id)
        )
    ).scalar_one()
    monster_count = (
        await db.execute(
            select(func.count()).select_from(CodexMonster).where(CodexMonster.user_id == user_id)
        )
    ).scalar_one()
    term_count = (
        await db.execute(select(func.count()).select_from(CodexTerm).where(CodexTerm.user_id == user_id))
    ).scalar_one()
    material_count = (
        await db.execute(
            select(func.count()).select_from(CodexMaterial).where(CodexMaterial.user_id == user_id)
        )
    ).scalar_one()
    fish_count = (
        await db.execute(
            select(func.count()).select_from(FishRecord).where(FishRecord.user_id == user_id)
        )
    ).scalar_one()
    return {
        "equipment": {"unlocked": int(equip_count), "total": len(CONFIG.base_items)},
        "monster": {"unlocked": int(monster_count), "total": len(monster_codex_entries())},
        "term": {"unlocked": int(term_count), "total": len(term_codex_entries()) * 3},
        "material": {"unlocked": int(material_count), "total": len(material_codex_entries())},
        "fish": {"unlocked": int(fish_count), "total": len(fish_codex_entries())},
    }

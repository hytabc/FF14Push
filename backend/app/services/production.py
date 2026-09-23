"""生产（能工巧匠）：按配方制造材料 / 半成品 / 装备 / 药水食物。

制造装备恒为「高品质」：属性区间上移且必带太古词条，并按配方权重抽品阶。
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivitySession, DohDolProgress, Hero, Item, User
from app.services import consumables, dohdol_util, drop_luck, luck_sources
from app.services.game_config import CONFIG
from app.services.grants import insert_items
from app.services.item_factory import (
    craft_rarity_luck,
    craft_xp_rarity_multiplier,
    generate_crafted_item,
)
from app.services.playtime import add_play_ms

MAX_CRAFTS_PER_REPORT = 200


async def _progress(db: AsyncSession, user_id: int) -> DohDolProgress:
    row = (
        await db.execute(
            select(DohDolProgress).where(
                DohDolProgress.user_id == user_id, DohDolProgress.kind == "doh"
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DohDolProgress(user_id=user_id, kind="doh", level=1, exp=0)
        db.add(row)
        await db.flush()
    return row


def craft_seconds(recipe: dict[str, Any], items: Sequence[Item]) -> float:
    """单次制造耗时（受专用装备制造速度加成影响）。"""
    speed = dohdol_util.equipped_bonus(items).get("craftSpeedPct", 0.0)
    return max(0.2, float(recipe["craftSeconds"]) * (1.0 - min(0.6, speed / 100.0)))


async def start_produce(
    db: AsyncSession,
    user: User,
    items: Sequence[Item],
    job_id: str,
    recipe_id: str,
    count: int | None = None,
) -> dict[str, Any]:
    """开始生产。count=None 表示「制作全部」（按当前材料上限），否则制造 min(count, 材料上限) 件。"""
    recipe = dohdol_util.recipe_def(recipe_id)
    if recipe is None:
        raise ValueError("配方不存在")
    if recipe["jobId"] != job_id:
        raise ValueError("该配方不属于该职业")
    progress = await _progress(db, user.id)
    if int(progress.level) < int(recipe["requiredLevel"]):
        raise ValueError(f"生产等级不足，需要生产等级 {recipe['requiredLevel']}")

    stock = await dohdol_util.stack_counts(db, user.id, dohdol_util.STACK_MATERIAL)
    max_by_materials = _max_crafts_by_materials(stock, recipe["inputs"])
    if max_by_materials <= 0:
        raise ValueError("材料不足，无法制造")
    target = max_by_materials if count is None else min(int(count), max_by_materials)

    await dohdol_util.end_active_sessions(db, user.id)
    await dohdol_util.end_other_battle_sessions(db, user.id)
    now = datetime.now(timezone.utc)
    session = ActivitySession(
        started_at=now, last_report_at=now,
        user_id=user.id,
        kind="produce",
        job_id=job_id,
        recipe_id=recipe_id,
        active=True,
        credit=0.0,
        target_actions=target,
    )
    db.add(session)
    await db.flush()
    return {
        "sessionId": session.id,
        "jobId": job_id,
        "recipeId": recipe_id,
        "targetActions": target,
        "cycle": dohdol_util.cycle_info(craft_seconds(recipe, items), 0.0, now),
    }


def _max_crafts_by_materials(stock: dict[str, int], inputs: list[dict[str, Any]]) -> int:
    best: int | None = None
    for entry in inputs:
        have = stock.get(entry["itemId"], 0)
        need = max(1, int(entry["count"]))
        possible = have // need
        best = possible if best is None else min(best, possible)
    return 0 if best is None else max(0, best)


async def report_produce(
    db: AsyncSession, user: User, items: Sequence[Item], session: ActivitySession
) -> dict[str, Any]:
    recipe = dohdol_util.recipe_def(session.recipe_id or "")
    if recipe is None:
        raise ValueError("配方不存在")

    progress = await _progress(db, user.id)
    now = datetime.now(timezone.utc)
    window = dohdol_util.window_seconds(session.last_report_at, now)
    add_play_ms(user, int(window * 1000))

    equip = dohdol_util.equipped_bonus(items)
    quality_bonus = await consumables.craft_quality_bonus(db, user.id) + equip.get(
        "craftQualityPct", 0.0
    ) / 100.0

    # 制造品阶概率随进度提升：英雄等级 / 通关地区数 / 生产等级 / 专用装备品阶幸运 /
    # 制造品阶概率药食 / 远征·高难通关（难度加权首通）。
    hero_level = await db.scalar(select(Hero.level).where(Hero.id == user.active_hero_id))
    rarity_luck, _ = craft_rarity_luck(
        {
            "heroLevel": int(hero_level or 0),
            "clearedRegions": await drop_luck.cleared_region_count(db, user.id),
            "prodLevel": int(progress.level),
            "gearPct": equip.get("craftRarityPct", 0.0),
            "consumablePct": await consumables.craft_rarity_bonus(db, user.id),
            "coopClears": await luck_sources.coop_clear_score(db, user.id),
            "raidClears": await luck_sources.raid_clear_score(db, user.id),
        }
    )

    target = int(session.target_actions) if session.target_actions is not None else None
    craft_seconds_value = craft_seconds(recipe, items)
    total = float(session.credit) + window
    by_time = int(total // craft_seconds_value)

    stock = await dohdol_util.stack_counts(db, user.id, dohdol_util.STACK_MATERIAL)
    by_materials = _max_crafts_by_materials(stock, recipe["inputs"])
    remaining = (
        MAX_CRAFTS_PER_REPORT if target is None else max(0, target - int(session.total_actions))
    )
    crafts = min(by_time, by_materials or 0, remaining, MAX_CRAFTS_PER_REPORT)

    session.credit = total - by_time * craft_seconds_value
    session.last_report_at = now
    session.total_actions = int(session.total_actions) + crafts
    produced_total = int(session.total_actions)
    finished = target is not None and produced_total >= target
    if finished:
        session.active = False
        session.ended_at = now

    rng = random.Random()
    produced: list[dict[str, Any]] = []
    material_out: dict[str, int] = {}
    equipment_out: list[dict[str, Any]] = []
    output = recipe["output"]
    # 经验按每件实际产出累计：装备按其抽到的品阶加权，材料 / 半成品 / 消耗品恒为 1.0。
    xp_units = 0.0
    for _ in range(crafts):
        for entry in recipe["inputs"]:
            await dohdol_util.stack_consume(
                db, user.id, dohdol_util.STACK_MATERIAL, entry["itemId"], int(entry["count"])
            )
        if output["kind"] == "equipment":
            crafted = generate_crafted_item(output["baseId"], rng, quality_bonus, rarity_luck)
            xp_units += craft_xp_rarity_multiplier(crafted["rarity"])
            equipment_out.append(crafted)
        elif output["kind"] == "consumable":
            spec = dohdol_util.consumable_def(output["itemId"])
            kind = spec["kind"] if spec else "potion"
            await dohdol_util.stack_add(db, user.id, kind, output["itemId"], int(output.get("count", 1)))
            material_out[output["itemId"]] = material_out.get(output["itemId"], 0) + int(output.get("count", 1))
            xp_units += 1.0
        else:
            await dohdol_util.stack_add(
                db, user.id, dohdol_util.STACK_MATERIAL, output["itemId"], int(output.get("count", 1))
            )
            material_out[output["itemId"]] = material_out.get(output["itemId"], 0) + int(output.get("count", 1))
            xp_units += 1.0

    if equipment_out:
        produced = await insert_items(db, user, equipment_out, source="craft")

    # 经验来源：专用装备（固定加成 + 经验词条）与药水 / 食物的经验加成。
    xp_sources, bonus_pct = dohdol_util.combine_xp_sources(
        dohdol_util.equipped_bonus_sources(items, "craftXpPct"),
        await consumables.effect_sources(db, user.id, "expGainPct"),
    )
    base_xp = int(recipe["xp"]) * crafts
    rarity_multiplier = (xp_units / crafts) if crafts else 1.0
    xp = round(xp_units * int(recipe["xp"]) * (1.0 + bonus_pct / 100.0))
    level_info = dohdol_util.apply_level_exp(progress, xp)

    return {
        "crafts": crafts,
        "recipeId": recipe["id"],
        "materials": [
            {"itemId": m, "name": dohdol_util.material_name(m), "count": c}
            for m, c in sorted(material_out.items())
        ],
        "items": produced if equipment_out else [],
        "xp": xp,
        "xpBreakdown": dohdol_util.xp_breakdown(base_xp, rarity_multiplier, bonus_pct, xp, xp_sources),
        "level": level_info,
        "targetActions": target,
        "producedTotal": produced_total,
        "finished": finished,
        "cycle": dohdol_util.cycle_info(craft_seconds_value, float(session.credit), now),
    }


async def stop_produce(db: AsyncSession, session: ActivitySession) -> None:
    session.active = False
    session.ended_at = datetime.now(timezone.utc)

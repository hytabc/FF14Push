"""游戏状态、职业与静态配置。"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentItems, CurrentUser, DbSession, OptionalHero
from app.services.game_config import CONFIG
from app.services.state import build_game_state

router = APIRouter(tags=["game"])


@router.get("/game/state")
async def game_state(
    db: DbSession, user: CurrentUser, hero: OptionalHero, items: CurrentItems
) -> dict:
    return await build_game_state(db, user, hero)


@router.get("/game/config")
async def game_config() -> dict:
    """静态配置（前端启动时拉取，避免打包进 bundle）。"""
    return {
        "rarities": CONFIG.rarities,
        "rarityOrder": CONFIG.rarity_order,
        "slots": CONFIG.slots,
        "attributes": CONFIG.attributes,
        "baseAttributes": CONFIG.raw["subAttributes"]["baseAttributes"],
        "jobs": CONFIG.jobs["jobs"],
        "jobRoles": CONFIG.jobs["roles"],
        "gcd": CONFIG.jobs["gcd"],
        "baseItems": [
            {
                "id": b.id,
                "name": b.name,
                "category": b.category,
                "slot": b.slot,
                "weaponType": b.weapon_type,
                "jobId": b.job_id,
                "levelReq": b.level_req,
                "tierIndex": b.tier_index,
                "tierName": b.tier_name,
                "baseAttrs": b.base_attrs,
                "subAttrPool": b.sub_attr_pool,
            }
            for b in CONFIG.base_items
        ],
        "terms": CONFIG.terms,
        "chests": CONFIG.chests,
        "crafting": CONFIG.crafting,
        "economy": CONFIG.economy,
        "talents": CONFIG.talents,
        "regions": CONFIG.regions,
        "raids": CONFIG.raids,
        "monsters": CONFIG.monsters,
        "bosses": CONFIG.bosses,
        "combat": CONFIG.combat,
        "heroes": CONFIG.heroes,
        "tutorial": CONFIG.tutorial,
        "dohdolJobs": CONFIG.dohdol_jobs,
        "dohdolLevels": CONFIG.dohdol_levels,
        "materials": CONFIG.materials,
        "gatherNodes": CONFIG.gather_nodes,
        "dohdolEquipment": CONFIG.dohdol_equipment,
        "fish": CONFIG.fish,
        "weather": CONFIG.weather,
        "recipes": CONFIG.recipes,
        "consumables": CONFIG.consumables,
        "titles": CONFIG.titles,
    }

"""游戏状态、职业与静态配置。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.core.deps import CurrentUser, DbSession, OptionalHero
from app.core.http_cache import conditional_json, json_body_and_etag, respond
from app.services.game_config import CONFIG
from app.services.state import build_game_state

router = APIRouter(tags=["game"])

# `/game/config` 的响应缓存：静态配置在进程内不变，构造一次即可（见 game_config）。
_CONFIG_CACHE_CONTROL = "public, max-age=3600"
_CONFIG_RESPONSE: tuple[bytes, str] | None = None


@router.get("/game/state")
async def game_state(
    request: Request, db: DbSession, user: CurrentUser, hero: OptionalHero
) -> Response:
    # 注意：不要在此声明 `CurrentItems` —— build_game_state 需要**全部**装备（含背包），
    # 依赖注入只加载当前英雄已装备的，声明了也用不上，反而每次请求白跑一次装备查询。
    # 带 ETag：内容未变时浏览器回源只拿到 304，省掉整包状态体。
    payload = await build_game_state(db, user, hero)
    return conditional_json(request, payload, cache_control="no-cache", vary="Authorization")


@router.get("/game/config")
async def game_config(request: Request) -> Response:
    """静态配置（前端启动时拉取，避免打包进 bundle）。仅随版本变化，故可强缓存 + ETag 校验。"""
    # 配置在进程生命周期内不变：首次请求构造一次 (body, etag) 后复用，
    # 避免每次请求都重新拼装含 ~935 条底材的大字典并序列化 + 哈希（纯 CPU 浪费）。
    global _CONFIG_RESPONSE
    if _CONFIG_RESPONSE is not None:
        body, etag = _CONFIG_RESPONSE
        return respond(request, body, etag, cache_control=_CONFIG_CACHE_CONTROL)
    payload = {
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
    body, etag = json_body_and_etag(payload)
    _CONFIG_RESPONSE = (body, etag)
    return respond(request, body, etag, cache_control=_CONFIG_CACHE_CONTROL)

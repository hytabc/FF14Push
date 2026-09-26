"""共享数据层的 Python 加载器。

与 `index.ts` 对应，读取同一个 `shared/data/*.json`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name: str) -> Any:
    with (DATA_DIR / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


@dataclass(frozen=True)
class BaseItem:
    id: str
    name: str
    category: str
    slot: str
    level_req: int
    tier_index: int
    tier_name: str
    base_attrs: list[dict[str, Any]]
    sub_attr_pool: list[str]
    sub_attr_scale: float = 1.0
    weapon_type: str | None = None
    job_id: str | None = None
    variant_id: str = ""
    # 职能词缀对应的战斗职能（tank / healer / melee / physicalRanged / magicalRanged）；
    # 基础型（无词缀）为 None。武器另有 job_id 可精确取职能。
    role: str | None = None
    # 世界BOSS 专属系列（绝境龙神）：并入 base_item_by_id 供属性/序列化/图鉴使用，
    # 但不并入 base_items，故抽箱/合成/生产的候选池天然不含它。
    exclusive: bool = False


@dataclass
class GameConfig:
    """全部静态配置。属性名与 `index.ts` 的 `gameData` 保持一致。"""

    rarities: dict[str, Any]
    rarity_order: list[str]
    slots: list[dict[str, Any]]
    slot_categories: dict[str, Any]
    attributes: list[dict[str, Any]]
    attribute_by_id: dict[str, Any]
    terms: dict[str, Any]
    term_by_id: dict[str, Any]
    jobs: dict[str, Any]
    job_by_id: dict[str, Any]
    dohdol_jobs: dict[str, Any]
    dohdol_job_by_id: dict[str, Any]
    dohdol_levels: dict[str, Any]
    materials: dict[str, Any]
    material_by_id: dict[str, Any]
    gather_nodes: dict[str, Any]
    gather_node_by: dict[tuple[int, str], dict[str, Any]]
    dohdol_equipment: dict[str, Any]
    dohdol_item_by_id: dict[str, Any]
    fish: dict[str, Any]
    fish_region_by_id: dict[int, dict[str, Any]]
    fish_by_id: dict[str, Any]
    weather: dict[str, Any]
    recipes: dict[str, Any]
    recipe_by_id: dict[str, Any]
    consumables: dict[str, Any]
    consumable_by_id: dict[str, Any]
    titles: dict[str, Any]
    materia: dict[str, Any]
    materia_by_id: dict[str, Any]
    farm: dict[str, Any]
    seed_by_id: dict[str, Any]
    treasure: dict[str, Any]
    base_items: list[BaseItem]
    base_item_by_id: dict[str, BaseItem]
    exclusive_items: list[BaseItem]
    exclusive_item_by_id: dict[str, BaseItem]
    worldboss: dict[str, Any]
    base_item_tiers: list[dict[str, Any]]
    base_attr_float: float
    sub_attr_float: float
    monsters: dict[str, Any]
    bosses: dict[str, Any]
    regions: dict[str, Any]
    region_by_id: dict[int, dict[str, Any]]
    raids: dict[str, Any]
    raid_by_id: dict[str, dict[str, Any]]
    chests: dict[str, Any]
    crafting: dict[str, Any]
    economy: dict[str, Any]
    market_reference: dict[str, Any]
    talents: dict[str, Any]
    egg_heroes: dict[str, Any]
    heroes: dict[str, Any]
    combat: dict[str, Any]
    tutorial: dict[str, Any]
    tag_colors: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)


def _variant_pool(variant: dict[str, Any], base_pool: list[str]) -> list[str]:
    """变体的副属性池：与族自身池求交后取用；交集为空则退回族自身池（基础型 pool 为空即此意）。"""
    wanted = [a for a in (variant.get("pool") or []) if a in base_pool]
    return wanted or list(base_pool)


def _variant_id_suffix(variant: dict[str, Any]) -> str:
    vid = variant.get("id") or ""
    return f"_{vid}" if vid else ""


def _expand_base_items(
    data: dict[str, Any],
    job_main_attr: dict[str, str],
    job_affixes: dict[str, str] | None = None,
) -> list[BaseItem]:
    pools = data["subAttrPools"]
    variants = data.get("variants", {})
    weapon_variants = variants.get("weapon") or [{}]
    armor_variants = variants.get("armor") or [{}]
    accessory_variants = variants.get("accessory") or [{}]
    affixes = job_affixes or {}
    out: list[BaseItem] = []

    for fam in data["weaponFamilies"]:
        is_magical = job_main_attr.get(fam["jobId"]) == "int"
        base_pool = list(pools[fam["pool"]])
        # 武器只保留「基础型（id 为空，随机）」+ 该职业自身职能词缀那一个变体。
        wanted_affix = affixes.get(fam["jobId"], "")
        for t in data["tiers"]:
            for v in weapon_variants:
                if v.get("id") and v["id"] != wanted_affix:
                    continue
                if int(v.get("minTier", 0)) > int(t["index"]):
                    continue
                out.append(
                    BaseItem(
                        id=f"w_{fam['weaponType']}{_variant_id_suffix(v)}_{t['index']}",
                        name=f"{t['name']}{v.get('name', '')}{fam['suffix']}",
                        category="weapon",
                        slot="mainHand",
                        weapon_type=fam["weaponType"],
                        job_id=fam["jobId"],
                        level_req=t["levelReq"],
                        tier_index=t["index"],
                        tier_name=t["name"],
                        base_attrs=[
                            {"attr": "magicAttack" if is_magical else "attack", "base": t["weaponAttack"]}
                        ],
                        sub_attr_pool=_variant_pool(v, base_pool),
                        sub_attr_scale=float(t.get("subAttrScale", 1.0)) * float(v.get("subAttrScale", 1.0)),
                        variant_id=v.get("id", ""),
                        role=v.get("role"),
                    )
                )

    for fam in data["armorFamilies"]:
        base_pool = list(pools["armor"])
        for t in data["tiers"]:
            for v in armor_variants:
                if int(v.get("minTier", 0)) > int(t["index"]):
                    continue
                attrs = []
                for b in fam["baseAttrs"]:
                    value = t["hp"] * b["ratio"] if b["attr"] == "hp" else t["defense"] * b["ratio"]
                    attrs.append({"attr": b["attr"], "base": value})
                out.append(
                    BaseItem(
                        id=f"a_{fam['slot']}{_variant_id_suffix(v)}_{t['index']}",
                        name=f"{t['name']}{v.get('name', '')}{fam['suffix']}",
                        category="armor",
                        slot=fam["slot"],
                        level_req=t["levelReq"],
                        tier_index=t["index"],
                        tier_name=t["name"],
                        base_attrs=attrs,
                        sub_attr_pool=_variant_pool(v, base_pool),
                        sub_attr_scale=float(t.get("subAttrScale", 1.0)) * float(v.get("subAttrScale", 1.0)),
                        variant_id=v.get("id", ""),
                        role=v.get("role"),
                    )
                )

    for fam in data["accessoryFamilies"]:
        base_pool = list(pools[fam["pool"]])
        for t in data["tiers"]:
            for v in accessory_variants:
                if int(v.get("minTier", 0)) > int(t["index"]):
                    continue
                out.append(
                    BaseItem(
                        id=f"c_{fam['slot']}{_variant_id_suffix(v)}_{t['index']}",
                        name=f"{t['name']}{v.get('name', '')}{fam['suffix']}",
                        category="accessory",
                        slot=fam["slot"],
                        level_req=t["levelReq"],
                        tier_index=t["index"],
                        tier_name=t["name"],
                        base_attrs=[{"attr": v.get("baseAttr") or fam["baseAttr"], "base": t["mainAttr"]}],
                        sub_attr_pool=_variant_pool(v, base_pool),
                        sub_attr_scale=float(t.get("subAttrScale", 1.0)) * float(v.get("subAttrScale", 1.0)),
                        variant_id=v.get("id", ""),
                        role=v.get("role"),
                    )
                )

    return out


@lru_cache(maxsize=1)
def load_game_data() -> GameConfig:
    raw = {
        "rarities": _load("rarities.json"),
        "slots": _load("slots.json"),
        "subAttributes": _load("sub-attributes.json"),
        "terms": _load("terms.json"),
        "jobs": _load("jobs.json"),
        "baseItems": _load("base-items.json"),
        "exclusiveEquipment": _load("exclusive-equipment.json"),
        "worldboss": _load("worldboss.json"),
        "monsters": _load("monsters.json"),
        "bosses": _load("bosses.json"),
        "regions": _load("regions.json"),
        "raids": _load("raids.json"),
        "chests": _load("chests.json"),
        "crafting": _load("crafting.json"),
        "economy": _load("economy.json"),
        "marketReference": _load("market-reference.json"),
        "talents": _load("talents.json"),
        "eggHeroes": _load("egg-heroes.json"),
        "heroes": _load("heroes.json"),
        "combat": _load("combat.json"),
        "tutorial": _load("tutorial.json"),
        "tags": _load("tags.json"),
        "dohdolJobs": _load("dohdol-jobs.json"),
        "dohdolLevels": _load("dohdol-levels.json"),
        "materials": _load("materials.json"),
        "gatherNodes": _load("gather-nodes.json"),
        "dohdolEquipment": _load("dohdol-equipment.json"),
        "fish": _load("fish.json"),
        "weather": _load("weather.json"),
        "recipes": _load("recipes.json"),
        "consumables": _load("consumables.json"),
        "titles": _load("titles.json"),
        "materia": _load("materia.json"),
        "farm": _load("farm.json"),
        "treasure": _load("treasure.json"),
    }

    jobs = raw["jobs"]
    job_by_id = {j["id"]: j for j in jobs["jobs"]}
    job_main_attr = {j["id"]: j["mainAttr"] for j in jobs["jobs"]}

    base_items_data = raw["baseItems"]
    job_affixes = base_items_data.get("jobAffixes", {})
    base_items = _expand_base_items(base_items_data, job_main_attr, job_affixes)

    # 绝境龙神系列：复用同一套「族 × 档位 × 变体」展开，标记 exclusive。
    # 单独特化出来，不并入 base_items（否则会污染抽箱/合成/生产候选池）。
    exclusive_items = [
        replace(item, exclusive=True)
        for item in _expand_base_items(raw["exclusiveEquipment"], job_main_attr, job_affixes)
    ]

    attributes = raw["subAttributes"]["attributes"]
    terms = raw["terms"]

    dohdol_jobs = raw["dohdolJobs"]
    dohdol_item_by_id = {it["id"]: it for it in raw["dohdolEquipment"]["items"]}

    # 材料注册表：采集材料 + 半成品 + 鱼（鱼也是烹饪材料；含普通鱼与特殊鱼）
    material_by_id: dict[str, Any] = {m["id"]: m for m in raw["materials"]["materials"]}
    fish_by_id: dict[str, Any] = {}
    for region in raw["fish"]["regions"]:
        for fish in region["normal"]:
            material_by_id[fish["id"]] = {
                "id": fish["id"], "name": fish["name"], "kind": "fish",
                "regionId": region["regionId"], "sell": int(fish.get("sell", 0)),
            }
            fish_by_id[fish["id"]] = {
                "name": fish["name"], "kind": "normal",
                "rarity": fish.get("rarity", "white"), "regionId": region["regionId"],
            }
        for fish in region["specials"]:
            material_by_id[fish["id"]] = {
                "id": fish["id"], "name": fish["name"], "kind": "fish",
                "regionId": region["regionId"], "sell": int(fish.get("sell", 0)),
            }
            fish_by_id[fish["id"]] = {
                "name": fish["name"], "kind": fish["kind"],
                "rarity": None, "regionId": region["regionId"],
            }

    gather_node_by = {
        (int(node["regionId"]), node["jobId"]): node for node in raw["gatherNodes"]["nodes"]
    }
    fish_region_by_id = {int(r["regionId"]): r for r in raw["fish"]["regions"]}

    # 魔晶石注册表：6 种 × 5 级 = 30 件。id = m_{type}_{level}。
    materia_raw = raw["materia"]
    materia_by_id: dict[str, Any] = {}
    for mtype in materia_raw["types"]:
        values = materia_raw["values"][mtype["id"]]
        for level, value in enumerate(values, start=1):
            materia_id = f"m_{mtype['id']}_{level}"
            materia_by_id[materia_id] = {
                "id": materia_id,
                "name": f"{mtype['name']}魔晶石{materia_raw['grades'][level - 1]}",
                "type": mtype["id"],
                "stat": mtype["stat"],
                "statName": mtype["statName"],
                "level": level,
                "value": float(value),
                "sell": int(materia_raw["sell"].get(str(level), 0)),
            }

    # 作物种子注册表（种田）。
    seed_by_id = {s["id"]: s for s in raw["farm"]["seeds"]}

    return GameConfig(
        rarities=raw["rarities"]["rarities"],
        rarity_order=raw["rarities"]["order"],
        slots=raw["slots"]["slots"],
        slot_categories=raw["slots"]["categories"],
        attributes=attributes,
        attribute_by_id={a["id"]: a for a in attributes},
        terms=terms,
        term_by_id={t["id"]: t for t in terms["terms"]},
        jobs=jobs,
        job_by_id=job_by_id,
        dohdol_jobs=dohdol_jobs,
        dohdol_job_by_id={j["id"]: j for j in dohdol_jobs["jobs"]},
        dohdol_levels=raw["dohdolLevels"],
        materials=raw["materials"],
        material_by_id=material_by_id,
        gather_nodes=raw["gatherNodes"],
        gather_node_by=gather_node_by,
        dohdol_equipment=raw["dohdolEquipment"],
        dohdol_item_by_id=dohdol_item_by_id,
        fish=raw["fish"],
        fish_region_by_id=fish_region_by_id,
        fish_by_id=fish_by_id,
        weather=raw["weather"],
        recipes=raw["recipes"],
        recipe_by_id={r["id"]: r for r in raw["recipes"]["recipes"]},
        consumables=raw["consumables"],
        consumable_by_id={c["id"]: c for c in raw["consumables"]["items"]},
        titles=raw["titles"],
        materia=materia_raw,
        materia_by_id=materia_by_id,
        farm=raw["farm"],
        seed_by_id=seed_by_id,
        treasure=raw["treasure"],
        base_items=base_items,
        base_item_by_id={b.id: b for b in (*base_items, *exclusive_items)},
        exclusive_items=exclusive_items,
        exclusive_item_by_id={b.id: b for b in exclusive_items},
        worldboss=raw["worldboss"],
        base_item_tiers=base_items_data["tiers"],
        base_attr_float=base_items_data["baseAttrFloat"],
        sub_attr_float=base_items_data["subAttrFloat"],
        monsters=raw["monsters"],
        bosses=raw["bosses"],
        regions=raw["regions"],
        region_by_id={r["id"]: r for r in raw["regions"]["regions"]},
        raids=raw["raids"],
        raid_by_id={r["id"]: r for r in raw["raids"]["raids"]},
        chests=raw["chests"],
        crafting=raw["crafting"],
        economy=raw["economy"],
        market_reference=raw["marketReference"],
        talents=raw["talents"],
        egg_heroes=raw["eggHeroes"],
        heroes=raw["heroes"],
        combat=raw["combat"],
        tutorial=raw["tutorial"],
        tag_colors=raw["tags"],
        raw=raw,
    )

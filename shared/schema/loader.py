"""共享数据层的 Python 加载器。

与 `index.ts` 对应，读取同一个 `shared/data/*.json`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
    base_items: list[BaseItem]
    base_item_by_id: dict[str, BaseItem]
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
    talents: dict[str, Any]
    heroes: dict[str, Any]
    combat: dict[str, Any]
    tutorial: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)


def _expand_base_items(data: dict[str, Any], job_main_attr: dict[str, str]) -> list[BaseItem]:
    pools = data["subAttrPools"]
    out: list[BaseItem] = []

    for fam in data["weaponFamilies"]:
        is_magical = job_main_attr.get(fam["jobId"]) == "int"
        for t in data["tiers"]:
            out.append(
                BaseItem(
                    id=f"w_{fam['weaponType']}_{t['index']}",
                    name=f"{t['name']}{fam['suffix']}",
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
                    sub_attr_pool=list(pools[fam["pool"]]),
                    sub_attr_scale=float(t.get("subAttrScale", 1.0)),
                )
            )

    for fam in data["armorFamilies"]:
        for t in data["tiers"]:
            attrs = []
            for b in fam["baseAttrs"]:
                value = t["hp"] * b["ratio"] if b["attr"] == "hp" else t["defense"] * b["ratio"]
                attrs.append({"attr": b["attr"], "base": value})
            out.append(
                BaseItem(
                    id=f"a_{fam['slot']}_{t['index']}",
                    name=f"{t['name']}{fam['suffix']}",
                    category="armor",
                    slot=fam["slot"],
                    level_req=t["levelReq"],
                    tier_index=t["index"],
                    tier_name=t["name"],
                    base_attrs=attrs,
                    sub_attr_pool=list(pools["armor"]),
                    sub_attr_scale=float(t.get("subAttrScale", 1.0)),
                )
            )

    for fam in data["accessoryFamilies"]:
        for t in data["tiers"]:
            out.append(
                BaseItem(
                    id=f"c_{fam['slot']}_{t['index']}",
                    name=f"{t['name']}{fam['suffix']}",
                    category="accessory",
                    slot=fam["slot"],
                    level_req=t["levelReq"],
                    tier_index=t["index"],
                    tier_name=t["name"],
                    base_attrs=[{"attr": fam["baseAttr"], "base": t["mainAttr"]}],
                    sub_attr_pool=list(pools[fam["pool"]]),
                    sub_attr_scale=float(t.get("subAttrScale", 1.0)),
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
        "monsters": _load("monsters.json"),
        "bosses": _load("bosses.json"),
        "regions": _load("regions.json"),
        "raids": _load("raids.json"),
        "chests": _load("chests.json"),
        "crafting": _load("crafting.json"),
        "economy": _load("economy.json"),
        "talents": _load("talents.json"),
        "heroes": _load("heroes.json"),
        "combat": _load("combat.json"),
        "tutorial": _load("tutorial.json"),
    }

    jobs = raw["jobs"]
    job_by_id = {j["id"]: j for j in jobs["jobs"]}
    job_main_attr = {j["id"]: j["mainAttr"] for j in jobs["jobs"]}

    base_items_data = raw["baseItems"]
    base_items = _expand_base_items(base_items_data, job_main_attr)

    attributes = raw["subAttributes"]["attributes"]
    terms = raw["terms"]

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
        base_items=base_items,
        base_item_by_id={b.id: b for b in base_items},
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
        talents=raw["talents"],
        heroes=raw["heroes"],
        combat=raw["combat"],
        tutorial=raw["tutorial"],
        raw=raw,
    )

"""组装生产 / 采集 DLC 的状态快照（供 /game/state 与 /dohdol/state 复用）。"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DohDolProgress, FishRecord, Item, StackItem, UserTitle
from app.services import consumables, dohdol_util
from app.services.game_config import CONFIG
from app.services.serialization import item_to_dict


async def _progress_map(db: AsyncSession, user_id: int) -> dict[str, dict[str, Any]]:
    rows = (
        await db.execute(select(DohDolProgress).where(DohDolProgress.user_id == user_id))
    ).scalars().all()
    by_kind = {row.kind: row for row in rows}
    out: dict[str, dict[str, Any]] = {}
    for kind in ("doh", "dol"):
        row = by_kind.get(kind)
        level = int(row.level) if row else 1
        out[kind] = {
            "kind": kind,
            "name": CONFIG.dohdol_levels["kinds"][kind]["name"],
            "level": level,
            "exp": int(row.exp) if row else 0,
            "expToNext": dohdol_util.exp_to_next(level),
            "levelCap": dohdol_util.level_cap(),
        }
    return out


async def _stacks(db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(StackItem).where(StackItem.user_id == user_id, StackItem.count > 0)
        )
    ).scalars().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        spec = dohdol_util.material_def(row.item_id) or dohdol_util.consumable_def(row.item_id) or {}
        entry: dict[str, Any] = {
            "itemId": row.item_id,
            "kind": row.kind,
            "count": int(row.count),
            "name": spec.get("name", row.item_id),
            "sell": dohdol_util.sell_price(row.kind, row.item_id),
        }
        if row.kind in ("potion", "food"):
            entry["consumableKind"] = row.kind
            entry["effects"] = spec.get("effects", [])
            entry["desc"] = spec.get("desc", "")
        else:
            entry["materialKind"] = spec.get("kind", "gather")
        out.append(entry)
    return out


def _recipe_view(recipe: dict[str, Any], level: int, stock: dict[str, int]) -> dict[str, Any]:
    inputs = [
        {
            "itemId": e["itemId"],
            "name": dohdol_util.material_name(e["itemId"]),
            "count": int(e["count"]),
            "have": int(stock.get(e["itemId"], 0)),
        }
        for e in recipe["inputs"]
    ]
    craftable = None
    for e in recipe["inputs"]:
        have = int(stock.get(e["itemId"], 0))
        possible = have // max(1, int(e["count"]))
        craftable = possible if craftable is None else min(craftable, possible)
    output = recipe["output"]
    out_name = dohdol_util.material_name(output.get("itemId") or output.get("baseId") or "")
    dohdol_item = CONFIG.dohdol_item_by_id.get(output.get("baseId") or "")
    return {
        "id": recipe["id"],
        "jobId": recipe["jobId"],
        "requiredLevel": int(recipe["requiredLevel"]),
        "unlocked": level >= int(recipe["requiredLevel"]),
        "craftSeconds": float(recipe["craftSeconds"]),
        "xp": int(recipe["xp"]),
        "inputs": inputs,
        "output": {
            "kind": output["kind"],
            "itemId": output.get("itemId"),
            "baseId": output.get("baseId"),
            "name": out_name,
            "count": int(output.get("count", 1)),
            "quality": "high" if output["kind"] == "equipment" else None,
            "supply": "dohdol" if dohdol_item else ("combat" if output["kind"] == "equipment" else "material"),
        },
        "craftable": craftable if craftable is not None else 0,
    }


async def build_dohdol_state(
    db: AsyncSession, user_id: int, items: Sequence[Item] | None = None
) -> dict[str, Any]:
    progress = await _progress_map(db, user_id)
    stacks = await _stacks(db, user_id)
    stack_map = {row["itemId"]: row["count"] for row in stacks if row["kind"] == "material"}

    recipes = [
        _recipe_view(r, progress["doh"]["level"], stack_map) for r in CONFIG.recipes["recipes"]
    ]

    # 专用装备（仅生产/采集装备）
    if items is None:
        items = (await db.execute(select(Item).where(Item.user_id == user_id))).scalars().all()
    dedicated_loadout: dict[str, dict[str, Any]] = {}
    for item in items:
        if item.category in ("doh_tool", "doh_gear", "dol_tool", "dol_gear") and item.equipped_slot:
            dedicated_loadout[item.equipped_slot] = item_to_dict(item)

    fish_rows = (
        await db.execute(select(FishRecord).where(FishRecord.user_id == user_id))
    ).scalars().all()
    fish_species = len(fish_rows)
    fish_count = sum(int(r.count) for r in fish_rows)
    king_count = sum(1 for r in fish_rows if r.kind == "king")
    emperor_count = sum(1 for r in fish_rows if r.kind == "emperor")

    title_rows = (
        await db.execute(select(UserTitle).where(UserTitle.user_id == user_id))
    ).scalars().all()
    owned_titles = {row.title_id for row in title_rows}
    titles = [
        {**t, "owned": t["id"] in owned_titles} for t in CONFIG.titles["titles"]
    ]

    return {
        "progress": progress,
        "materials": [row for row in stacks if row["kind"] == "material"],
        "consumables": [row for row in stacks if row["kind"] in ("potion", "food")],
        "active": await consumables.active_state(db, user_id),
        "recipes": recipes,
        "loadout": dedicated_loadout,
        "bonus": dohdol_util.equipped_bonus(items),
        "titles": titles,
        "fishStats": {
            "species": fish_species,
            "count": fish_count,
            "king": king_count,
            "kingTotal": len(CONFIG.fish["regions"]),
            "emperor": emperor_count,
            "emperorTotal": len(CONFIG.fish["regions"]),
        },
    }

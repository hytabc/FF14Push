"""称号解锁：数据驱动的条件判定。来源：`shared/data/titles.json`。

两类：
- **确定性条件**（`evaluate_titles`）：按鱼获记录等聚合达成后补发，如全部鱼王 / 困难鱼。
- **彩蛋掉落**（`roll_random_titles`）：极低概率、非确定性（如挖宝下底 / 采集动作），
  每个事件各自 roll，每个未拥有的彩蛋称号按自身 `chance` 独立抽取。

旧称号（鱼王猎手 / 海皇 / 烟波钓徒 / 太公封神）只统计 **legacy** 特殊鱼（原 40 区鱼王 / 鱼皇 +
第一批困难鱼），故后续新增的鱼王 / 鱼皇 / 困难鱼不影响它们的达成条件；新内容用 `legacy: false`
的 `all_legend` / `all_special` 条件另设称号。一旦已解锁即永久保留（evaluate_titles 只补发缺失的称号）。
"""

from __future__ import annotations

import random
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FishRecord, UserTitle
from app.models.multiplayer import CoopProgress
from app.services.game_config import CONFIG


def _specials(kind: str | None = None, legacy: bool | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for region in CONFIG.fish["regions"]:
        for s in region["specials"]:
            if kind is not None and s["kind"] != kind:
                continue
            if legacy is not None and bool(s.get("legacy")) != legacy:
                continue
            out.append(s)
    return out


def _region_group_ids(region_ids: set[int]) -> set[str]:
    target: set[str] = set()
    for region in CONFIG.fish["regions"]:
        if int(region["regionId"]) not in region_ids:
            continue
        for s in region["specials"]:
            if bool(s.get("legacy")):
                target.add(s["id"])
    return target


def _context(rows: Sequence[FishRecord]) -> dict[str, Any]:
    caught_kind: dict[str, int] = {}
    caught_rarity: dict[str, int] = {}
    ids: set[str] = set()
    total = 0
    for row in rows:
        ids.add(row.fish_id)
        total += int(row.count)
        info = CONFIG.fish_by_id.get(row.fish_id)
        if info is None:
            continue
        caught_kind[info["kind"]] = caught_kind.get(info["kind"], 0) + 1
        rarity = info.get("rarity")
        if rarity:
            caught_rarity[rarity] = caught_rarity.get(rarity, 0) + 1
    return {"ids": ids, "kind": caught_kind, "rarity": caught_rarity, "species": len(ids), "count": total}


def matches(condition: dict[str, Any], ctx: dict[str, Any]) -> bool:
    kind = condition.get("type")
    if kind == "all_king":
        return {s["id"] for s in _specials("king", legacy=True)} <= ctx["ids"]
    if kind == "all_emperor":
        return {s["id"] for s in _specials("emperor", legacy=True)} <= ctx["ids"]
    if kind == "all_legend":
        # 默认只统计 legacy（第一批）困难鱼，保证旧称号「烟波钓徒」达成条件不随新增内容变难；
        # 新内容的「全部新困难鱼」用 legacy=false 条件。
        legacy = bool(condition.get("legacy", True))
        target = {s["id"] for s in _specials("legend", legacy=legacy)}
        return bool(target) and target <= ctx["ids"]
    if kind == "all_special":
        # 同上：默认只统计 legacy 特殊鱼（旧「太公封神」集合不变）；legacy=false 为新增特殊鱼。
        legacy = bool(condition.get("legacy", True))
        target = {s["id"] for s in _specials(legacy=legacy)}
        return bool(target) and target <= ctx["ids"]
    if kind == "count_kind":
        return ctx["kind"].get(condition["kind"], 0) >= int(condition["count"])
    if kind == "count_rarity":
        return ctx["rarity"].get(condition["rarity"], 0) >= int(condition["count"])
    if kind == "specific_fish":
        return set(condition["fishIds"]) <= ctx["ids"]
    if kind == "species_count":
        return ctx["species"] >= int(condition["count"])
    if kind == "fish_count":
        return ctx["count"] >= int(condition["count"])
    if kind == "region_group_king":
        return _region_group_ids({int(r) for r in condition["regionIds"]}) <= ctx["ids"]
    return False


async def evaluate_titles(db: AsyncSession, user_id: int) -> list[str]:
    """按当前鱼获记录补发尚未拥有的称号，返回本次新解锁的称号 id 列表。

    只处理**确定性**条件；彩蛋（`random_drop`）由 `roll_random_titles` 在对应事件处抽取。
    """
    rows = (
        await db.execute(select(FishRecord).where(FishRecord.user_id == user_id))
    ).scalars().all()
    if not rows:
        return []
    existing = set(
        (
            await db.execute(select(UserTitle.title_id).where(UserTitle.user_id == user_id))
        ).scalars().all()
    )
    ctx = _context(rows)
    new: list[str] = []
    for title in CONFIG.titles["titles"]:
        if title["id"] in existing:
            continue
        if matches(title["condition"], ctx):
            db.add(UserTitle(user_id=user_id, title_id=title["id"]))
            new.append(title["id"])
    return new


async def evaluate_coop_titles(db: AsyncSession, user_id: int) -> list[str]:
    """远征通关称号：按 `CoopProgress` 中已通关（clears > 0）的副本补发。

    条件为 `condition.type == "coop_clear"` + `dungeonIds`（需全部通关）。幂等：只补发缺失的称号。
    与钓鱼的确定性条件（`evaluate_titles`）互不干扰——`matches()` 对 `coop_clear` 返回 False。
    """
    rows = (
        await db.execute(
            select(CoopProgress.dungeon_id).where(
                CoopProgress.user_id == user_id, CoopProgress.clears > 0
            )
        )
    ).scalars().all()
    cleared = set(rows)
    if not cleared:
        return []
    existing = set(
        (
            await db.execute(select(UserTitle.title_id).where(UserTitle.user_id == user_id))
        ).scalars().all()
    )
    new: list[str] = []
    for title in CONFIG.titles["titles"]:
        condition = title.get("condition", {})
        if condition.get("type") != "coop_clear" or title["id"] in existing:
            continue
        if set(condition.get("dungeonIds") or []) <= cleared:
            db.add(UserTitle(user_id=user_id, title_id=title["id"]))
            new.append(title["id"])
    return new


async def evaluate_palace_titles(db: AsyncSession, user_id: int) -> list[str]:
    """死者宫殿称号：按 `PalaceProfile.floor10_clears` 补发。

    条件为 `condition.type == "palace_clear"` + `count`（通关第 10 层次数达到 count）。
    幂等：只补发缺失的称号；`matches()` 对该类型返回 False，不干扰确定性条件。
    """
    from app.models import PalaceProfile

    profile = await db.scalar(select(PalaceProfile).where(PalaceProfile.user_id == user_id))
    clears = int(profile.floor10_clears or 0) if profile is not None else 0
    if clears <= 0:
        return []
    existing = set(
        (
            await db.execute(select(UserTitle.title_id).where(UserTitle.user_id == user_id))
        ).scalars().all()
    )
    new: list[str] = []
    for title in CONFIG.titles["titles"]:
        condition = title.get("condition", {})
        if condition.get("type") != "palace_clear" or title["id"] in existing:
            continue
        if clears >= int(condition.get("count", 1)):
            db.add(UserTitle(user_id=user_id, title_id=title["id"]))
            new.append(title["id"])
    return new


def random_drop_titles(event: str) -> list[dict[str, Any]]:
    """按事件列出彩蛋称号（`condition.type == "random_drop"` 且 event 匹配）。"""
    return [
        title
        for title in CONFIG.titles["titles"]
        if title.get("condition", {}).get("type") == "random_drop"
        and title.get("condition", {}).get("event") == event
    ]


async def roll_random_titles(
    db: AsyncSession,
    user_id: int,
    event: str,
    rolls: int = 1,
    rng: random.Random | None = None,
) -> list[str]:
    """彩蛋称号掉落：每个未拥有的彩蛋称号按各自 `chance` 独立抽取。

    `rolls` = 本次事件重复次数（如一次上报的采集动作数），合并概率 = 1 − (1−p)^rolls；
    挖宝下底等单次事件 rolls=1。返回本次新解锁的称号 id（无则空列表）。
    """
    candidates = random_drop_titles(event)
    if not candidates or rolls <= 0:
        return []
    rng = rng or random.Random()
    owned = set(
        (
            await db.execute(select(UserTitle.title_id).where(UserTitle.user_id == user_id))
        ).scalars().all()
    )
    new: list[str] = []
    for title in candidates:
        if title["id"] in owned:
            continue
        chance = min(1.0, max(0.0, float(title["condition"].get("chance", 0.0))))
        if chance <= 0:
            continue
        probability = 1.0 - (1.0 - chance) ** int(rolls)
        if rng.random() < probability:
            db.add(UserTitle(user_id=user_id, title_id=title["id"]))
            new.append(title["id"])
    return new

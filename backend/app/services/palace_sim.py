"""死者宫殿：无头数值标定（供 scripts/palace-balance.py 与 pytest 共用）。

用**真实战斗公式**（`combat_model.theoretical_dps` + `palace_stats.compute_run_stats`）估算
「一路推进能到第几层」。这是**标定工具**，不是权威结算——它只回答两个设计问题：

1. 零局外成长的玩家（运气任意）最多能到第几层；
2. 满局外成长的玩家在前几层有多快。

平均化假设（保守）：每层换一套该层等级的装备、累计 2 条随机祝福、层内走约 7 个战斗节点 +
1 个层主；不计局内掉落运气的极端值。
"""

from __future__ import annotations

import random
from typing import Any, Iterable

from app.services import palace_data, palace_stats
from app.services.combat_model import theoretical_dps
from app.services.game_config import CONFIG

# 层内近似战斗节点数（普通/精英合计），用于累计经验与损耗。
NODES_PER_FLOOR = 7
# 生存余量：实际战斗有伤害波动与未建模的技能，要求「击杀时间 < 生存时间 × 余量」才算过。
SURVIVAL_MARGIN = 0.75


def _gain_exp(hero: dict[str, Any], amount: int) -> None:
    cap = palace_data.level_cap()
    hero["exp"] = int(hero.get("exp", 0)) + max(0, int(amount))
    while int(hero["level"]) < cap:
        need = palace_data.exp_to_next(int(hero["level"]))
        if int(hero["exp"]) < need:
            break
        hero["exp"] = int(hero["exp"]) - need
        hero["level"] = int(hero["level"]) + 1
    if int(hero["level"]) >= cap:
        hero["exp"] = 0


def _survives(
    hero: dict[str, Any],
    items: list[dict[str, Any]],
    equipped: dict[str, int],
    unlocked: Iterable[str],
    buffs: list[dict[str, Any]],
    floor: int,
    node_type: str,
    rng: random.Random,
) -> bool:
    stats = palace_stats.compute_run_stats(hero, items, equipped, unlocked, buffs)
    enemy = palace_data.enemy_stats(floor, node_type, rng)
    dps = max(1.0, theoretical_dps(stats, float(enemy["defense"]), None, str(enemy["kind"])))
    kill_seconds = float(enemy["hp"]) / dps
    incoming = max(float(enemy["attack"]) * 0.1, float(enemy["attack"]) - min(stats.phys_def, stats.magic_def))
    incoming /= max(0.1, float(enemy["attackInterval"]))
    survival_seconds = float(stats.max_hp) / max(1e-6, incoming)
    return kill_seconds <= survival_seconds * SURVIVAL_MARGIN


def simulate_reach(
    unlocked: Iterable[str] | None = None,
    seed: int = 0,
    *,
    floors: int | None = None,
    max_level: int | None = None,
) -> int:
    """返回本次模拟到达的层数（0 = 第 1 层就没打过）。"""
    rng = random.Random(seed)
    unlocked = list(unlocked or [])
    _, add = palace_stats.growth_mods(unlocked)

    talent_bonus = float(add.get("heroTalentWeight", 0.0))
    candidates = palace_data.hero_candidates(talent_bonus, 1, rng)
    start_level = min(
        max_level or palace_data.level_cap(),
        1 + int(round(float(add.get("startLevel", 0.0)))),
    )
    hero = palace_data.hero_snapshot(candidates[0], start_level)
    equip_bonus = int(round(float(add.get("equipLevel", 0.0))))
    luck = float(add.get("equipQualityWeight", 0.0))
    quality = min(0.5, float(add.get("dropQualityWeight", 0.0)))

    weapon = palace_data.generate_item("weapon", palace_data.item_level(1, equip_bonus), rng)
    items: list[dict[str, Any]] = [weapon]
    equipped: dict[str, int] = {weapon["slot"]: 0}
    buffs: list[dict[str, Any]] = []

    total_floors = int(floors or palace_data.floors())
    reached = 0
    for floor in range(1, total_floors + 1):
        for category in ("weapon", "armor", "accessory"):
            item = palace_data.generate_item(
                category, palace_data.item_level(floor, equip_bonus), rng,
                luck=luck, quality_bonus=quality,
            )
            items.append(item)
            equipped[item["slot"]] = len(items) - 1
        for _ in range(2):
            buff = palace_data.pick_buff(rng)
            buffs.append({
                "id": buff["id"], "name": buff["name"], "stat": buff["stat"],
                "value": buff["value"], "desc": buff["desc"],
            })

        for _ in range(NODES_PER_FLOOR):
            if not _survives(hero, items, equipped, unlocked, buffs, floor, "battle", rng):
                return reached
            _grant_rewards(items, equipped, buffs, floor, equip_bonus, luck, quality, rng)
            xp, _gold = palace_data.enemy_rewards(floor, "battle")
            _gain_exp(hero, xp)
        if not _survives(hero, items, equipped, unlocked, buffs, floor, "boss", rng):
            return reached
        _grant_rewards(items, equipped, buffs, floor, equip_bonus, luck, quality, rng)
        _grant_rewards(items, equipped, buffs, floor, equip_bonus, luck, quality, rng)
        xp, _gold = palace_data.enemy_rewards(floor, "boss")
        _gain_exp(hero, xp)
        reached = floor
    return reached


def _grant_rewards(
    items: list[dict[str, Any]],
    equipped: dict[str, int],
    buffs: list[dict[str, Any]],
    floor: int,
    equip_bonus: int,
    luck: float,
    quality: float,
    rng: random.Random,
) -> None:
    """按 3 选 1 奖励的真实概率补充装备 / 祝福（equip 0.65、buff 0.55，含 both）。"""
    if rng.random() < 0.65:
        category = rng.choices(["weapon", "armor", "accessory"], weights=[0.4, 0.35, 0.25], k=1)[0]
        item = palace_data.generate_item(
            category, palace_data.item_level(floor, equip_bonus), rng, luck=luck, quality_bonus=quality
        )
        items.append(item)
        equipped[item["slot"]] = len(items) - 1
    if rng.random() < 0.55:
        buff = palace_data.pick_buff(rng)
        buffs.append({
            "id": buff["id"], "name": buff["name"], "stat": buff["stat"],
            "value": buff["value"], "desc": buff["desc"],
        })


def kill_seconds(
    unlocked: Iterable[str] | None,
    floor: int,
    node_type: str = "battle",
    seed: int = 0,
    hero_level: int | None = None,
) -> float:
    """满配面板下击杀某层某类敌人的理论秒数（用于「前几层是否速通」的断言）。"""
    rng = random.Random(seed)
    unlocked = list(unlocked or [])
    _, add = palace_stats.growth_mods(unlocked)
    candidates = palace_data.hero_candidates(float(add.get("heroTalentWeight", 0.0)), 1, rng)
    level = hero_level or (1 + int(round(float(add.get("startLevel", 0.0)))))
    hero = palace_data.hero_snapshot(candidates[0], level)
    equip_bonus = int(round(float(add.get("equipLevel", 0.0))))
    luck = float(add.get("equipQualityWeight", 0.0))
    quality = min(0.5, float(add.get("dropQualityWeight", 0.0)))
    items = [
        palace_data.generate_item(cat, palace_data.item_level(floor, equip_bonus), rng, luck=luck, quality_bonus=quality)
        for cat in ("weapon", "armor", "accessory")
    ]
    equipped = {item["slot"]: i for i, item in enumerate(items)}
    stats = palace_stats.compute_run_stats(hero, items, equipped, unlocked, [])
    enemy = palace_data.enemy_stats(floor, node_type, rng)
    dps = max(1.0, theoretical_dps(stats, float(enemy["defense"]), None, str(enemy["kind"])))
    return float(enemy["hp"]) / dps


def full_growth_nodes() -> list[str]:
    return list(CONFIG.palace_growth_by_id.keys())

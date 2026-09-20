"""高难副本：BOSS 属性、进入门槛与通关下限。来源：需求「高难副本」"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from app.services.combat_model import theoretical_dps
from app.services.game_config import CONFIG
from app.services.regions_util import monster_base_stats
from app.services.stats import HeroStats
from app.services.valuation import hero_power

SLOT_COUNT = len(CONFIG.slots)
BOSS_TYPE_BY_ID = {t["id"]: t for t in CONFIG.bosses["types"]}


def raid_by_id(raid_id: str) -> dict[str, Any] | None:
    return CONFIG.raid_by_id.get(raid_id)


def all_raids() -> list[dict[str, Any]]:
    return sorted(CONFIG.raids["raids"], key=lambda r: int(r["order"]))


def boss_stats_for_raid(raid: dict[str, Any], hero_level: int) -> list[dict[str, Any]]:
    """按英雄等级锚定 BOSS 属性。怪物属性与玩家等级一致，再乘副本倍率大幅放大。"""
    base = monster_base_stats(hero_level)
    out: list[dict[str, Any]] = []
    for boss in raid["bosses"]:
        boss_type = BOSS_TYPE_BY_ID.get(str(boss.get("type", "")))
        out.append(
            {
                "id": boss["id"],
                "raidId": raid["id"],
                "name": boss["name"],
                "templateId": boss["id"],
                "kind": "boss",
                "hp": round(base["hp"] * float(boss["hpMultiplier"]), 1),
                "attack": round(base["attack"] * float(boss["attackMultiplier"]), 1),
                "defense": round(base["defense"] * float(boss["defenseMultiplier"]), 1),
                "attackInterval": float(boss["attackInterval"]),
                "level": hero_level,
                "resistancePct": float(boss["resistancePct"]),
                "bossType": boss.get("type"),
                "skills": boss_type["skills"] if boss_type else [],
            }
        )
    return out


def equipped_slot_count(items: Iterable[Any]) -> int:
    return sum(1 for item in items if getattr(item, "equipped_slot", None))


def eligibility(
    raid: dict[str, Any], hero_level: int, stats: HeroStats, items: Iterable[Any]
) -> tuple[bool, str | None]:
    """进入门槛：等级 + 栏位穿满 + 战力阈值。返回 (是否可进入, 拦截原因)。"""
    required_level = int(raid["requiredLevel"])
    if hero_level < required_level:
        return False, f"需要英雄等级 {required_level}"

    if bool(raid.get("requiresAllSlots", True)):
        equipped = equipped_slot_count(items)
        if equipped < SLOT_COUNT:
            return False, f"需要穿满全部 {SLOT_COUNT} 个装备栏位（当前 {equipped} 个）"

    required_power = int(raid["requiredPower"])
    power = hero_power(stats)
    if power < required_power:
        return False, f"战力不足（需要 {required_power}，当前 {power}）"
    return True, None


def min_clear_seconds(
    stats: HeroStats,
    bosses: Sequence[dict[str, Any]],
    tolerance: float = 1.0,
) -> float:
    """通关所需的最少时间下界 = Σ BOSS 血量 / 理论 DPS（含抗性）。用于服务端防作弊。"""
    if not bosses:
        return 0.0
    avg_defense = sum(float(b["defense"]) for b in bosses) / len(bosses)
    avg_resistance = sum(float(b.get("resistancePct", 0.0)) for b in bosses) / len(bosses)
    dps = theoretical_dps(stats, avg_defense, None) * (1.0 - avg_resistance / 100.0)
    total_hp = sum(float(b["hp"]) for b in bosses)
    return total_hp / max(0.01, dps) / max(0.01, tolerance)

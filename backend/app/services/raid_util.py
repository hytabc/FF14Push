"""高难副本：BOSS 属性、进入门槛与通关下限。来源：需求「高难副本」"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

from app.services.combat_model import theoretical_dps
from app.services.game_config import CONFIG
from app.services.regions_util import monster_base_stats
from app.services.stats import HeroStats
from app.services.valuation import hero_power

SLOT_COUNT = len(CONFIG.slots)
BOSS_TYPE_BY_ID = {t["id"]: t for t in CONFIG.bosses["types"]}
RARITY_RANK = {r: i for i, r in enumerate(CONFIG.rarity_order)}
RARITY_NAME = {r: CONFIG.rarities[r]["name"] for r in CONFIG.rarity_order}
REF = CONFIG.monsters["reference"]
BALANCE = CONFIG.raids.get("balance", {})


def raid_by_id(raid_id: str) -> dict[str, Any] | None:
    return CONFIG.raid_by_id.get(raid_id)


def all_raids() -> list[dict[str, Any]]:
    return sorted(CONFIG.raids["raids"], key=lambda r: int(r["order"]))


def anchor_dps(hero_level: float) -> float:
    """等级锚定的参考输出：怪物基准血量 ÷ targetKillSeconds。"""
    return monster_base_stats(hero_level)["hp"] / float(REF["targetKillSeconds"])


def ref_dps(hero_level: int, difficulty: str) -> float:
    """该难度「刚好够门槛的装备」在此等级的参考输出。"""
    multipliers = BALANCE.get("refDpsMultiplier", {})
    multiplier = float(multipliers.get(difficulty, 1.0))
    return max(1.0, anchor_dps(hero_level) * multiplier)


def power_scale(stats: HeroStats, hero_level: int, difficulty: str) -> float:
    """BOSS 血量缩放系数 = (玩家输出 ÷ 本等级参考输出) ^ powerScaleExponent（下限 1）。

    只放大、不缩小：刚好够门槛的装备比值≈1（维持基准难度），
    装备越超模 BOSS 越强，避免「等级锚定 + 装备碾压」的漏洞。
    """
    exponent = float(BALANCE.get("powerScaleExponent", 0.0))
    if exponent <= 0 or stats is None:
        return 1.0
    ratio = theoretical_dps(stats, 0.0, None) / ref_dps(hero_level, difficulty)
    return max(1.0, ratio) ** exponent


def attack_scale(stats: HeroStats, hero_level: int, difficulty: str) -> float:
    exponent = float(BALANCE.get("attackScaleExponent", 0.0))
    if exponent <= 0 or stats is None:
        return 1.0
    ratio = theoretical_dps(stats, 0.0, None) / ref_dps(hero_level, difficulty)
    return max(1.0, ratio) ** exponent


def top_rarity_required(raid: dict[str, Any]) -> int:
    """需要达到 topRarity 的件数：栏位数 × 比例，向上取整（11 × 0.5 → 6）。"""
    return math.ceil(SLOT_COUNT * float(raid.get("topRarityRatio", 0.5)))


def ancient_term_count(item: Any, minimum: int = 1) -> bool:
    return sum(1 for t in (item.terms or []) if t.get("quality") == "ancient") >= minimum


def boss_stats_for_raid(
    raid: dict[str, Any], hero_level: int, stats: HeroStats | None = None
) -> list[dict[str, Any]]:
    """按英雄等级锚定 BOSS 属性，再乘副本倍率与「战力缩放」。

    怪物属性与玩家等级一致；装备超出本等级参考水平时 BOSS 同步变强（见 power_scale）。
    """
    base = monster_base_stats(hero_level)
    difficulty = str(raid.get("difficulty", "normal"))
    hp_scale = power_scale(stats, hero_level, difficulty)
    atk_scale = attack_scale(stats, hero_level, difficulty)
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
                "hp": round(base["hp"] * float(boss["hpMultiplier"]) * hp_scale, 1),
                "attack": round(base["attack"] * float(boss["attackMultiplier"]) * atk_scale, 1),
                "defense": round(base["defense"] * float(boss["defenseMultiplier"]), 1),
                "attackInterval": float(boss["attackInterval"]),
                "level": hero_level,
                "resistancePct": float(boss["resistancePct"]),
                "bossType": boss.get("type"),
                "skills": boss_type["skills"] if boss_type else [],
            }
        )
    return out


def eligibility(
    raid: dict[str, Any], hero_level: int, stats: HeroStats, items: Iterable[Any]
) -> tuple[bool, str | None]:
    """进入门槛：等级 → 栏位穿满 → 装备品阶 → 太古词条 → 战力。返回 (是否可进入, 拦截原因)。"""
    required_level = int(raid["requiredLevel"])
    if hero_level < required_level:
        return False, f"需要英雄等级 {required_level}"

    equipped = [item for item in items if getattr(item, "equipped_slot", None)]
    if bool(raid.get("requiresAllSlots", True)) and len(equipped) < SLOT_COUNT:
        return False, f"需要穿满全部 {SLOT_COUNT} 个装备栏位（当前 {len(equipped)} 个）"

    min_rarity = str(raid.get("minEquipRarity", "common"))
    min_rank = RARITY_RANK.get(min_rarity, 0)
    below = [item for item in equipped if RARITY_RANK.get(item.rarity, 0) < min_rank]
    if below:
        return False, (
            f"全部装备品阶不得低于{RARITY_NAME.get(min_rarity, min_rarity)}"
            f"（当前 {len(below)} 件未达标）"
        )

    top_rarity = raid.get("topRarity")
    if top_rarity:
        need = top_rarity_required(raid)
        top_rank = RARITY_RANK.get(str(top_rarity), 0)
        got = sum(1 for item in equipped if RARITY_RANK.get(item.rarity, 0) >= top_rank)
        if got < need:
            return False, (
                f"需要至少 {need} 件{RARITY_NAME.get(str(top_rarity), top_rarity)}装备（当前 {got} 件）"
            )

    need_ancient = int(raid.get("minAncientTermsPerItem", 0) or 0)
    if need_ancient > 0:
        ok = sum(1 for item in equipped if ancient_term_count(item, need_ancient))
        if ok < SLOT_COUNT:
            return False, (
                f"需要每件装备至少 {need_ancient} 个太古词条（当前 {ok}/{SLOT_COUNT} 件达标）"
            )

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

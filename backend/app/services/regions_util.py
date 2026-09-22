"""地区、小怪与 BOSS 的属性推导与金币结算。

对应前端 `src/game/core/regions.ts`。所有数值必须两端一致，客户端才能正确模拟战斗。
"""

from __future__ import annotations

import random
from typing import Any

from app.services.game_config import CONFIG

REF = CONFIG.monsters["reference"]
MONSTER_INTERVAL = float(CONFIG.monsters["monsterAttackInterval"])
TEMPLATE_BY_ID = {t["id"]: t for t in CONFIG.monsters["templates"]}
BOSS_TYPE_BY_ID = {t["id"]: t for t in CONFIG.bosses["types"]}

BOSS_KIND = "boss"


def region_level(region: dict[str, Any]) -> float:
    """地区等级取区间下限，与参考英雄曲线对齐。"""
    return float(region["levelMin"])


def region_level_mid(region: dict[str, Any]) -> float:
    return (float(region["levelMin"]) + float(region["levelMax"])) / 2.0


def _ref_attack(level: float) -> float:
    return float(REF["heroAttack"]["base"]) + float(REF["heroAttack"]["perLevel"]) * (level - 1)


def _ref_hp(level: float) -> float:
    return float(REF["heroHp"]["base"]) + float(REF["heroHp"]["perLevel"]) * (level - 1)


def monster_base_stats(level: float) -> dict[str, float]:
    """由「期望英雄」曲线推导的小怪基准属性。

    期望英雄 = 等级匹配地区 + 已装备等级对应底材武器 + 5 技能职业。
    怪物 HP 按「期望英雄的每秒伤害 × targetKillSeconds」锚定，因此等级匹配、
    装备到位时单怪耗时约等于 targetKillSeconds；装备越差耗时越长（可能阵亡）。
    """
    atk = _ref_attack(level)
    hp = _ref_hp(level)
    expected_dps = (
        atk
        * float(REF["refGearAttackMultiplier"])
        * float(REF["refPotencyPerSecond"]) / 100.0
        * float(REF["refDamageMultiplier"])
    )
    return {
        "hp": expected_dps * float(REF["targetKillSeconds"]),
        "attack": hp / (float(REF["targetSurvivalSeconds"]) / MONSTER_INTERVAL),
        "defense": atk * float(REF["defenseRatioOfAttack"]),
    }


def monster_stats(region_id: int, template_id: str) -> dict[str, Any]:
    region = CONFIG.region_by_id[region_id]
    template = TEMPLATE_BY_ID[template_id]
    base = monster_base_stats(region_level(region))
    m = template["multipliers"]
    return {
        "id": f"{template_id}",
        "regionId": region_id,
        "name": f"{region['name']}·{template['examples'][0]}",
        "templateId": template_id,
        "kind": "elite" if template_id == "elite" else "normal",
        "hp": round(base["hp"] * float(m["hp"]), 1),
        "attack": round(base["attack"] * float(m["attack"]), 1),
        "defense": round(base["defense"] * float(m["defense"]), 1),
        "attackInterval": round(MONSTER_INTERVAL / float(m["attackSpeed"]), 2),
        "level": round(region_level(region), 1),
    }


def _mid(rng_range: list[float]) -> float:
    return (float(rng_range[0]) + float(rng_range[1])) / 2.0


def boss_stats(region_id: int) -> dict[str, Any]:
    """BOSS 属性取配置区间中值，保证前后端一致。"""
    region = CONFIG.region_by_id[region_id]
    base = monster_base_stats(region_level(region))
    hp_mult = _mid(CONFIG.bosses["hpMultiplierRange"])
    atk_mult = _mid(CONFIG.bosses["attackMultiplierRange"])
    def_mult = _mid(CONFIG.bosses["defenseMultiplierRange"])
    boss_type = BOSS_TYPE_BY_ID[region["bossType"]]
    return {
        "id": f"boss_r{region_id}",
        "regionId": region_id,
        "name": region["bossName"],
        "bossType": region["bossType"],
        "kind": BOSS_KIND,
        "hp": round(base["hp"] * hp_mult, 1),
        "attack": round(base["attack"] * atk_mult, 1),
        "defense": round(base["defense"] * def_mult, 1),
        "attackInterval": float(CONFIG.bosses["attackInterval"]),
        "level": round(region_level(region), 1),
        "skills": boss_type["skills"],
    }


def spawn_interval(region_id: int) -> float:
    return float(CONFIG.region_by_id[region_id]["spawnInterval"])


def kills_required(region_id: int) -> int:
    return int(CONFIG.region_by_id[region_id]["killsRequired"])


def roll_gold(
    region_id: int,
    kind: str,
    gold_bonus_pct: float = 0.0,
    rng: random.Random | None = None,
) -> int:
    """金币 = 地区基准 × 类型系数 × (1±30%) × (1 + 金币加成)，加成上限 +80%。"""
    rng = rng or random
    region = CONFIG.region_by_id[region_id]
    multiplier = float(CONFIG.regions["goldMultipliers"].get(kind, 1.0))
    spread = float(CONFIG.regions["goldFloat"])
    base = float(region["baseGold"]) * multiplier
    value = base * rng.uniform(1.0 - spread, 1.0 + spread)
    bonus = min(float(CONFIG.regions["maxGoldBonus"]), max(0.0, gold_bonus_pct / 100.0))
    return max(1, int(value * (1.0 + bonus)))


def roll_exp(gold: int) -> int:
    return max(1, int(gold * float(CONFIG.monsters["xpPerGold"])))


def gold_bonus_from_terms(term_mods: dict[str, float], kind: str) -> float:
    """金币获取效率类 Buff 的加法叠加。"""
    total = term_mods.get("goldGainPct", 0.0) + term_mods.get("goldAllPct", 0.0)
    if kind == BOSS_KIND:
        total += term_mods.get("goldBossPct", 0.0)
    return total


def exp_bonus_from_terms(term_mods: dict[str, float]) -> float:
    """经验获取效率 Buff 的加法叠加（百分比，由服务端在结算时乘算）。"""
    return float(term_mods.get("expGainPct", 0.0))


def apply_exp_bonus(exp: int, term_mods: dict[str, float]) -> int:
    return max(0, int(int(exp) * (1.0 + exp_bonus_from_terms(term_mods) / 100.0)))


def elite_chance(term_mods: dict[str, float]) -> float:
    base = float(CONFIG.monsters["eliteBaseChance"])
    return min(1.0, base + term_mods.get("eliteChancePct", 0.0) / 100.0)


def level_penalty(hero_level: int, region_id: int) -> dict[str, float]:
    """英雄等级低于地区下限时的软惩罚：命中下降 + 输出下降 + 受伤增加 + 防御衰减。

    每落后 1 级按配置比例累加，超过上限取上限；等级达标则为全 0。
    `defenseIgnorePct` 用于削减英雄防御（否则高防御会把「受伤增加」吃掉，越级仍能磨过去）。
    来源：PRD 地区 7.3
    """
    return level_penalty_for_level(hero_level, int(CONFIG.region_by_id[region_id]["levelMin"]))


def level_penalty_for_level(hero_level: int, target_level: int) -> dict[str, float]:
    """英雄等级低于目标等级（地区下限 / 副本目标等级）时的软惩罚。

    与 `level_penalty` 同源，只是把「地区下限」抽象成任意目标等级，
    供高难副本按 `challengeLevel` 施加等级压制。
    """
    deficit = max(0, int(target_level) - int(hero_level))
    if deficit == 0:
        return {
            "hitRatePenaltyPct": 0.0,
            "damageDealtPenaltyPct": 0.0,
            "damageTakenBonusPct": 0.0,
            "defenseIgnorePct": 0.0,
        }

    cfg = CONFIG.regions["levelPenalty"]
    return {
        "hitRatePenaltyPct": min(
            float(cfg["maxHitRatePenaltyPct"]), deficit * float(cfg["hitRatePenaltyPctPerLevel"])
        ),
        "damageDealtPenaltyPct": min(
            float(cfg["maxDamageDealtPenaltyPct"]), deficit * float(cfg["damageDealtPenaltyPctPerLevel"])
        ),
        "damageTakenBonusPct": min(
            float(cfg["maxDamageTakenBonusPct"]), deficit * float(cfg["damageTakenBonusPctPerLevel"])
        ),
        "defenseIgnorePct": min(
            float(cfg["maxDefenseIgnorePct"]), deficit * float(cfg["defenseIgnorePctPerLevel"])
        ),
    }


def is_region_unlocked(region_id: int, cleared_max: int) -> bool:
    return region_id <= cleared_max + 1

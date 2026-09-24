"""战斗难度等级：怪物数值按「加法」叠加、玩家攻击/防御按「乘法」叠加。

难度 0 = 当前各地区数值（全部乘数 = 1）。配置见 `shared/data/combat.json:difficulty`。
前端镜像：`frontend/src/game/core/difficulty.ts`。两端公式必须保持一致。
"""

from __future__ import annotations

from dataclasses import replace

from app.services.game_config import CONFIG
from app.services.stats import HeroStats

DIFF = CONFIG.combat["difficulty"]
MAX_LEVEL = int(DIFF["maxLevel"])

# 地区战斗难度只作用于关底 BOSS 之前的地区关卡；高难副本 / 远征 / 世界BOSS 不走此系统。
REGION_KIND = "region"


def clamp_level(level: int | None) -> int:
    """夹取到 [0, maxLevel]。非法值按 0 处理。"""
    try:
        value = int(level)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(MAX_LEVEL, value))


def active_difficulty(user: object) -> int:
    """当前生效难度：夹到 [0, maxLevel] 且不超过账号已解锁上限。"""
    return min(
        clamp_level(getattr(user, "battle_difficulty", 0)),
        clamp_level(getattr(user, "battle_difficulty_max", 0)),
    )


def player_attack_multiplier(level: int) -> float:
    return float(DIFF["playerAttackMultiplierPerLevel"]) ** max(0, int(level))


def player_defense_multiplier(level: int) -> float:
    return float(DIFF["playerDefenseMultiplierPerLevel"]) ** max(0, int(level))


def monster_hp_multiplier(level: int) -> float:
    return 1.0 + float(DIFF["monsterHpBonusPerLevel"]) * max(0, int(level))


def monster_attack_multiplier(level: int) -> float:
    return 1.0 + float(DIFF["monsterAttackBonusPerLevel"]) * max(0, int(level))


def monster_defense_multiplier(level: int) -> float:
    return 1.0 + float(DIFF["monsterDefenseBonusPerLevel"]) * max(0, int(level))


def monster_gold_multiplier(level: int) -> float:
    return 1.0 + float(DIFF["monsterGoldBonusPerLevel"]) * max(0, int(level))


def monster_exp_multiplier(level: int) -> float:
    return 1.0 + float(DIFF["monsterExpBonusPerLevel"]) * max(0, int(level))


def monster_multipliers(level: int) -> tuple[float, float, float]:
    """返回 (hp, attack, defense) 的难度乘数。"""
    return (
        monster_hp_multiplier(level),
        monster_attack_multiplier(level),
        monster_defense_multiplier(level),
    )


def scale_player_stats(stats: HeroStats, level: int) -> HeroStats:
    """按难度缩放玩家攻击/防御（物理 + 魔法），不改动生命 / 其它属性。

    仅用于战斗结算（客户端模拟与服务端理论模型），不参与战力/门槛计算。
    """
    level = max(0, int(level))
    if level == 0:
        return stats
    atk = player_attack_multiplier(level)
    dfn = player_defense_multiplier(level)
    return replace(
        stats,
        attack=stats.attack * atk,
        magic_attack=stats.magic_attack * atk,
        phys_def=stats.phys_def * dfn,
        magic_def=stats.magic_def * dfn,
    )

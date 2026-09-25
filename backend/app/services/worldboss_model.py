"""世界BOSS 伤害上限模型：校验客户端上报的伤害增量是否合理。

与地区战斗的 `combat_model` 同性质——**客户端模拟、服务端只夹取上限**。
本模型与 `services/worldboss_engine` 的实际结算逐项对应，并**刻意取上界**：

- 假设全部英雄全程存活、普攻与技能永不空转；
- 攻击增益（allDamageBuff / attackBuff）按「所有增益技能同时生效且常驻」估算；
- 随机浮动取上界 `MAX_ROLL`（引擎为 0.9~1.1）；
- 忽略 BOSS 阶段防御（`defenseMultiplier`）与减伤（`damageReduce`）——它们只会让合法输出更小。

因此合法玩家的实际输出必然低于该上界；再乘配置容差，避免误伤满练度玩家。
改 `worldboss_engine` 的伤害公式时必须同步本模型。
"""

from __future__ import annotations

from typing import Any

# 与 worldboss_engine 同源常量。
BASIC_CD_MS = 2000
GCD_MS = 1500
MAX_ROLL = 1.1


def _damage_buff_upper_bound(skills: list[dict[str, Any]]) -> float:
    """英雄可获得的攻击增益上界（假设所有增益技能的效果同时生效）。"""
    total = 0.0
    for skill in skills:
        for effect in skill.get("effects") or []:
            if effect.get("type") in ("allDamageBuff", "attackBuff"):
                total += max(0.0, float(effect.get("value", 0.0)))
    return total


def hero_max_dps(snapshot: dict[str, Any]) -> float:
    """单个英雄的每秒伤害上界。"""
    stats = snapshot.get("stats") or {}
    attack = float(
        stats.get("magic_attack", 0.0) if stats.get("main_attr") == "int" else stats.get("attack", 0.0)
    )
    level_multiplier = float(snapshot.get("levelMultiplier", 1.0))

    crit = 1.0 + float(stats.get("crit_rate_pct", 0.0)) / 100.0 * max(
        0.0, float(stats.get("crit_damage_pct", 0.0)) / 100.0 - 1.0
    )
    det = 1.0 + float(stats.get("det_bonus_pct", 0.0)) / 100.0
    skills = snapshot.get("skills") or []
    mult = (1.0 + _damage_buff_upper_bound(skills)) * crit * det * level_multiplier

    attack_speed = 1.0 + max(0.0, float(stats.get("attack_speed_pct", 0.0))) / 100.0
    basic_rate = attack_speed / (BASIC_CD_MS / 1000.0)

    max_potency = max([float(s.get("potency", 0.0) or 0.0) for s in skills] + [0.0])
    skill_multiplier = float(snapshot.get("skillMultiplier", 1.0))
    # 技能受 GCD 约束：每秒最多 1000/GCD_MS 次，每次威力不超过技能池内最高威力。
    skill_rate = 1000.0 / GCD_MS

    return max(
        0.0,
        attack * mult * MAX_ROLL * basic_rate
        + attack * (max_potency / 100.0) * skill_multiplier * mult * MAX_ROLL * skill_rate,
    )


def max_damage_in_seconds(
    snapshots: list[dict[str, Any]], seconds: float, tolerance: float = 1.0
) -> float:
    """窗口内伤害上界 = Σ 各英雄每秒上界 × 时间 × 容差。"""
    total = sum(hero_max_dps(snapshot) for snapshot in snapshots)
    return total * max(0.0, float(seconds)) * max(1.0, float(tolerance))

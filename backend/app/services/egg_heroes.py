"""彩蛋英雄：技能集、被动与 DPS 折算。来源：shared/data/egg-heroes.json"""

from __future__ import annotations

from typing import Any

from app.services.game_config import CONFIG

# 会把「技能威力」放大的 effect 类型（用于击杀额度的平均 DPS 估算）
_DAMAGE_BUFF_TYPES = ("skillDamageBuff", "allDamageBuff", "attackBuff")
# 充能类 effect：技能释放后给英雄叠加计数
_CHARGE_EFFECT_TYPES = ("doublePowerCharges", "doubleRewardCharges")


def _heroes() -> list[dict[str, Any]]:
    return list(CONFIG.egg_heroes.get("heroes", []))


def egg_def(egg_id: str | None) -> dict[str, Any] | None:
    if not egg_id:
        return None
    for hero in _heroes():
        if hero.get("id") == egg_id:
            return hero
    return None


def skills_for(egg_id: str | None, job_id: str) -> tuple[list[dict[str, Any]], bool] | None:
    """彩蛋英雄在该职业下的技能集。

    返回 (技能列表, 是否替换职业技能)；彩蛋未绑定该职业或无技能时为 None。
    jobId 为 null 表示任意职业。
    """
    egg = egg_def(egg_id)
    if not egg:
        return None
    bound = egg.get("jobId")
    if bound and bound != job_id:
        return None
    skills = egg.get("skills") or []
    if not skills:
        return None
    return list(skills), bool(egg.get("replaceSkills"))


def luck_bonus(egg_id: str | None) -> float:
    """彩蛋被动的装备品阶幸运加成（luck 系数）。"""
    egg = egg_def(egg_id)
    passive = egg.get("passive") if egg else None
    if not passive or passive.get("type") != "chestLuckBonus":
        return 0.0
    return float(passive.get("value", 0.0) or 0.0)


def exp_bonus_pct(egg_id: str | None) -> float:
    """彩蛋被动的经验获取加成（百分比），如「豆芽精」+25%。"""
    egg = egg_def(egg_id)
    passive = egg.get("passive") if egg else None
    if not passive or passive.get("type") != "expGainBonus":
        return 0.0
    return float(passive.get("value", 0.0) or 0.0) * 100.0


def normal_mob_potency100_bonus(egg_id: str | None) -> float:
    """彩蛋被动「战斗爽」：对战普通怪物时，威力恰为 100% 的技能威力加成（1 = 翻倍）。"""
    egg = egg_def(egg_id)
    passive = egg.get("passive") if egg else None
    if not passive or passive.get("type") != "normalMobPotency100Bonus":
        return 0.0
    return max(0.0, float(passive.get("value", 0.0) or 0.0))


def craft_extra_chance(egg_id: str | None) -> float:
    """彩蛋被动「生产专家」：生产物品时额外多产出一件的概率（0-1）。"""
    egg = egg_def(egg_id)
    passive = egg.get("passive") if egg else None
    if not passive or passive.get("type") != "craftExtraChance":
        return 0.0
    return min(1.0, max(0.0, float(passive.get("value", 0.0) or 0.0)))


def charge_grants(egg_id: str | None, job_id: str) -> dict[str, int]:
    """该彩蛋英雄充能类技能：技能 id -> 每次释放叠加的计数。"""
    result: dict[str, int] = {}
    egg = egg_def(egg_id)
    if not egg:
        return result
    bound = egg.get("jobId")
    if bound and bound != job_id:
        return result
    for skill in egg.get("skills") or []:
        total = 0
        for effect in skill.get("effects") or []:
            if str(effect.get("type")) in _CHARGE_EFFECT_TYPES:
                total += int(float(effect.get("value", 0.0) or 0.0))
        if total:
            result[str(skill["id"])] = total
    return result


def dps_uplift(egg_id: str | None) -> float:
    """彩蛋技能增伤效果折算的平均 DPS 提升系数（服务端击杀额度估算用）。

    对增伤类 effect 按 duration / cd 估算平均覆盖：uplift *= 1 + value × min(1, duration / cd)。
    """
    egg = egg_def(egg_id)
    if not egg:
        return 1.0
    uplift = 1.0
    for skill in egg.get("skills") or []:
        cd = float(skill.get("cd", 0) or 0)
        if cd <= 0:
            continue
        for effect in skill.get("effects") or []:
            if str(effect.get("type")) not in _DAMAGE_BUFF_TYPES:
                continue
            value = float(effect.get("value", 0.0) or 0.0)
            duration = float(effect.get("duration", 0.0) or 0.0)
            if value > 0 and duration > 0:
                uplift *= 1.0 + value * min(1.0, duration / cd)
    return uplift

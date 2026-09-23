"""高难副本：BOSS 属性、进入门槛与通关下限。来源：需求「高难副本」"""

from __future__ import annotations

import math
from typing import Any, Iterable

from app.services.game_config import CONFIG
from app.services.regions_util import level_penalty_for_level, monster_base_stats
from app.services.stats import HeroStats
from app.services.valuation import hero_power

SLOT_COUNT = len(CONFIG.slots)
BOSS_TYPE_BY_ID = {t["id"]: t for t in CONFIG.bosses["types"]}
RARITY_RANK = {r: i for i, r in enumerate(CONFIG.rarity_order)}
RARITY_NAME = {r: CONFIG.rarities[r]["name"] for r in CONFIG.rarity_order}
BALANCE = CONFIG.raids.get("balance", {})


def raid_by_id(raid_id: str) -> dict[str, Any] | None:
    return CONFIG.raid_by_id.get(raid_id)


def all_raids() -> list[dict[str, Any]]:
    return sorted(CONFIG.raids["raids"], key=lambda r: int(r["order"]))


def challenge_level(raid: dict[str, Any], hero_level: int) -> int:
    """副本的目标等级：BOSS 数值固定按此等级锚定，缺省回退进入等级 / 英雄等级。"""
    return int(raid.get("challengeLevel") or raid.get("requiredLevel") or hero_level)


def daily_reward_clears(raid: dict[str, Any]) -> int:
    """每个账号每天可获得奖励的通关次数（首通计入），副本可覆盖全局默认值。"""
    value = raid.get("dailyRewardClears") or BALANCE.get("dailyRewardClears", 3) or 3
    return max(1, int(value))


def raid_penalty(raid: dict[str, Any], hero_level: int, stats: HeroStats) -> dict[str, float]:
    """副本结算与模拟用的惩罚。

    由两部分取各项较大值合成：
      - 等级压制：英雄低于 `challengeLevel` 时，命中/输出下降、承伤提升、防御衰减（`level_penalty_for_level`）。
      - 战力软惩罚：普通副本低于推荐战力时削弱治疗/资源/机制间隔并降低奖励效率（`soft_penalty`）。
    绝* 未达标时战力软惩罚为 0（进入已被硬门槛拦截）。
    """
    from app.services.balance import BALANCE as RULES, soft_penalty

    normal = raid.get("difficulty", "normal") == "normal"
    rule = RULES["raids"][raid["id"]]
    merged = dict(soft_penalty(hero_power(stats), rule["power"] if normal else 0))
    for key, value in level_penalty_for_level(hero_level, challenge_level(raid, hero_level)).items():
        merged[key] = max(float(merged.get(key, 0.0)), float(value))
    return merged


def top_rarity_required(raid: dict[str, Any]) -> int:
    """需要达到 topRarity 的件数：栏位数 × 比例，向上取整（11 × 0.5 → 6）。"""
    return math.ceil(SLOT_COUNT * float(raid.get("topRarityRatio", 0.5)))


def ancient_term_count(item: Any, minimum: int = 1) -> bool:
    return sum(1 for t in (item.terms or []) if t.get("quality") == "ancient") >= minimum


def boss_stats_for_raid(
    raid: dict[str, Any], hero_level: int, stats: HeroStats | None = None
) -> list[dict[str, Any]]:
    """按副本「目标等级」固定锚定 BOSS 属性，再乘副本倍率。

    BOSS 数值**只取决于副本配置**：不随玩家等级或战力变化（`stats` 仅保留形参、不再参与计算）。
    英雄等级低于目标等级时由 `raid_penalty` 施加等级压制，而不是给 BOSS 加血。
    每个 BOSS 都附带共享技能池（`bossSkillPool`），由客户端按共享 CD + 随机数释放。
    """
    anchor = challenge_level(raid, hero_level)
    base = monster_base_stats(anchor)
    pool = list(CONFIG.raids.get("bossSkillPool", []) or [])
    skill_interval = float(BALANCE.get("bossSkillIntervalSeconds", 6.0))
    out: list[dict[str, Any]] = []
    for boss in raid["bosses"]:
        boss_type = BOSS_TYPE_BY_ID.get(str(boss.get("type", "")))
        skills: list[dict[str, Any]] = []
        seen: set[str] = set()
        for skill in list(boss_type["skills"] if boss_type else []) + pool:
            skill_id = str(skill.get("id", ""))
            if skill_id and skill_id in seen:
                continue
            seen.add(skill_id)
            skills.append(skill)
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
                "level": anchor,
                "resistancePct": float(boss["resistancePct"]),
                "bossType": boss.get("type"),
                "skillInterval": skill_interval,
                "skills": skills,
            }
        )
    return out


def eligibility(
    raid: dict[str, Any], hero_level: int, stats: HeroStats, items: Iterable[Any]
) -> tuple[bool, str | None]:
    """进入门槛：等级 → 栏位穿满 → 装备品阶 → 太古词条 → 战力。返回 (是否可进入, 拦截原因)。

    全部副本都按 `requiredLevel` 开放（普通高难 20/40/60/80，高难度高难满级 100）；
    BOSS 数值仍按英雄当前等级锚定。
    """
    if raid.get("difficulty", "normal") == "normal":
        return True, None
    from app.services.balance import BALANCE as RULES
    raid = {**raid, **RULES["raids"][raid["id"]]}
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

    from app.services.balance import BALANCE as RULES
    rule = RULES["raids"][raid["id"]]
    if stats.power_attack < rule["attack"]:
        return False, f"主攻击属性需要 {rule['attack']}"
    if min(stats.phys_def,stats.magic_def) < rule["defense"]:
        return False, f"双防属性需要 {rule['defense']}"
    required_power = int(rule["power"])
    power = hero_power(stats)
    if power < required_power:
        return False, f"战力不足（需要 {required_power}，当前 {power}）"
    return True, None

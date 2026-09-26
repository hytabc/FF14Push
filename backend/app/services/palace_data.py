"""死者宫殿：内容生成（英雄候选 / 武器与装备 / 敌人 / 奖励 / 商店）。

全部走 `shared/data` 配置 + 既有生成器（`recruiting` / `item_factory`），保证与账号侧同源。
"""

from __future__ import annotations

import random
from typing import Any

from app.services import item_factory, recruiting
from app.services.game_config import CONFIG

ENEMY_NAMES = [
    "骸骨兵", "亡灵术士", "腐尸行者", "深渊蝙蝠", "幽魂", "食尸鬼",
    "石像鬼", "影狼", "诅咒木乃伊", "炼狱犬", "坟场守卫", "骨龙之子",
]
BOSS_NAMES = [
    "骸骨领主", "深渊牧者", "不朽暴君", "亡灵之王", "腐化巨像",
    "黑暗骑士", "亡者执政官", "坟场主宰", "深渊监视者", "死灵法皇",
]
FLOOR_TITLES = [
    "第一层", "第二层", "第三层", "第四层", "第五层",
    "第六层", "第七层", "第八层", "第九层", "第十层",
]

_REWARD_CATEGORY_WEIGHTS = {"weapon": 0.4, "armor": 0.35, "accessory": 0.25}


def cfg() -> dict[str, Any]:
    return CONFIG.palace


def floors() -> int:
    return int(cfg()["floors"])


def level_cap() -> int:
    return int(cfg()["levelCap"])


def revives() -> int:
    return int(cfg()["revives"])


def exp_to_next(level: int) -> int:
    """副本内经验曲线（与账号侧解耦）：随等级次线性增长，保证前几层快速升级。"""
    return max(1, int(50 * max(1, int(level)) ** 1.5))


def floor_row(floor: int) -> dict[str, Any]:
    rows = cfg()["monsters"]["floors"]
    index = min(len(rows), max(1, int(floor))) - 1
    return rows[index]


# ------------------------------------------------------------------ 英雄候选
def _talent_weights_with_bonus(bonus: float) -> dict[str, float]:
    """把资质权重按「越高档加成越高」重排：高档权重 ×(1 + bonus × 档次序号)。"""
    order = list(CONFIG.talents["order"])
    weights = CONFIG.talents["talentWeights"]
    raw = {t: float(weights[t]) * (1.0 + max(0.0, bonus) * i) for i, t in enumerate(order)}
    total = sum(raw.values()) or 1.0
    return {t: v / total for t, v in raw.items()}


def roll_talent(bonus: float, rng: random.Random) -> str:
    weights = _talent_weights_with_bonus(bonus)
    roll = rng.random()
    cumulative = 0.0
    picked = next(iter(weights))
    for talent, weight in weights.items():
        cumulative += weight
        if roll < cumulative:
            picked = talent
            break
    return picked


def hero_candidates(talent_bonus: float, count: int, rng: random.Random) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _ in range(max(0, count)):
        talent = roll_talent(talent_bonus, rng)
        candidate = recruiting.generate_candidate(1, rng, ancient=False, talent=talent, allow_egg=False)
        out.append(
            {
                "name": candidate["name"],
                "talent": candidate["talent"],
                "talentName": CONFIG.talents["talents"][candidate["talent"]]["name"],
                "attrBias": candidate["attrBias"],
                "attrBiasLabel": candidate.get("attrBiasLabel"),
                "strength": candidate["strength"],
                "agility": candidate["agility"],
                "intellect": candidate["intellect"],
                "totalPoints": candidate["totalPoints"],
                "recommendedJobs": candidate.get("recommendedJobs", []),
            }
        )
    return out


def hero_snapshot(candidate: dict[str, Any], level: int) -> dict[str, Any]:
    return {
        "name": candidate["name"],
        "talent": candidate["talent"],
        "attrBias": candidate["attrBias"],
        "strength": int(candidate["strength"]),
        "agility": int(candidate["agility"]),
        "intellect": int(candidate["intellect"]),
        "level": max(1, int(level)),
        "exp": 0,
    }


# ------------------------------------------------------------------ 装备
def item_level(floor: int, equip_level_bonus: int = 0) -> int:
    """副本装备等级随层数上升（1 层 10 级 → 10 层 100 级），并叠加局外成长的「武器等级」。"""
    return max(1, min(100, int(floor) * 10 + int(equip_level_bonus)))


def generate_item(
    category: str,
    level: int,
    rng: random.Random,
    *,
    luck: float = 0.0,
    quality_bonus: float = 0.0,
) -> dict[str, Any]:
    item, _ = item_factory.generate_item(
        category=category,
        level=level,
        box_tier="advanced",
        rng=rng,
        luck=luck,
        quality_bonus=quality_bonus,
    )
    return item


def random_equip(rng: random.Random, floor: int, equip_level_bonus: int, luck: float, quality_bonus: float) -> dict[str, Any]:
    categories = list(_REWARD_CATEGORY_WEIGHTS)
    weights = [_REWARD_CATEGORY_WEIGHTS[c] for c in categories]
    category = rng.choices(categories, weights=weights, k=1)[0]
    return generate_item(
        category,
        item_level(floor, equip_level_bonus),
        rng,
        luck=luck,
        quality_bonus=quality_bonus,
    )


# ------------------------------------------------------------------ 敌人
def enemy_stats(floor: int, node_type: str, rng: random.Random | None = None) -> dict[str, Any]:
    rng = rng or random.Random()
    row = floor_row(floor)
    monsters = cfg()["monsters"]
    key = "boss" if node_type == "boss" else "elite" if node_type == "elite" else "normal"
    mult = monsters.get(key) or {"hp": 1.0, "attack": 1.0, "defense": 1.0, "xp": 1.0, "gold": 1.0}
    is_boss = node_type == "boss"
    name = rng.choice(BOSS_NAMES if is_boss else ENEMY_NAMES)
    title = FLOOR_TITLES[min(len(FLOOR_TITLES), max(1, int(floor))) - 1]
    enemy: dict[str, Any] = {
        "id": f"palace_f{floor}_{node_type}",
        "regionId": 0,
        "name": f"{title}·{name}",
        "templateId": "boss" if is_boss else "elite" if node_type == "elite" else "normal",
        "kind": "boss" if is_boss else "elite" if node_type == "elite" else "normal",
        "hp": round(float(row["hp"]) * float(mult["hp"]), 1),
        "attack": round(float(row["attack"]) * float(mult["attack"]), 1),
        "defense": round(float(row["defense"]) * float(mult["defense"]), 1),
        "attackInterval": float(CONFIG.bosses["attackInterval"] if is_boss else CONFIG.monsters["monsterAttackInterval"]),
        "level": int(floor) * 5,
        "resistancePct": 0.0,
    }
    if node_type in ("elite", "boss"):
        pool = list(CONFIG.raids.get("bossSkillPool") or [])
        if pool:
            enemy["skills"] = pool
            enemy["skillInterval"] = float(CONFIG.raids["balance"]["bossSkillIntervalSeconds"])
    return enemy


def enemy_rewards(floor: int, node_type: str) -> tuple[int, int]:
    """战斗节点的副本金币与经验产出。"""
    row = floor_row(floor)
    monsters = cfg()["monsters"]
    key = "boss" if node_type == "boss" else "elite" if node_type == "elite" else "normal"
    mult = monsters.get(key) or {"xp": 1.0, "gold": 1.0}
    return int(float(row["xp"]) * float(mult["xp"])), int(float(row["gold"]) * float(mult["gold"]))


# ------------------------------------------------------------------ BUFF / 奖励
def buff_pool() -> list[dict[str, Any]]:
    return list(cfg()["buffs"])


def pick_buff(rng: random.Random) -> dict[str, Any]:
    return rng.choice(buff_pool())


def _pick_reward_kind(drop_count_pct: float, rng: random.Random) -> str:
    weights = dict(cfg()["rewardWeights"])
    # 局外成长「掉落数量」把权重推向装备。
    weights["equip"] = float(weights["equip"]) * (1.0 + max(0.0, drop_count_pct) / 100.0)
    total = sum(float(v) for v in weights.values()) or 1.0
    roll = rng.random() * total
    cumulative = 0.0
    picked = next(iter(weights))
    for kind, weight in weights.items():
        cumulative += float(weight)
        if roll < cumulative:
            picked = kind
            break
    return picked


def reward_options(
    floor: int,
    node_type: str,
    rng: random.Random,
    *,
    equip_level_bonus: int = 0,
    quality_bonus: float = 0.0,
    rarity_luck: float = 0.0,
    drop_count_pct: float = 0.0,
) -> list[dict[str, Any]]:
    """战斗奖励三选一：每项为 equip / buff / both。"""
    choices = int(cfg()["rewardChoices"])
    bonus = cfg()["bossRewardBonus"] if node_type == "boss" else cfg()["eliteRewardBonus"] if node_type == "elite" else None
    luck = rarity_luck + (float(bonus["rarityLuck"]) if bonus else 0.0)
    options: list[dict[str, Any]] = []
    for _ in range(choices):
        kind = _pick_reward_kind(drop_count_pct, rng)
        option: dict[str, Any] = {"kind": kind}
        if kind in ("equip", "both"):
            option["equip"] = random_equip(rng, floor, equip_level_bonus, luck, quality_bonus)
        if kind in ("buff", "both"):
            option["buff"] = pick_buff(rng)
        options.append(option)
    return options


def shop_offers(floor: int, rng: random.Random, discount: float = 0.0) -> list[dict[str, Any]]:
    spec = cfg()["shop"]
    count = int(spec["offersPerShop"])
    pool = list(spec["pool"])
    rng.shuffle(pool)
    price_scale = (1.0 + float(spec["pricePerFloor"]) * (int(floor) - 1)) * (1.0 - min(0.8, max(0.0, discount)))
    offers: list[dict[str, Any]] = []
    for offer in pool[:count]:
        entry = dict(offer)
        entry["price"] = max(1, int(round(float(offer["price"]) * price_scale)))
        if entry.get("buffId"):
            entry["buff"] = CONFIG.palace_buff_by_id.get(entry["buffId"])
        offers.append(entry)
    return offers

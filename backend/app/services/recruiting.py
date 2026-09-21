"""英雄酒馆：候选生成、招募费用、解雇。来源：PRD 招募 2.3 / 2.4 / 3.2 / 3.3"""

from __future__ import annotations

import random
from typing import Any

from app.services.game_config import CONFIG

TALENT_WEIGHTS: dict[str, float] = {
    "common": 0.50,
    "uncommon": 0.25,
    "rare": 0.15,
    "epic": 0.07,
    "legendary": 0.025,
    "mythic": 0.005,
}

NAME_POOL = [
    "阿尔菲诺", "阿莉塞", "雅·修特拉", "桑克瑞德", "于里昂热", "埃斯蒂尼安",
    "塔塔露", "库尔扎斯", "兰吉特", "希尔达", "莉瑟", "格格鲁",
    "梅·娜格", "娜娜莫", "劳班", "伊达", "帕帕力莫", "尤埃尔",
]

BIAS_LABELS = {"str": "力量型", "dex": "敏捷型", "int": "智力型", "balanced": "均衡型"}


def talent_weights(rng: random.Random) -> str:
    roll = rng.random()
    cumulative = 0.0
    for talent, weight in TALENT_WEIGHTS.items():
        cumulative += weight
        if roll < cumulative:
            return talent
    return "mythic"


def recruit_cost(talent: str, current_hero_level: int) -> int:
    """招募费用 = 基础费用 × 资质系数 × (1 + 当前英雄等级 / 10)。"""
    cfg = CONFIG.talents
    coef = float(cfg["talents"][talent]["recruitCoef"])
    return int(float(cfg["baseRecruitCost"]) * coef * (1.0 + current_hero_level / 10.0))


def normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """带太古属性的候选必定为神话（红色）资质。

    生成端（`generate_candidate`）已保证；这里再兜底一次，防御规则上线前落库的旧候选，
    确保展示、计费与创建英雄三处口径一致。
    """
    if candidate.get("ancientAttr") and candidate.get("talent") != "mythic":
        return {**candidate, "talent": "mythic"}
    return candidate


def with_recruit_cost(candidate: dict[str, Any], current_hero_level: int) -> dict[str, Any]:
    """候选副本：按当前英雄等级重算 recruitCost。

    候选是生成时落库的，其中的 recruitCost 会随英雄升级而过期；
    招募实际扣费又按招募时的等级计算，两者不一致会让玩家看到「价格变了」。
    所有对外返回候选的接口都应经过这里。
    """
    candidate = normalize_candidate(candidate)
    return {**candidate, "recruitCost": recruit_cost(candidate["talent"], current_hero_level)}


def recommended_jobs(attr: str) -> list[str]:
    return [j["id"] for j in CONFIG.jobs["jobs"] if j["mainAttr"] == attr]


def ancient_pity_count() -> int:
    return max(1, int(CONFIG.talents["ancientPityCount"]))


def roll_ancient(counter: int, rng: random.Random) -> tuple[bool, int, bool]:
    """判定下一个候选是否带太古属性。返回 (是否太古, 新的保底计数, 是否保底触发)。

    每 ancientPityCount 个候选至少出一个太古：计数满则必出；否则按 ancientChance 随机。
    出太古后计数归零。任何太古（保底或自然触发）都必定为神话（红色）资质，见 `generate_candidate`。
    """
    if counter + 1 >= ancient_pity_count():
        return True, 0, True
    if rng.random() < float(CONFIG.talents["ancientChance"]):
        return True, 0, False
    return False, counter + 1, False


def generate_candidates(
    current_hero_level: int,
    count: int,
    counter: int = 0,
    rng: random.Random | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """批量生成候选并推进太古保底计数。返回 (候选列表, 新计数)。"""
    rng = rng or random.Random()
    candidates: list[dict[str, Any]] = []
    for _ in range(max(0, count)):
        is_ancient, counter, _ = roll_ancient(counter, rng)
        # 带太古属性的候选必定为神话（红色）资质（保底或自然触发皆然）：
        # 总点数因此落在 220-260，太古 ×1.25 计算后总值可超出该区间。
        candidates.append(generate_candidate(current_hero_level, rng, ancient=is_ancient))
    return candidates, counter


def generate_candidate(
    current_hero_level: int,
    rng: random.Random | None = None,
    *,
    ancient: bool | None = None,
    talent: str | None = None,
) -> dict[str, Any]:
    """生成候选英雄：资质决定总点数，偏向决定三维分配。

    ancient 显式指定是否带太古（由 `roll_ancient` 的保底结果决定）；省略时按 ancientChance 随机。
    talent 显式指定资质；省略时按资质权重随机。

    任何带太古属性的英雄都**必定是神话（红色）资质**（无论是否保底触发），因此太古判定
    先于点数抽取，使其落在神话区间（计算前总点数 220-260）。
    """
    rng = rng or random.Random()
    # 无论是否指定 talent 都消耗一次资质随机，避免改变后续随机序列。
    rolled_talent = talent_weights(rng)
    # 太古判定提前：太古英雄必定为神话，点数须按神话区间抽取。
    hit = rng.random() < float(CONFIG.talents["ancientChance"]) if ancient is None else ancient
    talent_id = "mythic" if hit else (talent or rolled_talent)
    spec = CONFIG.talents["talents"][talent_id]
    total_points = rng.randint(int(spec["pointMin"]), int(spec["pointMax"]))

    bias_id = rng.choice(["str", "dex", "int", "balanced"])
    weights = CONFIG.talents["biases"][bias_id]["weights"]

    # 按权重分配并加入少量抖动，保证总和不变
    raw = {k: total_points * float(w) * rng.uniform(0.94, 1.06) for k, w in weights.items()}
    scale = total_points / sum(raw.values())
    attrs = {k: max(1, int(round(v * scale))) for k, v in raw.items()}

    # 修正取整误差
    diff = total_points - sum(attrs.values())
    order = sorted(attrs, key=lambda k: attrs[k], reverse=True)
    i = 0
    while diff != 0:
        key = order[i % len(order)]
        if diff > 0:
            attrs[key] += 1
            diff -= 1
        elif attrs[key] > 1:
            attrs[key] -= 1
            diff += 1
        i += 1

    # 太古：使随机 1 条三维变为「三条中最高值 × ancientMultiplier」，每名英雄最多 1 条
    ancient_attr = None
    if hit:
        ancient_attr = rng.choice(["str", "dex", "int"])
        attrs[ancient_attr] = max(1, int(round(max(attrs.values()) * float(CONFIG.talents["ancientMultiplier"]))))

    attr_main = bias_id if bias_id != "balanced" else max(attrs, key=lambda k: attrs[k])
    return {
        "name": rng.choice(NAME_POOL),
        "talent": talent_id,
        "attrBias": bias_id,
        "attrBiasLabel": BIAS_LABELS[bias_id],
        "strength": attrs["str"],
        "agility": attrs["dex"],
        "intellect": attrs["int"],
        "ancientAttr": ancient_attr,
        "totalPoints": total_points,
        "recruitCost": recruit_cost(talent_id, current_hero_level),
        "recommendedJobs": recommended_jobs(attr_main),
    }


def initial_hero(rng: random.Random | None = None) -> dict[str, Any]:
    """初始英雄：均衡型、普通资质、三维平均。来源：PRD 招募 2.2"""
    rng = rng or random.Random()
    cfg = CONFIG.heroes["initialHero"]
    total = int(cfg["totalPoints"])
    each = total // 3
    return {
        "name": str(cfg["name"]),
        "talent": str(cfg["talent"]),
        "attrBias": str(cfg["attrBias"]),
        "strength": each,
        "agility": each,
        "intellect": total - each * 2,
        "ancientAttr": None,
        "totalPoints": total,
        "isInitial": True,
    }

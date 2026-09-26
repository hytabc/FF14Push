"""开发用：打印每个副本的难度标定参考（数值以 shared/data 与真实模型推导）。

`requiredLevel` 是进入等级，`challengeLevel` 是 BOSS 固定锚定的**目标等级**；BOSS 属性
不再随玩家等级/战力动态变化，低于目标等级的英雄由 `regions.levelPenalty` 压制。

对每个副本打印：
- 门槛装战力 / DPS：全神话底材 + N 个太古词条/件（N = minAncientTermsPerItem，副属性随机），
  分别取「进入等级」与「目标等级」。
- 满配装战力 / DPS：全神话 + 3 个攻击类太古词条 + 全部副属性取太古上限（可达性上界）。
- 目标等级地区「一次完整刷取（小怪 + BOSS）」的金币，作为奖励基准。
- 按当前 BOSS 倍率预测的理论耗时与承伤（用于核对高难手感与 maxFightSeconds）。

线上玩家分布用 `scripts/raid-player-baseline.py` 读取（只读）。

运行：`python scripts/derive-raid-power.py`
"""

from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.combat_model import theoretical_dps  # noqa: E402
from app.services.game_config import CONFIG  # noqa: E402
from app.services.item_factory import generate_item  # noqa: E402
from app.services.raid_util import all_raids, boss_stats_for_raid, challenge_level, daily_reward_clears  # noqa: E402
from app.services.regions_util import monster_base_stats  # noqa: E402
from app.services.slots_util import possible_slots  # noqa: E402
from app.services.stats import compute_stats  # noqa: E402
from app.services.valuation import hero_power  # noqa: E402

# 奖励系数：首通 / 重刷 相对「同等级地区一次完整刷取」的倍数（经验与金币同源）。
FIRST_FACTOR = {"normal": 10.0, "hard": 30.0}
FIRST_FACTOR_OVERRIDE = {"raid_h2": 40.5}
REPEAT_FACTOR = {"normal": 1.5, "hard": 5.0}


class Hero:
    def __init__(self, level: int) -> None:
        self.id = 1
        self.level = level
        self.talent = "common"
        self.attr_bias = "balanced"
        self.strength = 33
        self.agility = 33
        self.intellect = 34
        self.name = "门槛英雄"


class GearItem:
    def __init__(self, generated: dict[str, Any], slot: str, ancient: int, max_subs: bool) -> None:
        self.base_id = generated["baseId"]
        self.category = generated["category"]
        self.slot = slot
        self.rarity = generated["rarity"]
        self.level_req = generated["levelReq"]
        self.base_attrs = generated["baseAttrs"]
        self.sub_attrs = generated["subAttrs"]
        self.equipped_slot = slot
        if max_subs:
            base = CONFIG.base_item_by_id[generated["baseId"]]
            scale = float(getattr(base, "sub_attr_scale", 1.0))
        self.terms = [
            {
                "id": f"ancient{index}",
                "name": "力量增幅",
                "type": "buff",
                "stat": "attackPct",
                "trigger": "passive",
                "value": 18.75,
                "quality": "ancient",
                "desc": "攻击力 +{v}%",
            }
            for index in range(ancient)
        ]
        for entry in self.sub_attrs:
            if not max_subs:
                break
            spec = CONFIG.attribute_by_id[entry["attr"]]
            lo, hi = spec["ranges"][self.rarity]
            extreme = max(abs(float(lo) * scale), abs(float(hi) * scale))
            entry["value"] = round(extreme * 1.25, 2)
            entry["quality"] = "ancient"


def gear(level: int, ancient: int, max_subs: bool) -> list[GearItem]:
    rng = random.Random(11)
    items = []
    for slot in (s["id"] for s in CONFIG.slots):
        usable = [b for b in CONFIG.base_items if slot in possible_slots(b) and b.level_req <= level]
        base = max(usable, key=lambda b: (b.tier_index, b.level_req))
        generated, _ = generate_item(base.category, level, rarity="mythic", base_id=base.id, rng=rng)
        items.append(GearItem(generated, slot, ancient, max_subs))
    return items


def stats_at(level: int, ancient: int, max_subs: bool = False):
    return compute_stats(Hero(level), gear(level, ancient, max_subs))


def region_for_level(level: int) -> dict[str, Any]:
    best = CONFIG.regions["regions"][0]
    for region in CONFIG.regions["regions"]:
        if int(region["levelMin"]) <= level:
            best = region
    return best


def region_clear_gold(level: int) -> tuple[dict[str, Any], int]:
    """同等级地区一次完整刷取的金币 = baseGold × (killsRequired + 15)。"""
    region = region_for_level(level)
    return region, int(region["baseGold"]) * (int(region["killsRequired"]) + 15)


def predicted_fight(raid: dict[str, Any], stats) -> tuple[float, float, float]:
    """按当前 BOSS 倍率预测：总耗时(s)、每秒承伤、可存活秒数。"""
    bosses = boss_stats_for_raid(raid, 0)
    seconds = 0.0
    incoming = 0.0
    for boss in bosses:
        dps = theoretical_dps(stats, float(boss["defense"])) * (1 - float(boss["resistancePct"]) / 100)
        seconds += float(boss["hp"]) / max(1.0, dps)
        per_hit = max(float(boss["attack"]) * 0.1, float(boss["attack"]) - min(stats.phys_def, stats.magic_def))
        incoming += per_hit / float(boss["attackInterval"])
    survival = stats.max_hp / max(1.0, incoming)
    return seconds, incoming, survival


def main() -> None:
    for raid in all_raids():
        required = int(raid["requiredLevel"])
        anchor = challenge_level(raid, required)
        ancient = int(raid.get("minAncientTermsPerItem", 0) or 0)
        difficulty = str(raid.get("difficulty", "normal"))
        bar_req = stats_at(required, ancient)
        bar_anchor = stats_at(anchor, ancient)
        full_anchor = stats_at(anchor, 3, max_subs=True)
        region, clear_gold = region_clear_gold(anchor)
        first_factor = float(FIRST_FACTOR_OVERRIDE.get(raid["id"], FIRST_FACTOR.get(difficulty, 10.0)))
        repeat_factor = float(REPEAT_FACTOR.get(difficulty, 1.5))
        fight = predicted_fight(raid, bar_anchor)
        print(
            f"{raid['id']:8s} 进入Lv{required:<4d} 目标Lv{anchor:<4d} {difficulty:6s} 太古/件={ancient} "
            f"每日奖励={daily_reward_clears(raid)}"
        )
        print(
            f"    门槛装(进入等级) 战力={hero_power(bar_req):<7d} DPS={theoretical_dps(bar_req):<9.0f}"
            f"| 门槛装(目标等级) 战力={hero_power(bar_anchor):<7d} DPS={theoretical_dps(bar_anchor):<9.0f}"
        )
        print(
            f"    满配装(目标等级) 战力={hero_power(full_anchor):<7d} DPS={theoretical_dps(full_anchor):<9.0f}"
            f"| 人工门槛={raid['requiredPower']}"
        )
        print(
            f"    目标等级地区【{region['name']}】一次刷取金币={clear_gold} "
            f"→ 建议首通≈{int(clear_gold * first_factor)} 重刷≈{int(clear_gold * repeat_factor)}"
        )
        print(
            f"    预测耗时={fight[0]:.1f}s(上限600s) 承伤={fight[1]:.0f}/s 可存活={fight[2]:.0f}s"
        )


if __name__ == "__main__":
    main()

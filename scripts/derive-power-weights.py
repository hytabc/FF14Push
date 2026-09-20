"""开发用：按真实战斗模型推导 `economy.json` 的 `power.weights`。

以「Lv80 + 门槛装」为参考，衡量每点属性对战斗力的边际贡献：

    combat_value(stats) = theoretical_dps(stats) × survival_seconds(stats)

进攻类（暴击/直击/信念）用模型解析导数（避免三属性基准以下的钳制死区）；
其余用数值微分。最后以 attack 归一化为 1.0。

只打印建议值，不写文件；确认后手工写入 `shared/data/economy.json`。
运行：`python scripts/derive-power-weights.py`
"""

from __future__ import annotations

import dataclasses
import math
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.combat_model import survival_seconds, theoretical_dps  # noqa: E402
from app.services.game_config import CONFIG  # noqa: E402
from app.services.item_factory import generate_item  # noqa: E402
from app.services.slots_util import possible_slots  # noqa: E402
from app.services.stats import HeroStats, compute_stats, three_attr_tier  # noqa: E402

REFERENCE_LEVEL = 80
REFERENCE_REGION = 23
GATE_MIX = ["epic"] * 6 + ["rare"] * 5  # 与 TestRaidPressure 的 normal 门槛一致
DELTA = 1.0

PANEL_FIELD = {
    "attack": "attack",
    "magicAttack": "magic_attack",
    "hp": "max_hp",
    "physDef": "phys_def",
    "magicDef": "magic_def",
    "sks": "attack_speed_pct",
    "sps": "haste_pct",
    "regen": "hp_regen",
    "lifesteal": "lifesteal_pct",
    "dodge": "dodge_pct",
    "acc": "hit_rate_pct",
    "tenacity": "tenacity_pct",
}
CAPS = {"sks": 50.0, "dodge": 30.0, "acc": 20.0}


class Hero:
    def __init__(self, level: int) -> None:
        self.id = 1
        self.level = level
        self.exp = 0
        self.talent = "common"
        self.attr_bias = "str"
        self.strength = 120
        self.agility = 120
        self.intellect = 120
        self.name = "参考英雄"
        self.current_region_id = REFERENCE_REGION
        self.region_kill_count = 0
        self.is_initial = True


class RefItem:
    def __init__(self, generated: dict[str, Any], slot: str) -> None:
        self.base_id = generated["baseId"]
        self.category = generated["category"]
        self.slot = slot
        self.rarity = generated["rarity"]
        self.level_req = generated["levelReq"]
        self.base_attrs = generated["baseAttrs"]
        self.sub_attrs = generated["subAttrs"]
        self.terms = generated["terms"]
        self.equipped_slot = slot


def reference_stats() -> HeroStats:
    rng = random.Random(11)
    items = []
    for index, slot in enumerate(s["id"] for s in CONFIG.slots):
        usable = [b for b in CONFIG.base_items if slot in possible_slots(b) and b.level_req <= REFERENCE_LEVEL]
        base = max(usable, key=lambda b: (b.tier_index, b.level_req))
        generated, _ = generate_item(base.category, REFERENCE_LEVEL, rarity=GATE_MIX[index], base_id=base.id, rng=rng)
        items.append(RefItem(generated, slot))
    return compute_stats(Hero(REFERENCE_LEVEL), items)


def combat_value(stats: HeroStats) -> float:
    return max(1e-9, theoretical_dps(stats, 0.0, None)) * max(1e-9, survival_seconds(stats, REFERENCE_REGION))


def numeric_elasticity(stats: HeroStats, attr: str) -> float:
    field = PANEL_FIELD[attr]
    value = getattr(stats, field) + DELTA
    if attr in CAPS:
        value = min(value, CAPS[attr])
    bumped = dataclasses.replace(stats, **{field: value})
    return (math.log(combat_value(bumped)) - math.log(combat_value(stats))) / DELTA


def analytic_offense(stats: HeroStats) -> dict[str, float]:
    """暴击/直击/信念的解析边际（忽略基准以下的钳制死区）。"""
    c = CONFIG.combat
    denom = float(three_attr_tier(stats.level)["denominator"])
    d_crit = float(c["critRatePerDenomPct"]) / denom
    d_dh = float(c["directHitRateMaxPct"]) / denom
    d_det = float(c["determinationPerDenomPct"]) / denom

    cr, cd = stats.crit_rate_pct, stats.crit_damage_pct
    dh, det = stats.dh_rate_pct, stats.det_bonus_pct
    mult_crit = 1 + (cr / 100) * (cd / 100 - 1)
    mult_dh = 1 + (dh / 100) * (float(c["directHitMultiplier"]) - 1)
    mult_det = 1 + det / 100
    return {
        "crit": (d_crit / 100) * ((cd / 100 - 1) + cr / 100) / mult_crit,
        "dh": (d_dh / 100) * (float(c["directHitMultiplier"]) - 1) / mult_dh,
        "det": (d_det / 100) / mult_det,
    }


def main() -> None:
    stats = reference_stats()
    print(f"参考面板: attack={stats.attack:.0f} crit_value={stats.crit_value:.0f} "
          f"crit_rate={stats.crit_rate_pct:.1f}% cd={stats.crit_damage_pct:.1f}% "
          f"dh_rate={stats.dh_rate_pct:.1f}% det={stats.det_bonus_pct:.1f}% hp={stats.max_hp:.0f}")

    anchor = 1.0 / stats.power_attack
    offense = analytic_offense(stats)
    print("\n建议权重（attack = 1.0）:")
    print(f"  {'attack':12s} 1.000")
    for attr in ("crit", "dh", "det"):
        print(f"  {attr:12s} {offense[attr] / anchor:.3f}")
    for attr in ("hp", "physDef", "magicDef", "sks", "sps", "regen", "lifesteal", "dodge", "acc", "tenacity"):
        print(f"  {attr:12s} {numeric_elasticity(stats, attr) / anchor:.3f}")


if __name__ == "__main__":
    main()

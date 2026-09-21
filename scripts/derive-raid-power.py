"""开发用：打印每个副本的「门槛装」与「满配装」战力参考。

`requiredPower` 现在是**人工设定的高线**（按当前玩家数据：Lv100 需 12w），不再等于
「门槛装战力 × 0.95」。本脚本只做参考打印：

- 门槛装战力：全神话底材 + N 个太古词条/件（N = minAncientTermsPerItem，副属性随机）。
- 满配装战力：全神话 + 3 个攻击类太古词条 + **全部副属性取太古上限**（门槛可达性的上界）。

运行：`python scripts/derive-raid-power.py`
"""

from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.game_config import CONFIG  # noqa: E402
from app.services.item_factory import generate_item  # noqa: E402
from app.services.slots_util import possible_slots  # noqa: E402
from app.services.stats import compute_stats  # noqa: E402
from app.services.valuation import hero_power  # noqa: E402


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


def main() -> None:
    for raid in sorted(CONFIG.raids["raids"], key=lambda r: int(r["order"])):
        level = int(raid["requiredLevel"])
        ancient = int(raid.get("minAncientTermsPerItem", 0) or 0)
        gate = hero_power(compute_stats(Hero(level), gear(level, ancient, False)))
        full = hero_power(compute_stats(Hero(level), gear(level, 3, True)))
        print(
            f"{raid['id']:8s} Lv{level:<3d} {str(raid.get('difficulty')):6s} 太古/件={ancient} "
            f"门槛装战力={gate:<8d} 满配装战力={full:<8d} 人工门槛={raid['requiredPower']}"
        )


if __name__ == "__main__":
    main()

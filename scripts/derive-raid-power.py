"""开发用：为每个副本推算 `requiredPower` 门槛。

用与 `backend/tests/test_engine.py::TestRaidPressure._gate_items` 相同的方式构造
「刚好够门槛」的装备（按其 requiredLevel + 品阶组合），计算 hero_power，
建议门槛 = 该值 × 0.95（略低于门槛装，保证门槛装可通过）。

只打印建议值，不写文件。运行：`python scripts/derive-raid-power.py`
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

GATE_MIX = {
    "normal": ["epic"] * 6 + ["rare"] * 5,
    "hard": ["mythic"] * 6 + ["legendary"] * 5,
}


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


class GateItem:
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


def gate_items(level: int, difficulty: str) -> list[GateItem]:
    mix = GATE_MIX[difficulty]
    rng = random.Random(11)
    items = []
    for index, slot in enumerate(s["id"] for s in CONFIG.slots):
        usable = [b for b in CONFIG.base_items if slot in possible_slots(b) and b.level_req <= level]
        base = max(usable, key=lambda b: (b.tier_index, b.level_req))
        generated, _ = generate_item(base.category, level, rarity=mix[index], base_id=base.id, rng=rng)
        items.append(GateItem(generated, slot))
    return items


def main() -> None:
    for raid in sorted(CONFIG.raids["raids"], key=lambda r: int(r["order"])):
        level = int(raid["requiredLevel"])
        difficulty = str(raid.get("difficulty", "normal"))
        stats = compute_stats(Hero(level), gate_items(level, difficulty))
        power = hero_power(stats)
        suggested = int(power * 0.95)
        print(f"{raid['id']:8s} Lv{level:<3d} {difficulty:6s} 门槛装战力={power:<8d} "
              f"当前门槛={raid['requiredPower']:<8d} 建议={suggested}")


if __name__ == "__main__":
    main()

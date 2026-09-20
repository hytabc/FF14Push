"""测试替身：模拟 ORM 的 Hero / Item，避免依赖数据库。"""

from __future__ import annotations

from typing import Any


class FakeHero:
    def __init__(
        self,
        level: int = 1,
        talent: str = "common",
        attr_bias: str = "balanced",
        strength: int = 33,
        agility: int = 33,
        intellect: int = 34,
    ) -> None:
        self.id = 1
        self.level = level
        self.exp = 0
        self.talent = talent
        self.attr_bias = attr_bias
        self.strength = strength
        self.agility = agility
        self.intellect = intellect
        self.name = "测试英雄"
        self.current_region_id = 1
        self.region_kill_count = 0
        self.is_initial = True


class FakeItem:
    def __init__(
        self,
        category: str = "accessory",
        rarity: str = "common",
        base_id: str = "c_ring_0",
        slot: str = "ring",
        level_req: int = 1,
        base_attrs: list[dict[str, Any]] | None = None,
        sub_attrs: list[dict[str, Any]] | None = None,
        terms: list[dict[str, Any]] | None = None,
        equipped_slot: str | None = "ring1",
        refine_count: int = 0,
        enchant_count: int = 0,
    ) -> None:
        self.id = id(self)
        self.base_id = base_id
        self.name = "测试装备"
        self.category = category
        self.slot = slot
        self.rarity = rarity
        self.level_req = level_req
        self.base_attrs = base_attrs or []
        self.sub_attrs = sub_attrs or []
        self.terms = terms or []
        self.equipped_slot = equipped_slot
        self.refine_count = refine_count
        self.enchant_count = enchant_count
        self.source = "test"

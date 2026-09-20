"""栏位工具函数。"""

from __future__ import annotations

from app.services.game_config import CONFIG, BaseItem

SLOT_BY_ID = {s["id"]: s for s in CONFIG.slots}

# 底材 slot → 可装备的实际栏位
_MULTI_SLOT = {"ring": ["ring1", "ring2"]}


def possible_slots(base: BaseItem) -> list[str]:
    if base.slot in _MULTI_SLOT:
        return list(_MULTI_SLOT[base.slot])
    return [base.slot]


def accepts(slot_id: str, base: BaseItem) -> bool:
    slot = SLOT_BY_ID.get(slot_id)
    if slot is None:
        return False
    return base.slot in slot["accepts"]


def all_slot_ids() -> list[str]:
    return [s["id"] for s in sorted(CONFIG.slots, key=lambda s: s["order"])]


def slot_category(slot_id: str) -> str | None:
    slot = SLOT_BY_ID.get(slot_id)
    return slot["category"] if slot else None

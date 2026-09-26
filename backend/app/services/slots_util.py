"""栏位工具函数。"""

from __future__ import annotations

from app.services.game_config import CONFIG, BaseItem

SLOT_BY_ID = {s["id"]: s for s in CONFIG.slots}

# 底材 slot → 可装备的实际栏位
_MULTI_SLOT = {"ring": ["ring1", "ring2"]}
# 实际栏位 → 底材 slot（双戒指合并为「戒指」一种）
_BASE_SLOT_BY_ID = {"ring1": "ring", "ring2": "ring"}


def selectable_base_slots() -> list[str]:
    """可自选的装备种类（按栏位顺序去重，戒指合并为一种）。"""
    out: list[str] = []
    for slot in sorted(CONFIG.slots, key=lambda s: s["order"]):
        base_slot = _BASE_SLOT_BY_ID.get(slot["id"], slot["id"])
        if base_slot not in out:
            out.append(base_slot)
    return out


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


def role_of_base(base: BaseItem) -> str | None:
    """底材对应的战斗职能：武器按自身职业精确取，防具/饰品按职能词缀。

    基础型（无词缀）与世界BOSS 专属装备（强攻 / 守护）没有职能，返回 None（不限制穿戴）。
    """
    if base.job_id:
        job = CONFIG.job_by_id.get(base.job_id)
        return job["role"] if job else None
    return base.role


def role_name(role: str | None) -> str:
    """职能 id → 中文（坦克 / 治疗 / 近战DPS …）。"""
    info = CONFIG.jobs["roles"].get(role) if role else None
    return str(info["name"]) if info else (role or "")

"""死者宫殿：副本内面板计算。

与账号**完全隔离**：不读账号装备 / 英雄 / 秘药 / 魔晶石，只吃 run 快照 + 局外成长 + 副本 BUFF。
复用 `services.stats.compute_stats`（构造 transient hero / items），再以 `dataclasses.replace`
叠加成长与 BUFF —— 因此前后端共用同一份 `HeroStats`，客户端 `BattleSimulator` 与服务端理论模型
必然同源。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable

from app.services.game_config import CONFIG
from app.services.stats import HeroStats, compute_stats

CORE_KEYS = ("str", "dex", "int")


class RunHero:
    """`compute_stats` 需要的最小英雄接口（只读 run 快照，不落账号库）。"""

    __slots__ = (
        "id", "level", "exp", "talent", "attr_bias",
        "strength", "agility", "intellect", "egg_id",
    )

    def __init__(self, data: dict[str, Any], attr_scale: dict[str, float] | None = None) -> None:
        scale = attr_scale or {}
        self.id = None
        self.level = int(data.get("level", 1))
        self.exp = int(data.get("exp", 0))
        self.talent = str(data.get("talent", "common"))
        self.attr_bias = str(data.get("attrBias", "balanced"))
        self.strength = float(data.get("strength", 1)) * (1.0 + scale.get("str", 0.0))
        self.agility = float(data.get("agility", 1)) * (1.0 + scale.get("dex", 0.0))
        self.intellect = float(data.get("intellect", 1)) * (1.0 + scale.get("int", 0.0))
        self.egg_id = None  # 副本内不使用彩蛋被动，保证与账号侧隔离


class RunItem:
    """`compute_stats` 需要的最小装备接口（存 run 快照，不落 items 表）。"""

    __slots__ = (
        "base_id", "name", "category", "slot", "rarity", "level_req", "high_quality",
        "base_attrs", "sub_attrs", "terms", "equipped_slot", "equipped_hero_id",
    )

    def __init__(self, data: dict[str, Any], equipped_slot: str | None = None) -> None:
        self.base_id = data["baseId"]
        self.name = data["name"]
        self.category = data["category"]
        self.slot = data["slot"]
        self.rarity = data["rarity"]
        self.level_req = int(data["levelReq"])
        self.high_quality = bool(data.get("highQuality", False))
        self.base_attrs = data.get("baseAttrs") or []
        self.sub_attrs = data.get("subAttrs") or []
        self.terms = data.get("terms") or []
        self.equipped_slot = equipped_slot
        self.equipped_hero_id = None


def growth_mods(unlocked: Iterable[str] | None) -> tuple[dict[str, float], dict[str, float]]:
    """把已解锁的成长节点归并为 (乘算系数, 加值) 两个字典。

    `mode == "mul"` 的节点值语义为「每级 +X 倍率」（如 0.03 → +3%），`mode == "add"` 直接累加。
    """
    mul: dict[str, float] = {}
    add: dict[str, float] = {}
    for node_id in unlocked or ():
        node = CONFIG.palace_growth_by_id.get(node_id)
        if not node:
            continue
        effect = node.get("effect") or {}
        stat = effect.get("stat")
        if not stat:
            continue
        value = float(effect.get("value", 0.0))
        target = mul if effect.get("mode") == "mul" else add
        target[stat] = target.get(stat, 0.0) + value
    return mul, add


def growth_add(unlocked: Iterable[str] | None, stat: str) -> float:
    return growth_mods(unlocked)[1].get(stat, 0.0)


def growth_mul(unlocked: Iterable[str] | None, stat: str) -> float:
    return growth_mods(unlocked)[0].get(stat, 0.0)


def buff_mods(buffs: Iterable[dict[str, Any]] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for buff in buffs or ():
        stat = buff.get("stat")
        if stat:
            out[stat] = out.get(stat, 0.0) + float(buff.get("value", 0.0))
    return out


def equip_run_items(
    items: list[dict[str, Any]] | None, equipped: dict[str, int] | None
) -> list[RunItem]:
    slot_of = {int(idx): str(slot) for slot, idx in (equipped or {}).items()}
    return [RunItem(data, slot_of.get(i)) for i, data in enumerate(items or [])]


def _apply(
    stats: HeroStats, mul: dict[str, float], add: dict[str, float], buff: dict[str, float]
) -> HeroStats:
    def pct(key: str) -> float:
        return add.get(key, 0.0) + buff.get(key, 0.0)

    atk = (1.0 + mul.get("heroAttackPct", 0.0)) * (1.0 + buff.get("attackPct", 0.0) / 100.0)
    defense = (1.0 + mul.get("heroDefensePct", 0.0)) * (1.0 + buff.get("defensePct", 0.0) / 100.0)
    hp = (1.0 + mul.get("heroHpPct", 0.0)) * (1.0 + buff.get("hpPct", 0.0) / 100.0)
    mp_regen = stats.mp_regen * (1.0 + buff.get("mpRegenPct", 0.0) / 100.0)
    return replace(
        stats,
        max_hp=max(1.0, stats.max_hp * hp),
        attack=stats.attack * atk,
        magic_attack=stats.magic_attack * atk,
        phys_def=stats.phys_def * defense,
        magic_def=stats.magic_def * defense,
        mp_regen=mp_regen,
        crit_rate_pct=stats.crit_rate_pct + pct("critRatePct"),
        dh_rate_pct=stats.dh_rate_pct + pct("dhRatePct"),
        attack_speed_pct=stats.attack_speed_pct + pct("attackSpeedPct"),
        lifesteal_pct=stats.lifesteal_pct + pct("lifestealPct"),
        tenacity_pct=stats.tenacity_pct + pct("tenacityPct"),
        haste_pct=stats.haste_pct + pct("hastePct"),
        dodge_pct=min(30.0, stats.dodge_pct + pct("dodgePct")),
        det_bonus_pct=stats.det_bonus_pct + pct("detBonusPct"),
    )


def compute_run_stats(
    hero: dict[str, Any],
    items: list[dict[str, Any]] | None,
    equipped: dict[str, int] | None,
    unlocked: Iterable[str] | None,
    buffs: Iterable[dict[str, Any]] | None,
) -> HeroStats:
    """副本内当前面板：run 英雄（三维按成长放大）→ `compute_stats` → 叠加成长与 BUFF。"""
    mul, add = growth_mods(unlocked)
    attr_scale = {key: mul.get(f"hero{key.capitalize()}Pct", 0.0) for key in CORE_KEYS}
    transient = RunHero(hero, attr_scale)
    base = compute_stats(transient, equip_run_items(items, equipped))
    return _apply(base, mul, add, buff_mods(buffs))

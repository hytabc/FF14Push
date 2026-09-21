"""英雄面板属性计算。

对应前端 `src/game/core/attributes.ts`，两端必须保持一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.services.game_config import CONFIG

CORE_ATTRS = ("str", "dex", "int")


@dataclass
class EquipmentAggregate:
    """装备汇总。"""

    base_attrs: dict[str, float] = field(default_factory=dict)
    core_attrs: dict[str, float] = field(default_factory=dict)
    sub_attrs: dict[str, float] = field(default_factory=dict)
    term_mods: dict[str, float] = field(default_factory=dict)
    job_id: str | None = None
    weapon_type: str | None = None


@dataclass
class HeroStats:
    level: int
    job_id: str
    main_attr: str
    max_hp: float
    max_mp: float
    hp_regen: float
    mp_regen: float
    attack: float
    magic_attack: float
    phys_def: float
    magic_def: float
    dodge_pct: float
    attack_speed_pct: float
    hit_rate_pct: float
    haste_pct: float
    lifesteal_pct: float
    tenacity_pct: float
    crit_value: float
    dh_value: float
    det_value: float
    crit_rate_pct: float
    crit_damage_pct: float
    dh_rate_pct: float
    det_bonus_pct: float
    term_mods: dict[str, float] = field(default_factory=dict)
    # 彩蛋英雄 id（见 shared/data/egg-heroes.json）；None 表示普通英雄
    egg_id: str | None = None

    @property
    def is_magical(self) -> bool:
        job = CONFIG.job_by_id.get(self.job_id)
        return bool(job and job["mainAttr"] == "int")

    @property
    def power_attack(self) -> float:
        return self.magic_attack if self.is_magical else self.attack

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "jobId": self.job_id,
            "mainAttr": self.main_attr,
            "maxHp": round(self.max_hp, 2),
            "maxMp": round(self.max_mp, 2),
            "hpRegen": round(self.hp_regen, 2),
            "mpRegen": round(self.mp_regen, 2),
            "attack": round(self.attack, 2),
            "magicAttack": round(self.magic_attack, 2),
            "physDef": round(self.phys_def, 2),
            "magicDef": round(self.magic_def, 2),
            "dodgePct": round(self.dodge_pct, 2),
            "attackSpeedPct": round(self.attack_speed_pct, 2),
            "hitRatePct": round(self.hit_rate_pct, 2),
            "hastePct": round(self.haste_pct, 2),
            "lifestealPct": round(self.lifesteal_pct, 2),
            "tenacityPct": round(self.tenacity_pct, 2),
            "critValue": round(self.crit_value, 2),
            "dhValue": round(self.dh_value, 2),
            "detValue": round(self.det_value, 2),
            "critRatePct": round(self.crit_rate_pct, 2),
            "critDamagePct": round(self.crit_damage_pct, 2),
            "dhRatePct": round(self.dh_rate_pct, 2),
            "detBonusPct": round(self.det_bonus_pct, 2),
            "termMods": {k: round(v, 3) for k, v in self.term_mods.items()},
        }


def aggregate_equipment(items: Iterable[Any]) -> EquipmentAggregate:
    """汇总已穿戴装备的基础属性、副属性与词条。"""
    agg = EquipmentAggregate()
    for item in items:
        if getattr(item, "equipped_slot", None) is None:
            continue
        for entry in item.base_attrs or []:
            attr = entry["attr"]
            agg.base_attrs[attr] = agg.base_attrs.get(attr, 0.0) + float(entry["value"])
        for entry in item.sub_attrs or []:
            attr = entry["attr"]
            target = agg.core_attrs if attr in ("str", "dex", "int", "vit") else agg.sub_attrs
            target[attr] = target.get(attr, 0.0) + float(entry["value"])
        for term in item.terms or []:
            stat = term.get("stat")
            if stat:
                agg.term_mods[stat] = agg.term_mods.get(stat, 0.0) + float(term["value"])
        if item.slot == "mainHand":
            base = CONFIG.base_item_by_id.get(item.base_id)
            if base and base.weapon_type:
                agg.weapon_type = base.weapon_type
                agg.job_id = base.job_id
    return agg


def _bias_rate(bias: str, attr: str) -> float:
    cfg = CONFIG.heroes["attrGainRate"]
    if attr not in CORE_ATTRS:
        return 1.0
    if bias == "balanced":
        return float(cfg["balancedAll"])
    return float(cfg["main"] if attr == bias else cfg["off"])


def _job_main_attr_for_attack(job_id: str, bias: str) -> str:
    job = CONFIG.job_by_id.get(job_id)
    if job:
        return job["mainAttr"]
    if bias in CORE_ATTRS:
        return bias
    return "str"


def _resolve_coef(coef: dict[str, float], attr_source: str | None) -> dict[str, float]:
    if attr_source is None:
        return dict(coef)
    return {k: v for k, v in coef.items() if k == attr_source}


def compute_stats(hero: Any, items: Iterable[Any]) -> HeroStats:
    """计算英雄最终面板属性。"""
    agg = aggregate_equipment(items)
    level = int(hero.level)
    gc = float(CONFIG.talents["talents"][hero.talent]["growthCoef"])
    bias = hero.attr_bias
    job_id = agg.job_id or "adventurer"
    main_attr = _job_main_attr_for_attack(job_id, bias)

    job = CONFIG.job_by_id.get(agg.job_id) if agg.job_id else None
    job_match = bool(job and job["mainAttr"] == bias and bias != "balanced")

    hero_core = {
        "str": float(hero.strength),
        "dex": float(hero.agility),
        "int": float(hero.intellect),
        "vit": 0.0,
    }

    equip_core: dict[str, float] = {}
    for attr, value in agg.core_attrs.items():
        rate = _bias_rate(bias, attr)
        if job_match and attr == main_attr:
            rate *= 1.0 + float(CONFIG.heroes["jobMatchBonus"]["equipMainAttrPct"])
        equip_core[attr] = value * rate

    total_core = {a: hero_core.get(a, 0.0) + equip_core.get(a, 0.0) for a in ("str", "dex", "int", "vit")}

    attr_cfg: dict[str, Any] = CONFIG.heroes["attributes"]
    level_cfg: dict[str, Any] = CONFIG.heroes["levelUpGain"]
    panel: dict[str, float] = {}

    for name, spec in attr_cfg.items():
        by_job = bool(spec.get("byJobMainAttr"))
        coef = _resolve_coef(spec["coef"], main_attr if by_job else None)
        value = float(spec.get("base", 0)) + sum(c * total_core.get(a, 0.0) for a, c in coef.items())

        gain_cfg = level_cfg.get(name)
        if gain_cfg and level > 1:
            gain_coef = _resolve_coef(gain_cfg.get("coef", {}), main_attr if gain_cfg.get("byJobMainAttr") else None)
            base_ref = float(spec.get("base", 0)) + sum(c * hero_core.get(a, 0.0) for a, c in coef.items())
            per_level = base_ref * float(gain_cfg.get("basePct", 0)) + sum(
                c * hero_core.get(a, 0.0) for a, c in gain_coef.items()
            )
            value += per_level * (level - 1) * gc

        cap = spec.get("cap")
        if cap is not None:
            value = min(value, float(cap))
        panel[name] = value

    # 装备直接提供的基础属性
    panel["maxHp"] += agg.base_attrs.get("hp", 0.0)
    panel["attack"] += agg.base_attrs.get("attack", 0.0)
    panel["magicAttack"] += agg.base_attrs.get("magicAttack", 0.0)
    panel["physDef"] += agg.base_attrs.get("physDef", 0.0)
    panel["magicDef"] += agg.base_attrs.get("magicDef", 0.0)

    sub = agg.sub_attrs
    panel["hpRegen"] += sub.get("regen", 0.0)
    dodge_pct = min(panel["dodgePct"] + sub.get("dodge", 0.0), 30.0)
    attack_speed_pct = min(panel["attackSpeedPct"] + sub.get("sks", 0.0), 50.0)
    hit_rate_pct = min(panel["hitRatePct"] + sub.get("acc", 0.0), 20.0)
    haste_pct = sub.get("sps", 0.0)
    lifesteal_pct = sub.get("lifesteal", 0.0)
    tenacity_pct = sub.get("tenacity", 0.0)

    mods = agg.term_mods
    max_hp = panel["maxHp"] * (1.0 + mods.get("maxHpPct", 0.0) / 100.0)
    atk_mult = 1.0 + mods.get("attackPct", 0.0) / 100.0
    attack = panel["attack"] * atk_mult
    magic_attack = panel["magicAttack"] * atk_mult
    attack_speed_pct += mods.get("attackSpeedPct", 0.0)
    dodge_pct = max(0.0, dodge_pct + mods.get("dodgePct", 0.0))
    lifesteal_pct += mods.get("lifestealPct", 0.0)

    # 三属性：装备值 → 词条/主属性联动 → 换算
    crit_value = sub.get("crit", 0.0) * (1 + mods.get("critStatPct", 0.0) / 100.0)
    dh_value = sub.get("dh", 0.0) * (1 + mods.get("dhStatPct", 0.0) / 100.0)
    det_value = sub.get("det", 0.0) * (1 + mods.get("detStatPct", 0.0) / 100.0)

    link = CONFIG.combat["primaryLink"]
    crit_value *= 1.0 + link.get(bias, {}).get("crit", 0.0)
    dh_value *= 1.0 + link.get(bias, {}).get("dh", 0.0)
    det_value *= 1.0 + link.get(bias, {}).get("det", 0.0)

    crit_rate, crit_dmg, dh_rate, det_bonus = convert_three_attrs(level, crit_value, dh_value, det_value)
    crit_rate += mods.get("critRatePct", 0.0)
    crit_dmg += mods.get("critDamagePct", 0.0)
    if mods.get("dhConvertPct"):
        dh_rate += crit_rate * mods["dhConvertPct"] / 100.0

    return HeroStats(
        level=level,
        job_id=job_id,
        main_attr=main_attr,
        max_hp=max_hp,
        max_mp=panel["maxMp"],
        hp_regen=panel["hpRegen"],
        mp_regen=panel["mpRegen"],
        attack=attack,
        magic_attack=magic_attack,
        phys_def=panel["physDef"],
        magic_def=panel["magicDef"],
        dodge_pct=dodge_pct,
        attack_speed_pct=attack_speed_pct,
        hit_rate_pct=hit_rate_pct,
        haste_pct=haste_pct,
        lifesteal_pct=lifesteal_pct,
        tenacity_pct=tenacity_pct,
        crit_value=crit_value,
        dh_value=dh_value,
        det_value=det_value,
        crit_rate_pct=crit_rate,
        crit_damage_pct=crit_dmg,
        dh_rate_pct=dh_rate,
        det_bonus_pct=det_bonus,
        term_mods=dict(mods),
        egg_id=getattr(hero, "egg_id", None),
    )


def three_attr_tier(level: int) -> dict[str, Any]:
    for tier in CONFIG.combat["levelTiers"]:
        if tier["levelMin"] <= level <= tier["levelMax"]:
            return tier
    return CONFIG.combat["levelTiers"][-1]


def convert_three_attrs(
    level: int, crit_value: float, dh_value: float, det_value: float
) -> tuple[float, float, float, float]:
    """暴击/直击/信念值 → 暴击率、暴击倍率、直击率、信念增伤。来源：PRD 三属性 3.1"""
    c = CONFIG.combat
    tier = three_attr_tier(level)
    base = float(tier["base"])
    denom = max(1.0, float(tier["denominator"]))

    det_base = base + float(c.get("detBaseAdjust", 0))
    crit_rate = float(c["critBaseRatePct"]) + (crit_value - base) / denom * float(c["critRatePerDenomPct"])
    crit_dmg = float(c["critBaseMultiplierPct"]) + (crit_value - base) / denom * float(c["critDamagePerDenomPct"])
    dh_rate = (dh_value - base) / denom * float(c["directHitRateMaxPct"])
    det_bonus = (det_value - det_base) / denom * float(c["determinationPerDenomPct"])

    return max(0.0, crit_rate), max(1.0, crit_dmg), max(0.0, dh_rate), max(0.0, det_bonus)


def skill_damage_multiplier(stats: HeroStats, job_id: str) -> float:
    """技能伤害加成：词条 + 职业匹配。"""
    mult = 1.0 + stats.term_mods.get("skillDamagePct", 0.0) / 100.0
    job = CONFIG.job_by_id.get(job_id)
    if job and job["mainAttr"] == stats.main_attr and job_id != "adventurer":
        mult *= 1.0 + float(CONFIG.heroes["jobMatchBonus"]["skillDamagePct"])
    return mult


def skill_cooldown(stats: HeroStats, base_cd: float) -> float:
    """技能实际 CD = 基础 CD × (1 - 冷却缩减 - 技能急速)，最低 0.5 秒。"""
    reduce = min(0.7, stats.term_mods.get("cdReducePct", 0.0) / 100.0 + stats.haste_pct / 100.0)
    return max(0.5, base_cd * (1.0 - reduce))

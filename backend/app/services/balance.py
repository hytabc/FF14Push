"""Versioned combat balance. Pure audit, penalties and AND gates."""
from __future__ import annotations
import copy
import json
import logging
import math
from app.services.balance_defaults import DEFAULTS
from app.services.game_config import REPO_ROOT, CONFIG


def load_balance(path=None):
    try:
        data = json.loads((path or REPO_ROOT / 'shared/data/balance.json').read_text())
        def validate(value, default):
            if isinstance(default, dict):
                if not isinstance(value, dict) or value.keys() != default.keys():
                    raise ValueError('balance keys mismatch')
                for k in default: validate(value[k], default[k])
            elif default is None:
                if value is not None: raise ValueError('expected null')
            elif isinstance(default, bool):
                if type(value) is not bool: raise ValueError('expected boolean')
            elif isinstance(default, (int, float)):
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError('invalid numeric balance value')
            elif not isinstance(value, str): raise ValueError('expected string')
        validate(data, DEFAULTS)
        if not (data['migration'] in ('recalculate', 'new_unlocks_only')): raise ValueError("unsafe balance rule")
        if not (all(s['cap'] > 0 and s['group'] in ('offense','defense','sustain') for s in data['stats'].values())): raise ValueError("unsafe balance rule")
        if not (all(0 <= v < 1 for k,v in data['normal'].items() if k != 'hitFloor')): raise ValueError("unsafe balance rule")
        if not (data['normal']['hit'] <= .1 and .8 <= data['normal']['hitFloor'] <= 1): raise ValueError("unsafe balance rule")
        if not (0 < data['telemetry']['targetLow'] < data['telemetry']['targetHigh'] < 1): raise ValueError("unsafe balance rule")
        if not (data['telemetry']['days'] > 0 and data['telemetry']['minimumPlayers'] > 0): raise ValueError("unsafe balance rule")
        if not (data['telemetry']['consecutiveWindows'] >= 2): raise ValueError("unsafe balance rule")
        if not (data['trial']['rounds'] >= 1 and data['trial']['windowSeconds'] > data['trial']['minResponseSeconds']): raise ValueError("unsafe balance rule")
        for rid, rule in data['regions'].items():
            if int(rid) > 1:
                if not (rule['power'] > 0 and rule['attack'] + rule['defense'] > 0): raise ValueError("unsafe balance rule")
                if not (rule['prerequisite'] == int(rid)-1 and rule['trial']): raise ValueError("unsafe balance rule")
        if not (all(r['power'] > 0 and r['attack'] > 0 and r['defense'] > 0 and r['maxFightSeconds'] > 0 and r['minSurvivalSeconds'] > 0 for r in data['raids'].values())): raise ValueError("unsafe balance rule")
        return data
    except (OSError, ValueError, TypeError, KeyError, AssertionError):
        logging.getLogger(__name__).exception('Balance configuration invalid; using safe defaults v%s', DEFAULTS['version'])
        return copy.deepcopy(DEFAULTS)

BALANCE = load_balance()


def power_audit(stats, marks=()):
    raw = dict(hp=stats.max_hp, attack=stats.attack if not stats.is_magical else 0,
               magicAttack=stats.magic_attack if stats.is_magical else 0,
               physDef=stats.phys_def, magicDef=stats.magic_def, crit=stats.crit_value,
               dh=stats.dh_value, det=stats.det_value, sks=stats.attack_speed_pct,
               sps=stats.haste_pct, regen=stats.hp_regen, lifesteal=stats.lifesteal_pct,
               dodge=stats.dodge_pct, acc=stats.hit_rate_pct, tenacity=stats.tenacity_pct,
               mpRegen=stats.mp_regen, damageReduce=max(0,-stats.term_mods.get('damageTakenPct',0)),
               penetration=0,  # 当前战斗引擎尚无穿透属性，不虚增战力
               skillDamage=stats.term_mods.get('skillDamagePct',0),
               cooldown=stats.term_mods.get('cdReducePct',0))
    groups = dict(offense=0., defense=0., sustain=0.)
    contributions = {}
    for key, rule in BALANCE['stats'].items():
        value = max(0., float(raw[key]))
        effective = -rule['cap'] * math.expm1(-value / rule['cap'])
        contribution = effective * rule['weight']
        groups[rule['group']] += contribution
        contributions[key] = dict(raw=value, effective=effective, contribution=contribution, **rule)
    return dict(version=BALANCE['version'], total=int(sum(groups.values())), groups=groups,
                contributions=contributions, mechanismMarks=sorted(marks))


def soft_penalty(power, recommended):
    d = min(1., max(0., (recommended-power)/recommended)) if recommended > 0 else 0.
    c = BALANCE['normal']
    return dict(deficit=d, hitFloor=c["hitFloor"], hitRatePenaltyPct=100*c['hit']*d, damageDealtPenaltyPct=100*c['damage']*d,
                damageTakenBonusPct=100*c['taken']*d, defenseIgnorePct=0.,
                healingMultiplier=1-c['healing']*d, resourceMultiplier=1-c['resource']*d,
                cooldownMultiplier=1+c['cooldown']*d, windowMultiplier=1-c['window']*d,
                rewardMultiplier=1-c['reward']*d)


def equipment_quality(items):
    equipped = [i for i in items if getattr(i,'equipped_slot',None)]
    return sum(CONFIG.rarity_order.index(i.rarity) for i in equipped) / len(CONFIG.slots)


def region_gate(region_id, stats, items, cleared, marks, previously_unlocked=False):
    rule = BALANCE['regions'][str(region_id)]
    if BALANCE['migration'] == 'new_unlocks_only' and previously_unlocked:
        return []
    actual = dict(power=power_audit(stats)['total'], quality=equipment_quality(items),
                  attack=stats.power_attack, defense=min(stats.phys_def,stats.magic_def))
    labels = dict(power='综合战力',quality='装备质量',attack='主攻击属性',defense='双防属性')
    missing = [f'{labels[k]}需要 {rule[k]:g}（当前 {actual[k]:.1f}）' for k in actual if actual[k] < rule[k]]
    if rule['prerequisite'] and rule['prerequisite'] not in cleared: missing.append('需通关前一地区 BOSS')
    if rule['trial'] and f'region:{region_id}' not in marks: missing.append('需通过本地区机制试炼')
    return missing

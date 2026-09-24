"""Server-side clear checks and immutable attempt telemetry."""
from datetime import datetime, timedelta, timezone
from app.services.balance import BALANCE, equipment_quality
from app.services.combat_model import theoretical_dps
from app.services.raid_util import boss_stats_for_raid, eligibility, raid_penalty


def snapshot(raid, level, stats, items):
    # minimumFightMs = 理论时长 × durationTolerance：理论时长只是「期望值」，实战存在
    # 暴击 / 直击 / 技能 / 词条触发的方差，强练度玩家会显著快于期望值（客户端一次出手
    # 最快约 0.75s）。容差必须留足，否则合法快速通关会被 clear_failures 判为
    # invalid_duration（「战斗时长校验」）而拿不到通关。
    rule=BALANCE['raids'][raid['id']]
    normal=raid.get('difficulty','normal')=='normal'
    penalty=raid_penalty(raid,level,stats)
    bosses=boss_stats_for_raid(raid,level,stats)
    seconds=sum(b['hp']/max(1,theoretical_dps(stats,b['defense'],penalty)*(1-b['resistancePct']/100)) for b in bosses)
    incoming=sum(max(b['attack']*.1,b['attack']-min(stats.phys_def,stats.magic_def))/b['attackInterval'] for b in bosses)
    survival=stats.max_hp/max(1,incoming)
    eligible,reason=eligibility(raid,level,stats,items)
    return dict(version=BALANCE['version'],hard=not normal,eligible=eligible,entryReason=reason,
        equipmentQualified=equipment_qualified(raid,items), penalty=penalty,
        outputPassed=seconds<=rule['maxFightSeconds'],defensePassed=survival>=rule['minSurvivalSeconds'],
        minimumFightMs=max(1,int(seconds*1000*rule["durationTolerance"])),maxFightMs=int(rule['maxFightSeconds']*1000),clockToleranceMs=rule['clockToleranceMs'])


def equipment_qualified(raid,items):
    from app.services.game_config import CONFIG
    from app.services.raid_util import ancient_term_count, top_rarity_required
    rule=BALANCE['raids'][raid['id']]
    equipped=[i for i in items if getattr(i,'equipped_slot',None)]
    slots={i.equipped_slot for i in equipped}
    if rule['requiresAllSlots'] and len(slots)<len(CONFIG.slots): return False
    rank=CONFIG.rarity_order.index(rule['minEquipRarity'])
    if any(CONFIG.rarity_order.index(i.rarity)<rank for i in equipped): return False
    if rule['topRarity']:
        top=CONFIG.rarity_order.index(rule['topRarity'])
        if sum(CONFIG.rarity_order.index(i.rarity)>=top for i in equipped)<top_rarity_required(rule): return False
    if rule['minAncientTermsPerItem'] and any(not ancient_term_count(i,rule['minAncientTermsPerItem']) for i in equipped): return False
    return bool(equipped)


def clear_failures(start, current, server_ms, fight_ms):
    failures=[]
    if not start or not current: return ['missing_snapshot']
    if start['hard']:
        for key,reason in [('eligible','entry'),('outputPassed','output'),('defensePassed','defense')]:
            if not start.get(key) or not current.get(key): failures.append(reason)
        if fight_ms > start['maxFightMs']: failures.append('output')
    if server_ms < start['minimumFightMs'] or fight_ms < start['minimumFightMs'] or fight_ms > server_ms+start["clockToleranceMs"]:
        failures.append('invalid_duration')
    return sorted(set(failures))


def telemetry(attempts, now=None):
    now=now or datetime.now(timezone.utc)
    cfg=BALANCE['telemetry']
    def utc(d): return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    rows=[r for r in attempts if r.balance_snapshot.get('hard') and now-timedelta(days=cfg['days']) <= utc(r.started_at) <= now]
    entrants={r.user_id for r in rows}
    qualified={r.user_id for r in rows if r.balance_snapshot.get('eligible')}
    cohort={r.user_id for r in rows if r.balance_snapshot.get('equipmentQualified')}
    first={r.user_id for r in rows if r.outcome.get('firstClear') and r.cleared and r.ended_at and utc(r.ended_at)<=now}
    rate=len(first & cohort)/len(cohort) if cohort else None
    ended=[r for r in rows if r.ended_at and utc(r.ended_at)<=now]
    def failure(reason): return sum(reason in r.outcome.get('failures',[]) for r in ended)/len(ended) if ended else None
    return dict(windowDays=cfg['days'],firstEntrants=len({r.user_id for r in rows if r.balance_snapshot.get('firstEntry')}),
        entrants=len(entrants),qualifiedPlayers=len(qualified),firstClears=len(first),hardcorePlayers=len(cohort),
        hardcoreFirstClearRate=rate,mechanismFailureRates={key: sum(key in r.outcome.get('mechanismFailures',[]) for r in ended)/len(ended) for key in {k for r in ended for k in r.outcome.get('mechanismFailures',[])}},outputFailureRate=failure('output'),
        defenseFailureRate=failure('defense'),averageAttempts=len(rows)/len(entrants) if entrants else 0,
        averageFightSeconds=sum(r.outcome.get('fightMs',max(0,(utc(r.ended_at)-utc(r.started_at)).total_seconds()*1000)) for r in ended)/len(ended)/1000 if ended else 0,
        target=[cfg['targetLow'],cfg['targetHigh']],sufficientSample=len(cohort)>=cfg['minimumPlayers'])


def calibration(attempts, now=None):
    now=now or datetime.now(timezone.utc)
    windows=[telemetry(attempts,now-timedelta(days=i)) for i in range(BALANCE['telemetry']['consecutiveWindows'])]
    low,high=BALANCE['telemetry']['targetLow'],BALANCE['telemetry']['targetHigh']
    rates=[w['hardcoreFirstClearRate'] for w in windows]
    enough=all(w['sufficientSample'] for w in windows)
    direction='easier' if enough and all(r is not None and r<low for r in rates) else 'harder' if enough and all(r is not None and r>high for r in rates) else None
    return dict(**windows[0],calibrationDirection=direction,configurationOnly=True)

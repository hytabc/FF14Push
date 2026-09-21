"""Acceptance tests for versioned combat balance and server authority."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import json
import pytest
from sqlalchemy import select
from app.models import Hero, Item, RegionProgress, RaidSession
from app.services.balance import BALANCE, load_balance, power_audit, region_gate, soft_penalty
from app.services.damage import hit_chance
from app.services.raid_balance import telemetry, calibration, clear_failures
from app.services.stats import compute_stats
from tests.fakes import FakeHero, FakeItem

API='/api/v1'

def test_power_audit_diminishes_and_excludes_off_job_and_economy():
    stats=compute_stats(FakeHero(),[])
    values=[power_audit(replace(stats,attack=n))['total'] for n in (0,10000,20000,30000)]
    gains=[b-a for a,b in zip(values,values[1:])]
    assert gains[0]>gains[1]>gains[2]>0
    assert power_audit(replace(stats,magic_attack=1e12,term_mods={'goldGainPct':1e12}))['total']==power_audit(stats)['total']
    audit=power_audit(stats)
    assert audit['total']==int(sum(v['contribution'] for v in audit['contributions'].values()))


def test_penalties_monotone_bounded_and_hit_floor():
    stats=compute_stats(FakeHero(),[])
    penalties=[soft_penalty(p,100) for p in (0,25,50,75,100,150)]
    for field in ('healingMultiplier','resourceMultiplier','windowMultiplier','rewardMultiplier'):
        vals=[p[field] for p in penalties]
        assert vals==sorted(vals) and 0<min(vals)<=max(vals)==1
    for field in ('damageDealtPenaltyPct','damageTakenBonusPct','hitRatePenaltyPct','cooldownMultiplier'):
        vals=[p[field] for p in penalties]
        assert vals==sorted(vals,reverse=True)
    for s in (stats,replace(stats,hit_rate_pct=-50),replace(stats,hit_rate_pct=500)):
        for p in penalties:
            assert .8<=hit_chance(s,p['hitRatePenaltyPct'])<=.99
            assert hit_chance(s)-hit_chance(s,p['hitRatePenaltyPct'])<=.10+1e-9
    assert penalties[-1]==penalties[-2]
    assert soft_penalty(100,0)['deficit']==0


def test_all_region_conditions_and_time_cannot_bypass(monkeypatch):
    stats=replace(compute_stats(FakeHero(),[]),attack=20000,phys_def=20000,magic_def=20000)
    items=[FakeItem(rarity='mythic',equipped_slot=s['id']) for s in __import__('app.services.game_config',fromlist=['CONFIG']).CONFIG.slots]
    rule=BALANCE['regions']['2']
    monkeypatch.setitem(BALANCE['regions'],'2',dict(rule,power=100,quality=1,attack=100,defense=100))
    assert not region_gate(2,stats,items,{1})
    for attr in ('power','quality','attack','defense'):
        with monkeypatch.context() as m:
            m.setitem(BALANCE['regions']['2'],attr,1e10)
            assert region_gate(2,stats,items,{1})
    assert region_gate(2,stats,items,set())
    stats.online_seconds=stats.idle_seconds=stats.low_difficulty_clears=1e20
    assert region_gate(2,stats,items,set())
    monkeypatch.setitem(BALANCE,'migration','new_unlocks_only')
    assert not region_gate(2,stats,[],set(),True)
    assert region_gate(2,stats,[],set(),False)


def test_config_invalid_falls_back_with_log(tmp_path,caplog):
    file=tmp_path/'balance.json'
    for value in ('{',json.dumps({'version':'bad'})):
        file.write_text(value)
        assert load_balance(file)['version']=='2.0.0'
    bad=deepcopy(BALANCE);bad['normal']['hit']=.9
    file.write_text(json.dumps(bad));assert load_balance(file)['normal']['hit']==.1
    file.write_text(json.dumps(BALANCE));assert load_balance(file)==BALANCE
    assert 'using safe defaults' in caplog.text


@pytest.mark.parametrize('key,reason',[('eligible','entry'),('outputPassed','output'),('defensePassed','defense')])
def test_hard_clear_requires_every_gate_at_start_and_finish(key,reason):
    good=dict(hard=True,eligible=True,outputPassed=True,defensePassed=True,minimumFightMs=1000,maxFightMs=10000,clockToleranceMs=2000)
    assert clear_failures(good,good,5000,5000)==[]
    bad=dict(good,**{key:False})
    assert reason in clear_failures(bad,good,5000,5000)
    assert reason in clear_failures(good,bad,5000,5000)


def test_telemetry_uses_unique_rolling_equipment_cohort(monkeypatch):
    now=datetime.now(timezone.utc)
    rows=[]
    for i in range(100):
        rows.append(SimpleNamespace(user_id=i,started_at=now-timedelta(days=3),ended_at=now-timedelta(days=3)+timedelta(seconds=100),
            balance_snapshot=dict(hard=True,equipmentQualified=True,eligible=True,firstEntry=True),cleared=i<50,
            outcome=dict(firstClear=i<50,failures=[] if i<50 else ['output'],fightMs=100000)))
    old=deepcopy(rows[0]);old.user_id=100;old.started_at=now-timedelta(days=31)
    casual=deepcopy(rows[0]);casual.user_id=101;casual.balance_snapshot['equipmentQualified']=False
    repeat=deepcopy(rows[0]);repeat.outcome['firstClear']=False;repeat.balance_snapshot['firstEntry']=False
    result=telemetry(rows+[old,casual,repeat],now)
    assert result['hardcorePlayers']==100 and result['hardcoreFirstClearRate']==.5
    assert result['firstEntrants']==101
    assert calibration(rows,now)['calibrationDirection'] is None
    for row in rows: row.cleared=False;row.outcome['firstClear']=False
    assert calibration(rows,now)['calibrationDirection']=='easier'
    assert telemetry([],now)['hardcoreFirstClearRate'] is None


async def test_legacy_access_recalculated_at_every_entry(auth_client,session_factory,monkeypatch):
    uid=(await auth_client.get(f'{API}/auth/me')).json()['id']
    async with session_factory() as db:
        row=(await db.execute(select(RegionProgress).where(RegionProgress.user_id==uid,RegionProgress.region_id==2))).scalar_one()
        row.unlocked=True;row.cleared=True;row.best_clear_ms=12345
        hero=(await db.execute(select(Hero).where(Hero.user_id==uid))).scalar_one();hero.current_region_id=2
        await db.commit()
    for endpoint,body in [('region/enter',{'regionId':2}),('battle/session/start',{'regionId':2})]:
        response=await auth_client.post(f'{API}/{endpoint}',json=body)
        assert response.status_code==403 and '前一地区' in response.json()['detail']
    listing=(await auth_client.get(f'{API}/region')).json()['regions'][1]
    assert not listing['unlocked'] and listing['cleared'] and listing['bestClearMs']==12345
    state=(await auth_client.get(f'{API}/game/state')).json()
    assert state['currentRegion'] is None and state['powerAudit']['total']==state['power']
    monkeypatch.setitem(BALANCE,'migration','new_unlocks_only')
    assert (await auth_client.post(f'{API}/region/enter',json={'regionId':2})).status_code==200


async def test_low_power_normal_can_clear_with_reduced_reward(auth_client,session_factory):
    started=(await auth_client.post(f'{API}/raid/session/start',json={'raidId':'raid_1'})).json()
    assert started['penalty']['damageDealtPenaltyPct']>0
    async with session_factory() as db:
        session=await db.get(RaidSession,started['sessionId'])
        seconds=session.balance_snapshot['minimumFightMs']/1000+5
        session.started_at=datetime.now(timezone.utc)-timedelta(seconds=seconds)
        await db.commit()
    response=await auth_client.post(f'{API}/raid/session/report',json=dict(sessionId=started['sessionId'],raidId='raid_1',cleared=True,fightMs=int(seconds*1000)))
    assert response.status_code==200,response.text
    assert response.json()['cleared']
    assert 0<response.json()['goldGained']<50000
    assert (await auth_client.post(f'{API}/raid/session/report',json=dict(sessionId=started['sessionId'],raidId='raid_1',cleared=True))).status_code==404


async def test_hard_raid_no_longer_requires_trial(auth_client,session_factory):
    """高难副本不再要求机制试炼：会话不再有练习标记，快照与失败原因里也没有试炼。"""
    from tests.test_api import TestRaid
    await TestRaid()._gear_up(auth_client,session_factory,ancient=3)
    response=await auth_client.post(f'{API}/raid/session/start',json={'raidId':'raid_h1'})
    assert response.status_code==200,response.text
    started=response.json()
    assert 'practiceOnly' not in started
    async with session_factory() as db:
        session=await db.get(RaidSession,started['sessionId'])
        assert 'trialPassed' not in session.balance_snapshot
        session.started_at=datetime.now(timezone.utc)-timedelta(seconds=120)
        await db.commit()
    result=(await auth_client.post(f'{API}/raid/session/report',json=dict(
        sessionId=started['sessionId'],raidId='raid_h1',cleared=True,fightMs=120000))).json()
    assert 'mechanism' not in result.get('failures',[])


async def test_region_advance_requires_previous_boss_cleared(auth_client,session_factory):
    """击败前一地区 BOSS 才能推进下一地区；旧解锁标记不能绕过。"""
    uid=(await auth_client.get(f'{API}/auth/me')).json()['id']
    async with session_factory() as db:
        rows=(await db.execute(select(RegionProgress).where(RegionProgress.user_id==uid))).scalars().all()
        for row in rows:
            row.unlocked=True
            row.cleared=False
        await db.commit()
    response=await auth_client.post(f'{API}/region/advance')
    assert response.status_code==403 and '前一地区' in response.json()['detail']


def test_balance_migration_preserves_existing_records():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).parents[1]/'alembic/versions/g4b6c8d0e2f4_combat_balance.py'
    spec=importlib.util.spec_from_file_location('balance_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE raid_sessions (id INTEGER PRIMARY KEY, cleared BOOLEAN, pending_chest INTEGER)'))
        conn.execute(text('INSERT INTO raid_sessions VALUES (1, 1, 3)'))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            row=conn.execute(text('SELECT cleared, pending_chest, balance_snapshot FROM raid_sessions')).one()
            assert row==(1,3,'{}')
            assert 'mechanism_trials' in inspect(conn).get_table_names()
            migration.downgrade()
            assert conn.execute(text('SELECT cleared, pending_chest FROM raid_sessions')).one()==(1,3)
    engine.dispose()

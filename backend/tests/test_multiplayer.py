"""Team engine and API regression tests. All results use server state, never client wins."""
from copy import deepcopy
from types import SimpleNamespace
import time
import pytest
from sqlalchemy import select
from app.models import User,Hero,Item,BattleSession
from app.models.multiplayer import CoopBattle,CoopRoom,CoopMember,CoopCommand,CoopReward,CoopProgress
from app.services.multiplayer_config import MULTIPLAYER as CFG,DUNGEONS
from app.services.coop_engine import new_battle,advance,step,damage_hero,multiplier,command
from app.services.coop_rooms import validate_party
from app.services.coop_snapshot import entry_failures
from app.services.pvp_engine import duel
from app.services.stats import compute_stats
from app.services.game_config import CONFIG
from app.coop_worker import tick_rooms

API='/api/v1'
STARTER_JOB_ID=CONFIG.base_item_by_id[str(CONFIG.heroes['initialHero']['starterWeapon'])].job_id

def reference_seats(dungeon,boost=1):
    roles=['tank','healer','dps','dps','tank','healer','dps','dps'] if dungeon['seats']==8 else ['tank','dps']
    seats=[]
    for i,role in enumerate(roles):
        snap=deepcopy(CFG['references'][dungeon['referenceTier']][role])
        snap['heroId']=i+1;snap['ownerId']=i+1;snap['name']=f'{role}-{i}'
        for item in snap['items']:item['ownerId']=i+1
        for attr in ('attack','magic_attack','max_hp','phys_def','magic_def'):snap['stats'][attr]*=boost
        for attr in ('dps','healing','durability'):snap[attr]*=boost
        seats.append({'slot':i,'controllerId':i+1,'registrationId':None,'snapshot':snap})
    return seats

@pytest.mark.parametrize('dungeon',list(DUNGEONS.values()),ids=list(DUNGEONS))
@pytest.mark.parametrize('mode',['online','solo','offline'])
def test_all_dungeons_reference_can_clear(dungeon,mode):
    # Solo/clone ultimate references need upgraded output, by design.
    seats=reference_seats(dungeon,1.3 if mode!='online' and dungeon['difficulty'] in ('savage','ultimate') else 1)
    if mode=='offline':
        for s in seats[1:]:s['registrationId']=s['slot']
    state=new_battle(dungeon,seats,mode,CFG)
    advance(state,dungeon,CFG,dungeon['enrageSeconds']*1000)
    assert state['status']=='cleared',state['reason']
    assert state['phase']==len(dungeon['phases'])
    if dungeon['seats']==8:assert all(h['trialPassed'] for h in state['heroes'])

@pytest.mark.parametrize('dungeon',[d for d in DUNGEONS.values() if d['seats']==8],ids=[k for k,d in DUNGEONS.items() if d['seats']==8])
@pytest.mark.parametrize('weak_role',['tank','healer','dps'])
def test_entry_and_active_trial_reject_underqualified_hero(dungeon,weak_role):
    seats=reference_seats(dungeon,10)
    weak=next(s['snapshot'] for s in seats if s['snapshot']['role']==weak_role)
    for k in ('attack','magic_attack','max_hp','phys_def','magic_def'):weak['stats'][k]*=.001
    for k in ('dps','healing','durability'):weak[k]*=.001
    assert entry_failures(weak,dungeon,CFG)
    state=new_battle(dungeon,seats,'online',CFG)
    # 保持 Boss 存活以实际触发职责检查；爆发击杀现在允许跳过后续机制。
    for boss in state['bosses']:boss['hp']=boss['maxHp']=10**20
    advance(state,dungeon,CFG,45000)
    assert state['status']=='failed',state
    assert '职责' in state['reason']


def test_revive_weakness_refresh_and_wipe_priority():
    d=DUNGEONS['extreme_1'];state=new_battle(d,reference_seats(d),'solo',CFG);h=state['heroes'][0]
    h['mp']=7;h['cooldowns']['test']=99000
    damage_hero(state,h,10**12,'test')
    advance(state,d,CFG,4900);assert h['hp']==0
    step(state,d,CFG);assert h['hp']>0 and h['weakUntil']==65000
    assert h['cooldowns']['test']==99000 and h['mp']<h['snapshot']['stats']['max_mp']
    assert multiplier(h,state)==pytest.approx(.85*.5)
    h['clone']=True;assert multiplier(h,state)==pytest.approx(.85*.5*.8)
    damage_hero(state,h,10**12,'test');advance(state,d,CFG,5000)
    assert h['weakUntil']==70000
    state['elapsedMs']=70000;assert multiplier(h,state)==pytest.approx(.85*.8)
    for hero in state['heroes']:hero['hp']=0;hero['deadUntil']=0
    step(state,d,CFG);assert state['status']=='failed' and state['reason']=='全员倒下'


def test_damage_never_leaves_sub_one_hp():
    """小数伤害不应让英雄残留 (0,1) 生命值——否则会出现「显示 0 血却仍可战斗」。"""
    d=DUNGEONS['extreme_1'];state=new_battle(d,reference_seats(d),'solo',CFG);h=state['heroes'][0]
    h['hp']=100.0
    damage_hero(state,h,99.5,'test')
    assert h['hp']==0
    assert h['deadUntil']>state['elapsedMs'] and h['deaths']==1


def test_manual_mechanic_ownership_and_failure():
    d=DUNGEONS['extreme_1'];seats=reference_seats(d)
    for s in seats:s['snapshot']['strategy']='manual'
    st=new_battle(d,seats,'online',CFG);advance(st,d,CFG,4000)
    m=st['mechanics'][0];assert st['phase']==0 and st['bosses'][0]['hp']>0
    assert not command(st,{'slots':[0],'action':m['action'],'mechanicId':m['id']},999)
    assert command(st,{'slots':[0],'action':m['action'],'mechanicId':m['id']},1)
    advance(st,d,CFG,9000);assert st['status']=='failed'


def test_deterministic_checkpoint_replay_and_pvp():
    d=DUNGEONS['normal_1'];seats=reference_seats(d)
    a=new_battle(d,seats,'solo',CFG,123);b=deepcopy(a)
    advance(a,d,CFG,30000);advance(b,d,CFG,11000);b=deepcopy(b);advance(b,d,CFG,19000)
    assert a==b
    r=duel(seats[0]['snapshot'],seats[1]['snapshot'],CFG['pvp'],42)
    assert r==duel(seats[0]['snapshot'],seats[1]['snapshot'],CFG['pvp'],42)
    assert r['durationMs']<=180000 and r['events']

@pytest.mark.parametrize('n',range(2,9))
def test_balanced_seat_distribution(n):
    d=DUNGEONS['extreme_1'];seats=reference_seats(d)
    rows=[SimpleNamespace(slot=s['slot'],controller_id=s['slot']%n+1,registration_id=None,snapshot=s['snapshot']) for s in seats]
    for row in rows:
        row.snapshot['ownerId']=row.controller_id
        for item in row.snapshot['items']:
            item['ownerId']=row.controller_id;item['id']+=row.slot*100
    room=SimpleNamespace(dungeon_id=d['id'],mode='online')
    members=[SimpleNamespace(user_id=i+1,ready=True,heartbeat_at=100) for i in range(n)]
    assert not validate_party(room,rows,members,100)
    rows[0].controller_id=99
    assert validate_party(room,rows,members,100)

async def recruit(client,sessions):
    uid=(await client.get(API+'/auth/me')).json()['id']
    async with sessions() as db:
        user=await db.get(User,uid);user.gold=10000000;await db.commit()
    r=await client.post(API+'/tavern/recruit',json={'confirm':True});assert r.status_code==200,r.text
    return r.json()['hero']['id']

async def test_roster_preserves_equipment_isolation_and_session_binding(auth_client,session_factory):
    c=auth_client;before=(await c.get(API+'/game/state')).json();old=before['hero']['id'];item=before['loadout']['mainHand']['id']
    session=(await c.post(API+'/battle/session/start',json={'regionId':1})).json()['sessionId']
    new=await recruit(c,session_factory)
    state=(await c.get(API+'/game/state')).json()
    assert len(state['heroes'])==2 and state['activeHeroId']==old and state['loadout']['mainHand']['id']==item
    bad=await c.post(f'{API}/heroes/{new}/equip',json={'itemId':item,'slot':'mainHand'});assert bad.status_code==409
    assert (await c.post(API+'/heroes/switch',json={'heroId':new})).status_code==200
    state=(await c.get(API+'/game/state')).json();assert state['loadout']=={} and len(state['items'])==len(before['items'])
    late=await c.post(API+'/battle/session/report',json={'sessionId':session,'regionId':1,'elapsedMs':1000,'kills':[]})
    assert late.status_code==404
    assert (await c.post(f'{API}/heroes/{old}/unequip',json={'slot':'mainHand'})).status_code==200
    assert (await c.post(f'{API}/heroes/{new}/equip',json={'itemId':item,'slot':'mainHand'})).status_code==200
    async with session_factory() as db:
        heroes=(await db.scalars(select(Hero).where(Hero.user_id==before['user']['id']))).all()
        items=(await db.scalars(select(Item))).all()
        assert compute_stats(next(h for h in heroes if h.id==old),items).job_id=='adventurer'
        assert compute_stats(next(h for h in heroes if h.id==new),items).job_id==STARTER_JOB_ID

async def test_roster_capacity_explicit_dismiss(auth_client,session_factory):
    for _ in range(7):await recruit(auth_client,session_factory)
    full=await auth_client.post(API+'/tavern/recruit',json={'confirm':True});assert full.status_code==409
    assert (await auth_client.post(API+'/tavern/dismiss',json={})).status_code==422
    roster=(await auth_client.get(API+'/heroes')).json();assert len(roster['heroes'])==8
    assert (await auth_client.delete(f"{API}/heroes/{roster['heroes'][-1]['id']}")).status_code==200
    assert len((await auth_client.get(API+'/heroes')).json()['heroes'])==7


async def _set_gold(sessions,amount):
    async with sessions() as db:
        user=(await db.scalars(select(User))).first();user.gold=amount;await db.commit()


async def test_roster_expand_scales_cost_and_raises_capacity(auth_client,session_factory):
    cfg=CONFIG.heroes['roster']
    base,top=int(cfg['baseCapacity']),int(cfg['maxCapacity'])
    first,step=int(cfg['firstExpandCost']),int(cfg['expandCostStep'])
    roster=(await auth_client.get(API+'/heroes')).json()
    assert roster['capacity']==base and roster['maxCapacity']==top and roster['expandCost']==first

    await _set_gold(session_factory,first-1)
    poor=await auth_client.post(API+'/heroes/expand')
    assert poor.status_code==400 and '金币不足' in poor.json()['detail']

    await _set_gold(session_factory,10**12)
    gold=10**12
    for i in range(top-base):
        resp=await auth_client.post(API+'/heroes/expand');assert resp.status_code==200,resp.text
        body=resp.json();cost=first+i*step
        assert body['cost']==cost and body['capacity']==base+1+i and body['maxCapacity']==top
        assert body['expandCost']==(first+(i+1)*step if base+1+i<top else None)
        gold-=cost;assert body['gold']==gold
    capped=await auth_client.post(API+'/heroes/expand')
    assert capped.status_code==400 and '上限' in capped.json()['detail']
    assert (await auth_client.get(API+'/heroes')).json()['capacity']==top


async def test_recruit_past_base_capacity_after_expand(auth_client,session_factory):
    for _ in range(7):await recruit(auth_client,session_factory)
    assert (await auth_client.post(API+'/tavern/recruit',json={'confirm':True})).status_code==409
    await _set_gold(session_factory,10**12)
    assert (await auth_client.post(API+'/heroes/expand')).status_code==200
    assert (await auth_client.post(API+'/tavern/recruit',json={'confirm':True})).status_code==200
    assert len((await auth_client.get(API+'/heroes')).json()['heroes'])==9

async def seed_heroes(sessions,uid,dungeon_id='normal_1',count=2):
    """Real items from recorded reference fixture; no API-supplied combat stats."""
    from app.services.game_config import CONFIG
    async with sessions() as db:
        ids=[]
        for i in range(count):
            role=['tank','dps'][i%2];snap=CFG['references'][dungeon_id][role]
            h=Hero(user_id=uid,name=f'远征{i}',level=snap['level'],talent='mythic',attr_bias=snap['stats']['main_attr'],strength=80,agility=80,intellect=80)
            db.add(h);await db.flush();ids.append(h.id)
            for slot,raw in zip(CONFIG.slots,snap['referenceEquipment']):
                base=CONFIG.base_item_by_id[raw['baseId']]
                db.add(Item(user_id=uid,equipped_hero_id=h.id,equipped_slot=slot['id'],base_id=base.id,name=base.name,
                    category=base.category,slot=base.slot,rarity=raw.get('rarity','rare'),high_quality=raw.get('highQuality',False),level_req=base.level_req,base_attrs=raw['baseAttrs'],sub_attrs=raw['subAttrs'],terms=raw['terms']))
        await db.commit();return ids

async def make_room(c,ids,mode='solo'):
    r=await c.post(API+'/coop/rooms',json={'dungeonId':'normal_1','mode':mode});assert r.status_code==200,r.text
    room=r.json();uid=(await c.get(API+'/auth/me')).json()['id']
    for i,hid in enumerate(ids):
        r=await c.put(f"{API}/coop/rooms/{room['id']}/seat",json={'slot':i,'controllerId':uid,'heroId':hid,'strategy':'assist'});assert r.status_code==200,r.text
    assert (await c.post(f"{API}/coop/rooms/{room['id']}/ready",json={})).status_code==200
    return room

async def test_coop_worker_reconnect_locks_and_reward_once(auth_client,session_factory):
    c=auth_client;uid=(await c.get(API+'/auth/me')).json()['id'];ids=await seed_heroes(session_factory,uid)
    room=await make_room(c,ids);rid=room['id']
    r=await c.post(f'{API}/coop/rooms/{rid}/start');assert r.status_code==200,r.text
    assert (await c.post(API+'/heroes/switch',json={'heroId':ids[0]})).status_code==409
    assert (await c.delete(f'{API}/heroes/{ids[1]}')).status_code==409
    now=time.time()
    async with session_factory() as db:
        m=await db.scalar(select(CoopMember).where(CoopMember.room_id==rid));m.heartbeat_at=now-16
        await db.commit()
    await tick_rooms(session_factory,'test',now)
    async with session_factory() as db:
        b=await db.scalar(select(CoopBattle).where(CoopBattle.room_id==rid));assert all(h['clone'] for h in b.state['heroes'])
        st=deepcopy(b.state);st['heroes'][0]['hp']=123;st['heroes'][0]['weakUntil']=65000;st['heroes'][0]['cooldowns']['test']=90000;b.state=st
        m=await db.scalar(select(CoopMember).where(CoopMember.room_id==rid));m.heartbeat_at=now+.1;await db.commit()
    await tick_rooms(session_factory,'test',now+.1)
    async with session_factory() as db:
        b=await db.scalar(select(CoopBattle).where(CoopBattle.room_id==rid));h=b.state['heroes'][0]
        assert not h['clone'] and h['weakUntil']==65000 and h['cooldowns']['test']==90000 and h['hp']<h['snapshot']['stats']['max_hp']
        # Finish using the real engine, then persist its terminal checkpoint.
        state=deepcopy(b.state);advance(state,DUNGEONS['normal_1'],CFG,450000);assert state['status']=='cleared',state['reason']
        b.state=state;b.status='cleared';r=await db.get(CoopRoom,rid);r.status='cleared';await db.commit()
    first=await c.post(f'{API}/coop/rooms/{rid}/claim');assert first.status_code==200,first.text
    second=await c.post(f'{API}/coop/rooms/{rid}/claim');assert second.json()==first.json()
    async with session_factory() as db:
        rewards=(await db.scalars(select(CoopReward))).all();assert len(rewards)==1
        assert (await db.scalar(select(CoopProgress))).clears==1
        for hid in ids:assert (await db.get(Hero,hid)).exp>0

async def test_coop_reward_grants_recraft_cards_and_ultimate_title(session_factory):
    """通关奖励：按难度产出「重新打造卡」、按模式加成，并在绝境战通关时授予 FF14 称号。"""
    from app.models import StackItem, UserTitle
    from app.services.coop_rewards import grant_reward

    async with session_factory() as db:
        user = User(username='card_reward', nickname='Card', password_hash='x', gold=0)
        db.add(user)
        await db.flush()
        hero = Hero(user_id=user.id, name='英雄', level=100, talent='common', attr_bias='balanced',
                    strength=33, agility=33, intellect=34)
        db.add(hero)
        await db.flush()
        uid, hid = int(user.id), int(hero.id)
        dungeon = DUNGEONS['ultimate_1']
        mult = CFG['modeRewardMultiplier']['online']
        battle = SimpleNamespace(id=91, status='cleared', state={'hadClone': False, 'elapsedMs': 60000, 'heroes': [
            {'controllerId': uid, 'registeredClone': False, 'snapshot': {'heroId': hid}}
        ]}, config={'dungeons': [dungeon]})
        room = SimpleNamespace(dungeon_id='ultimate_1', mode='online')
        receipt = await grant_reward(db, uid, room, battle)
        await db.commit()

    assert receipt['rewardMultiplier'] == mult
    assert receipt['goldGained'] == round(dungeon['reward']['firstGold'] * mult)
    assert receipt['cards'] == round(dungeon['reward']['cards'] * mult)
    assert 'coop_ultimate_bahamut' in receipt['newTitles']

    async with session_factory() as db:
        card = await db.scalar(select(StackItem).where(StackItem.user_id == uid, StackItem.kind == 'card'))
        assert card is not None and int(card.count) == receipt['cards']
        owned = set((await db.scalars(select(UserTitle.title_id).where(UserTitle.user_id == uid))).all())
        assert 'coop_ultimate_bahamut' in owned

    # 幂等：同一次战斗重复领取返回同一回执（不重复发卡 / 称号）
    async with session_factory() as db:
        assert await grant_reward(db, uid, room, battle) == receipt


async def test_room_rejects_duplicates_and_single_online(auth_client,session_factory):
    c=auth_client;uid=(await c.get(API+'/auth/me')).json()['id'];ids=await seed_heroes(session_factory,uid)
    room=await make_room(c,[ids[0],ids[0]])
    r=await c.post(f"{API}/coop/rooms/{room['id']}/start");assert r.status_code==409 and '重复' in r.text
    room=await make_room(c,ids,'online')
    r=await c.post(f"{API}/coop/rooms/{room['id']}/start");assert r.status_code==409 and '至少2' in r.text

async def test_pvp_registration_history_and_idempotency(auth_client,session_factory):
    from app.models.multiplayer import HeroRegistration
    c=auth_client;uid=(await c.get(API+'/auth/me')).json()['id'];hid=(await c.get(API+'/heroes')).json()['activeHeroId']
    r=await c.post(API+'/registrations',json={'heroId':hid,'kind':'pvp'});assert r.status_code==200
    assert (await c.post(API+'/pvp/challenge',json={'heroId':hid,'registrationId':r.json()['id'],'key':'own-test'})).status_code==400
    async with session_factory() as db:
        user=User(username='rival',nickname='Rival',password_hash='x');db.add(user);await db.flush()
        h=Hero(user_id=user.id,name='对手',level=1,talent='common',attr_bias='balanced',strength=33,agility=33,intellect=34);db.add(h);await db.flush();user.active_hero_id=h.id
        from app.services.coop_snapshot import snapshot_hero
        reg=HeroRegistration(user_id=user.id,hero_id=h.id,kind='pvp',snapshot=await snapshot_hero(db,h));db.add(reg);await db.commit();rid=reg.id
    payload={'heroId':hid,'registrationId':rid,'key':'unique-request'}
    a=await c.post(API+'/pvp/challenge',json=payload);assert a.status_code==200,a.text
    b=await c.post(API+'/pvp/challenge',json=payload);assert a.json()==b.json()
    assert len((await c.get(API+'/pvp')).json()['battles'])==1
    assert (await c.get(f"{API}/pvp/{a.json()['id']}")).json()['report']['events']


@pytest.mark.parametrize('dungeon', list(DUNGEONS.values()), ids=list(DUNGEONS))
def test_burst_kills_skip_pending_mechanics_and_trials(dungeon):
    seats = reference_seats(dungeon, 1000000)
    for seat in seats: seat['snapshot']['strategy'] = 'manual'
    state = new_battle(dungeon, seats, 'online', CFG)
    advance(state, dungeon, CFG, 15000)
    assert state['status'] == 'cleared', state['reason']
    assert all(boss['hp'] == 0 for boss in state['bosses'])
    assert not any(e['kind'] in ('mechanicFail', 'failed') for e in state['events'])


def test_kill_cancels_cast_expiring_on_same_tick():
    dungeon = DUNGEONS['extreme_1']
    state = new_battle(dungeon, reference_seats(dungeon), 'online', CFG)
    for boss in state['bosses']: boss['hp'] = 1
    mechanic = state['mechanics'][0]
    mechanic.update(opened=True, deadline=100, hard=True, responses={})
    step(state, dungeon, CFG)
    assert state['status'] == 'running'
    assert state['phase'] == 1


def test_partial_boss_kill_still_requires_synchronized_kill():
    dungeon = next(d for d in DUNGEONS.values() if len(d['phases'][0]['bosses']) > 1)
    state = new_battle(dungeon, reference_seats(dungeon, 100), 'online', CFG)
    state['bosses'][0]['hp'] = 0
    state['bosses'][1]['hp'] = 10**20
    state['firstBossDeath'] = 0
    state['elapsedMs'] = dungeon['syncKillSeconds'] * 1000
    step(state, dungeon, CFG)
    assert state['status'] == 'failed'
    assert state['reason'] == '双Boss未同步击杀'

"""Deterministic 100ms team simulation. Pure JSON in/out, no wall clock or client damage."""
from copy import deepcopy

TICK = 100

def random_unit(state):
    state['rng'] = (1664525 * state['rng'] + 1013904223) & 0xffffffff
    return state['rng'] / 4294967296

def event(state, kind, text, **data):
    state['eventSequence'] += 1
    state['events'].append({'seq':state['eventSequence'],'at':state['elapsedMs'],'kind':kind,'text':text,**data})
    state['events'] = state['events'][-200:]

def multiplier(hero, state):
    value = state['rules']['soloMultiplier'] if state['mode']=='solo' else 1.
    if hero['clone']: value *= state['rules']['cloneMultiplier']
    if hero['weakUntil'] > state['elapsedMs']: value *= state['rules']['weaknessMultiplier']
    return value

def new_battle(dungeon, seats, mode, config, seed=20260922):
    state={'version':config['version'],'mode':mode,'elapsedMs':0,'phase':0,'phaseMs':0,
        'status':'running','reason':None,'rng':seed,'eventSequence':0,'events':[],
        'heroes':[], 'bosses':[], 'mechanics':[], 'trial':None,'trialDone':dungeon['seats']==2,
        'hadClone':False,'allOfflineSince':None, 'firstBossDeath':None,
        'rules':{**{k:config[k] for k in ['soloMultiplier','cloneMultiplier','weaknessMultiplier','weaknessSeconds','reviveSeconds']},'healingMultiplier':config.get('healingMultiplier',1.0)}}
    for seat in seats:
        snap=deepcopy(seat['snapshot']); stats=snap['stats']
        state['heroes'].append({'slot':seat['slot'],'controllerId':seat['controllerId'],
            'snapshot':snap,'clone':bool(seat.get('registrationId')),'registeredClone':bool(seat.get('registrationId')),
            'hp':stats['max_hp'],'mp':stats['max_mp'],'shield':0.,'deadUntil':0,'weakUntil':0,
            'cooldowns':{},'nextAttack':0,'gcdUntil':0,'buffs':[], 'dots':[], 'nextHeal':0,
            'damage':0.,'healing':0.,'damageTaken':0.,'minHpRatio':1.,'dangerMs':0,'deaths':0,'target':0,'threat':0.,'trialPassed':False})
    state['hadClone']=any(h['clone'] for h in state['heroes'])
    enter_phase(state,dungeon,config)
    return state

def enter_phase(state,dungeon,config):
    phase=dungeon['phases'][state['phase']]
    refs=config['references'][dungeon['referenceTier']]
    party_dps=sum(refs[h['snapshot']['role']]['dps'] for h in state['heroes'])
    hp=party_dps*phase['hpScale']/len(phase['bosses'])
    state['bosses']=[{'id':i,'name':name,'hp':hp,'maxHp':hp,'nextAttack':state['elapsedMs']+2000,
        'attack':refs['tank']['stats']['max_hp']*dungeon['pressure']['autoHpRatio']+refs['tank']['stats']['phys_def']*.8,
        'stunUntil':0,'dots':[]} for i,name in enumerate(phase['bosses'])]
    state['mechanics']=[{**m,'id':f"{state['phase']}:{i}",'opened':False,'resolved':False,'responses':{}} for i,m in enumerate(phase['mechanics'])]
    state['phaseMs']=0; state['trial']=None; state['trialDone']=dungeon['seats']==2
    state['firstBossDeath']=None
    state['nextRaidwide']=state['elapsedMs']+dungeon['pressure']['raidwideIntervalMs']
    state['nextBuster']=state['elapsedMs']+15000
    for h in state['heroes']: h['target']=0; h['trialPassed']=False
    event(state,'phase',phase['name'])

def fail(state,reason):
    state['status']='failed';state['reason']=reason
    event(state,'failed',reason)

def damage_hero(state,hero,amount,source):
    if hero['hp']<=0:return
    reduction=max([b['value'] for b in hero['buffs'] if b['type']=='damageReduction' and b['until']>state['elapsedMs']]+[0])
    amount=max(0,amount)*(1-min(.8,reduction))
    absorbed=min(hero['shield'],amount);hero['shield']-=absorbed;amount-=absorbed
    hero['damageTaken']+=min(hero['hp'],amount)
    hero['hp']=max(0,hero['hp']-amount)
    hero['minHpRatio']=min(hero['minHpRatio'],hero['hp']/hero['snapshot']['stats']['max_hp'])
    if hero['hp']==0:
        hero['deadUntil']=state['elapsedMs']+state['rules']['reviveSeconds']*1000
        hero['deaths']+=1; hero['shield']=0;hero['buffs']=[];hero['dots']=[]
        event(state,'death',hero['snapshot']['name']+'倒下了',slot=hero['slot'],source=source)

def heal_hero(state,source,target,amount,shield=False):
    if target['hp']<=0:return
    amount=max(0,amount)*multiplier(source,state)*state['rules'].get('healingMultiplier',1.0)
    if shield:target['shield']=min(target['snapshot']['stats']['max_hp'],target['shield']+amount)
    else:
        actual=min(amount,target['snapshot']['stats']['max_hp']-target['hp']);target['hp']+=actual;source['healing']+=actual

def command(state,payload,controller_id):
    """Return acceptance; commands cannot touch another controller or a closed window."""
    if state['status']!='running':return False
    selected=[h for h in state['heroes'] if h['slot'] in payload.get('slots',[]) and h['controllerId']==controller_id and not h['clone'] and h['hp']>0]
    if len(selected)!=len(set(payload.get('slots',[]))) or not selected:return False
    if payload.get('action')=='target':
        target=payload.get('target',0)
        if not isinstance(target,int) or target<0 or target>=len(state['bosses']):return False
        for h in selected:h['target']=target
        return True
    mech=next((m for m in state['mechanics'] if m['id']==payload.get('mechanicId') and m['opened'] and not m['resolved']),None)
    if not mech or payload.get('action')!=mech['action']:return False
    value=payload.get('value',0)
    if not isinstance(value,int) or not 0<=value<8:return False
    for h in selected:mech['responses'][str(h['slot'])]=value
    return True

def apply_mechanic(state,mech,dungeon):
    alive=[h for h in state['heroes'] if h['hp']>0]
    responses=mech['responses']; action=mech['action']
    actors=alive
    if action=='swap':actors=[h for h in alive if h['snapshot']['role']=='tank']
    if action=='dispel':actors=[h for h in alive if h['snapshot']['role']=='healer']
    good=bool(actors) and all(str(h['slot']) in responses for h in actors)
    vals=[responses.get(str(h['slot']),-1) for h in actors]
    if action=='spread':good=good and len(set(vals))==len(actors)
    if action=='stack':good=good and all(v in (0,1) for v in vals) and (len(vals)<=2 or abs(vals.count(0)-vals.count(1))<=1)
    if action=='focus':good=good and len(set(vals))==1
    if not good:
        if mech['hard']:fail(state,mech['name']+'：机制指令失败');return
        for h in alive:damage_hero(state,h,h['snapshot']['stats']['max_hp']*.35,mech['name'])
        event(state,'mechanicFail',mech['name']+'失败')
    else:
        if action=='swap':
            for h in actors:h['threat']=100000000 if h==actors[-1] else 0
        if action=='mitigate':
            for h in alive:h['buffs'].append({'type':'damageReduction','value':.4,'until':state['elapsedMs']+6000})
        if action=='dispel':
            for h in alive:h['dots']=[]
        if action=='rescue':
            for h in alive:heal_hero(state,h,h,h['snapshot']['stats']['max_hp']*.1)
        if action=='focus':
            for h in alive:h['target']=vals[0]%len(state['bosses'])
        event(state,'mechanic',mech['name']+'成功')
    # Damage is an actual encounter consequence, including successful mitigation.
    if action in ('stack','mitigate','swap'):
        for h in actors:damage_hero(state,h,h['snapshot']['stats']['max_hp']*.12,mech['name'])
    if action=='spread' and not good:
        for h in alive:h['dots'].append({'until':state['elapsedMs']+6000,'damage':h['snapshot']['stats']['max_hp']*.025})

def tick_trial(state,dungeon,config):
    if dungeon['seats']==2 or state['trialDone']:return
    now=state['elapsedMs']; refs=config['references'][dungeon['referenceTier']]
    if state['phaseMs']>=18000 and state['trial'] is None:
        checks={}
        for h in state['heroes']:
            role=h['snapshot']['role'];ref=refs[role]
            amount=ref['dps']*8*dungeon['trialScale'] if role=='dps' else ref['healing']*4*dungeon['trialScale']
            checks[str(h['slot'])]={'role':role,'remaining':amount if role!='tank' else 3,'next':now+2000,'passed':False}
        state['trial']={'endsAt':now+12000,'checks':checks}
        event(state,'trial','个人职责检查：专属目标、独立救治、坦克承伤')
    trial=state['trial']
    if not trial:return
    for h in state['heroes']:
        check=trial['checks'][str(h['slot'])]
        if check['role']=='tank' and h['hp']>0 and now>=check['next'] and check['remaining']>0:
            ref=refs['tank']['stats']; stats=h['snapshot']['stats']
            hit=max(ref['max_hp']*.1, ref['max_hp']*.16+ref['phys_def']-stats['phys_def'])
            damage_hero(state,h,hit,'个人承伤'); check['remaining']-=1;check['next']=now+3000
            if h['hp']<=0:check['remaining']=999
    if now>=trial['endsAt']:
        failed=[h['slot'] for h in state['heroes'] if trial['checks'][str(h['slot'])]['remaining']>0 or h['hp']<=0]
        if failed:fail(state,'个人职责检查失败：席位'+','.join(str(i+1) for i in failed));return
        state['trialDone']=True
        for h in state['heroes']:h['trialPassed']=True
        event(state,'trialPassed','全部英雄完成个人职责检查')

def deal_damage(state,hero,damage):
    amount=damage*multiplier(hero,state)
    check=(state.get('trial') or {}).get('checks',{}).get(str(hero['slot']))
    if check and not state['trialDone'] and check['role']=='dps' and check['remaining']>0:
        check['remaining']=max(0,check['remaining']-amount);hero['damage']+=amount;return
    living=[b for b in state['bosses'] if b['hp']>0]
    if not living:return
    target=next((b for b in living if b['id']==hero['target']),min(living,key=lambda b:b['hp']))
    # Auto balance simultaneous bosses; manual target overrides via 'manual' strategy.
    if hero['clone'] or hero['snapshot']['strategy']=='assist':target=max(living,key=lambda b:b['hp'])
    target['hp']=max(0,target['hp']-amount)
    hero['damage']+=amount;hero['threat']+=amount*(5 if hero['snapshot']['role']=='tank' else 1)

def auto_actions(state,hero):
    now=state['elapsedMs'];snap=hero['snapshot'];stats=snap['stats'];role=snap['role']
    attack=stats['magic_attack'] if stats['main_attr']=='int' else stats['attack']
    buff=1+sum(b['value'] for b in hero['buffs'] if b['type'] in ('allDamageBuff','attackBuff') and b['until']>now)
    crit=1+stats['crit_rate_pct']/100*max(0,stats['crit_damage_pct']/100-1)
    mult=buff*crit*(1+stats['det_bonus_pct']/100)
    if now>=hero['nextAttack']:
        deal_damage(state,hero,attack*mult*(.9+random_unit(state)*.2))
        hero['nextAttack']=now+int(2000/(1+stats['attack_speed_pct']/100))
    if role=='healer' and now>=hero['nextHeal']:
        amount=snap['healing'];check=(state.get('trial') or {}).get('checks',{}).get(str(hero['slot']))
        if check and not state['trialDone'] and check['remaining']>0:
            check['remaining']=max(0,check['remaining']-amount*multiplier(hero,state))
        else:
            alive=[h for h in state['heroes'] if h['hp']>0]
            if alive:heal_hero(state,hero,min(alive,key=lambda h:h['hp']/h['snapshot']['stats']['max_hp']),amount)
        hero['nextHeal']=now+2000
    if now<hero['gcdUntil']:return
    skills=sorted(snap['skills'],key=lambda s:s.get('priority',3))
    skill=next((s for s in skills if hero['cooldowns'].get(s['id'],0)<=now and s.get('mpCost',0)<=hero['mp']),None)
    if not skill:return
    hero['mp']-=skill.get('mpCost',0);hero['gcdUntil']=now+1500;hero['cooldowns'][skill['id']]=now+round(skill['cd']*1000)
    if skill.get('potency',0):deal_damage(state,hero,attack*skill['potency']/100*snap['skillMultiplier']*mult*(.9+random_unit(state)*.2))
    alive=[h for h in state['heroes'] if h['hp']>0]
    for effect in skill.get('effects',[]):
        typ=effect['type'];value=effect.get('value',0);duration=effect.get('duration',10)*1000
        target=min(alive,key=lambda h:h['hp']/h['snapshot']['stats']['max_hp']) if role=='healer' and alive else hero
        if typ in ('heal','fullHeal','shield'):
            targets=alive if skill.get('teamTarget')=='party' else [target]
            for ally in targets:heal_hero(state,hero,ally,stats['max_hp']*(1 if typ=='fullHeal' else value),typ=='shield')
        elif typ=='healOverTime':
            targets=alive if skill.get('teamTarget')=='party' else [target]
            for ally in targets:ally['buffs'].append({'type':typ,'value':stats['max_hp']*value*multiplier(hero,state)*state['rules'].get('healingMultiplier',1.0),'until':now+duration})
        elif typ in ('damageReduction','allDamageBuff','attackBuff','critRateBuff'):
            hero['buffs'].append({'type':typ,'value':value,'until':now+duration})
        elif typ=='dot':
            living=[b for b in state['bosses'] if b['hp']>0]
            if living:living[0]['dots'].append({'until':now+duration,'potency':effect.get('potency',value),'slot':hero['slot']})
        elif typ=='stun':
            for boss in state['bosses']:boss['stunUntil']=now+min(1500,duration)

def step(state,dungeon,config):
    if state['status']!='running':return
    state['elapsedMs']+=TICK;state['phaseMs']+=TICK;now=state['elapsedMs']
    if now>=dungeon['enrageSeconds']*1000:fail(state,'狂暴');return
    # Wipe always wins over scheduled revival.
    if not any(h['hp']>0 for h in state['heroes']):fail(state,'全员倒下');return
    for h in state['heroes']:
        if h['hp']<=0:
            if now>=h['deadUntil']:
                h['hp']=h['snapshot']['stats']['max_hp'];h['weakUntil']=now+config['weaknessSeconds']*1000
                event(state,'revive',h['snapshot']['name']+'复活，衰弱60秒',slot=h['slot'])
            else:continue
        stats=h['snapshot']['stats']
        if h['hp']/stats['max_hp']<.4:h['dangerMs']+=TICK
        h['mp']=min(stats['max_mp'],h['mp']+stats['mp_regen']*.1)
        h['buffs']=[b for b in h['buffs'] if b['until']>now]
        h['dots']=[d for d in h['dots'] if d['until']>now]
        # Regeneration is healing and obeys mode/weakness multipliers.
        heal_hero(state,h,h,stats['hp_regen']*.1)
        for b in h['buffs']:
            if b['type']=='healOverTime':h['hp']=min(stats['max_hp'],h['hp']+b['value']*.1)
        for dot in h['dots']:damage_hero(state,h,dot['damage']*.1,'持续伤害')
        if h['hp']>0:auto_actions(state,h)
    if all(b['hp']<=0 for b in state['bosses']):
        finish_phase(state,dungeon,config)
        return
    for m in state['mechanics']:
        if not m['opened'] and state['phaseMs']>=m['at']*1000:
            m['opened']=True;m['deadline']=now+m['window']*1000
            event(state,'cast',m['name'],action=m['action'],mechanicId=m['id'],deadline=m['deadline'])
        if m['opened'] and not m['resolved']:
            for h in state['heroes']:
                if h['hp']<=0 or not (h['clone'] or h['snapshot']['strategy']=='assist'):continue
                if now < m['deadline']-m['window']*1000+1000:continue
                m['responses'][str(h['slot'])]=h['slot'] if m['action']=='spread' else h['slot']%2 if m['action']=='stack' else 0
            if now>=m['deadline']:
                m['resolved']=True;apply_mechanic(state,m,dungeon)
                if state['status']!='running':return
    tick_trial(state,dungeon,config)
    if state['status']!='running':return
    for boss in state['bosses']:
        if boss['hp']<=0:continue
        boss['dots']=[d for d in boss['dots'] if d['until']>now]
        for dot in boss['dots']:
            source=next(h for h in state['heroes'] if h['slot']==dot['slot'])
            if source['hp']>0:
                stats=source['snapshot']['stats'];power=stats['magic_attack'] if stats['main_attr']=='int' else stats['attack']
                deal_damage(state,source,power*dot['potency']/100*.1)
        if boss['hp']<=0:continue
        if now>=boss['nextAttack'] and now>=boss['stunUntil']:
            alive=[h for h in state['heroes'] if h['hp']>0]
            if not alive:break
            tanks=[h for h in alive if h['snapshot']['role']=='tank']
            ordered=sorted(tanks or alive,key=lambda h:h['threat'],reverse=True)
            target=ordered[boss['id']%len(ordered)]
            damage_hero(state,target,max(boss['attack']*.1,boss['attack']-target['snapshot']['stats']['phys_def']*.8),boss['name'])
            boss['nextAttack']=now+2000
    if all(b['hp']<=0 for b in state['bosses']):
        finish_phase(state,dungeon,config)
        return
    refs=config['references'][dungeon['referenceTier']]
    pressure=dungeon['pressure']
    if now>=state['nextRaidwide']:
        for h in state['heroes']:
            ref=refs[h['snapshot']['role']]['stats'];stats=h['snapshot']['stats']
            # Absolute damage from the reference build, never from the victim's max HP.
            hit=max(ref['max_hp']*pressure['raidwideHpRatio']*.25,
                ref['max_hp']*pressure['raidwideHpRatio']+ref['magic_def']*2-stats['magic_def']*2)
            damage_hero(state,h,hit,'团队范围伤害')
        state['nextRaidwide']=now+pressure['raidwideIntervalMs']
        event(state,'raidwide','全队承受范围伤害')
    if now>=state['nextBuster']:
        tanks=[h for h in state['heroes'] if h['snapshot']['role']=='tank' and h['hp']>0]
        if tanks:
            target=max(tanks,key=lambda h:h['threat']);ref=refs['tank']['stats'];stats=target['snapshot']['stats']
            damage_hero(state,target,max(ref['max_hp']*.1,ref['max_hp']*pressure['busterHpRatio']+ref['phys_def']*3-stats['phys_def']*3),'坦克重击')
        state['nextBuster']=now+25000
    if not any(h['hp']>0 for h in state['heroes']):fail(state,'全员倒下');return
    finish_phase(state,dungeon,config)

def finish_phase(state,dungeon,config):
    """Defeated bosses never wait for future mechanics or personal trials."""
    if not any(h['hp']>0 for h in state['heroes']):fail(state,'全员倒下');return
    dead=sum(b['hp']<=0 for b in state['bosses'])
    if 0<dead<len(state['bosses']):
        if state['firstBossDeath'] is None:state['firstBossDeath']=state['elapsedMs']
        elif state['elapsedMs']-state['firstBossDeath']>=dungeon['syncKillSeconds']*1000:fail(state,'双Boss未同步击杀');return
    if dead==len(state['bosses']):
        state['phase']+=1
        if state['phase']==len(dungeon['phases']):
            state['status']='cleared';event(state,'cleared','挑战成功');return
        if dungeon['seats']==2:
            for h in state['heroes']:
                if h['hp']>0:h['hp']=h['snapshot']['stats']['max_hp'];h['mp']=h['snapshot']['stats']['max_mp']
        enter_phase(state,dungeon,config)

def advance(state,dungeon,config,milliseconds):
    for _ in range(milliseconds//TICK):
        step(state,dungeon,config)
        if state['status']!='running':break
    return state

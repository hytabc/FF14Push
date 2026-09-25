"""Seeded asynchronous duel, using registered skill rotations and independent PvP tuning."""
from copy import deepcopy
from app.services.coop_engine import random_unit, shield_cap_pct

def duel(attacker,defender,config,seed):
    fighters=[]
    for s in (attacker,defender):
        fighters.append({'snapshot':deepcopy(s),'hp':s['stats']['max_hp'],'mp':s['stats']['max_mp'],
            'cooldowns':{},'lastCastAt':{},'gcd':0,'attackAt':0,'stunUntil':0,'shield':0,'buffUntil':0})
    rng={'rng':seed};events=[];winner=None;tick=0
    for tick in range(0,config['maxSeconds']*1000,100):
        hits=[]
        for i,h in enumerate(fighters):
            s=h['snapshot'];st=s['stats'];enemy=fighters[1-i]
            h['mp']=min(st['max_mp'],h['mp']+st['mp_regen']*.1)
            if tick<h['stunUntil']:continue
            attack=st['magic_attack'] if st['main_attr']=='int' else st['attack']
            potency=0
            if tick>=h['attackAt']:potency+=100;h['attackAt']=tick+2000
            skill=None
            if tick>=h['gcd']:
                skill=next((a for a in sorted(s['skills'],key=lambda a:(a.get('priority',3),h['lastCastAt'].get(a['id'],float('-inf')) if a.get('priority',3)==3 else 0.0,float(a.get('potency',0) or 0))) if h['cooldowns'].get(a['id'],0)<=tick and a.get('mpCost',0)<=h['mp']),None)
            if skill:
                potency+=skill.get('potency',0)*s['skillMultiplier'];h['gcd']=tick+1500
                h['cooldowns'][skill['id']]=tick+round(skill['cd']*1000);h['lastCastAt'][skill['id']]=tick;h['mp']-=skill.get('mpCost',0)
                for effect in skill.get('effects',[]):
                    typ=effect['type'];value=effect.get('value',0)
                    if typ in ('heal','fullHeal','healOverTime'):
                        amount=st['max_hp']*(1 if typ=='fullHeal' else value)*config['healingMultiplier']
                        h['hp']=min(st['max_hp'],h['hp']+amount)
                    elif typ=='shield':
                        cap=st['max_hp']*shield_cap_pct()/100
                        h['shield']=min(cap,h['shield']+st['max_hp']*value*config['healingMultiplier'])
                    elif typ=='stun':enemy['stunUntil']=tick+round(config['controlSeconds']*1000)
                    elif typ in ('attackBuff','allDamageBuff'):h['buffUntil']=tick+round(effect.get('duration',5)*1000)
            if potency:
                defense=enemy['snapshot']['stats']['magic_def' if st['main_attr']=='int' else 'phys_def']
                raw=attack*potency/100*(1.2 if h['buffUntil']>tick else 1)*(1+st['det_bonus_pct']/100)
                if random_unit(rng)<st['crit_rate_pct']/100:raw*=st['crit_damage_pct']/100
                amount=max(raw*.1,raw-defense)*config['damageMultiplier']*(.9+random_unit(rng)*.2)
                hits.append((i,amount,skill['name'] if skill else '普攻'))
        for i,amount,name in hits:
            target=fighters[1-i];absorb=min(target['shield'],amount);target['shield']-=absorb
            target['hp']=max(0,target['hp']-(amount-absorb))
            events.append({'at':tick,'actor':i,'skill':name,'damage':round(amount-absorb),'hp':[round(h['hp']) for h in fighters],'shield':[round(h['shield']) for h in fighters]})
        if any(h['hp']<=0 for h in fighters):
            winner=None if all(h['hp']<=0 for h in fighters) else 0 if fighters[1]['hp']<=0 else 1
            break
    return {'seed':seed,'version':1,'fighters':[attacker,defender],'events':events,'durationMs':tick+100,
        'winner':winner,'result':'draw' if winner is None else 'attacker' if winner==0 else 'defender'}

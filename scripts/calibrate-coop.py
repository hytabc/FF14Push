"""Reproducible Lv100 legendary progression, anchored to anonymous supplied-player stats.
Generate config references with seed 20260922; never opens or changes the original database.
"""
import sys,random,json
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.services.game_config import CONFIG
from app.services.item_factory import generate_item,base_attr_range,sub_attr_range,sub_attr_cap,term_range
from app.services.serialization import item_from_generated
from app.services.coop_snapshot import make_snapshot

SEED=20260922

# 参考三维（主属性 119 / 次 71 / 再次 52，合计 242）：与引擎的压力 / 职责检查公式配套，
# 是「合格参考队」的标定输入；改动会打破 test_all_dungeons_reference_can_clear 契约。
REF_ATTRS=('str',119,71,52)

def reference(level,job,seed,quality,crafted=False):
    rng=random.Random(seed);main=CONFIG.job_by_id[job]['mainAttr']
    _,hi,mid,lo=REF_ATTRS
    attrs={'str':mid,'dex':lo,'int':mid};attrs[main]=hi
    others=[a for a in attrs if a!=main];attrs[others[0]]=mid;attrs[others[1]]=lo
    h=SimpleNamespace(id=1,user_id=1,name='参考'+job,level=level,exp=0,talent='mythic',attr_bias=main,
        strength=attrs['str'],agility=attrs['dex'],intellect=attrs['int'],ancient_attr=None,egg_id=None,
        current_region_id=1,region_kill_count=0,is_initial=False,double_reward_charges=0)
    items=[]
    for idx,slot in enumerate(CONFIG.slots):
        candidates=[b for b in CONFIG.base_item_by_id.values() if b.slot in slot['accepts'] and b.level_req<=level and (slot['id']!='mainHand' or b.job_id==job)]
        top=max(b.level_req for b in candidates)
        base=sorted([b for b in candidates if b.level_req==top],key=lambda b:b.id)[0]
        rarity='legendary' if level==100 else 'rare'
        # Reference is a viable build, not a random negative-affix collection.
        for _ in range(1000):
            raw,_=generate_item(base.category,level,rarity=rarity,base_id=base.id,rng=rng,high_quality=False)
            if all(t.get('type')!='debuff' for t in raw['terms']) and (not crafted or len(raw['terms'])>=2):break
        if quality:
            raw['highQuality']=True
            for a in raw['baseAttrs']:a['value']=round(a['value']*CONFIG.recipes['equipment']['highQualityMultiplier'],2)
            if raw['terms']:
                term=raw['terms'][0];lo,hi=term_range(term['id']);term['quality']='ancient';term['value']=round(max(lo,hi)*1.25,2)
        if crafted:
            for a in raw['baseAttrs']:
                lo,hi=base_attr_range(base,rarity,a['attr'],quality);a['value']=round(lo+(hi-lo)*.9,2)
            for a in raw['subAttrs']:
                lo,hi=sub_attr_range(base,rarity,a['attr']);a['value']=round(min(hi,sub_attr_cap(base,rarity,a['attr'])),2);a['quality']='rare'
            for term in raw['terms']:
                lo,hi=term_range(term['id']);term['quality']='ancient';term['value']=round(max(lo,hi)*1.25,2)
        item=SimpleNamespace(id=idx+1,user_id=1,equipped_hero_id=1,equipped_slot=slot['id'],refine_count=20 if crafted else 0,enchant_count=40 if crafted else 0,**item_from_generated(raw,'reference'))
        items.append(item)
    snap=make_snapshot(h,items,['extreme_1','extreme_2','extreme_3','savage_1','savage_2','savage_3'])
    snap['referenceEquipment']=[{'baseId':i.base_id,'rarity':i.rarity,'highQuality':i.high_quality,'baseAttrs':i.base_attrs,'subAttrs':i.sub_attrs,'terms':i.terms} for i in items]
    return snap

if __name__=='__main__':
    path=Path(__file__).resolve().parents[1]/'shared/data/multiplayer.json';cfg=json.loads(path.read_text())
    cfg['references']={tier:{r:reference(level,j,SEED,tier in ('savage','ultimate'),tier=='ultimate') for r,j in [('tank','PLD'),('healer','WHM'),('dps','DRG')]} for tier,level in [('normal_1',20),('normal_2',40),('normal_3',60),('extreme',100),('savage',100),('ultimate',100)]}
    cfg['calibration']={'seed':SEED,'sourceHeroes':45,'sourceLevel100Heroes':1,'sourceCombatItems':3851,'sourceLevel100CombatItems':0,'sourceHQCombatItems':0,'referenceAttributes':[119,71,52],
        'note':'Real snapshot supplies growth/equipment distributions only; Lv100 HQ/crafted tiers are legal forward projections, not observed completion rates. 2026-09 重锚：参考队保持原标定（引擎契约），仅按线上真实能力上界重定准入门槛 gateScale。'}
    for d in cfg['dungeons']:
        tier=d['difficulty'];high=d['seats']==8
        d['minRarity']='legendary' if high else 'common';d['minItemLevel']=100 if high else 1
        d['requiresHighQuality']=tier in ('savage','ultimate');d['minAncientTerms']=2 if tier=='ultimate' else 0
        d['minBaseRoll']=.75 if tier=='ultimate' else 0
        d['gateScale']={'extreme':.78,'savage':.82,'ultimate':.82}.get(tier,.4) if high else .4
        d['trialScale']={'normal':.4,'extreme':.48,'savage':.58,'ultimate':.72}[tier]
        d['pressure']={'autoHpRatio':{'normal':.015,'extreme':.055,'savage':.07,'ultimate':.075}[tier],
            'raidwideHpRatio':{'normal':.07,'extreme':.16,'savage':.21,'ultimate':.225}[tier],
            'raidwideIntervalMs':{'normal':14000,'extreme':11000,'savage':10000,'ultimate':9000}[tier],
            'busterHpRatio':{'normal':.12,'extreme':.32,'savage':.4,'ultimate':.42}[tier]}
        for phase in d['phases']:phase['hpScale']={'normal':70,'extreme':170,'savage':215,'ultimate':230}[tier]
    path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
    print({k:{r:{m:round(s[m]) for m in ('dps','healing','durability')} for r,s in v.items()} for k,v in cfg['references'].items()})

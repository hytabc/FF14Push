"""Immutable loadouts used by registrations, entry checks and the battle worker."""
from dataclasses import asdict
from sqlalchemy import select
from app.models import Hero, Item
from app.models.multiplayer import CoopProgress
from app.services.game_config import CONFIG
from app.services.stats import compute_stats, hero_items, skill_cooldown, skill_damage_multiplier
from app.services.combat_model import theoretical_dps, resolve_job_skills
from app.services.serialization import hero_to_dict
from app.services.multiplayer_config import MULTIPLAYER
from app.services.item_factory import base_attr_range

def make_snapshot(hero, items, clears=(), strategy='assist'):
    equipped = [i for i in hero_items(items, hero.id) if i.equipped_slot and i.category in ('weapon','armor','accessory')]
    stats = compute_stats(hero, equipped)
    job = CONFIG.job_by_id.get(stats.job_id, {})
    role = job.get('role', 'melee')
    role = role if role in ('tank','healer') else 'dps'
    return {'heroId': hero.id, 'ownerId': hero.user_id, 'name': hero.name,
        'level': hero.level, 'role': role, 'jobId': stats.job_id,
        'stats': asdict(stats), 'panel': hero_to_dict(hero, stats),
        'items': [item_snapshot(i,hero.user_id) for i in equipped],
        'skills': [{**s,'teamTarget':MULTIPLAYER.get('teamSkillTargets',{}).get(s['id'],'self'),'cd':skill_cooldown(stats,s['cd'])} for s in resolve_job_skills(stats)],
        'skillMultiplier':skill_damage_multiplier(stats, stats.job_id),
        'dps': theoretical_dps(stats), 'healing': stats.power_attack * .8 + stats.max_hp * .025,
        'durability': stats.max_hp + min(stats.phys_def,stats.magic_def)*5,
        'clears': list(clears), 'strategy':strategy}

def item_snapshot(item,owner_id):
    quality=bool(getattr(item,'high_quality',False));base=CONFIG.base_item_by_id.get(item.base_id)
    rolls=[]
    if base:
        for attr in item.base_attrs:
            lo,hi=base_attr_range(base,item.rarity,attr['attr'],quality)
            if hi>lo:rolls.append(max(0,min(1,(attr['value']-lo)/(hi-lo))))
    return {'id':item.id,'ownerId':owner_id,'slot':item.equipped_slot,'baseId':item.base_id,
        'rarity':item.rarity,'level':item.level_req,'highQuality':quality,
        'ancientTerms':sum(t.get('quality')=='ancient' and t.get('type')=='buff' for t in item.terms or []),
        'baseRoll':min(rolls,default=0)}


async def snapshot_hero(db, hero, strategy='assist'):
    items = (await db.scalars(select(Item).where(Item.user_id == hero.user_id))).all()
    clears = (await db.scalars(select(CoopProgress.dungeon_id).where(CoopProgress.user_id == hero.user_id, CoopProgress.clears > 0))).all()
    return make_snapshot(hero, items, clears, strategy)

def entry_failures(snapshot, dungeon, config):
    errors=[]
    if snapshot['level'] < dungeon['requiredLevel']: errors.append(f"等级不足{dungeon['requiredLevel']}")
    if dungeon['prerequisite'] and dungeon['prerequisite'] not in snapshot['clears']: errors.append('尚未完成前置副本')
    ref=config['references'][dungeon['referenceTier']][snapshot['role']]
    if dungeon['seats']==8:
        slots={i['slot'] for i in snapshot['items']}
        missing=[s['name'] for s in CONFIG.slots if s['id'] not in slots]
        if missing: errors.append('缺少装备：'+ '、'.join(missing))
        for item in snapshot['items']:
            slot=item['slot']
            if item.get('level',0)<dungeon.get('minItemLevel',100):errors.append(f'{slot}：需要100级装备')
            if CONFIG.rarity_order.index(item['rarity'])<CONFIG.rarity_order.index(dungeon.get('minRarity','legendary')):errors.append(f'{slot}：需要传说或更高品阶')
            if dungeon.get('requiresHighQuality') and not item.get('highQuality'):errors.append(f'{slot}：需要高品质装备')
            if item.get('ancientTerms',0)<dungeon.get('minAncientTerms',0):errors.append(f'{slot}：至少2条太古正面词条')
            if item.get('baseRoll',0)+.001<dungeon.get('minBaseRoll',0):errors.append(f'{slot}：基础属性打造需达到合法区间75%')
    metric={'dps':'dps','healer':'healing','tank':'durability'}[snapshot['role']]
    if snapshot[metric] < ref[metric]*dungeon['gateScale']: errors.append('职责能力不足：'+metric)
    if snapshot['stats']['max_hp'] < ref['stats']['max_hp']*dungeon['gateScale']: errors.append('生命不足')
    for attr in ('phys_def','magic_def'):
        if snapshot['stats'][attr]<ref['stats'][attr]*dungeon['gateScale']:errors.append('生存防御不足：'+attr)
    return errors

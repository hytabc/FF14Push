from fastapi import HTTPException
from sqlalchemy import select
from app.models import Hero
from app.models.multiplayer import CoopReward,CoopProgress
from app.services import dohdol_util, titles
from app.services.roster import lock_user
from app.services.progression import apply_exp, catch_up_exp, highest_hero_level
from app.services.item_factory import generate_item
from app.services.grants import grant_generated_items
from app.services.multiplayer_config import MULTIPLAYER

# 「重新打造卡」：远征高难度副本（极/零式/绝）通关产出的堆叠物 id（定义见 consumables.json）。
CARD_ITEM_ID='recraft_card'

def mode_reward_multiplier(mode):
    """通关奖励的模式倍率：在线真人联机（online）额外加成，solo / offline 保持 1.0。"""
    return float((MULTIPLAYER.get('modeRewardMultiplier') or {}).get(mode,1.0))

async def grant_reward(db,user_id,room,battle):
    if battle is None or battle.status!='cleared':raise HTTPException(409,'尚未通关')
    user=await lock_user(db,user_id)
    old=await db.scalar(select(CoopReward).where(CoopReward.battle_id==battle.id,CoopReward.user_id==user_id))
    if old:return old.receipt
    heroes=[h for h in battle.state['heroes'] if h['controllerId']==user_id and not h['registeredClone']]
    if not heroes:raise HTTPException(403,'没有真实参战英雄')
    dungeon=next(d for d in battle.config['dungeons'] if d['id']==room.dungeon_id)
    progress=await db.scalar(select(CoopProgress).where(CoopProgress.user_id==user_id,CoopProgress.dungeon_id==room.dungeon_id))
    first=progress is None or progress.clears==0
    if progress is None:
        progress=CoopProgress(user_id=user_id,dungeon_id=room.dungeon_id,clears=0,records={});db.add(progress)
    reward=dungeon['reward']
    multiplier=mode_reward_multiplier(room.mode)
    base_gold=reward['firstGold' if first else 'repeatGold'];base_exp=reward['firstExp' if first else 'repeatExp']
    gold=int(round(base_gold*multiplier));exp=int(round(base_exp*multiplier))
    user.gold=int(user.gold)+gold
    allocations=[]
    highest_level=await highest_hero_level(db,user_id)
    for i,h in enumerate(sorted(heroes,key=lambda h:h['snapshot']['heroId'])):
        hero=await db.get(Hero,h['snapshot']['heroId'])
        amount=exp//len(heroes)+(1 if i<exp%len(heroes) else 0)
        if hero and hero.user_id==user_id:
            amount=catch_up_exp(hero,amount,highest_level)
            apply_exp(hero,amount)
        allocations.append({'heroId':h['snapshot']['heroId'],'exp':amount})
    items=[]
    for _ in range(reward['chests']):
        raw,_=generate_item('weapon',dungeon['requiredLevel'],box_tier='advanced');items.append(raw)
    grants=await grant_generated_items(db,user,items,'coop') if items else {'items':[]}
    cards=int(round(int(reward.get('cards',0))*multiplier))
    if cards>0:
        await dohdol_util.stack_add(db,user_id,dohdol_util.STACK_CARD,CARD_ITEM_ID,cards)
    progress.clears+=1
    category=room.mode+(':clone' if battle.state['hadClone'] else ':real')
    records=dict(progress.records);records[category]=min(records.get(category,10**12),battle.state['elapsedMs']);progress.records=records
    # 绝境战通关称号：按已通关副本补发（幂等；autoflush 后本次通关已可见）。
    new_titles=await titles.evaluate_coop_titles(db,user_id)
    receipt={'firstClear':first,'goldGained':gold,'baseGold':base_gold,'rewardMultiplier':multiplier,
        'exp':allocations,'grants':grants,'gold':int(user.gold),'recordCategory':category,
        'cards':cards,'newTitles':new_titles}
    db.add(CoopReward(battle_id=battle.id,user_id=user_id,receipt=receipt))
    await db.flush()
    return receipt

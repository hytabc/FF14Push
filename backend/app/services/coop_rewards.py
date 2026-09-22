from fastapi import HTTPException
from sqlalchemy import select
from app.models import Hero
from app.models.multiplayer import CoopReward,CoopProgress
from app.services.roster import lock_user
from app.services.progression import apply_exp
from app.services.item_factory import generate_item
from app.services.grants import grant_generated_items

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
    reward=dungeon['reward'];gold=reward['firstGold' if first else 'repeatGold'];exp=reward['firstExp' if first else 'repeatExp']
    user.gold=int(user.gold)+gold
    allocations=[]
    for i,h in enumerate(sorted(heroes,key=lambda h:h['snapshot']['heroId'])):
        hero=await db.get(Hero,h['snapshot']['heroId'])
        amount=exp//len(heroes)+(1 if i<exp%len(heroes) else 0)
        if hero and hero.user_id==user_id:apply_exp(hero,amount)
        allocations.append({'heroId':h['snapshot']['heroId'],'exp':amount})
    items=[]
    for _ in range(reward['chests']):
        raw,_=generate_item('weapon',dungeon['requiredLevel'],box_tier='advanced');items.append(raw)
    grants=await grant_generated_items(db,user,items,'coop') if items else {'items':[]}
    progress.clears+=1
    category=room.mode+(':clone' if battle.state['hadClone'] else ':real')
    records=dict(progress.records);records[category]=min(records.get(category,10**12),battle.state['elapsedMs']);progress.records=records
    receipt={'firstClear':first,'goldGained':gold,'exp':allocations,'grants':grants,'gold':int(user.gold),'recordCategory':category}
    db.add(CoopReward(battle_id=battle.id,user_id=user_id,receipt=receipt))
    await db.flush()
    return receipt

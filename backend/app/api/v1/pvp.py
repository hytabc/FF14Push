import secrets,time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select,or_
from app.core.deps import CurrentUser,DbSession,guard_rate
from app.models import User
from app.models.multiplayer import HeroRegistration,PvpBattle
from app.services.roster import owned_hero,stop_activities
from app.services.coop_snapshot import snapshot_hero
from app.services.multiplayer_config import MULTIPLAYER
from app.services.pvp_engine import duel

router=APIRouter(prefix='/pvp',tags=['pvp'])
class Challenge(BaseModel):
    heroId:int
    registrationId:int
    key:str=Field(min_length=8,max_length=64)

@router.post('/challenge')
async def challenge(payload:Challenge,db:DbSession,user:CurrentUser):
    old=await db.scalar(select(PvpBattle).where(PvpBattle.attacker_id==user.id,PvpBattle.key==payload.key))
    if old:return {'id':old.id,'report':old.report}
    await guard_rate(db,'pvp',str(user.id),20,60,'挑战过于频繁')
    hero=await owned_hero(db,user.id,payload.heroId)
    reg=await db.scalar(select(HeroRegistration).join(User,User.id==HeroRegistration.user_id).where(HeroRegistration.id==payload.registrationId,
        HeroRegistration.kind=='pvp',HeroRegistration.active.is_(True),User.banned.is_(False)))
    if not reg or reg.user_id==user.id:raise HTTPException(400,'请选择其他玩家的有效防守登记')
    await stop_activities(db,user.id)
    report=duel(await snapshot_hero(db,hero),reg.snapshot,MULTIPLAYER['pvp'],secrets.randbits(32))
    row=PvpBattle(attacker_id=user.id,defender_id=reg.user_id,key=payload.key,report=report,created_at=time.time());db.add(row)
    await db.commit();return {'id':row.id,'report':report}

@router.get('')
async def history(db:DbSession,user:CurrentUser):
    rows=(await db.scalars(select(PvpBattle).where(or_(PvpBattle.attacker_id==user.id,PvpBattle.defender_id==user.id)).order_by(PvpBattle.id.desc()).limit(100))).all()
    return {'battles':[{'id':r.id,'attackerId':r.attacker_id,'defenderId':r.defender_id,'result':r.report['result'],'createdAt':r.created_at} for r in rows]}

@router.get('/{battle_id}')
async def replay(battle_id:int,db:DbSession,user:CurrentUser):
    row=await db.scalar(select(PvpBattle).where(PvpBattle.id==battle_id,or_(PvpBattle.attacker_id==user.id,PvpBattle.defender_id==user.id)))
    if not row:raise HTTPException(404,'战报不存在')
    return {'id':row.id,'report':row.report}

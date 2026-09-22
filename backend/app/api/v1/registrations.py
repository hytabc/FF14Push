from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from app.core.deps import CurrentUser, DbSession
from app.models import User
from app.models.multiplayer import HeroRegistration
from app.services.roster import owned_hero
from app.services.coop_snapshot import snapshot_hero

router=APIRouter(prefix='/registrations',tags=['registrations'])
class Register(BaseModel):
    heroId:int
    kind:Literal['clone','pvp']='clone'
    strategy:Literal['assist','manual']='assist'

@router.get('')
async def listing(db:DbSession,user:CurrentUser,kind:Literal['clone','pvp']='clone'):
    rows=(await db.scalars(select(HeroRegistration).join(User,User.id==HeroRegistration.user_id).where(
        HeroRegistration.kind==kind,HeroRegistration.active.is_(True),User.banned.is_(False)).order_by(HeroRegistration.id.desc()).limit(200))).all()
    return {'registrations':[{'id':r.id,'userId':r.user_id,'kind':r.kind,'snapshot':r.snapshot} for r in rows]}

@router.post('')
async def register(payload:Register,db:DbSession,user:CurrentUser):
    hero=await owned_hero(db,user.id,payload.heroId)
    row=await db.scalar(select(HeroRegistration).where(HeroRegistration.hero_id==hero.id,HeroRegistration.kind==payload.kind))
    snap=await snapshot_hero(db,hero,'assist' if payload.kind=='clone' else payload.strategy)
    if row is None:
        row=HeroRegistration(user_id=user.id,hero_id=hero.id,kind=payload.kind,snapshot=snap);db.add(row)
    else:row.snapshot=snap;row.active=True
    await db.commit()
    return {'id':row.id,'snapshot':snap}

@router.delete('/{registration_id}')
async def withdraw(registration_id:int,db:DbSession,user:CurrentUser):
    row=await db.scalar(select(HeroRegistration).where(HeroRegistration.id==registration_id,HeroRegistration.user_id==user.id))
    if row is None:raise HTTPException(404,'登记不存在')
    row.active=False;await db.commit();return {'ok':True}

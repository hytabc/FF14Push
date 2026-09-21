"""Timed mechanism practice: server chooses cues, verifies order and deadlines."""
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.core.deps import CurrentUser, DbSession
from app.models import MechanismTrial
from app.services.balance import BALANCE

router = APIRouter(prefix='/trial',tags=['trial'])
CUES = [('正面顺劈：移动到侧面','sidestep'),('全屏冲击：展开防御','guard'),('蓄力施法：打断施法','interrupt')]

class Start(BaseModel):
    scope: str
class Respond(BaseModel):
    trialId: int
    step: int = Field(ge=0)
    action: str

def challenge(row):
    return dict(trialId=row.id,step=row.step,cue=CUES[row.challenge][0],
                windowSeconds=BALANCE['trial']['windowSeconds'],passed=row.passed,
                actions=['sidestep','guard','interrupt'])

@router.post('/start')
async def start(payload: Start, db: DbSession, user: CurrentUser):
    valid = {f'region:{r}' for r in BALANCE['regions']} | {f'raid:{r}' for r in BALANCE['raids']}
    if payload.scope not in valid: raise HTTPException(404,'试炼不存在')
    rows=(await db.execute(select(MechanismTrial).where(MechanismTrial.user_id==user.id,MechanismTrial.active.is_(True)))).scalars().all()
    for old in rows: old.active=False
    row=MechanismTrial(user_id=user.id,scope=payload.scope,version=BALANCE['version'],step=0,
                       challenge=secrets.randbelow(len(CUES)),active=True,passed=False,issued_at=datetime.now(timezone.utc))
    db.add(row)
    await db.commit()
    return challenge(row)

@router.post('/respond')
async def respond(payload: Respond, db: DbSession, user: CurrentUser):
    row=(await db.execute(select(MechanismTrial).where(MechanismTrial.id==payload.trialId,
        MechanismTrial.user_id==user.id).with_for_update())).scalar_one_or_none()
    if not row or not row.active or row.version != BALANCE['version']: raise HTTPException(400,'试炼已结束，请重新开始')
    now=datetime.now(timezone.utc)
    issued=row.issued_at.replace(tzinfo=timezone.utc) if row.issued_at.tzinfo is None else row.issued_at
    elapsed=(now-issued).total_seconds()
    ok=(payload.step==row.step and payload.action==CUES[row.challenge][1]
        and BALANCE['trial']['minResponseSeconds'] <= elapsed <= BALANCE['trial']['windowSeconds'])
    if not ok:
        row.active=False
        await db.commit()
        return dict(passed=False,failed=True,message='处理错误或超时，请重新练习')
    row.step+=1
    row.passed=row.step >= BALANCE['trial']['rounds']
    row.active=not row.passed
    row.issued_at=now
    row.challenge=secrets.randbelow(len(CUES))
    await db.commit()
    return challenge(row)

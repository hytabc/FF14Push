"""Run with python -m app.coop_worker. Multiple workers safely share PostgreSQL leases."""
import asyncio,logging,time,uuid
from copy import deepcopy
from sqlalchemy import select,or_
from app.core.database import SessionLocal
from app.models import User
from app.models.multiplayer import CoopRoom,CoopMember,CoopBattle,CoopCommand
from app.services.coop_engine import advance,command,event,fail
from app.services.coop_records import record_clear

log=logging.getLogger('coop-worker')

async def tick_rooms(session_factory=SessionLocal,worker_id='worker',now=None):
    now=time.time() if now is None else now
    async with session_factory() as db:
        # Rooms are always locked before battle rows, matching API lock ordering.
        rooms=(await db.scalars(select(CoopRoom).join(CoopBattle,CoopRoom.id==CoopBattle.room_id).where(
            CoopRoom.status=='running',or_(CoopBattle.lease_until<now,CoopBattle.lease_owner==worker_id))
            .order_by(CoopBattle.updated_at,CoopRoom.id).limit(32).with_for_update(skip_locked=True,of=CoopRoom))).all()
        for room in rooms:
            battle=await db.scalar(select(CoopBattle).where(CoopBattle.room_id==room.id).with_for_update())
            if battle.status!='running':continue
            old_owner=battle.lease_owner
            battle.lease_owner=worker_id;battle.lease_until=now+2
            config=battle.config;dungeon=next(d for d in config['dungeons'] if d['id']==room.dungeon_id)
            state=deepcopy(battle.state)
            members=(await db.scalars(select(CoopMember).where(CoopMember.room_id==room.id))).all()
            ids=[m.user_id for m in members]
            banned=set((await db.scalars(select(User.id).where(User.id.in_(ids),User.banned.is_(True)))).all())
            online={m.user_id for m in members if now-m.heartbeat_at<config['disconnectSeconds'] and m.user_id not in banned}
            for hero in state['heroes']:
                clone=hero['registeredClone'] or hero['controllerId'] not in online
                if clone!=hero['clone']:
                    event(state,'connection',hero['snapshot']['name']+('切换为克隆体' if clone else '恢复在线控制'),slot=hero['slot'])
                hero['clone']=clone
                state['hadClone']=state['hadClone'] or clone
            if online:state['allOfflineSince']=None
            elif state['allOfflineSince'] is None:state['allOfflineSince']=max(m.heartbeat_at for m in members)
            if not online and now-state['allOfflineSince']>=config['abandonSeconds']:fail(state,'所有玩家离线超过60秒')
            commands=(await db.scalars(select(CoopCommand).where(CoopCommand.battle_id==battle.id,CoopCommand.id>battle.command_cursor).order_by(CoopCommand.id))).all()
            for cmd in commands:
                accepted=command(state,cmd.payload,cmd.user_id)
                event(state,'command','指令已执行' if accepted else '指令过期或角色不可操作',commandId=cmd.id,accepted=accepted)
                battle.command_cursor=cmd.id
            # No offline catch-up after worker loss. Normal scheduling keeps fractional time.
            elapsed=max(0,now-battle.updated_at)
            if old_owner not in (None,worker_id) or elapsed>2:elapsed=.1
            ticks=min(10,int((elapsed+1e-7)*10))
            if ticks:advance(state,dungeon,config,ticks*100)
            battle.updated_at=now if elapsed==.1 else battle.updated_at+ticks*.1
            battle.state=state;battle.sequence+=1;battle.status=state['status']
            if state['status']!='running':
                room.status=state['status'];battle.lease_until=0
                # Record the clear in the same transaction; room leaves 'running' so it runs once.
                if state['status']=='cleared':await record_clear(db,room,battle,now)
        await db.commit()
    return len(rooms)

async def main():
    worker_id=str(uuid.uuid4())
    while True:
        started=time.monotonic()
        try:await tick_rooms(worker_id=worker_id)
        except Exception:log.exception('Failed to advance rooms; transaction rolled back')
        await asyncio.sleep(max(.01,.1-(time.monotonic()-started)))

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

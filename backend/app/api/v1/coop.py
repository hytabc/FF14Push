import asyncio,secrets,time
from copy import deepcopy
from typing import Any, Literal
from fastapi import APIRouter,HTTPException,WebSocket,WebSocketDisconnect
from pydantic import BaseModel,Field
from sqlalchemy import select,delete
from app.core.deps import CurrentUser,DbSession
from app.core.database import SessionLocal
from app.models import Hero,User
from app.models.multiplayer import (CoopRoom,CoopMember,CoopSeat,CoopBattle,CoopCommand,CoopReward,CoopProgress,CoopTicket,HeroRegistration)
from app.services.broadcast import MEMBER_CHECK_SECONDS, Producer, ProducerFactory, hub
from app.services.roster import owned_hero,require_idle_team,lock_user,stop_activities
from app.services.coop_snapshot import snapshot_hero
from app.services.coop_rooms import room_member,lobby,invalidate_ready,validate_party,room_view
from app.services.coop_engine import new_battle,command
from app.services.multiplayer_config import DUNGEONS,MULTIPLAYER

router=APIRouter(prefix='/coop',tags=['coop'])
# 房间 WS 轮询间隔与终止状态（与前端 CoopView 的 sequence 去重契约保持一致）。
COOP_POLL_SECONDS=0.5
COOP_TERMINAL_STATUSES=('cleared','failed','closed')
class CreateRoom(BaseModel):
    dungeonId:str
    mode:Literal['solo','offline','online']
    public:bool=True
class Join(BaseModel):
    code:str=Field(min_length=6,max_length=12)
class Seat(BaseModel):
    slot:int=Field(ge=0,le=7)
    controllerId:int
    heroId:int|None=None
    registrationId:int|None=None
    strategy:Literal['assist','manual']='assist'
class Ready(BaseModel):
    ready:bool=True
class Command(BaseModel):
    key:str=Field(min_length=8,max_length=64)
    slots:list[int]=Field(min_length=1,max_length=8)
    action:Literal['target','focus','interrupt','spread','stack','mitigate','swap','rescue','dispel']
    mechanicId:str|None=None
    target:int=Field(default=0,ge=0,le=7)
    value:int=Field(default=0,ge=0,le=7)

@router.get('/dungeons')
async def dungeons(db:DbSession,user:CurrentUser):
    progress=(await db.scalars(select(CoopProgress).where(CoopProgress.user_id==user.id))).all()
    return {'version':MULTIPLAYER['version'],'dungeons':list(DUNGEONS.values()),'progress':[
        {'dungeonId':p.dungeon_id,'clears':p.clears,'records':p.records} for p in progress]}

@router.get('/rooms')
async def rooms(db:DbSession,user:CurrentUser):
    rows=(await db.scalars(select(CoopRoom).where(CoopRoom.public.is_(True),CoopRoom.mode=='online',CoopRoom.status=='lobby').order_by(CoopRoom.id.desc()).limit(100))).all()
    mine=(await db.scalars(select(CoopRoom).join(CoopMember,CoopRoom.id==CoopMember.room_id).where(CoopMember.user_id==user.id).order_by(CoopRoom.id.desc()).limit(30))).all()
    def brief(r):return {'id':r.id,'code':r.code,'dungeonId':r.dungeon_id,'mode':r.mode,'status':r.status}
    return {'rooms':[brief(r) for r in rows],'mine':[brief(r) for r in mine]}

@router.post('/rooms')
async def create(payload:CreateRoom,db:DbSession,user:CurrentUser):
    if payload.dungeonId not in DUNGEONS:raise HTTPException(404,'副本不存在')
    await lock_user(db,user.id);await require_idle_team(db,user.id)
    count=len((await db.scalars(select(CoopRoom.id).where(CoopRoom.owner_id==user.id,CoopRoom.status=='lobby'))).all())
    if count>=5:raise HTTPException(409,'请先关闭闲置房间（最多5个）')
    room=CoopRoom(code=secrets.token_hex(4).upper(),owner_id=user.id,dungeon_id=payload.dungeonId,mode=payload.mode,
        public=payload.public and payload.mode=='online',created_at=time.time())
    db.add(room);await db.flush()
    db.add(CoopMember(room_id=room.id,user_id=user.id,ready=False,heartbeat_at=time.time()))
    await db.commit();return await room_view(db,room,time.time())

@router.post('/rooms/join')
async def join(payload:Join,db:DbSession,user:CurrentUser):
    room=await db.scalar(select(CoopRoom).where(CoopRoom.code==payload.code.upper()).with_for_update())
    if not room:raise HTTPException(404,'房间码不存在')
    lobby(room)
    if room.mode!='online':raise HTTPException(403,'此房间不接受联机加入')
    await lock_user(db,user.id);await require_idle_team(db,user.id)
    members=(await db.scalars(select(CoopMember).where(CoopMember.room_id==room.id))).all()
    if not any(m.user_id==user.id for m in members):
        if len(members)>=DUNGEONS[room.dungeon_id]['seats']:raise HTTPException(409,'房间已满')
        db.add(CoopMember(room_id=room.id,user_id=user.id,ready=False,heartbeat_at=time.time()))
        await invalidate_ready(db,room.id)
    await db.commit();return await room_view(db,room,time.time())

@router.get('/rooms/{room_id}')
async def get_room(room_id:int,db:DbSession,user:CurrentUser):
    room,_=await room_member(db,room_id,user.id)
    return await room_view(db,room,time.time())

@router.post('/rooms/{room_id}/heartbeat')
async def heartbeat(room_id:int,db:DbSession,user:CurrentUser):
    _,member=await room_member(db,room_id,user.id,True);member.heartbeat_at=time.time()
    await db.commit();return {'ok':True}

@router.put('/rooms/{room_id}/seat')
async def seat(room_id:int,payload:Seat,db:DbSession,user:CurrentUser):
    room,_=await room_member(db,room_id,user.id,True);lobby(room)
    if payload.slot>=DUNGEONS[room.dungeon_id]['seats']:raise HTTPException(422,'席位超出队伍容量')
    # Each player selects their own heroes; owner can move already supplied seats via assignment.
    if payload.controllerId!=user.id:raise HTTPException(403,'只能提交自己控制的英雄')
    previous=await db.scalar(select(CoopSeat).where(CoopSeat.room_id==room_id,CoopSeat.slot==payload.slot))
    if previous and previous.controller_id!=user.id:raise HTTPException(409,'席位被其他玩家占用')
    if (payload.heroId is None)==(payload.registrationId is None):raise HTTPException(422,'英雄与克隆登记二选一')
    if payload.registrationId:
        if room.mode!='offline':raise HTTPException(400,'仅离线合作可招募克隆')
        reg=await db.scalar(select(HeroRegistration).join(User,User.id==HeroRegistration.user_id).where(HeroRegistration.id==payload.registrationId,
            HeroRegistration.kind=='clone',HeroRegistration.active.is_(True),User.banned.is_(False)))
        if not reg or reg.user_id==user.id:raise HTTPException(400,'请选择外部有效克隆')
        snapshot=reg.snapshot;hero_id=reg.hero_id
    else:
        hero=await owned_hero(db,user.id,payload.heroId);snapshot=await snapshot_hero(db,hero,payload.strategy);hero_id=hero.id
    if previous is None:
        previous=CoopSeat(room_id=room_id,slot=payload.slot,controller_id=user.id,hero_id=hero_id,snapshot=snapshot);db.add(previous)
    previous.hero_id=hero_id;previous.registration_id=payload.registrationId;previous.snapshot=snapshot
    await invalidate_ready(db,room_id);await db.commit();return await room_view(db,room,time.time())

@router.delete('/rooms/{room_id}/seats/{slot}')
async def remove_seat(room_id:int,slot:int,db:DbSession,user:CurrentUser):
    room,_=await room_member(db,room_id,user.id,True);lobby(room)
    row=await db.scalar(select(CoopSeat).where(CoopSeat.room_id==room_id,CoopSeat.slot==slot))
    if row and (row.controller_id==user.id or room.owner_id==user.id):await db.delete(row)
    elif row:raise HTTPException(403,'不能移除其他玩家的席位')
    await invalidate_ready(db,room_id);await db.commit();return {'ok':True}

@router.post('/rooms/{room_id}/ready')
async def ready(room_id:int,payload:Ready,db:DbSession,user:CurrentUser):
    room,member=await room_member(db,room_id,user.id,True);lobby(room)
    member.ready=payload.ready;member.heartbeat_at=time.time();await db.commit()
    return await room_view(db,room,time.time())

@router.post('/rooms/{room_id}/start')
async def start(room_id:int,db:DbSession,user:CurrentUser):
    room,_=await room_member(db,room_id,user.id,True)
    if room.owner_id!=user.id:raise HTTPException(403,'仅房主可开战')
    if room.status=='running':return await room_view(db,room,time.time())
    lobby(room)
    members=(await db.scalars(select(CoopMember).where(CoopMember.room_id==room_id).order_by(CoopMember.user_id))).all()
    for m in members:
        owner=await lock_user(db,m.user_id)
        if owner.banned:raise HTTPException(403,'队员不可用')
        await require_idle_team(db,m.user_id)
    seats=(await db.scalars(select(CoopSeat).where(CoopSeat.room_id==room_id).order_by(CoopSeat.slot))).all()
    # Refresh real loadouts and validate clone visibility at the final locked boundary.
    for s in seats:
        if s.registration_id:
            reg=await db.scalar(select(HeroRegistration).join(User,User.id==HeroRegistration.user_id).where(HeroRegistration.id==s.registration_id,User.banned.is_(False)))
            if not reg or not reg.active:raise HTTPException(409,'克隆登记已撤回')
            s.snapshot=deepcopy(reg.snapshot)
        else:
            h=await owned_hero(db,s.controller_id,s.hero_id)
            s.snapshot=await snapshot_hero(db,h,s.snapshot['strategy'])
    errors=validate_party(room,seats,members,time.time())
    if errors:raise HTTPException(409,{'rejected':errors})
    for m in members:await stop_activities(db,m.user_id)
    dungeon=DUNGEONS[room.dungeon_id]
    state=new_battle(dungeon,[{'slot':s.slot,'controllerId':s.controller_id,'registrationId':s.registration_id,'snapshot':s.snapshot} for s in seats],room.mode,MULTIPLAYER,secrets.randbits(32))
    db.add(CoopBattle(room_id=room.id,state=state,config=deepcopy(MULTIPLAYER),updated_at=time.time(),lease_until=0))
    room.status='running';await db.commit();return await room_view(db,room,time.time())

@router.post('/rooms/{room_id}/commands')
async def submit(room_id:int,payload:Command,db:DbSession,user:CurrentUser):
    room,member=await room_member(db,room_id,user.id,True)
    battle=await db.scalar(select(CoopBattle).where(CoopBattle.room_id==room_id).with_for_update())
    if not battle or battle.status!='running':raise HTTPException(409,'战斗未进行')
    old=await db.scalar(select(CoopCommand).where(CoopCommand.battle_id==battle.id,CoopCommand.user_id==user.id,CoopCommand.key==payload.key))
    if old:return {'id':old.id,'duplicate':True}
    data=payload.model_dump(exclude={'key'})
    if not command(deepcopy(battle.state),data,user.id):raise HTTPException(409,'指令无效、窗口已关闭或英雄不可控制')
    row=CoopCommand(battle_id=battle.id,user_id=user.id,key=payload.key,payload=data);db.add(row)
    member.heartbeat_at=time.time();await db.commit();return {'id':row.id,'duplicate':False}

@router.post('/rooms/{room_id}/leave')
async def leave(room_id:int,db:DbSession,user:CurrentUser):
    room,member=await room_member(db,room_id,user.id,True)
    if room.status=='running':
        member.heartbeat_at=0
    elif room.owner_id==user.id:room.status='closed'
    else:
        await db.execute(delete(CoopSeat).where(CoopSeat.room_id==room_id,CoopSeat.controller_id==user.id))
        await db.delete(member);await invalidate_ready(db,room_id)
    await db.commit();return {'ok':True}

@router.post('/rooms/{room_id}/claim')
async def claim(room_id:int,db:DbSession,user:CurrentUser):
    from app.services.coop_rewards import grant_reward
    room,_=await room_member(db,room_id,user.id,True)
    battle=await db.scalar(select(CoopBattle).where(CoopBattle.room_id==room_id))
    receipt=await grant_reward(db,user.id,room,battle)
    await db.commit();return receipt

@router.post('/rooms/{room_id}/ticket')
async def ticket(room_id:int,db:DbSession,user:CurrentUser):
    await room_member(db,room_id,user.id)
    await db.execute(delete(CoopTicket).where(CoopTicket.expires_at<time.time()))
    token=secrets.token_urlsafe(32);db.add(CoopTicket(token=token,user_id=user.id,room_id=room_id,expires_at=time.time()+30))
    await db.commit();return {'ticket':token}

def _coop_producer_factory(room_id:int)->ProducerFactory:
    """创建该房间的广播生产者（每个进程按房间只创建一次）。

    原实现每个连接各自每 0.5s 查一次战斗 / 房间，连接数越多负载越高；改为每房间一个
    生产者，读一次后分发给房间内全部连接（见 services/broadcast.py）。
    """
    def factory()->Producer:
        state:dict[str,Any]={'sequence':-1,'event':0,'status':None}
        async def producer()->dict|None:
            async with SessionLocal() as db:
                battle=await db.scalar(select(CoopBattle).where(CoopBattle.room_id==room_id))
                room=await db.get(CoopRoom,room_id)
            if battle is None:return None
            status=room.status if room is not None else 'closed'
            if int(battle.sequence)==state['sequence'] and status==state['status']:return None
            snapshot=deepcopy(battle.state)
            snapshot['events']=[e for e in snapshot.get('events',[]) if e.get('seq',0)>state['event']]
            state['sequence']=int(battle.sequence)
            state['event']=int(battle.state.get('eventSequence',0))
            state['status']=status
            return {'type':'update','sequence':int(battle.sequence),'state':snapshot,'battleId':battle.id,'status':status}
        return producer
    return factory


@router.websocket('/ws')
async def stream(ws:WebSocket):
    token=ws.query_params.get('ticket','')
    async with SessionLocal() as db:
        row=await db.scalar(select(CoopTicket).where(CoopTicket.token==token).with_for_update())
        if not row or row.expires_at<time.time():await ws.close(code=4401);return
        uid,rid=row.user_id,row.room_id
        user=await db.get(User,uid)
        if not user or user.banned:await ws.close(code=4403);return
        await db.delete(row);await db.commit()
    await ws.accept()
    # 先订阅再取快照：之后发布的增量按 sequence 去重，不漏帧（与前端契约一致）。
    queue=await hub.subscribe(f'coop:{rid}',_coop_producer_factory(rid),COOP_POLL_SECONDS)
    sequence=-1;event_sequence=0
    try:
        async with SessionLocal() as db:
            battle=await db.scalar(select(CoopBattle).where(CoopBattle.room_id==rid))
            room=await db.get(CoopRoom,rid)
        if battle is not None:
            await ws.send_json({'type':'snapshot','sequence':int(battle.sequence),'state':deepcopy(battle.state),'battleId':battle.id})
            sequence=int(battle.sequence);event_sequence=int(battle.state.get('eventSequence',0))
        if room is None or room.status in COOP_TERMINAL_STATUSES:
            await ws.close(code=1000);return
        while True:
            try:
                payload=await asyncio.wait_for(queue.get(),timeout=MEMBER_CHECK_SECONDS)
            except asyncio.TimeoutError:
                async with SessionLocal() as db:
                    user=await db.get(User,uid)
                if not user or user.banned:await ws.close(code=4403);return
                continue
            if payload.get('status') in COOP_TERMINAL_STATUSES:
                await ws.close(code=1000);return
            if int(payload['sequence'])<=sequence:continue
            snapshot=payload['state']
            new_events=[e for e in snapshot.get('events',[]) if e.get('seq',0)>event_sequence]
            snapshot['events']=new_events
            if new_events:event_sequence=max(int(e['seq']) for e in new_events)
            await ws.send_json({'type':'update','sequence':int(payload['sequence']),'state':snapshot,'battleId':payload['battleId']})
            sequence=int(payload['sequence'])
    except (WebSocketDisconnect,RuntimeError):return
    finally:
        await hub.unsubscribe(f'coop:{rid}',queue)

from collections import Counter
from fastapi import HTTPException
from sqlalchemy import select,update
from app.models.multiplayer import CoopRoom,CoopMember,CoopSeat,CoopBattle
from app.services.multiplayer_config import DUNGEONS,MULTIPLAYER
from app.services.coop_snapshot import entry_failures

async def room_member(db,room_id,user_id,lock=False):
    stmt=select(CoopRoom).where(CoopRoom.id==room_id)
    if lock:stmt=stmt.with_for_update().execution_options(populate_existing=True)
    room=await db.scalar(stmt)
    member=await db.scalar(select(CoopMember).where(CoopMember.room_id==room_id,CoopMember.user_id==user_id))
    if room is None or member is None:raise HTTPException(404,'房间不存在或无访问权限')
    return room,member

def lobby(room):
    if room.status!='lobby':raise HTTPException(409,'编队已锁定')

async def invalidate_ready(db,room_id):
    await db.execute(update(CoopMember).where(CoopMember.room_id==room_id).values(ready=False))

def validate_party(room,seats,members,now):
    dungeon=DUNGEONS[room.dungeon_id];errors=[];n=len(members)
    member_ids={m.user_id for m in members}
    if any(s.controller_id not in member_ids for s in seats):errors.append('席位控制者不是房间成员')
    if any(not s.registration_id and s.snapshot['ownerId'] != s.controller_id for s in seats):errors.append('英雄不属于席位控制者')
    if len(seats)!=dungeon['seats']:errors.append(f"需要{dungeon['seats']}名英雄")
    if room.mode=='online':
        if not 2<=n<=dungeon['seats']:errors.append('在线合作至少2名玩家')
        counts=Counter(s.controller_id for s in seats)
        if any(counts[m.user_id] not in (dungeon['seats']//n,(dungeon['seats']+n-1)//n) or counts[m.user_id]<1 for m in members):errors.append('各玩家席位必须尽量均分')
        if any(s.registration_id for s in seats):errors.append('在线开战不能使用登记克隆')
    if room.mode=='offline' and (not any(s.registration_id for s in seats) or not any(not s.registration_id for s in seats)):
        errors.append('离线合作需要自有英雄和外部克隆')
    if room.mode=='solo' and any(s.registration_id for s in seats):errors.append('个人挑战仅限自有英雄')
    if any(now-m.heartbeat_at>=15 for m in members):errors.append('有玩家离线')
    if not all(m.ready for m in members):errors.append('所有玩家必须准备')
    seen_heroes=set();seen_items=set();roles=Counter()
    for seat in seats:
        snap=seat.snapshot;key=(snap['ownerId'],snap['heroId']);roles[snap['role']]+=1
        if key in seen_heroes:errors.append('重复来源英雄')
        seen_heroes.add(key)
        for item in snap['items']:
            key=(item['ownerId'],item['id'])
            if key in seen_items:errors.append('重复使用同一件装备（含登记快照）')
            seen_items.add(key)
        errors.extend(f'席位{seat.slot+1}：{e}' for e in entry_failures(snap,dungeon,MULTIPLAYER))
    if dungeon['seats']==8 and roles!={'tank':2,'healer':2,'dps':4}:errors.append('阵容必须为2坦克、2治疗、4输出')
    return errors

async def room_view(db,room,now):
    members=(await db.scalars(select(CoopMember).where(CoopMember.room_id==room.id).order_by(CoopMember.id))).all()
    seats=(await db.scalars(select(CoopSeat).where(CoopSeat.room_id==room.id).order_by(CoopSeat.slot))).all()
    battle=await db.scalar(select(CoopBattle).where(CoopBattle.room_id==room.id))
    return {'id':room.id,'code':room.code,'ownerId':room.owner_id,'mode':room.mode,'status':room.status,
        'dungeon':DUNGEONS[room.dungeon_id],
        'members':[{'userId':m.user_id,'ready':m.ready,'online':now-m.heartbeat_at<15} for m in members],
        'seats':[{'slot':s.slot,'controllerId':s.controller_id,'heroId':s.hero_id,'registrationId':s.registration_id,'snapshot':s.snapshot} for s in seats],
        'entryFailures':validate_party(room,seats,members,now) if room.status=='lobby' else [],
        'battle':{'id':battle.id,'sequence':battle.sequence,'state':battle.state} if battle else None}

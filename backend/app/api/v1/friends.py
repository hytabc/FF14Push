"""好友系统接口：好友码、好友列表 / 申请、在线心跳与金币转账。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.deps import CurrentUser, DbSession, client_ip, guard_rate
from app.models.base import utcnow
from app.schemas.game import FriendByCodeRequest, FriendTargetRequest, FriendTransferRequest
from app.services import devices, friends

router = APIRouter(prefix="/friends", tags=["friends"])


@router.get("")
async def overview(db: DbSession, user: CurrentUser) -> dict:
    """好友概览：好友码、在线状态、待处理申请与转账配置 / 今日额度。"""
    return await friends.overview_payload(db, user)


@router.get("/heartbeat")
async def heartbeat(request: Request, db: DbSession, user: CurrentUser) -> dict:
    """在线心跳：用 GET 以免触发写锁（远征中同样保持在线）。"""
    user.last_seen_at = utcnow()
    # 反多开：心跳顺带刷新最近 IP 与设备登记（数据源，不触发任何拦截）。
    user.last_ip = client_ip(request)
    await devices.record_device(
        db, user.id, devices.device_id_from_request(request), user.last_ip
    )
    await db.commit()
    return {
        "serverTime": utcnow().isoformat(),
        "heartbeatSeconds": friends.HEARTBEAT_SECONDS,
        "onlineSeconds": friends.ONLINE_SECONDS,
    }


@router.post("/request")
async def request_friend(payload: FriendByCodeRequest, db: DbSession, user: CurrentUser) -> dict:
    await guard_rate(db, "friend_request", str(user.id), 20, 60, "好友申请过于频繁，请稍后再试")
    return await friends.request_friend(db, user, payload.code)


@router.post("/accept")
async def accept(payload: FriendTargetRequest, db: DbSession, user: CurrentUser) -> dict:
    return await friends.accept_request(db, user, payload.userId)


@router.post("/reject")
async def reject(payload: FriendTargetRequest, db: DbSession, user: CurrentUser) -> dict:
    return await friends.reject_request(db, user, payload.userId)


@router.post("/remove")
async def remove(payload: FriendTargetRequest, db: DbSession, user: CurrentUser) -> dict:
    return await friends.remove_friend(db, user, payload.userId)


@router.post("/transfer")
async def transfer(
    payload: FriendTransferRequest, request: Request, db: DbSession, user: CurrentUser
) -> dict:
    await guard_rate(db, "friend_transfer", str(user.id), 30, 60, "转账过于频繁，请稍后再试")
    return await friends.transfer_gold(db, user, payload.userId, payload.amount, client_ip(request))

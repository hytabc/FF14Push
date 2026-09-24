"""好友系统接口：好友码、好友列表 / 申请、在线心跳与金币转账。"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

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
async def heartbeat(request: Request, response: Response, db: DbSession, user: CurrentUser) -> dict:
    """在线心跳：用 GET 以免触发写锁（远征中同样保持在线）。"""
    user.last_seen_at = utcnow()
    # 反多开：心跳顺带刷新最近 IP、设备登记与「最近在线时间」（关联判定与并发动线的数据源）。
    user.last_ip = client_ip(request)
    device_ids = devices.device_ids_from_request(request)
    await devices.record_device(db, user.id, device_ids, user.last_ip)
    # 并发动线：按心跳窗口重算资格；超限则暂停本账号的写请求。心跳本身始终放行，
    # 其他账号离线后本账号会在此自动恢复（响应回带 blocked 供前端暂停 / 恢复循环）。
    allowed = await devices.enforce_online_limit(db, user, device_ids)
    await db.commit()
    devices.issue_device_cookie(response, devices.header_device_id(request))
    return {
        "serverTime": utcnow().isoformat(),
        "heartbeatSeconds": friends.HEARTBEAT_SECONDS,
        "onlineSeconds": friends.ONLINE_SECONDS,
        "blocked": not allowed,
        "maxOnline": devices.max_online_per_device(),
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

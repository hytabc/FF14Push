"""好友系统业务：好友码、在线状态、好友关系与金币转账。

口径对齐市场交易（`services/market.py`）：手续费 `floor(amount × feePct)` 直接销毁回收，
因此转账不构成刷金币来源。转账为服务端权威：双行锁按 id 升序获取，避免 A→B / B→A 并发死锁。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CoinTransfer, Friendship, Hero, User
from app.models.base import utcnow
from app.models.friends import STATUS_ACCEPTED, STATUS_PENDING
from app.services import devices
from app.services.game_config import CONFIG
from app.services.roster import lock_user

# 前端心跳间隔与在线判定阈值（秒）：超过阈值未心跳即视为离线。
HEARTBEAT_SECONDS = 20
ONLINE_SECONDS = 45

# 好友码：8 位易读字符（排除 0/O/1/I/L）
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8
_CODE_ATTEMPTS = 20


# ------------------------------------------------------------------ 配置
def _cfg() -> dict[str, Any]:
    return CONFIG.economy["transfer"]


def fee_pct() -> float:
    return float(_cfg()["feePct"])


def fee_of(amount: int) -> int:
    """手续费（金币回收），向下取整。"""
    return max(0, int(int(amount) * fee_pct()))


def net_of(amount: int) -> int:
    return int(amount) - fee_of(amount)


def min_amount() -> int:
    return int(_cfg()["minAmount"])


def max_amount() -> int:
    return int(_cfg()["maxAmount"])


def daily_limit() -> int:
    return int(_cfg()["dailyLimit"])


# ------------------------------------------------------------------ 好友码
def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite 下 DateTime(timezone=True) 会返回 naive datetime，统一补上 UTC。"""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _code_exists(db: AsyncSession, code: str) -> bool:
    row = (await db.execute(select(User.id).where(User.friend_code == code).limit(1))).scalar_one_or_none()
    return row is not None


async def generate_friend_code(db: AsyncSession) -> str:
    for _ in range(_CODE_ATTEMPTS):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
        if not await _code_exists(db, code):
            return code
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="好友码生成失败，请稍后再试")


async def ensure_friend_code(db: AsyncSession, user: User) -> str:
    """旧数据兜底：无好友码时惰性生成。"""
    if not user.friend_code:
        user.friend_code = await generate_friend_code(db)
        await db.flush()
    return user.friend_code


# ------------------------------------------------------------------ 在线状态
def is_online(user: User, now: datetime | None = None) -> bool:
    last = _as_utc(user.last_seen_at)
    if last is None:
        return False
    return ((now or utcnow()) - last) < timedelta(seconds=ONLINE_SECONDS)


def _last_seen_seconds(user: User, now: datetime | None = None) -> int | None:
    last = _as_utc(user.last_seen_at)
    if last is None:
        return None
    return max(0, int(((now or utcnow()) - last).total_seconds()))


# ------------------------------------------------------------------ 好友关系
async def _find_friendship(db: AsyncSession, a: int, b: int) -> Friendship | None:
    return (
        await db.execute(
            select(Friendship)
            .where(
                or_(
                    (Friendship.requester_id == a) & (Friendship.addressee_id == b),
                    (Friendship.requester_id == b) & (Friendship.addressee_id == a),
                )
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def are_friends(db: AsyncSession, a: int, b: int) -> bool:
    row = await _find_friendship(db, a, b)
    return row is not None and row.status == STATUS_ACCEPTED


async def request_friend(db: AsyncSession, user: User, code: str) -> dict[str, Any]:
    normalized = (code or "").strip().upper()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请输入好友码")

    target = (await db.execute(select(User).where(User.friend_code == normalized))).scalar_one_or_none()
    if target is None or target.banned:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="好友码不存在")
    if target.id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能添加自己为好友")

    existing = await _find_friendship(db, user.id, target.id)
    if existing is not None:
        if existing.status == STATUS_ACCEPTED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="你们已经是好友")
        if existing.requester_id == target.id:
            # 对方此前已申请我 → 视为同意
            existing.status = STATUS_ACCEPTED
            existing.accepted_at = utcnow()
            await db.commit()
            return {"status": STATUS_ACCEPTED, "message": f"已成为好友：{target.nickname}"}
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="好友申请已发送，请等待对方同意")

    db.add(Friendship(requester_id=user.id, addressee_id=target.id, status=STATUS_PENDING))
    await db.commit()
    return {"status": STATUS_PENDING, "message": f"已向 {target.nickname} 发送好友申请"}


async def _pending_incoming(db: AsyncSession, user: User, other_id: int) -> Friendship:
    row = (
        await db.execute(
            select(Friendship).where(
                Friendship.requester_id == other_id,
                Friendship.addressee_id == user.id,
                Friendship.status == STATUS_PENDING,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有来自该玩家的好友申请")
    return row


async def accept_request(db: AsyncSession, user: User, other_id: int) -> dict[str, Any]:
    row = await _pending_incoming(db, user, other_id)
    row.status = STATUS_ACCEPTED
    row.accepted_at = utcnow()
    await db.commit()
    other = await db.get(User, other_id)
    return {"status": STATUS_ACCEPTED, "message": f"已同意 {(other.nickname if other else '')} 的好友申请"}


async def reject_request(db: AsyncSession, user: User, other_id: int) -> dict[str, Any]:
    row = await _pending_incoming(db, user, other_id)
    await db.delete(row)
    await db.commit()
    return {"status": "rejected", "message": "已拒绝好友申请"}


async def remove_friend(db: AsyncSession, user: User, other_id: int) -> dict[str, Any]:
    """删除好友；若存在未处理的申请（含自己发出的），一并撤销。"""
    row = await _find_friendship(db, user.id, other_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="你们不是好友")
    await db.delete(row)
    await db.commit()
    return {"status": "removed", "message": "已移除"}


# ------------------------------------------------------------------ 概览
async def _levels_for(db: AsyncSession, ids: set[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(User.id, Hero.level)
            .join(Hero, Hero.id == User.active_hero_id)
            .where(User.id.in_(ids))
        )
    ).all()
    return {user_id: int(level) for user_id, level in rows}


def _entry(user: User, level: int | None, now: datetime) -> dict[str, Any]:
    return {
        "userId": user.id,
        "nickname": user.nickname,
        "username": user.username,
        "online": is_online(user, now),
        "lastSeenSecondsAgo": _last_seen_seconds(user, now),
        "level": level,
    }


async def friends_overview(db: AsyncSession, user: User) -> dict[str, Any]:
    now = utcnow()
    rows = (
        await db.execute(
            select(Friendship).where(
                or_(Friendship.requester_id == user.id, Friendship.addressee_id == user.id)
            )
        )
    ).scalars().all()

    accepted_ids: set[int] = set()
    pending_direction: dict[int, str] = {}
    for row in rows:
        other_id = row.addressee_id if row.requester_id == user.id else row.requester_id
        if row.status == STATUS_ACCEPTED:
            accepted_ids.add(other_id)
        else:
            pending_direction[other_id] = "outgoing" if row.requester_id == user.id else "incoming"

    involved = accepted_ids | set(pending_direction)
    others: dict[int, User] = {}
    if involved:
        found = (await db.execute(select(User).where(User.id.in_(involved)))).scalars().all()
        others = {u.id: u for u in found}
    levels = await _levels_for(db, accepted_ids)

    friends: list[dict[str, Any]] = []
    for other_id in accepted_ids:
        other = others.get(other_id)
        if other is None or other.banned:
            continue
        friends.append(_entry(other, levels.get(other_id), now))
    # 在线优先，其次等级高者优先
    friends.sort(key=lambda f: (not f["online"], -(f["level"] or 0), f["nickname"]))

    incoming: list[dict[str, Any]] = []
    outgoing: list[dict[str, Any]] = []
    for other_id, direction in pending_direction.items():
        other = others.get(other_id)
        if other is None or other.banned:
            continue
        entry = _entry(other, levels.get(other_id), now)
        (outgoing if direction == "outgoing" else incoming).append(entry)

    return {"friends": friends, "incoming": incoming, "outgoing": outgoing}


async def spent_today(db: AsyncSession, user_id: int) -> int:
    since = utcnow() - timedelta(hours=24)
    total = (
        await db.execute(
            select(func.coalesce(func.sum(CoinTransfer.amount), 0)).where(
                CoinTransfer.from_user_id == user_id,
                CoinTransfer.created_at >= since,
            )
        )
    ).scalar_one()
    return int(total or 0)


async def remaining_today(db: AsyncSession, user_id: int) -> int:
    return max(0, daily_limit() - await spent_today(db, user_id))


async def spent_between(db: AsyncSession, a: int, b: int) -> int:
    """两个账号之间最近 24 小时的双向转账总额（按 amount 计）。

    反多开：关联账号（同设备 / 同 IP）的转账额度按 pair 双向累计，抑制 A→B→A 往返洗钱。
    """
    since = utcnow() - timedelta(hours=24)
    total = (
        await db.execute(
            select(func.coalesce(func.sum(CoinTransfer.amount), 0)).where(
                CoinTransfer.created_at >= since,
                or_(
                    (CoinTransfer.from_user_id == a) & (CoinTransfer.to_user_id == b),
                    (CoinTransfer.from_user_id == b) & (CoinTransfer.to_user_id == a),
                ),
            )
        )
    ).scalar_one()
    return int(total or 0)


async def overview_payload(db: AsyncSession, user: User) -> dict[str, Any]:
    """`GET /friends` 的完整响应：刷新自己在线状态后返回好友 / 申请与转账配置。"""
    await ensure_friend_code(db, user)
    user.last_seen_at = utcnow()
    await db.commit()
    data = await friends_overview(db, user)
    return {
        "friendCode": user.friend_code,
        "feePct": fee_pct(),
        "minAmount": min_amount(),
        "maxAmount": max_amount(),
        "dailyLimit": daily_limit(),
        "remainingToday": await remaining_today(db, user.id),
        **data,
    }


# ------------------------------------------------------------------ 转账
async def transfer_gold(
    db: AsyncSession, sender: User, recipient_id: int, amount: int, ip: str | None
) -> dict[str, Any]:
    if recipient_id == sender.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能给自己转账")
    if amount < min_amount():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"单笔转账不能少于 {min_amount()} 金币"
        )
    if amount > max_amount():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"单笔转账不能超过 {max_amount()} 金币"
        )

    # 双行锁按 id 升序获取，避免 A→B / B→A 并发死锁
    first_id, second_id = sorted((sender.id, recipient_id))
    await lock_user(db, first_id)
    await lock_user(db, second_id)

    recipient = (await db.execute(select(User).where(User.id == recipient_id))).scalar_one_or_none()
    if recipient is None or recipient.banned:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对方不存在或不可转账")
    if not await are_friends(db, sender.id, recipient.id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能给好友转账")

    if int(sender.gold) < amount:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="金币不足")
    remaining = await remaining_today(db, sender.id)
    if amount > remaining:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"超出今日转账额度，今日剩余 {remaining} 金币"
        )

    # 反多开：同设备 / 同 IP 的关联账号之间，转账额度按 pair 双向累计下调。
    if await devices.are_linked(db, sender.id, recipient.id):
        cap = devices.linked_transfer_daily_limit()
        pair_spent = await spent_between(db, sender.id, recipient.id)
        if pair_spent + amount > cap:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"关联账号（同设备 / 同 IP）之间每日转账额度为 {cap} 金币",
            )

    fee = fee_of(amount)
    net = amount - fee
    sender.gold = int(sender.gold) - amount
    recipient.gold = int(recipient.gold) + net

    db.add(
        CoinTransfer(
            from_user_id=sender.id,
            to_user_id=recipient.id,
            amount=amount,
            fee=fee,
            net=net,
            from_ip=ip,
            to_ip=recipient.last_ip,
        )
    )
    await db.commit()
    return {
        "gold": int(sender.gold),
        "amount": amount,
        "fee": fee,
        "net": net,
        "recipientNickname": recipient.nickname,
        "remainingToday": await remaining_today(db, sender.id),
    }

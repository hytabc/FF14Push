"""兑换码：码与奖励金币来自环境变量，每个用户对同一码至多兑换一次。"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession, client_ip, guard_rate
from app.models import RedeemRecord
from app.schemas.game import RedeemRequest

router = APIRouter(prefix="/redeem", tags=["redeem"])


def _configured() -> tuple[str, int]:
    """返回 (兑换码, 金币)。码为空或金币非正数即视为未开启。

    每次调用都重新取配置（get_settings 有缓存），便于测试与配置热更新。
    """
    settings = get_settings()
    code = settings.redeem_code.strip()
    gold = int(settings.redeem_gold)
    if not code or gold <= 0:
        return "", 0
    return code, gold


@router.get("")
async def redeem_state(db: DbSession, user: CurrentUser) -> dict:
    """兑换功能状态。只下发「能否兑换」与奖励数额，绝不下发兑换码本身。"""
    code, gold = _configured()
    if not code:
        return {"enabled": False, "canRedeem": False, "rewardGold": 0}

    used = (
        await db.execute(
            select(RedeemRecord).where(RedeemRecord.user_id == user.id, RedeemRecord.code == code)
        )
    ).scalar_one_or_none() is not None
    return {"enabled": True, "canRedeem": not used, "rewardGold": gold}


@router.post("")
async def redeem(payload: RedeemRequest, db: DbSession, user: CurrentUser, request: Request) -> dict:
    code, gold = _configured()
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="兑换码功能未开启")

    # 奖励数额一律取自服务端配置，请求体只有 code；客户端改前端数字不影响实际发放。
    # 这里再限制同一 IP 的尝试频率，避免脚本撞码。
    limits = get_settings()
    ip = client_ip(request)
    await guard_rate(
        db,
        "redeem_ip_hour",
        ip,
        limits.redeem_per_ip_per_hour,
        3600,
        detail="兑换尝试过于频繁，请稍后再试",
    )

    submitted = payload.code.strip()
    if not secrets.compare_digest(submitted.encode("utf-8"), code.encode("utf-8")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="兑换码无效")

    used = (
        await db.execute(
            select(RedeemRecord).where(RedeemRecord.user_id == user.id, RedeemRecord.code == code)
        )
    ).scalar_one_or_none()
    if used is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该兑换码你已经兑换过了")

    # 防多开刷码：同一 IP 下能兑换同一码的账号数有上限（默认 5），
    # 因此「注册小号 → 重复兑换」无法换来无上限金币。
    if limits.redeem_accounts_per_ip > 0:
        same_ip = (
            await db.execute(
                select(func.count())
                .select_from(RedeemRecord)
                .where(RedeemRecord.code == code, RedeemRecord.ip == ip)
            )
        ).scalar_one()
        if int(same_ip) >= limits.redeem_accounts_per_ip:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="该兑换码的兑换次数已达上限")

    user.gold = int(user.gold) + gold
    db.add(RedeemRecord(user_id=user.id, code=code, gold=gold, ip=ip))
    try:
        await db.commit()
    except IntegrityError:
        # 并发重复提交：唯一约束兜底
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该兑换码你已经兑换过了") from None

    return {
        "ok": True,
        "gold": int(user.gold),
        "goldGained": gold,
        "message": f"兑换成功，获得 {gold} 金币",
    }

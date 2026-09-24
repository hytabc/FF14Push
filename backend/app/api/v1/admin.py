"""管理员接口：协助用户找回密码、封禁账号、查看在线玩家。账号来自环境变量，见 `services/admin.py`。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.core.deps import CurrentUser, DbSession
from app.core.security import hash_password
from app.models import Hero, User
from app.models.base import utcnow
from app.schemas.game import AdminBanRequest, AdminResetPasswordRequest
from app.services.admin import admin_enabled, is_admin
from app.services.admin_monitor import online_overview

router = APIRouter(prefix="/admin", tags=["admin"])

MAX_RESULTS = 50


async def require_admin(user: CurrentUser) -> User:
    if not admin_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="管理员功能未启用")
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


AdminUser = Depends(require_admin)


@router.get("/users")
async def list_users(
    db: DbSession,
    _: User = AdminUser,
    query: str = Query(default="", max_length=64),
    limit: int = Query(default=20, ge=1, le=MAX_RESULTS),
) -> dict:
    """按账号或昵称搜索用户（供改密前定位）。"""
    stmt = select(User, Hero.level).outerjoin(Hero, Hero.id == User.active_hero_id)
    keyword = query.strip()
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.nickname.ilike(like)))
    rows = (await db.execute(stmt.order_by(User.id).limit(limit))).all()

    return {
        "users": [
            {
                "id": user.id,
                "username": user.username,
                "nickname": user.nickname,
                "gold": int(user.gold),
                "level": level,
                "hasHero": level is not None,
                "isAdmin": is_admin(user),
                "banned": bool(user.banned),
            }
            for user, level in rows
        ]
    }


@router.post("/reset-password")
async def reset_password(
    payload: AdminResetPasswordRequest,
    db: DbSession,
    _: User = AdminUser,
) -> dict:
    """重置指定用户的登录密码（用于用户忘记密码）。"""
    target = (
        await db.execute(select(User).where(User.id == payload.userId))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if is_admin(target):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="管理员密码由环境变量管理，不能通过此接口修改",
        )

    target.password_hash = hash_password(payload.newPassword)
    await db.commit()
    return {"ok": True, "message": f"已重置「{target.username}」的密码"}


@router.post("/ban")
async def set_ban(payload: AdminBanRequest, db: DbSession, _: User = AdminUser) -> dict:
    """封禁 / 解封指定账号。

    封禁后：登录被拒绝、已登录的令牌在下一次请求即被拒（强制下线）、不参与排行榜。
    对外只回传机器码，不返回任何封禁文案，避免被封用户反推。
    """
    target = (await db.execute(select(User).where(User.id == payload.userId))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if is_admin(target):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能封禁管理员账号",
        )

    target.banned = payload.banned
    target.banned_at = utcnow() if payload.banned else None
    await db.commit()
    return {
        "ok": True,
        "banned": payload.banned,
        "message": f"已{'封禁' if payload.banned else '解封'}「{target.username}」",
    }


@router.get("/online")
async def online_players(db: DbSession, _: User = AdminUser) -> dict:
    """当前在线玩家列表 + 按设备 / IP 的关联分组（反多开排查）。只读。"""
    return await online_overview(db)

"""管理员接口：协助用户找回密码。账号来自环境变量，见 `services/admin.py`。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.core.deps import CurrentUser, DbSession
from app.core.security import hash_password
from app.models import Hero, User
from app.schemas.game import AdminResetPasswordRequest
from app.services.admin import admin_enabled, is_admin

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
    stmt = select(User, Hero.level).outerjoin(Hero, Hero.user_id == User.id)
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

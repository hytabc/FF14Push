"""认证：注册 / 登录 / 当前用户。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.security import BANNED_DETAIL, create_access_token, hash_password, verify_password
from app.models import (
    AutoSellSetting,
    Hero,
    Item,
    RegionProgress,
    TavernState,
    TutorialProgress,
    User,
)
from app.schemas.game import ChangePasswordRequest, LoginRequest, RegisterRequest, TokenResponse
from app.services.admin import admin_username, is_admin
from app.services.codex import unlock_equipment, unlock_terms
from app.services.game_config import CONFIG
from app.services.item_factory import generate_item
from app.services.recruiting import generate_candidates, initial_hero
from app.services.serialization import item_from_generated

router = APIRouter(prefix="/auth", tags=["auth"])

# 昵称是唯一由玩家自由填写、且会展示给他人（排行榜 / 页头 / 管理页）的文本。
# 前端一律用插值渲染（自动转义，无 v-html），这里再去掉尖括号与控制字符做纵深防御，
# 防止将来误用 v-html 时形成存储型 XSS。
_NICKNAME_FORBIDDEN = frozenset("<>")


def sanitize_nickname(raw: str) -> str:
    cleaned = "".join(ch for ch in raw if ch.isprintable() and ch not in _NICKNAME_FORBIDDEN)
    return cleaned.strip()


async def _bootstrap_new_user(db: DbSession, user: User) -> Hero:
    """新账号初始化：初始英雄 + 地区进度 + 新手指引 + 酒馆候选。"""
    preset = initial_hero()
    hero = Hero(
        user_id=user.id,
        name=preset["name"],
        level=1,
        exp=0,
        talent=preset["talent"],
        attr_bias=preset["attrBias"],
        strength=preset["strength"],
        agility=preset["agility"],
        intellect=preset["intellect"],
        current_region_id=1,
        region_kill_count=0,
        is_initial=True,
    )
    db.add(hero)

    for region in CONFIG.regions["regions"]:
        db.add(
            RegionProgress(
                user_id=user.id,
                region_id=region["id"],
                unlocked=region["id"] == 1,
                cleared=False,
            )
        )

    db.add(TutorialProgress(user_id=user.id, current_step=1))
    tavern_candidates, tavern_pity = generate_candidates(1, 1)
    db.add(TavernState(user_id=user.id, candidate=tavern_candidates[0], ancient_pity=tavern_pity))
    db.add(
        AutoSellSetting(
            user_id=user.id,
            enabled=False,
            rarities=list(CONFIG.economy["sell"]["autoSellRarities"]),
        )
    )

    # 起始武器：重锚定后裸英雄无法完成地区 1 的击杀要求，开局直接给一把铁制长剑并装备。
    starter_id = CONFIG.heroes["initialHero"].get("starterWeapon")
    starter_base = CONFIG.base_item_by_id.get(starter_id) if starter_id else None
    starter_item: Item | None = None
    if starter_base is not None:
        generated, _ = generate_item(starter_base.category, 1, rarity="common", base_id=starter_id)
        starter_item = Item(
            user_id=user.id,
            **item_from_generated(generated, "starter"),
            equipped_slot="mainHand",
        )
        db.add(starter_item)

    await db.flush()
    if starter_item is not None:
        await unlock_equipment(db, user.id, starter_item)
        await unlock_terms(db, user.id, starter_item.terms or [])
    return hero


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DbSession) -> TokenResponse:
    # 管理员账号名保留，避免被普通玩家占用（否则启动同步会与之冲突）
    if payload.username.strip() == admin_username():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该用户名为保留的管理员账号")

    exists = (await db.execute(select(User).where(User.username == payload.username))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已被占用")

    nickname = sanitize_nickname(payload.nickname) if payload.nickname else ""
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        nickname=nickname or payload.username,
        gold=0,
    )
    db.add(user)
    await db.flush()
    await _bootstrap_new_user(db, user)
    await db.commit()
    return TokenResponse(accessToken=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = (await db.execute(select(User).where(User.username == payload.username))).scalar_one_or_none()
    # 先校验账号密码：密码错误与否都返回同一提示，不暴露账号是否存在。
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    # 封号：拒绝发放令牌，只回传机器码（前端静默拦截，不渲染提示）。
    if user.banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=BANNED_DETAIL)
    return TokenResponse(accessToken=create_access_token(user.id))


@router.post("/change-password")
async def change_password(payload: ChangePasswordRequest, db: DbSession, user: CurrentUser) -> dict:
    """玩家自助修改密码：需验证当前密码；管理员密码由环境变量托管，不可通过此接口修改。"""
    if is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="管理员密码由环境变量管理，不能通过此接口修改",
        )
    if not verify_password(payload.currentPassword, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码错误")
    if payload.newPassword != payload.confirmPassword:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="两次输入的新密码不一致")

    user.password_hash = hash_password(payload.newPassword)
    await db.commit()
    return {"ok": True, "message": "密码已修改"}


@router.get("/me")
async def me(user: CurrentUser, db: DbSession) -> dict:
    hero = (await db.execute(select(Hero).where(Hero.user_id == user.id))).scalar_one_or_none()
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "gold": int(user.gold),
        "hasHero": hero is not None,
        "isAdmin": is_admin(user),
    }

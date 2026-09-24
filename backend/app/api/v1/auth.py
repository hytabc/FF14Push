"""认证：注册 / 登录 / 当前用户。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession, client_ip, guard_rate
from app.core.security import BANNED_DETAIL, create_access_token, hash_password, verify_password
from app.models import (
    AutoSellSetting,
    DohDolProgress,
    Hero,
    Item,
    RegionProgress,
    RankingEntry,
    TavernState,
    TutorialProgress,
    User,
)
from app.schemas.game import ChangeNicknameRequest, ChangePasswordRequest, LoginRequest, RegisterRequest, TokenResponse
from app.services import devices
from app.services.admin import admin_username, is_admin
from app.services.codex import unlock_equipment, unlock_terms
from app.services.friends import ensure_friend_code, generate_friend_code
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
    await db.flush()
    user.active_hero_id = hero.id

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
    # 生产 / 采集等级：新账号从 1 级开始
    db.add(DohDolProgress(user_id=user.id, kind="doh", level=1, exp=0))
    db.add(DohDolProgress(user_id=user.id, kind="dol", level=1, exp=0))
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
            equipped_hero_id=hero.id,
        )
        db.add(starter_item)

    await db.flush()
    if starter_item is not None:
        await unlock_equipment(db, user.id, starter_item)
        await unlock_terms(db, user.id, starter_item.terms or [])
    return hero


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, db: DbSession, request: Request, response: Response
) -> TokenResponse:
    # 防多开：限制同一 IP 的建号频率与总量（每个新号都会立即获得可挂机的初始英雄）。
    limits = get_settings()
    ip = client_ip(request)
    await guard_rate(db, "register_ip_hour", ip, limits.register_per_ip_per_hour, 3600)
    await guard_rate(db, "register_ip_day", ip, limits.register_per_ip_per_day, 86400)

    # 反多开：同一设备最多注册 N 个账号（1 大号 + 1 小号）。设备标识取「前端指纹请求头 ∪
    # 服务端签发的设备 Cookie」，因此清 localStorage 换新指纹也绕不过该上限。
    # 两者皆缺时不启用该上限（脚本 / 老客户端不误伤）。
    device_ids = devices.device_ids_from_request(request)
    if len(await devices.accounts_on_device(db, device_ids)) >= devices.max_accounts_per_device():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"同一设备最多注册 {devices.max_accounts_per_device()} 个账号（1 个大号 + 1 个小号）",
        )
    # 反多开：同一真实 IP 的注册上限，堵「清缓存换指纹」绕过设备上限。
    ip_cap = devices.max_accounts_per_ip()
    if ip_cap > 0 and devices.is_real_ip(ip) and len(await devices.accounts_on_ip(db, ip)) >= ip_cap:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"同一网络最多注册 {ip_cap} 个账号",
        )

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
        friend_code=await generate_friend_code(db),
    )
    db.add(user)
    await db.flush()
    # 反多开：记录注册设备与 IP（关联账号判定的数据源）。
    user.reg_ip = ip
    user.last_ip = ip
    await devices.record_device(db, user.id, device_ids, ip)
    await _bootstrap_new_user(db, user)
    await db.commit()
    # 反多开：把前端指纹写入服务端签名的 Cookie（后续请求优先采信它，清 localStorage 也换不掉）。
    devices.issue_device_cookie(response, devices.header_device_id(request))
    return TokenResponse(accessToken=create_access_token(user.id, int(user.session_epoch or 0)))


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, db: DbSession, request: Request, response: Response
) -> TokenResponse:
    # 防撞库 / 防脚本批量登录：限制同一 IP 的尝试频率。
    limits = get_settings()
    await guard_rate(
        db,
        "login_ip",
        client_ip(request),
        limits.login_per_ip_per_5min,
        300,
        detail="登录尝试过于频繁，请稍后再试",
    )

    user = (await db.execute(select(User).where(User.username == payload.username))).scalar_one_or_none()
    # 先校验账号密码：密码错误与否都返回同一提示，不暴露账号是否存在。
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    # 封号：拒绝发放令牌，只回传机器码（前端静默拦截，不渲染提示）。
    if user.banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=BANNED_DETAIL)

    # 反多开：同一设备并发在线账号上限。本账号不在当前在线集合内且名额已满 → 拒绝登录。
    device_ids = devices.device_ids_from_request(request)
    online_cap = devices.max_online_per_device()
    if online_cap > 0 and device_ids:
        online = await devices.online_accounts_on_device(db, device_ids)
        if user.id not in online and len(online) >= online_cap:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"同一设备同时最多在线 {online_cap} 个账号，请先关闭其他账号",
            )

    # 反多开：记录登录设备与最近 IP（关联判定数据源）。设备指纹不一致时不在此处硬拦，
    # 避免锁死存量多开账号（注册上限与并发动线才是强制点）。
    user.last_ip = client_ip(request)
    await devices.record_device(db, user.id, device_ids, user.last_ip)
    # 单端登录：推进会话纪元，旧令牌随即失效（见 core/deps.get_current_user）。
    user.session_epoch = int(user.session_epoch or 0) + 1
    await db.commit()
    devices.issue_device_cookie(response, devices.header_device_id(request))
    return TokenResponse(accessToken=create_access_token(user.id, int(user.session_epoch)))


@router.post("/logout")
async def logout(db: DbSession, user: CurrentUser) -> dict:
    """登出：推进会话纪元，使当前令牌（含其它端的同账号令牌）立即失效。"""
    user.session_epoch = int(user.session_epoch or 0) + 1
    await db.commit()
    return {"ok": True}


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


@router.post("/change-nickname")
async def change_nickname(payload: ChangeNicknameRequest, db: DbSession, user: CurrentUser) -> dict:
    nickname = sanitize_nickname(payload.nickname)
    if not nickname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="昵称不能为空")
    user.nickname = nickname
    # 缓存榜单同步改名，无需等待下一次定时刷新。
    await db.execute(update(RankingEntry).where(RankingEntry.user_id == user.id).values(nickname=nickname))
    await db.commit()
    return {"nickname": nickname, "message": "昵称已修改"}


@router.get("/me")
async def me(user: CurrentUser, db: DbSession) -> dict:
    hero = (await db.execute(select(Hero).where(Hero.user_id == user.id, Hero.id == user.active_hero_id))).scalar_one_or_none()
    friend_code = await ensure_friend_code(db, user)
    await db.commit()
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "gold": int(user.gold),
        "hasHero": hero is not None,
        "isAdmin": is_admin(user),
        "friendCode": friend_code,
    }

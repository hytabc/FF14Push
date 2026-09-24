"""反多开：设备指纹 + IP 的账号关联判定、并发在线上限与关联账号额度限制。

判定「同一人」的两条信号：
- 设备：`user_devices.device_id`（前端浏览器指纹，或服务端签发的设备 Cookie，注册 / 登录 / 心跳时记录）。
- IP：`users.reg_ip` / `users.last_ip` 与 `user_devices.first_ip` / `last_ip`。

两个账号「关联」= 设备集合相交 **或** IP 集合相交。注册硬上限只认设备
（同一设备最多 `maxAccountsPerDevice` 个账号 = 1 大号 + 1 小号）；好友转账与交易板
成交对关联账号下调额度。配置见 shared/data/economy.json:antiAlt。

并发降载相关：
- `enforce_online_limit`：同一设备**同时在线**的账号数上限（先到先得，超出的账号被标记暂停）。
- `is_blocked`：每请求零额外查询地判断本账号是否被暂停（读已加载的用户行）。

诚实边界：`X-Device-Id` 与设备 Cookie 都由客户端持有，换设备 / 清 Cookie 仍可绕过；
真正的强制力来自「单端登录」（core/security + users.session_epoch）与本文件的并发在线上限。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    DEVICE_COOKIE_MAX_AGE,
    DEVICE_COOKIE_NAME,
    sign_device_cookie,
    verify_device_cookie,
)
from app.models import User, UserDevice
from app.models.base import utcnow
from app.services.game_config import CONFIG

DEVICE_HEADER = "X-Device-Id"
DEVICE_MAX_LEN = 64

# 在线判定窗口（秒）：与好友在线状态同量级（前端心跳 20s，超过即视为离线）。
ONLINE_WINDOW_SECONDS = 45

# 无法用于关联判定的 IP：缺失值、本地回环、测试客户端。
_SENTINEL_IPS = frozenset(
    {"", "unknown", "none", "null", "127.0.0.1", "::1", "localhost", "testclient"}
)


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite 下 DateTime(timezone=True) 会返回 naive datetime，统一补上 UTC。"""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ 配置
def _cfg() -> dict[str, Any]:
    return CONFIG.economy["antiAlt"]


def max_accounts_per_device() -> int:
    return int(_cfg()["maxAccountsPerDevice"])


def max_accounts_per_ip() -> int:
    """同一真实 IP 可注册的账号数上限；<= 0 关闭。"""
    return int(_cfg().get("maxAccountsPerIp", 0))


def max_online_per_device() -> int:
    """同一设备同时在线的账号数上限；<= 0 关闭。"""
    return int(_cfg().get("maxOnlineAccountsPerDevice", 0))


def online_limit_scope() -> str:
    """并发动线的关联口径：`device`（仅指纹）| `device_or_ip`（含同 IP）。"""
    scope = str(_cfg().get("onlineLimitScope", "device")).strip().lower()
    return scope if scope in ("device", "device_or_ip") else "device"


def single_session_enabled() -> bool:
    """是否启用「同一账号单端登录」。"""
    return bool(_cfg().get("singleSessionPerAccount", False))


def linked_transfer_daily_limit() -> int:
    return int(_cfg()["transferDailyLimit"])


def linked_market_daily_limit() -> int:
    return int(_cfg()["marketDailyLimit"])


# ------------------------------------------------------------------ 设备标识
def normalize_device_id(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    return value[:DEVICE_MAX_LEN]


def header_device_id(request: Request) -> str | None:
    """前端指纹请求头里的设备标识。"""
    return normalize_device_id(request.headers.get(DEVICE_HEADER))


def cookie_device_id(request: Request) -> str | None:
    """服务端签发的设备 Cookie 里的设备标识（验签失败返回 None）。"""
    return normalize_device_id(verify_device_cookie(request.cookies.get(DEVICE_COOKIE_NAME)))


def device_ids_from_request(request: Request) -> set[str]:
    """本请求可归因的全部设备标识（并集）。

    两者都算：前端指纹请求头（清 localStorage 会变）**与**服务端签发的设备 Cookie（清不掉）。
    取并集意味着「清 localStorage 换新指纹」仍会被旧 Cookie 关联到同一设备，
    从而无法绕过注册上限与并发动线；同时不影响显式指定设备的 API 客户端。
    """
    ids = {header_device_id(request), cookie_device_id(request)}
    return {d for d in ids if d}


def issue_device_cookie(response: Response, device_id: str | None) -> None:
    """把设备标识写入服务端签名的 httpOnly Cookie（含有效期）。"""
    if not device_id:
        return
    response.set_cookie(
        DEVICE_COOKIE_NAME,
        sign_device_cookie(device_id),
        max_age=DEVICE_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path="/",
    )


def is_real_ip(ip: str | None) -> bool:
    """是否可用于关联判定的真实客户端 IP（过滤哨兵值）。"""
    if not ip:
        return False
    return ip.strip().lower() not in _SENTINEL_IPS


# ------------------------------------------------------------------ 记录
async def record_device(
    db: AsyncSession, user_id: int, device_ids: Iterable[str] | None, ip: str | None
) -> None:
    """登记账号在这些设备上的出现，并刷新最近在线时间。不提交，由调用方 commit。"""
    ids = {d for d in (device_ids or ()) if d}
    if not ids:
        return
    real_ip = ip if is_real_ip(ip) else None
    now = utcnow()
    rows = {
        str(row.device_id): row
        for row in (
            await db.execute(
                select(UserDevice).where(
                    UserDevice.user_id == user_id, UserDevice.device_id.in_(ids)
                )
            )
        ).scalars().all()
    }
    for device_id in ids:
        row = rows.get(device_id)
        if row is None:
            db.add(
                UserDevice(
                    user_id=user_id,
                    device_id=device_id,
                    first_ip=real_ip,
                    last_ip=real_ip,
                    last_seen_at=now,
                    online_since=now,
                )
            )
            continue
        if real_ip is not None:
            row.last_ip = real_ip
        # 连续在线时保留首次上线时间；离线（超过在线窗口）后重新计时 —— 并发在线上限
        # 按 `online_since` 做「先到先得」排序，结果确定，不依赖各账号心跳的先后。
        if not _seen_fresh(row.last_seen_at, now):
            row.online_since = now
        row.last_seen_at = now


async def accounts_on_device(db: AsyncSession, device_ids: Iterable[str] | None) -> set[int]:
    """这些设备已关联的账号 id 集合。"""
    ids = {d for d in (device_ids or ()) if d}
    if not ids:
        return set()
    rows = (
        await db.execute(select(UserDevice.user_id).where(UserDevice.device_id.in_(ids)))
    ).scalars().all()
    return {int(uid) for uid in rows}


async def accounts_on_ip(db: AsyncSession, ip: str | None) -> set[int]:
    """该真实 IP 已注册的账号 id 集合（哨兵值返回空集）。"""
    if not is_real_ip(ip):
        return set()
    rows = (
        await db.execute(select(User.id).where(User.reg_ip == ip))
    ).scalars().all()
    return {int(uid) for uid in rows}


# ------------------------------------------------------------------ 关联判定
async def _facts(db: AsyncSession, user_id: int) -> tuple[set[str], set[str]]:
    """返回该账号的（设备集合, IP 集合）。"""
    rows = (
        await db.execute(
            select(UserDevice.device_id, UserDevice.first_ip, UserDevice.last_ip).where(
                UserDevice.user_id == user_id
            )
        )
    ).all()
    devices: set[str] = set()
    ips: set[str] = set()
    for device_id, first_ip, last_ip in rows:
        if device_id:
            devices.add(device_id)
        if is_real_ip(first_ip):
            ips.add(first_ip)
        if is_real_ip(last_ip):
            ips.add(last_ip)
    return devices, ips


async def are_linked(db: AsyncSession, a_id: int, b_id: int) -> bool:
    """两个账号是否判定为同一人的关联账号（同设备或同 IP）。"""
    if a_id == b_id:
        return False
    a_dev, a_ip = await _facts(db, a_id)
    b_dev, b_ip = await _facts(db, b_id)

    if a_dev & b_dev:
        return True

    users = {
        user.id: user
        for user in (
            await db.execute(select(User).where(User.id.in_((a_id, b_id))))
        ).scalars().all()
    }
    for uid, ips in ((a_id, a_ip), (b_id, b_ip)):
        user = users.get(uid)
        if user is None:
            continue
        if is_real_ip(user.reg_ip):
            ips.add(user.reg_ip)
        if is_real_ip(user.last_ip):
            ips.add(user.last_ip)

    return bool(a_ip & b_ip)


# ------------------------------------------------------------------ 并发在线上限
def is_blocked(user: User, now: datetime | None = None) -> bool:
    """本账号是否因并发在线超限被暂停（复用已加载的用户行，不产生查询）。"""
    return _flag_fresh(user.multi_online_blocked_at, now or utcnow())


def _flag_fresh(blocked_at: datetime | None, now: datetime) -> bool:
    """封锁标记是否仍然新鲜（窗口内）。"""
    moment = _as_utc(blocked_at)
    if moment is None:
        return False
    return (now - moment) < timedelta(seconds=ONLINE_WINDOW_SECONDS)


def _seen_fresh(last_seen_at: datetime | None, now: datetime) -> bool:
    """账号是否仍在在线窗口内。"""
    moment = _as_utc(last_seen_at)
    if moment is None:
        return False
    return (now - moment) < timedelta(seconds=ONLINE_WINDOW_SECONDS)


async def _online_rows_on_devices(
    db: AsyncSession, device_ids: set[str], now: datetime
) -> list[tuple[int, datetime]]:
    """这些设备上仍在线的账号，按「连续在线起始时间」升序（先到先得）。

    同一账号可能有多条设备记录，取其最早的上线时间。
    """
    ids = {d for d in device_ids if d}
    if not ids:
        return []
    cutoff = now - timedelta(seconds=ONLINE_WINDOW_SECONDS)
    rows = (
        await db.execute(
            select(UserDevice.user_id, UserDevice.online_since, UserDevice.last_seen_at).where(
                UserDevice.device_id.in_(ids),
                UserDevice.last_seen_at.is_not(None),
                UserDevice.last_seen_at >= cutoff,
            )
        )
    ).all()
    earliest: dict[int, datetime] = {}
    for uid, online_since, last_seen in rows:
        uid = int(uid)
        since = _as_utc(online_since) or _as_utc(last_seen) or now
        prev = earliest.get(uid)
        if prev is None or since < prev:
            earliest[uid] = since
    return sorted(earliest.items(), key=lambda kv: (kv[1], kv[0]))


async def _scope_device_ids(
    db: AsyncSession, user: User, device_ids: set[str]
) -> set[str]:
    """参与并发动线判定的设备集合（`device_or_ip` 口径下并入同 IP 账号的设备）。"""
    ids = {d for d in device_ids if d}
    if online_limit_scope() != "device_or_ip":
        return ids
    _, ips = await _facts(db, user.id)
    if is_real_ip(user.reg_ip):
        ips.add(user.reg_ip)
    if is_real_ip(user.last_ip):
        ips.add(user.last_ip)
    if not ips:
        return ids
    rows = (
        await db.execute(select(UserDevice.device_id).where(UserDevice.last_ip.in_(ips)))
    ).scalars().all()
    ids.update(str(d) for d in rows if d)
    return ids


async def enforce_online_limit(
    db: AsyncSession, user: User, device_ids: set[str]
) -> bool:
    """按「连续在线起始时间」先到先得，重算本账号的并发在线资格并写回暂停标记。

    在线的账号按上线时间排序，只有前 `maxOnlineAccountsPerDevice` 个可正常活动；
    其余账号被暂停非读请求（返回 False）。不提交，由调用方 commit。
    """
    limit = max_online_per_device()
    now = utcnow()
    if limit <= 0:
        user.multi_online_blocked_at = None
        return True

    scoped = await _scope_device_ids(db, user, device_ids)
    if not scoped:
        user.multi_online_blocked_at = None
        return True

    ordered = await _online_rows_on_devices(db, scoped, now)
    allowed = int(user.id) in {uid for uid, _ in ordered[:limit]}
    user.multi_online_blocked_at = None if allowed else now
    return allowed


async def online_accounts_on_device(
    db: AsyncSession, device_ids: set[str], now: datetime | None = None
) -> set[int]:
    """这些设备当前在线的账号集合（用于登录处的并发在线上限判定）。"""
    moment = now or utcnow()
    rows = await _online_rows_on_devices(db, device_ids, moment)
    return {uid for uid, _ in rows}

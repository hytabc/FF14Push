"""反多开：设备指纹 + IP 的账号关联判定，以及关联账号的额度限制。

判定「同一人」的两条信号：
- 设备：`user_devices.device_id`（前端浏览器指纹，注册 / 登录 / 心跳时记录）。
- IP：`users.reg_ip` / `users.last_ip` 与 `user_devices.first_ip` / `last_ip`。

两个账号「关联」= 设备集合相交 **或** IP 集合相交。注册硬上限只认设备
（同一设备最多 `maxAccountsPerDevice` 个账号 = 1 大号 + 1 小号）；好友转账与交易板
成交对关联账号下调额度。配置见 shared/data/economy.json:antiAlt。
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserDevice
from app.services.game_config import CONFIG

DEVICE_HEADER = "X-Device-Id"
DEVICE_MAX_LEN = 64

# 无法用于关联判定的 IP：缺失值、本地回环、测试客户端。
_SENTINEL_IPS = frozenset(
    {"", "unknown", "none", "null", "127.0.0.1", "::1", "localhost", "testclient"}
)


# ------------------------------------------------------------------ 配置
def _cfg() -> dict[str, Any]:
    return CONFIG.economy["antiAlt"]


def max_accounts_per_device() -> int:
    return int(_cfg()["maxAccountsPerDevice"])


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


def device_id_from_request(request: Request) -> str | None:
    return normalize_device_id(request.headers.get(DEVICE_HEADER))


def is_real_ip(ip: str | None) -> bool:
    """是否可用于关联判定的真实客户端 IP（过滤哨兵值）。"""
    if not ip:
        return False
    return ip.strip().lower() not in _SENTINEL_IPS


# ------------------------------------------------------------------ 记录
async def record_device(
    db: AsyncSession, user_id: int, device_id: str | None, ip: str | None
) -> None:
    """登记账号在某设备上的出现。不提交，由调用方 commit。"""
    if not device_id:
        return
    real_ip = ip if is_real_ip(ip) else None
    row = (
        await db.execute(
            select(UserDevice).where(
                UserDevice.user_id == user_id, UserDevice.device_id == device_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(
            UserDevice(user_id=user_id, device_id=device_id, first_ip=real_ip, last_ip=real_ip)
        )
        return
    if real_ip is not None:
        row.last_ip = real_ip


async def accounts_on_device(db: AsyncSession, device_id: str | None) -> set[int]:
    """该设备已关联的账号 id 集合。"""
    if not device_id:
        return set()
    rows = (
        await db.execute(select(UserDevice.user_id).where(UserDevice.device_id == device_id))
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

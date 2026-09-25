"""管理端在线监控：当前在线账号列表 + 按设备 / IP 的关联分组（反多开排查）。

只读，不写库，也不影响任何反多开的拦截 / 额度逻辑。在线判定与好友系统一致：
`users.last_seen_at` 落在 `devices.ONLINE_WINDOW_SECONDS` 秒内即视为在线（前端心跳刷新）。

「同一用户」的判定口径与 `devices.are_linked` 一致：设备集合相交 **或** IP 集合相交
（IP 取 `users.reg_ip` / `users.last_ip` 与 `user_devices.first_ip` / `last_ip`，哨兵值已过滤）。
分组是全局连通分量（同设备链、同 IP 链会一路合并），只保留含至少一个在线账号的分组。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Hero, User, UserDevice
from app.models.base import utcnow
from app.services import devices, friends
from app.services.admin import is_admin


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite 下 DateTime(timezone=True) 会返回 naive datetime，统一补上 UTC。"""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _seconds_ago(moment: datetime | None, now: datetime) -> int | None:
    value = _as_utc(moment)
    if value is None:
        return None
    return max(0, int((now - value).total_seconds()))


class _UnionFind:
    """按账号 id 合并「同设备 / 同 IP」的账号；根取较小 id，保证结果确定。"""

    def __init__(self) -> None:
        self._parent: dict[int, int] = {}

    def find(self, key: int) -> int:
        self._parent.setdefault(key, key)
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[max(root_a, root_b)] = min(root_a, root_b)


def _shared(
    buckets: dict[str, set[int]], ids: set[int], key: str
) -> list[dict]:
    """组内被 ≥2 个账号引用的信号（设备 / IP）。"""
    return [
        {key: value, "accountIds": sorted(members & ids)}
        for value, members in buckets.items()
        if len(members & ids) >= 2
    ]


async def online_overview(db: AsyncSession) -> dict:
    """在线账号概览 + 反多开关联分组。

    **为什么这里是全表扫描、且不要「优化」成 `WHERE last_seen_at >= cutoff`**：
    分组结果是「含至少一个在线账号的全局连通分量」，组内**同时包含与之关联的离线小号**——
    这正是管理员要看的。若先按 `last_seen_at` 缩小候选，这些离线小号会被丢掉，
    等于破坏反多开的排查能力（`services/devices.py` 的判定口径也会随之不一致）。
    真正要降内存只能改成「以在线账号为种子做设备/IP 有界扩张」，属于后续项。

    另外：`users.last_seen_at` **故意不加索引**——它在每次心跳都会被 UPDATE，
    而当前没有任何 SQL 按它过滤（在线判定在 Python 侧），加索引只会给写路径添成本。
    """
    now = utcnow()

    users = (await db.execute(select(User))).scalars().all()
    levels = dict((await db.execute(select(Hero.id, Hero.level))).all())
    device_rows = (
        await db.execute(
            select(
                UserDevice.user_id,
                UserDevice.device_id,
                UserDevice.first_ip,
                UserDevice.last_ip,
                UserDevice.last_seen_at,
            )
        )
    ).all()

    # 每账号的设备明细 / 真实 IP 集合，以及「设备 / IP → 账号」倒排，供并查集合并。
    user_devices: dict[int, list[dict]] = defaultdict(list)
    user_ips: dict[int, set[str]] = defaultdict(set)
    device_accounts: dict[str, set[int]] = defaultdict(set)
    ip_accounts: dict[str, set[int]] = defaultdict(set)

    for user_id, device_id, first_ip, last_ip, last_seen in device_rows:
        uid = int(user_id)
        user_devices[uid].append(
            {
                "deviceId": device_id,
                "firstIp": first_ip,
                "lastIp": last_ip,
                "lastSeenSecondsAgo": _seconds_ago(last_seen, now),
            }
        )
        if device_id:
            device_accounts[str(device_id)].add(uid)
        for ip in (first_ip, last_ip):
            if devices.is_real_ip(ip):
                user_ips[uid].add(str(ip))

    for user in users:
        uid = int(user.id)
        for ip in (user.reg_ip, user.last_ip):
            if devices.is_real_ip(ip):
                user_ips[uid].add(str(ip))

    for uid, ips in user_ips.items():
        for ip in ips:
            ip_accounts[ip].add(uid)

    uf = _UnionFind()
    for user in users:
        uf.find(int(user.id))
    for accounts in (list(device_accounts.values()) + list(ip_accounts.values())):
        if not accounts:
            continue
        anchor = next(iter(accounts))
        for uid in accounts:
            uf.union(anchor, uid)

    members: dict[int, list[User]] = defaultdict(list)
    for user in users:
        members[uf.find(int(user.id))].append(user)

    groups: list[dict] = []
    online_total = 0
    for root, group_users in members.items():
        ids = {int(user.id) for user in group_users}
        accounts = [
            {
                "id": int(user.id),
                "username": user.username,
                "nickname": user.nickname,
                "level": levels.get(user.active_hero_id),
                "gold": int(user.gold),
                "banned": bool(user.banned),
                "isAdmin": is_admin(user),
                "online": friends.is_online(user, now),
                "lastSeenSecondsAgo": _seconds_ago(user.last_seen_at, now),
                "regIp": user.reg_ip,
                "lastIp": user.last_ip,
                "ips": sorted(user_ips.get(int(user.id), set())),
                "devices": user_devices.get(int(user.id), []),
            }
            for user in group_users
        ]

        online_count = sum(1 for account in accounts if account["online"])
        if online_count == 0:
            continue
        online_total += online_count

        # 在线优先 → 最近活跃；无活跃时间的排最后。
        accounts.sort(
            key=lambda a: (
                not a["online"],
                a["lastSeenSecondsAgo"] if a["lastSeenSecondsAgo"] is not None else 10**9,
                a["id"],
            )
        )
        freshest = min(
            a["lastSeenSecondsAgo"] for a in accounts if a["lastSeenSecondsAgo"] is not None
        )

        groups.append(
            {
                "id": root,
                "onlineCount": online_count,
                "sharedDevices": _shared(device_accounts, ids, "deviceId"),
                "sharedIps": _shared(ip_accounts, ids, "ip"),
                "accounts": accounts,
                "_freshest": freshest,
            }
        )

    groups.sort(key=lambda g: (-g["onlineCount"], g["_freshest"], g["id"]))
    for group in groups:
        group.pop("_freshest")

    return {
        "serverTime": now.isoformat(),
        "windowSeconds": devices.ONLINE_WINDOW_SECONDS,
        "onlineCount": online_total,
        "totalAccounts": len(users),
        "groups": groups,
    }

"""反滥用限流：基于数据库的滑动窗口计数。

为什么不放在进程内存：多 worker / 重启会让内存计数失真，落库才准。
每次写入前清理过期事件，因此表大小收敛在「活跃 key 数 × 限值」量级。

用途：限制同一客户端 IP 的注册 / 登录 / 兑换频率，堵住「多开小号刷副本、刷金币」。
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SecurityEvent
from app.models.base import utcnow

MAX_SCOPE_LEN = 32
MAX_KEY_LEN = 64


async def hit(
    db: AsyncSession,
    scope: str,
    key: str,
    limit: int,
    window_seconds: int,
) -> bool:
    """记录一次事件并判断是否放行。

    返回 False 表示「窗口内已达上限，应拒绝」。limit <= 0 视为不限制。
    被拒绝的请求同样计入，持续刷请求者必须等满一个完整窗口才能恢复。
    """
    if limit <= 0:
        return True

    now = utcnow().timestamp()
    scope, key = scope[:MAX_SCOPE_LEN], (key or "unknown")[:MAX_KEY_LEN]
    await db.execute(
        delete(SecurityEvent).where(
            SecurityEvent.scope == scope,
            SecurityEvent.key == key,
            SecurityEvent.occurred_at < now - window_seconds,
        )
    )
    count = (
        await db.execute(
            select(func.count())
            .select_from(SecurityEvent)
            .where(SecurityEvent.scope == scope, SecurityEvent.key == key)
        )
    ).scalar_one()
    db.add(SecurityEvent(scope=scope, key=key, occurred_at=now))
    await db.commit()
    return int(count) < limit

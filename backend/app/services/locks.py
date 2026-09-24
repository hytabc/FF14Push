"""跨进程互斥：用 PostgreSQL 的会话级 advisory lock 串行化批量后台任务。

用途：排行榜刷新这类「全量重算」的定时任务在多个 uvicorn worker / 独立进程下不能并发执行，
否则会重复做全量扫描与全表重写（并可能互相覆盖）。advisory lock 由数据库保证全局唯一。

SQLite（本地测试）没有 advisory lock，测试又是单进程，因此直接放行。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _dialect_name(db: AsyncSession) -> str:
    try:
        bind = db.get_bind()
    except Exception:  # noqa: BLE001
        return ""
    return getattr(getattr(bind, "dialect", None), "name", "")


def _is_postgres(db: AsyncSession) -> bool:
    return _dialect_name(db) == "postgresql"


async def try_advisory_lock(db: AsyncSession, key: str) -> bool:
    """尝试获取 advisory lock。

    返回 True 表示拿到锁（非 PostgreSQL 或无法判断方言时恒返回 True，即不做互斥）。
    拿到后应在同一会话内尽快 `release_advisory_lock`（会话关闭也会自动释放）。
    """
    if not _is_postgres(db):
        return True
    result = await db.scalar(text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": key})
    return bool(result)


async def release_advisory_lock(db: AsyncSession, key: str) -> None:
    if not _is_postgres(db):
        return
    await db.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": key})

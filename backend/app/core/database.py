"""数据库引擎与会话。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()


def _engine_kwargs(url: str) -> dict:
    """按方言与进程角色构造引擎参数。

    PostgreSQL 需要显式指定连接池；但连接数必须**按角色分档**，否则
    「进程数 × (pool_size + max_overflow)」会超过 PostgreSQL 的 `max_connections`：
    API 进程用 `db_pool_size`/`db_max_overflow`，worker 进程（DB_POOL_PROFILE=worker）
    只暴露 2 条连接即可。SQLite（本地开发 / 测试）不支持这些参数，保持默认行为。
    """
    kwargs: dict = {"pool_pre_ping": True}
    if not url.startswith("sqlite"):
        kwargs.update(
            pool_size=settings.effective_pool_size,
            max_overflow=settings.effective_max_overflow,
            pool_recycle=settings.db_pool_recycle,
            pool_timeout=settings.db_pool_timeout,
        )
    return kwargs


engine = create_async_engine(settings.database_url, echo=False, **_engine_kwargs(settings.database_url))
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session

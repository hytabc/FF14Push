"""FastAPI 应用入口。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.models import Base
from app.services.admin import ensure_admin_user
from app.services.ranking import refresh_all_rankings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eorzea")

settings = get_settings()
RANKING_REFRESH_SECONDS = 300  # PRD 排行榜 2.4：每 5 分钟刷新一次


async def _ranking_loop() -> None:
    while True:
        await asyncio.sleep(RANKING_REFRESH_SECONDS)
        try:
            async with SessionLocal() as db:
                await refresh_all_rankings(db)
                await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("排行榜刷新失败")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("已确保数据库表结构存在（AUTO_CREATE_TABLES=true）")
    try:
        async with SessionLocal() as db:
            action = await ensure_admin_user(db)
        if action != "disabled":
            logger.info("管理员账号已同步（%s）", action)
    except Exception:  # noqa: BLE001
        logger.exception("管理员账号同步失败（不影响服务启动）")
    task = asyncio.create_task(_ranking_loop())
    logger.info("艾欧泽亚放置录 后端已启动")
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="艾欧泽亚放置录 API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "eorzea-idle-backend"}

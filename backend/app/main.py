"""FastAPI 应用入口。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.api.v1.router import api_router
from app.core.compression import BrotliMiddleware, RequestDecompressMiddleware
from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.models import Base
from app.services.admin import ensure_admin_user
from app.services.broadcast import hub
from app.services.ranking import refresh_all_rankings
from app.services.world_boss import ensure_world_boss, roll_world_boss

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eorzea")

settings = get_settings()
RANKING_REFRESH_SECONDS = settings.ranking_refresh_seconds  # 缓存榜刷新间隔（可配，见 core/config.py）
WORLD_BOSS_RESPAWN_SECONDS = 30  # 世界BOSS 全局时间轮询间隔（换轮 / 短休整复活由 periodSeconds / respawnSeconds 决定）


async def _ranking_loop() -> None:
    while True:
        await asyncio.sleep(RANKING_REFRESH_SECONDS)
        try:
            async with SessionLocal() as db:
                await refresh_all_rankings(db)
                await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("排行榜刷新失败")


async def _worldboss_loop() -> None:
    """世界BOSS 全局时间兜底：周期换轮与周期内短休整复活（worker 已在推进，这里仅作备份）。"""
    while True:
        await asyncio.sleep(WORLD_BOSS_RESPAWN_SECONDS)
        try:
            async with SessionLocal() as db:
                if await roll_world_boss(db):
                    await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("世界BOSS 刷新失败")


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
    try:
        async with SessionLocal() as db:
            await ensure_world_boss(db)
    except Exception:  # noqa: BLE001
        logger.exception("世界BOSS 初始化失败（不影响服务启动）")
    ranking_tasks = []
    # 多 worker 部署应设 RANKING_IN_API=false，改由独立进程 `python -m app.ranking_worker` 刷新
    # （见 docker-compose 的 ranking-worker）。留在 API 内时由 advisory lock 保证只刷一次。
    if settings.ranking_in_api:
        ranking_tasks.append(asyncio.create_task(_ranking_loop()))
    # 世界BOSS 全局时间兜底：默认关闭（专用 worldboss-worker 已承担），避免每个 API worker 空转打库。
    loop_tasks = list(ranking_tasks)
    if settings.worldboss_loop_in_api:
        loop_tasks.append(asyncio.create_task(_worldboss_loop()))
    logger.info("艾欧泽亚放置录 后端已启动")
    try:
        yield
    finally:
        for task in loop_tasks:
            task.cancel()
        for task in loop_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await hub.shutdown()


app = FastAPI(title="艾欧泽亚放置录 API", version="1.0.1", lifespan=lifespan)

# 传输层压缩/解压。`add_middleware` 后注册的在外层，故注册顺序决定嵌套：
#   CORS（最外）→ GZip → Brotli → RequestDecompress → 应用
# 响应方向：Brotli 命中 `Accept-Encoding: br` 时设 `Content-Encoding: br`，外层 GZip
# 见到已有 `Content-Encoding` 即跳过；不支持 br 的客户端由 GZip 兜底。
# 请求方向：以 gzip 压缩请求体（`Content-Encoding: gzip`）时先解压再交给下游。
if settings.request_decompress_enabled:
    app.add_middleware(
        RequestDecompressMiddleware, max_decompressed_bytes=settings.request_max_decompressed_bytes
    )

if settings.brotli_enabled:
    app.add_middleware(
        BrotliMiddleware, minimum_size=settings.brotli_min_size, quality=settings.brotli_quality
    )

if settings.gzip_enabled:
    app.add_middleware(
        GZipMiddleware, minimum_size=settings.gzip_min_size, compresslevel=6
    )

# CORS 置于最外层，错误响应（含压缩/解压中间件直接返回的 4xx）同样带上 CORS 头。
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

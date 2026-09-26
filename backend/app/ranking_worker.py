"""Run with python -m app.ranking_worker.

排行榜缓存榜的定时刷新进程：独立于 API 进程运行，避免全量重算与请求处理互相影响。
多实例 / 多 API worker 由 `services/locks.try_advisory_lock` 保证同一时刻只有一个在执行
（SQLite 本地开发无 advisory lock，但通常只跑一个实例）。

该进程同时承担「数据保留清理」（`services/retention.py`，按 `RETENTION_INTERVAL_SECONDS` 触发）：
终态超期的历史行清理属于低频后台任务，放在这里可以避免在 API 进程里做批删除。
"""
import asyncio
import logging
import time

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.ishgard import settle_titles
from app.services.ranking import refresh_all_rankings
from app.services.retention import run_retention

log = logging.getLogger('ranking-worker')

# 缓存榜刷新间隔（默认 600s，可配）：等级/战力/金币/关卡/游玩时间是缓存榜，
# 拉长间隔可把全量重算的 CPU/内存尖峰频率减半。
REFRESH_SECONDS = get_settings().ranking_refresh_seconds


async def refresh_once() -> dict:
    async with SessionLocal() as db:
        counts = await refresh_all_rankings(db)
        await db.commit()
    return counts


async def settle_ishgard_titles_once() -> None:
    """兜底结算「重建伊修加德」的周期称号（窗口到点即换人，无人读状态也按时发）。"""
    async with SessionLocal() as db:
        result = await settle_titles(db)
        if result.get("settled"):
            await db.commit()
            log.info('ishgard titles settled: %s', result)


async def retain_once() -> dict:
    async with SessionLocal() as db:
        return await run_retention(db)


async def main() -> None:
    settings = get_settings()
    next_retention = 0.0  # 首次循环即执行一轮清理
    while True:
        try:
            counts = await refresh_once()
            if any(counts.values()):
                log.info('rankings refreshed: %s', counts)
        except Exception:  # noqa: BLE001
            log.exception('Failed to refresh rankings')

        try:
            await settle_ishgard_titles_once()
        except Exception:  # noqa: BLE001 - 称号结算失败不应中断刷新循环
            log.exception('Failed to settle ishgard titles')

        now = time.monotonic()
        if settings.retention_enabled and now >= next_retention:
            try:
                await retain_once()
            except Exception:  # noqa: BLE001 - 清理失败不应中断刷新循环
                log.exception('Failed to run retention')
            next_retention = now + settings.retention_interval_seconds

        await asyncio.sleep(REFRESH_SECONDS)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

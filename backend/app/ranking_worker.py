"""Run with python -m app.ranking_worker.

排行榜缓存榜的定时刷新进程：独立于 API 进程运行，避免全量重算与请求处理互相影响。
多实例 / 多 API worker 由 `services/locks.try_advisory_lock` 保证同一时刻只有一个在执行
（SQLite 本地开发无 advisory lock，但通常只跑一个实例）。
"""
import asyncio
import logging

from app.core.database import SessionLocal
from app.services.ranking import refresh_all_rankings

log = logging.getLogger('ranking-worker')

REFRESH_SECONDS = 300  # PRD 排行榜 2.4：每 5 分钟刷新一次


async def refresh_once() -> dict:
    async with SessionLocal() as db:
        counts = await refresh_all_rankings(db)
        await db.commit()
    return counts


async def main() -> None:
    while True:
        try:
            counts = await refresh_once()
            if any(counts.values()):
                log.info('rankings refreshed: %s', counts)
        except Exception:  # noqa: BLE001
            log.exception('Failed to refresh rankings')
        await asyncio.sleep(REFRESH_SECONDS)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

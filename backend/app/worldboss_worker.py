"""世界BOSS 全局时间推进进程：`python -m app.worldboss_worker`。

**逐玩家的战斗会话已改由客户端本地模拟**（后端只做上限夹取 + 结算，见
`api/v1/worldboss.py:/report`），因此本进程不再扫描 / 推进任何会话，CPU 不再随在线人数增长。

保留的职责只有全局时间的两件事（都是条件 UPDATE，多 worker 安全）：
周期换轮（`period_ends_at` 到期 → 满血、cycle+1、结束上一周期会话）与周期内短休整复活。
响应要求不高（周期以小时计、休整以秒计），故轮询间隔放宽到 1 秒，避免无谓的 DB 轮询。
"""

import asyncio
import logging
import time
import uuid

from app.core.database import SessionLocal
from app.services.world_boss import kill_boss_if_depleted, roll_world_boss

log = logging.getLogger("worldboss-worker")

POLL_SECONDS = 1.0


async def tick_worldboss(session_factory=SessionLocal, worker_id: str = "worker", now: float | None = None) -> int:
    """推进全局 BOSS 的时间状态（周期换轮 / 短休整复活 / 血量归零判定）。

    返回 0：不再有「推进了多少会话」的概念（旧实现返回推进的会话数）。
    """
    now = time.time() if now is None else now
    async with session_factory() as db:
        await roll_world_boss(db, now)
        await kill_boss_if_depleted(db, now)
        await db.commit()
    return 0


async def main() -> None:
    worker_id = str(uuid.uuid4())
    while True:
        started = time.monotonic()
        try:
            await tick_worldboss(worker_id=worker_id)
        except Exception:  # noqa: BLE001
            log.exception("世界BOSS 全局推进失败，事务已回滚")
        await asyncio.sleep(max(0.05, POLL_SECONDS - (time.monotonic() - started)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

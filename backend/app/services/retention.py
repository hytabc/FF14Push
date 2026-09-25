"""数据保留：定期清理「终态 + 超期」的历史行，遏制表无限膨胀。

由 `ranking_worker` 按 `settings.retention_interval_seconds` 周期执行（`retention_enabled=false` 关闭）。

**永不清理**（榜单真相 / 对账依据 / 反多开判定依据）：

- `world_boss_contributions` / `world_boss_rewards`：世界BOSS 历史贡献与奖励，
  AGENT.md 明确「不随版本更新重置」。
- `coop_records`：远征榜实时聚合的真相。
- `coin_transfers`：好友转账对账依据。
- `user_devices`：反多开「同设备多账号」判定依据（清了会削弱多开识别）。
- `rankings`：每次刷新自行 `delete + insert`，天然有界。

**故意不清理**（有硬约束，见下）：

- `coop_rooms` / `coop_battles` 及其子表：`coop_records` 以**无 CASCADE** 的外键引用它们，
  删除房间会因外键约束失败或破坏远征榜数据。要清理必须先设计归档方案。
- `chat_messages` 的公告：AGENT.md 明确公告是「不保留记录」的例外（长期置顶保留）。

`security_events` 的清理在此集中做（`services/ratelimit.py` 里只删当前 scope+key 的行为保持不变
——那里是热路径，必须走索引；全表级的沉寂 key 清扫交给本任务）。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import engine
from app.models import (
    ActivitySession,
    AuditLog,
    BattleSession,
    RaidSession,
    SecurityEvent,
    TreasureRun,
)
from app.models.multiplayer import PvpBattle

log = logging.getLogger("eorzea.retention")

# 清理后顺带 VACUUM 的高 churn 表（仅 PostgreSQL；VACUUM 不能在事务内执行）。
_VACUUM_TABLES = ("security_events", "battle_sessions", "activity_sessions", "rankings")


def _utc_cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _epoch_cutoff(days: int) -> float:
    return time.time() - days * 86400


async def purge_expired(db: AsyncSession) -> dict[str, int]:
    """删除各表「终态 + 超期」的行（保留期见 settings.retention_*），返回每表删除行数。

    全部条件都要求「已终态」——进行中的会话 / 房间永远不会被清；`world_boss_*`、
    `coop_records`、`coin_transfers`、`user_devices` 不在清理范围内。
    """
    settings = get_settings()
    counts: dict[str, int] = {}

    def _record(name: str, result) -> None:
        counts[name] = int(result.rowcount or 0)

    # 限流事件：按 occurred_at 全局清理（保留期必须大于所有限流窗口，见 config 注释）。
    _record(
        "security_events",
        await db.execute(
            delete(SecurityEvent).where(
                SecurityEvent.occurred_at < _epoch_cutoff(settings.retention_ratelimit_days)
            )
        ),
    )
    # 已结束的地区战斗会话（last_report_at 非空，用它而不是可空的 ended_at）。
    _record(
        "battle_sessions",
        await db.execute(
            delete(BattleSession).where(
                BattleSession.active.is_(False),
                BattleSession.last_report_at < _utc_cutoff(settings.retention_sessions_days),
            )
        ),
    )
    # 已结束的采集 / 生产 / 钓鱼会话。
    _record(
        "activity_sessions",
        await db.execute(
            delete(ActivitySession).where(
                ActivitySession.active.is_(False),
                ActivitySession.last_report_at < _utc_cutoff(settings.retention_sessions_days),
            )
        ),
    )
    # 已结束的副本挑战（started_at 非空）。
    _record(
        "raid_sessions",
        await db.execute(
            delete(RaidSession).where(
                RaidSession.active.is_(False),
                RaidSession.started_at < _utc_cutoff(settings.retention_sessions_days),
            )
        ),
    )
    # 已结束的挖宝副本（ended_reason 非空即已终止）。
    _record(
        "treasure_runs",
        await db.execute(
            delete(TreasureRun).where(
                TreasureRun.ended_reason.is_not(None),
                TreasureRun.created_at < _utc_cutoff(settings.retention_sessions_days),
            )
        ),
    )
    # 竞技场战报（异步 PvP，双方回放用）。
    _record(
        "pvp_battles",
        await db.execute(
            delete(PvpBattle).where(PvpBattle.created_at < _epoch_cutoff(settings.retention_pvp_days))
        ),
    )
    # 反作弊审计日志。
    _record(
        "audit_logs",
        await db.execute(
            delete(AuditLog).where(AuditLog.created_at < _utc_cutoff(settings.retention_audit_days))
        ),
    )

    await db.commit()
    return {name: removed for name, removed in counts.items() if removed}


async def vacuum_tables(tables: Sequence[str] = _VACUUM_TABLES) -> None:
    """对高 churn 表执行 `VACUUM (ANALYZE)`（仅 PostgreSQL；需在事务外执行）。"""
    if engine.dialect.name != "postgresql":
        return
    autocommit = engine.execution_options(isolation_level="AUTOCOMMIT")
    try:
        async with autocommit.connect() as conn:
            for table in tables:
                # 表名来自本模块的固定白名单，非外部输入。
                await conn.execute(text(f"VACUUM (ANALYZE) {table}"))
    finally:
        await autocommit.dispose()


async def run_retention(db: AsyncSession) -> dict[str, int]:
    """执行一轮保留清理（含 VACUUM），返回删除统计。"""
    settings = get_settings()
    if not settings.retention_enabled:
        return {}
    counts = await purge_expired(db)
    if counts and settings.retention_vacuum:
        try:
            await vacuum_tables()
        except Exception:  # noqa: BLE001 - VACUUM 失败不应影响清理结果
            log.exception("VACUUM 失败（忽略）")
    if counts:
        log.info("retention purged: %s", counts)
    return counts

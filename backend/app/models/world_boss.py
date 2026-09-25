"""世界BOSS 持久化状态。

- `WorldBoss`：全局单行（id=1），持有共享血量 / 讨伐周期（cycle）/ 周期结束时间 / 本周期击杀数。
- `WorldBossSession`：每个玩家当前周期的战斗会话（8 英雄 state JSON，租约推进）。
- `WorldBossContribution`：每账号每周期一行，累计伤害（持久，榜单真相，不随版本更新清除）。
- `WorldBossReward`：每账号每周期一行，周期结算幂等领取。
- `WorldBossTicket`：WebSocket 一次性 ticket（照抄 CoopTicket）。

结算单位是「讨伐周期」：周期内 BOSS 可被反复击杀（cycle 不变），周期到时 cycle+1 并结算。
JSON 值整体替换、不原地修改；时间统一用 epoch 浮点（与 multiplayer 一致，避免方言差异）。
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonType

STATUS_ALIVE = "alive"
STATUS_DEAD = "dead"
SESSION_RUNNING = "running"
SESSION_ENDED = "ended"


class WorldBoss(Base):
    __tablename__ = "world_bosses"

    id: Mapped[int] = mapped_column(primary_key=True)
    boss_key: Mapped[str] = mapped_column(sa.String(32))
    name: Mapped[str] = mapped_column(sa.String(64))
    cycle: Mapped[int] = mapped_column(default=1)
    hp: Mapped[int] = mapped_column(sa.BigInteger)
    max_hp: Mapped[int] = mapped_column(sa.BigInteger)
    attack: Mapped[int] = mapped_column(sa.BigInteger)
    status: Mapped[str] = mapped_column(sa.String(16), default=STATUS_ALIVE, index=True)
    killed_at: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    respawn_at: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    # 讨伐周期：period_ends_at 为当前周期结束时间（epoch 秒），kills 为本周期已击杀次数。
    period_ends_at: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    kills: Mapped[int] = mapped_column(default=0)
    last_kill_by: Mapped[int | None] = mapped_column(nullable=True)
    config: Mapped[dict] = mapped_column(JsonType)
    updated_at: Mapped[float] = mapped_column(sa.Float, default=0)


class WorldBossSession(Base):
    __tablename__ = "world_boss_sessions"
    __table_args__ = (
        sa.UniqueConstraint("cycle", "user_id", name="uq_world_boss_session"),
        sa.Index("ix_world_boss_session_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    boss_id: Mapped[int] = mapped_column(sa.ForeignKey("world_bosses.id", ondelete="CASCADE"))
    cycle: Mapped[int] = mapped_column()
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(sa.String(16), default=SESSION_RUNNING, index=True)
    state: Mapped[dict] = mapped_column(JsonType)
    sequence: Mapped[int] = mapped_column(default=0)
    damage: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    heartbeat_at: Mapped[float] = mapped_column(sa.Float, default=0)
    # 客户端模拟下放：上报窗口与幂等游标（窗口一律由服务端时钟计算，不采信客户端 elapsedMs）。
    last_report_at: Mapped[float] = mapped_column(sa.Float, default=0)
    last_report_seq: Mapped[int] = mapped_column(default=0)
    lease_owner: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    lease_until: Mapped[float] = mapped_column(sa.Float, default=0)
    updated_at: Mapped[float] = mapped_column(sa.Float, default=0)
    created_at: Mapped[float] = mapped_column(sa.Float, default=0)


class WorldBossContribution(Base):
    __tablename__ = "world_boss_contributions"
    __table_args__ = (
        sa.UniqueConstraint("cycle", "user_id", name="uq_world_boss_contribution"),
        sa.Index("ix_world_boss_contribution_damage", "cycle", "damage"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    boss_id: Mapped[int] = mapped_column(sa.ForeignKey("world_bosses.id", ondelete="CASCADE"))
    cycle: Mapped[int] = mapped_column()
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    damage: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    party: Mapped[list] = mapped_column(JsonType, default=list)
    updated_at: Mapped[float] = mapped_column(sa.Float, default=0)
    created_at: Mapped[float] = mapped_column(sa.Float, default=0)


class WorldBossReward(Base):
    __tablename__ = "world_boss_rewards"
    __table_args__ = (sa.UniqueConstraint("cycle", "user_id", name="uq_world_boss_reward"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    boss_id: Mapped[int] = mapped_column(sa.ForeignKey("world_bosses.id", ondelete="CASCADE"))
    cycle: Mapped[int] = mapped_column()
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(default=0)
    items: Mapped[int] = mapped_column(default=0)
    receipt: Mapped[dict] = mapped_column(JsonType)
    claimed_at: Mapped[float] = mapped_column(sa.Float, default=0)


class WorldBossTicket(Base):
    __tablename__ = "world_boss_tickets"

    token: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    boss_id: Mapped[int] = mapped_column(sa.ForeignKey("world_bosses.id"))
    expires_at: Mapped[float] = mapped_column(sa.Float)

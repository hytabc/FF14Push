"""战斗会话、排行榜缓存、审计日志。"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonType, TimestampMixin


class BattleSession(Base):
    __tablename__ = "battle_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    hero_id: Mapped[int | None] = mapped_column(sa.ForeignKey("heroes.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    region_id: Mapped[int] = mapped_column(sa.Integer)
    started_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    last_report_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    ended_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    kill_credit: Mapped[float] = mapped_column(sa.Float, default=0.0)
    total_kills: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    total_gold: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    total_exp: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True, index=True)


class RankingEntry(Base, TimestampMixin):
    __tablename__ = "rankings"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "board", name="uq_ranking_user_board"),
        sa.Index("ix_rankings_board_value", "board", sa.text("value DESC")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    board: Mapped[str] = mapped_column(sa.String(16))
    value: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    secondary: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    nickname: Mapped[str] = mapped_column(sa.String(64), default="")
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(sa.String(64))
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    rejected: Mapped[bool] = mapped_column(sa.Boolean, default=False)


class SecurityEvent(Base):
    """反滥用限流事件：按 (scope, key) 做滑动窗口计数，key 通常是客户端 IP。

    单进程内存计数在多 worker / 重启后会失真，故落库。每次写入前清理过期行，
    表大小收敛在「活跃 key 数 × 限值」量级，不会无限增长。
    """

    __tablename__ = "security_events"
    __table_args__ = (sa.Index("ix_security_events_scope_key", "scope", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(sa.String(32))
    key: Mapped[str] = mapped_column(sa.String(64))
    # 用 epoch 秒存储，避开 SQLite / PostgreSQL 的时区比较差异
    occurred_at: Mapped[float] = mapped_column(sa.Float)

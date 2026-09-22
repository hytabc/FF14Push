"""高难副本：挑战会话与通关进度。"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, JsonType


class RaidSession(Base, TimestampMixin):
    """一次副本挑战。与 BattleSession 不同，副本不按地区、不做周期上报。"""

    __tablename__ = "raid_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    hero_id: Mapped[int | None] = mapped_column(sa.ForeignKey("heroes.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    raid_id: Mapped[str] = mapped_column(sa.String(32), index=True)
    started_at: Mapped[sa.DateTime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    ended_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    cleared: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    balance_snapshot: Mapped[dict] = mapped_column(JsonType, default=dict)
    outcome: Mapped[dict] = mapped_column(JsonType, default=dict)
    # 待开启的高难宝箱数量：通关结算后由玩家自选装备种类再开箱
    pending_chest: Mapped[int] = mapped_column(sa.Integer, default=0)


class RaidProgress(Base, TimestampMixin):
    """每个账号对每个副本的进度：是否已通关、最快用时、通关次数，以及每日奖励计数。"""

    __tablename__ = "raid_progress"
    __table_args__ = (sa.UniqueConstraint("user_id", "raid_id", name="uq_raid_progress"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    raid_id: Mapped[str] = mapped_column(sa.String(32), index=True)
    cleared: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    cleared_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    best_clear_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    clear_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    # 每日奖励通关计数：reward_day 为计数所属日期（UTC），跨天自动清零，用于防刷。
    reward_day: Mapped[dt.date | None] = mapped_column(sa.Date, nullable=True)
    rewarded_today: Mapped[int] = mapped_column(sa.Integer, default=0)

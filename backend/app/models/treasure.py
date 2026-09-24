"""挖宝：5 层副本的服务端权威状态机（门、宝箱、猜大小奖励）。

客户端只模拟每层战斗并上报结果；门的 50/50、宝箱内容与猜大小结果全部由服务端结算。
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

STATUS_FIGHTING = "fighting"  # 本层怪物未击败
STATUS_CLEARED = "cleared"  # 已击败本层怪物，待开箱 / 猜大小
STATUS_ENDED = "ended"  # 本次挖宝结束


class TreasureRun(Base, TimestampMixin):
    __tablename__ = "treasure_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    hero_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("heroes.id", ondelete="SET NULL"), nullable=True
    )
    floor: Mapped[int] = mapped_column(sa.Integer, default=1)
    status: Mapped[str] = mapped_column(sa.String(16), default=STATUS_FIGHTING, index=True)
    # 本层战斗的服务端开始时刻：进入该层 / 重试该层时刷新，用于最短时长校验与在线时长。
    floor_started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    # 猜大小：当前牌面（None 表示未进入事件）与剩余状态
    card: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    # 当前层宝箱奖励倍率：初始 1.0，猜对递增、猜错归零
    multiplier: Mapped[float] = mapped_column(sa.Float, default=1.0, server_default="1.0")
    guesses_used: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    event_active: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    chest_opened: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    # 结束原因：wrong_door | completed | abandoned | superseded
    ended_reason: Mapped[str | None] = mapped_column(sa.String(24), nullable=True)

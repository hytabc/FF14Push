"""生产 / 采集 DLC 的数据模型。

- 生产 / 采集等级（所有能工巧匠共用一个生产等级，所有大地使者共用一个采集等级）
- 可堆叠库存（材料 / 半成品 / 鱼 / 药水 / 食物）
- 服务端权威活动会话（采集 / 生产 / 钓鱼），与战斗互斥
- 钓鱼记录、生效中的药水 / 食物、称号
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonType, TimestampMixin


class DohDolProgress(Base, TimestampMixin):
    __tablename__ = "dohdol_progress"
    __table_args__ = (sa.UniqueConstraint("user_id", "kind", name="uq_dohdol_user_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # kind: "doh"（生产）| "dol"（采集）
    kind: Mapped[str] = mapped_column(sa.String(8))
    level: Mapped[int] = mapped_column(sa.Integer, default=1)
    exp: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    # 累计经验：升级扣减 / 满级清零都不影响它，用于排行榜（满级后仍继续累计）。
    total_exp: Mapped[int] = mapped_column(sa.BigInteger, default=0, server_default="0")


class StackItem(Base):
    """可堆叠库存。kind: material（含材料/半成品/鱼）| potion | food。"""

    __tablename__ = "stack_items"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "kind", "item_id", name="uq_stack_user_kind_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(sa.String(16))
    item_id: Mapped[str] = mapped_column(sa.String(48))
    count: Mapped[int] = mapped_column(sa.BigInteger, default=0)


class ActivitySession(Base):
    """采集 / 生产 / 钓鱼会话。与战斗一样：服务端时钟结算，不做离线收益。"""

    __tablename__ = "activity_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # kind: gather | produce | fish
    kind: Mapped[str] = mapped_column(sa.String(16))
    job_id: Mapped[str] = mapped_column(sa.String(8))
    region_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    recipe_id: Mapped[str | None] = mapped_column(sa.String(48), nullable=True)
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    last_report_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    # 未结算的进度余额（不足一次动作的剩余秒数 / 次数）
    credit: Mapped[float] = mapped_column(sa.Float, default=0.0)
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True, index=True)
    total_actions: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    # 生产：本次会话要制造的总件数（「制作X个」/「制作全部」）。None = 不设上限（旧会话）。
    target_actions: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    # 钓鱼：捕鱼人之识到期时间（服务端时钟）与本次会话已钓起的普通鱼 id
    insight_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    session_fish: Mapped[list] = mapped_column(JsonType, default=list)


class FishRecord(Base):
    __tablename__ = "fish_records"
    __table_args__ = (sa.UniqueConstraint("user_id", "fish_id", name="uq_fish_user_fish"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    fish_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    region_id: Mapped[int] = mapped_column(sa.Integer, default=0)
    # kind: normal | king | emperor
    kind: Mapped[str] = mapped_column(sa.String(16), default="normal")
    count: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    max_size: Mapped[int] = mapped_column(sa.Integer, default=0)
    first_caught_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class ActiveConsumable(Base):
    """生效中的药水 / 食物，二者各占一个槽位，可共存；同槽位连续使用时长叠加。"""

    __tablename__ = "active_consumables"
    __table_args__ = (sa.UniqueConstraint("user_id", "kind", name="uq_consumable_user_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(sa.String(8))
    item_id: Mapped[str] = mapped_column(sa.String(48))
    effects: Mapped[list] = mapped_column(JsonType, default=list)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))


class UserTitle(Base):
    __tablename__ = "user_titles"
    __table_args__ = (sa.UniqueConstraint("user_id", "title_id", name="uq_title_user_title"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title_id: Mapped[str] = mapped_column(sa.String(48))
    unlocked_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())

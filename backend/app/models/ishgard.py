"""重建伊修加德：全服共享进度的生活玩法。

- `IshgardState`：全局单行（id=1），持有轮次 / 阶段 / 全服阶段进度，以及称号窗口与两位称号持有者。
- `IshgardMember`：每账号一行，累计总积分（跨轮次保留；用于积分榜 / 称号判定 / 主手装备解锁）。
- `IshgardTool`：每账号每类（doh / dol）一行，可成长主手装备的等级、对应 `Item` 与紫色附魔。
- `IshgardContribution`：每账号每轮一行，该轮贡献积分（永久保留）。

时间统一用 epoch 浮点（与 world_boss 一致，避免方言差异）。所有表只新增行 / 只建表，永不清理。
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonType


class IshgardState(Base):
    __tablename__ = "ishgard_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 轮次（赛季）：5 个阶段全部达成后 +1，阶段回到 1；个人侧数据不受影响。
    round: Mapped[int] = mapped_column(default=1)
    # 当前阶段 1..5（= 第 X 次重建的 X）；物资按阶段划分、不可跨阶段使用。
    stage: Mapped[int] = mapped_column(default=1)
    stage_points: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    stage_target: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    # 称号结算窗口：到点后按累计积分重算前二，唯一持有、严格超越才转移。
    title_period_ends_at: Mapped[float] = mapped_column(sa.Float, default=0)
    saint_user_id: Mapped[int | None] = mapped_column(nullable=True)
    saint_since: Mapped[float] = mapped_column(sa.Float, default=0)
    apostle_user_id: Mapped[int | None] = mapped_column(nullable=True)
    apostle_since: Mapped[float] = mapped_column(sa.Float, default=0)
    updated_at: Mapped[float] = mapped_column(sa.Float, default=0)


class IshgardMember(Base):
    __tablename__ = "ishgard_members"
    __table_args__ = (sa.UniqueConstraint("user_id", name="uq_ishgard_member_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    points: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    updated_at: Mapped[float] = mapped_column(sa.Float, default=0)


class IshgardTool(Base):
    __tablename__ = "ishgard_tools"
    __table_args__ = (sa.UniqueConstraint("user_id", "kind", name="uq_ishgard_tool_user_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # kind: "doh"（生产主手）| "dol"（采集主手）
    kind: Mapped[str] = mapped_column(sa.String(8))
    # 0 = 未拥有；否则 20 / 40 / 60 / 80 / 100。
    level: Mapped[int] = mapped_column(sa.Integer, default=0)
    item_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("items.id", ondelete="SET NULL"), nullable=True
    )
    pink_id: Mapped[str | None] = mapped_column(sa.String(48), nullable=True)
    # 紫色附魔各 stat 的具体数值（stat → value），按配置 range 逐项 roll。
    pink_values: Mapped[dict] = mapped_column(JsonType, default=dict)
    unlocked_at: Mapped[float] = mapped_column(sa.Float, default=0)
    updated_at: Mapped[float] = mapped_column(sa.Float, default=0)


class IshgardContribution(Base):
    __tablename__ = "ishgard_contributions"
    __table_args__ = (sa.UniqueConstraint("round", "user_id", name="uq_ishgard_contribution"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    round: Mapped[int] = mapped_column(index=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    points: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    updated_at: Mapped[float] = mapped_column(sa.Float, default=0)

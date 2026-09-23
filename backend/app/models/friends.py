"""好友关系与好友金币转账流水。

- `Friendship`：方向化（requester → addressee）。`A→B` 的 `pending` 表示「A 申请 B」；
  B 同意后置 `accepted`。A、B 互为好友 = 存在一条 `(A,B)` 或 `(B,A)` 的 accepted 行。
- `CoinTransfer`：转账流水，用于审计与每日累计额度计算。手续费销毁（金币回收），
  净额不会凭空增长，因此不构成刷金币来源。
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# status 取值
STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"


class Friendship(Base, TimestampMixin):
    __tablename__ = "friendships"
    __table_args__ = (
        sa.UniqueConstraint("requester_id", "addressee_id", name="uq_friendship_pair"),
        sa.Index("ix_friendships_requester_status", "requester_id", "status"),
        sa.Index("ix_friendships_addressee_status", "addressee_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    addressee_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(sa.String(16), default=STATUS_PENDING)
    accepted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class CoinTransfer(Base, TimestampMixin):
    __tablename__ = "coin_transfers"
    __table_args__ = (
        sa.Index("ix_coin_transfers_from_created", "from_user_id", "created_at"),
        sa.Index("ix_coin_transfers_to_created", "to_user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    to_user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 转账方支出（gross）
    amount: Mapped[int] = mapped_column(sa.BigInteger)
    # 手续费（销毁）
    fee: Mapped[int] = mapped_column(sa.BigInteger)
    # 收款方实收 = amount - fee
    net: Mapped[int] = mapped_column(sa.BigInteger)
    from_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    to_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

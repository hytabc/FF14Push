"""兑换码兑换记录。"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RedeemRecord(Base, TimestampMixin):
    """每个用户对同一个兑换码至多兑换一次。"""

    __tablename__ = "redeem_records"
    __table_args__ = (sa.UniqueConstraint("user_id", "code", name="uq_redeem_user_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(sa.String(64))
    gold: Mapped[int] = mapped_column(sa.BigInteger, default=0)

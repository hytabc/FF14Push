"""种田：账号级田地。初始 2 片，可用金币扩张至 10 片；作物按真实时间生长（离线也生长）。"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class FarmPlot(Base, TimestampMixin):
    """一片田地。空田（seed_id 为空）不落行；仅种植后创建。"""

    __tablename__ = "farm_plots"
    __table_args__ = (sa.UniqueConstraint("user_id", "index", name="uq_farm_user_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(sa.Integer)
    seed_id: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    planted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

"""魔晶石镶嵌：账号级 11 个战斗装备栏位，每栏 5 孔，不随装备更换而变化。"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MateriaSocket(Base, TimestampMixin):
    """一个已镶嵌的魔晶石。空孔不落行；孔位按 index 顺序填充（index 0 = 第 1 孔）。"""

    __tablename__ = "materia_sockets"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "slot", "index", name="uq_materia_user_slot_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    slot: Mapped[str] = mapped_column(sa.String(16))
    index: Mapped[int] = mapped_column(sa.Integer)
    materia_id: Mapped[str] = mapped_column(sa.String(32))

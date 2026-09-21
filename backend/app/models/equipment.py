"""装备与宝箱保底。

装备归属账号（而非英雄）：PRD 招募 2.4 要求解雇/替换英雄时装备不丢失。
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JsonType


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        sa.Index("ix_items_user_slot", "user_id", "equipped_slot"),
        sa.Index("ix_items_user_base", "user_id", "base_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    base_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    name: Mapped[str] = mapped_column(sa.String(64))
    category: Mapped[str] = mapped_column(sa.String(16))
    slot: Mapped[str] = mapped_column(sa.String(16))
    rarity: Mapped[str] = mapped_column(sa.String(16), index=True)
    level_req: Mapped[int] = mapped_column(sa.Integer, default=1)
    base_attrs: Mapped[list] = mapped_column(JsonType, default=list)
    sub_attrs: Mapped[list] = mapped_column(JsonType, default=list)
    terms: Mapped[list] = mapped_column(JsonType, default=list)
    refine_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    enchant_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    # 制造装备恒为「高品质」：属性区间整体上移且必带太古词条（与抽奖装备区分）
    high_quality: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false()
    )
    equipped_slot: Mapped[str | None] = mapped_column(sa.String(16), nullable=True, index=True)
    source: Mapped[str] = mapped_column(sa.String(32), default="chest")
    # 玩家自定义标签（ItemTag.id 列表），用于背包筛选
    tag_ids: Mapped[list] = mapped_column(JsonType, default=list)
    acquired_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    user: Mapped["User"] = relationship(back_populates="items")


class ItemTag(Base):
    """玩家自定义的装备标签（命名 + 调色板颜色），用于给装备打标并按标签筛选。"""

    __tablename__ = "item_tags"
    __table_args__ = (sa.UniqueConstraint("user_id", "name", name="uq_item_tags_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(sa.String(16))
    color: Mapped[str] = mapped_column(sa.String(16))
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class ChestPity(Base):
    __tablename__ = "chest_pity"
    __table_args__ = (sa.UniqueConstraint("user_id", "chest_type", name="uq_pity_user_chest"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    chest_type: Mapped[str] = mapped_column(sa.String(32))
    since_rare: Mapped[int] = mapped_column(sa.Integer, default=0)
    since_epic: Mapped[int] = mapped_column(sa.Integer, default=0)
    since_legendary: Mapped[int] = mapped_column(sa.Integer, default=0)

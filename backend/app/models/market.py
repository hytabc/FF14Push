"""玩家间交易板（市场）。

上架即从卖家背包 / 库存扣除进入托管，整单买断成交，成交价抽取手续费（金币回收）。
未售出到期自动退回卖家。归属账号（`user_id`），与装备 / 堆叠库存一致。
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonType, utcnow

# kind 取值：装备用 "equipment"，堆叠物沿用 StackItem 的 kind（material | potion | food）。
LISTING_KIND_EQUIPMENT = "equipment"

# status 取值
STATUS_ACTIVE = "active"
STATUS_SOLD = "sold"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"


class MarketListing(Base):
    __tablename__ = "market_listings"
    __table_args__ = (
        sa.Index("ix_market_listings_status_kind_price", "status", "kind", "unit_price"),
        sa.Index("ix_market_listings_seller_status", "seller_id", "status"),
        sa.Index("ix_market_listings_status_expires", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # equipment | material | potion | food
    kind: Mapped[str] = mapped_column(sa.String(16), index=True)
    # 装备 = 底材 base_id；堆叠 = 物品 id
    item_key: Mapped[str] = mapped_column(sa.String(48), index=True)
    name: Mapped[str] = mapped_column(sa.String(64))
    rarity: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    category: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    slot: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    level_req: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    quantity: Mapped[int] = mapped_column(sa.Integer, default=1)
    # 单价（装备即总价，装备恒为 1 件）
    unit_price: Mapped[int] = mapped_column(sa.BigInteger)
    # 上架时的系统回收价（参考值，仅供 UI 提示，不参与结算）
    reference_price: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    # 仅装备：完整物品快照，用于原样退回 / 交付买家
    snapshot: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(16), default=STATUS_ACTIVE, index=True)
    buyer_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sold_price: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    fee: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    seller_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    buyer_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

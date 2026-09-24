"""聊天室：单一大厅的滚动消息与 WebSocket 一次性票据。

- `ChatMessage`：大厅消息（普通发言 / 管理员公告）。聊天室「不保留聊天记录」，
  因此服务层只读取最近 `services/chat.RETENTION_SECONDS` 秒内的行，并在发言时清理过期行；
  表本身只是滚动暂存，并非长期归档。
- `ChatTicket`：WebSocket 不便于携带 Authorization 头，故先用 HTTP 申请短时效票据，
  连接 `/chat/ws?ticket=...` 时一次性核销（镜像 `CoopTicket`）。
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# kind 取值
KIND_NORMAL = "normal"
KIND_ANNOUNCEMENT = "announcement"


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"
    __table_args__ = (
        sa.Index("ix_chat_messages_created_at", "created_at"),
        # WS 广播按 (kind, id 游标) 增量读取普通发言 / 公告：复合索引避免 kind 过滤后回表排序。
        sa.Index("ix_chat_messages_kind_id", "kind", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(sa.String(16), default=KIND_NORMAL)
    text: Mapped[str] = mapped_column(sa.String(200))


class ChatTicket(Base):
    __tablename__ = "chat_tickets"

    token: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    expires_at: Mapped[float] = mapped_column(sa.Float)

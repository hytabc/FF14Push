"""玩家保存的生产 / 采集序列（自定义序列库）。

每个账号最多保存 `services.sequences.MAX_SEQUENCES_PER_USER` 条；每条带一个可分享的
「蓝图ID」（`share_code`），任何登录玩家凭该 ID 即可导入到自己的工作队列。
序列只保存编排（步骤 + 循环设置），运行断点仍由前端本地续传，不入库。
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonType, utcnow


class SequenceBlueprint(Base):
    """玩家自定义的生产 / 采集序列，带可分享的蓝图ID。"""

    __tablename__ = "sequence_blueprints"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "name", name="uq_sequence_blueprints_user_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(sa.String(24))
    steps: Mapped[list] = mapped_column(JsonType, default=list)
    loop_mode: Mapped[str] = mapped_column(sa.String(8), default="once")
    loop_total: Mapped[int] = mapped_column(sa.Integer, default=3)
    share_code: Mapped[str] = mapped_column(sa.String(12), unique=True, index=True)
    # 用 Python 侧 default/onupdate：SQL 表达式会让属性在 flush 后过期，序列化时触发同步懒加载。
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, server_default=sa.func.now()
    )
    updated_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=sa.func.now()
    )

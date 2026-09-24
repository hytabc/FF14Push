"""fishing 2.0: weather/time + per-fish intuition + active title

- `users.active_title_id`：佩戴中的称号（设置页最多选一个）。
- `activity_sessions.session_insights`：各特殊鱼的「捕鱼人之识」到期时间（一鱼一 BUFF）。
- `activity_sessions.session_intuition`：各特殊鱼的直觉前置累计（触发后清零）。
- 删除旧的单值 `activity_sessions.insight_expires_at`（已被 session_insights 取代）。
  `session_fish` 语义改为「fishId → 数量」计数表，无需 DDL。

Revision ID: v8b0d2f4a6c8
Revises: u7a9c1e3b5d7
Create Date: 2026-09-24 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'v8b0d2f4a6c8'
down_revision = 'u7a9c1e3b5d7'
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.add_column('users', sa.Column('active_title_id', sa.String(length=48), nullable=True))
    op.add_column(
        'activity_sessions',
        sa.Column('session_insights', JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        'activity_sessions',
        sa.Column('session_intuition', JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
    )
    op.drop_column('activity_sessions', 'insight_expires_at')


def downgrade() -> None:
    op.add_column(
        'activity_sessions',
        sa.Column('insight_expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_column('activity_sessions', 'session_intuition')
    op.drop_column('activity_sessions', 'session_insights')
    op.drop_column('users', 'active_title_id')

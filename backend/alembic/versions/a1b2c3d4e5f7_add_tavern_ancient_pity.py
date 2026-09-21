"""add tavern ancient pity

英雄「太古属性」保底：每 ancientPityCount（500）个候选至少出一个太古。
新增 tavern.ancient_pity 记录距上次出太古已生成的候选数，出太古后归零。

Revision ID: a1b2c3d4e5f7
Revises: f3a5b7c9d1e2
Create Date: 2026-09-21 10:10:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f7'
down_revision = 'f3a5b7c9d1e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tavern',
        sa.Column('ancient_pity', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('tavern', 'ancient_pity')

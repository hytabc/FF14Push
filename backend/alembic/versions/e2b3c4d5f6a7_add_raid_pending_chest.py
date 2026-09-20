"""add raid pending_chest

Revision ID: e2b3c4d5f6a7
Revises: d1a2b3c4e5f6
Create Date: 2026-09-20 22:40:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'e2b3c4d5f6a7'
down_revision = 'd1a2b3c4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'raid_sessions',
        sa.Column('pending_chest', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('raid_sessions', 'pending_chest')

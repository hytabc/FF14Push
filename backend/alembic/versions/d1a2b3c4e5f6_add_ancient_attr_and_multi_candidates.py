"""add ancient_attr and multi_candidates

Revision ID: d1a2b3c4e5f6
Revises: c4d18a7e5b93
Create Date: 2026-09-20 21:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd1a2b3c4e5f6'
down_revision = 'c4d18a7e5b93'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('heroes', sa.Column('ancient_attr', sa.String(length=8), nullable=True))
    op.add_column(
        'tavern',
        sa.Column(
            'multi_candidates',
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('tavern', 'multi_candidates')
    op.drop_column('heroes', 'ancient_attr')

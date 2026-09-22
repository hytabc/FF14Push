"""add dohdol_progress.total_exp

生产/采集累计经验：升级扣减与满级清零都不影响它，供排行榜使用。
存量行按当前等级曲线回填一个近似累计值（Σ exp_to_next(1..level-1) + 当前 exp）；
满级后历史溢出的经验无法还原，故仅作近似。

Revision ID: i6a8c0e2f4b6
Revises: h5b8d2f4a6c8
Create Date: 2026-09-22 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'i6a8c0e2f4b6'
down_revision = 'h5b8d2f4a6c8'
branch_labels = None
depends_on = None

# 与 shared/data/dohdol-levels.json 的 expCurve 一致（迁移自包含，不 import 应用配置）。
EXP_BASE = 80.0
EXP_GROWTH = 1.045

progress = sa.table(
    "dohdol_progress",
    sa.column("id", sa.Integer),
    sa.column("level", sa.Integer),
    sa.column("exp", sa.BigInteger),
    sa.column("total_exp", sa.BigInteger),
)


def _exp_to_next(level: int) -> int:
    return max(1, round(EXP_BASE * EXP_GROWTH ** max(0, level - 1)))


def _cumulative(level: int, exp: int) -> int:
    return sum(_exp_to_next(l) for l in range(1, int(level))) + int(exp)


def upgrade() -> None:
    op.add_column(
        "dohdol_progress",
        sa.Column("total_exp", sa.BigInteger(), nullable=False, server_default="0"),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.select(progress.c.id, progress.c.level, progress.c.exp)).fetchall()
    for row_id, level, exp in rows:
        bind.execute(
            progress.update()
            .where(progress.c.id == row_id)
            .values(total_exp=_cumulative(level, exp or 0))
        )


def downgrade() -> None:
    op.drop_column("dohdol_progress", "total_exp")

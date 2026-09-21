"""Versioned balance snapshots and server-issued mechanism trials."""
from alembic import op
import sqlalchemy as sa
revision = 'g4b6c8d0e2f4'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('raid_sessions', sa.Column('balance_snapshot',sa.JSON(),nullable=False,server_default='{}'))
    op.add_column('raid_sessions', sa.Column('outcome',sa.JSON(),nullable=False,server_default='{}'))
    op.create_table('mechanism_trials',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('scope',sa.String(40),nullable=False),sa.Column('version',sa.String(20),nullable=False),
        sa.Column('step',sa.Integer(),nullable=False),sa.Column('challenge',sa.Integer(),nullable=False),
        sa.Column('active',sa.Boolean(),nullable=False),sa.Column('passed',sa.Boolean(),nullable=False),
        sa.Column('issued_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_index('ix_mechanism_trials_user_id','mechanism_trials',['user_id'])

def downgrade():
    op.drop_table('mechanism_trials')
    op.drop_column('raid_sessions','outcome')
    op.drop_column('raid_sessions','balance_snapshot')

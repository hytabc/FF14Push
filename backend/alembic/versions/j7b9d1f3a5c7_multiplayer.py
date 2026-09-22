"""Eight hero roster and durable multiplayer. Existing sessions are stopped on upgrade."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = 'j7b9d1f3a5c7'
down_revision = 'i6a8c0e2f4b6'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for index in inspector.get_indexes('heroes'):
        if index.get('unique') and index['column_names'] == ['user_id']:
            op.drop_index(index['name'], table_name='heroes')
    for constraint in inspector.get_unique_constraints('heroes'):
        if constraint['column_names'] == ['user_id']:
            with op.batch_alter_table('heroes') as batch:
                batch.drop_constraint(constraint['name'], type_='unique')
    if not any(i['name'] == 'ix_heroes_user_id' and not i.get('unique') for i in inspector.get_indexes('heroes')):
        op.create_index('ix_heroes_user_id', 'heroes', ['user_id'])
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('active_hero_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_users_active_hero', 'heroes', ['active_hero_id'], ['id'], ondelete='SET NULL')
    with op.batch_alter_table('items') as batch:
        batch.add_column(sa.Column('equipped_hero_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_items_equipped_hero', 'heroes', ['equipped_hero_id'], ['id'], ondelete='SET NULL')
        batch.create_index('ix_items_equipped_hero_id', ['equipped_hero_id'])
        batch.create_unique_constraint('uq_hero_equipped_slot', ['equipped_hero_id', 'equipped_slot'])
    bind.execute(sa.text('UPDATE users SET active_hero_id = (SELECT MIN(id) FROM heroes WHERE heroes.user_id = users.id)'))
    bind.execute(sa.text("UPDATE items SET equipped_hero_id = (SELECT active_hero_id FROM users WHERE users.id = items.user_id) WHERE equipped_slot IS NOT NULL AND category NOT IN ('doh_tool','doh_gear','dol_tool','dol_gear')"))
    for table in ('battle_sessions', 'raid_sessions'):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('hero_id', sa.Integer(), nullable=True))
            batch.create_foreign_key('fk_' + table + '_hero', 'heroes', ['hero_id'], ['id'], ondelete='SET NULL')
        bind.execute(sa.text('UPDATE ' + table + ' SET hero_id = (SELECT active_hero_id FROM users WHERE users.id = ' + table + '.user_id)'))
    for table in ('battle_sessions','raid_sessions','activity_sessions'):
        bind.execute(sa.text('UPDATE ' + table + ' SET active = false, ended_at = CURRENT_TIMESTAMP WHERE active = true'))
    op.create_table('coop_progress',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('dungeon_id', sa.String(length=32), nullable=False, primary_key=False),
        sa.Column('clears', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('records', sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete=None),
        sa.UniqueConstraint('user_id', 'dungeon_id', name='uq_coop_progress'),
    )
    op.create_table('coop_rooms',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('code', sa.String(length=12), nullable=False, primary_key=False),
        sa.Column('owner_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('dungeon_id', sa.String(length=32), nullable=False, primary_key=False),
        sa.Column('mode', sa.String(length=12), nullable=False, primary_key=False),
        sa.Column('status', sa.String(length=16), nullable=False, primary_key=False),
        sa.Column('public', sa.Boolean(), nullable=False, primary_key=False),
        sa.Column('created_at', sa.Float(), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete=None),
        sa.UniqueConstraint('code', name=None),
    )
    op.create_index('ix_coop_rooms_status', 'coop_rooms', ['status'], unique=False)
    op.create_table('pvp_battles',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('attacker_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('defender_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('key', sa.String(length=64), nullable=False, primary_key=False),
        sa.Column('report', sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, primary_key=False),
        sa.Column('created_at', sa.Float(), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(['defender_id'], ['users.id'], ondelete=None),
        sa.ForeignKeyConstraint(['attacker_id'], ['users.id'], ondelete=None),
        sa.UniqueConstraint('attacker_id', 'key', name='uq_pvp_request'),
    )
    op.create_index('ix_pvp_battles_attacker_id', 'pvp_battles', ['attacker_id'], unique=False)
    op.create_index('ix_pvp_battles_defender_id', 'pvp_battles', ['defender_id'], unique=False)
    op.create_table('coop_battles',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('room_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('status', sa.String(length=16), nullable=False, primary_key=False),
        sa.Column('state', sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, primary_key=False),
        sa.Column('config', sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, primary_key=False),
        sa.Column('sequence', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('command_cursor', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('updated_at', sa.Float(), nullable=False, primary_key=False),
        sa.Column('lease_until', sa.Float(), nullable=False, primary_key=False),
        sa.Column('lease_owner', sa.String(length=64), nullable=True, primary_key=False),
        sa.ForeignKeyConstraint(['room_id'], ['coop_rooms.id'], ondelete=None),
        sa.UniqueConstraint('room_id', name=None),
    )
    op.create_index('ix_coop_battles_status', 'coop_battles', ['status'], unique=False)
    op.create_table('coop_members',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('room_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('user_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('ready', sa.Boolean(), nullable=False, primary_key=False),
        sa.Column('heartbeat_at', sa.Float(), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(['room_id'], ['coop_rooms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete=None),
        sa.UniqueConstraint('room_id', 'user_id', name='uq_room_member'),
    )
    op.create_index('ix_coop_members_user_id', 'coop_members', ['user_id'], unique=False)
    op.create_index('ix_coop_members_room_id', 'coop_members', ['room_id'], unique=False)
    op.create_table('coop_seats',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('room_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('slot', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('controller_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('hero_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('registration_id', sa.Integer(), nullable=True, primary_key=False),
        sa.Column('snapshot', sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(['controller_id'], ['users.id'], ondelete=None),
        sa.ForeignKeyConstraint(['room_id'], ['coop_rooms.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('room_id', 'slot', name='uq_room_seat'),
    )
    op.create_index('ix_coop_seats_room_id', 'coop_seats', ['room_id'], unique=False)
    op.create_table('coop_tickets',
        sa.Column('token', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('room_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('expires_at', sa.Float(), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete=None),
        sa.ForeignKeyConstraint(['room_id'], ['coop_rooms.id'], ondelete=None),
    )
    op.create_table('hero_registrations',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('hero_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('kind', sa.String(length=12), nullable=False, primary_key=False),
        sa.Column('active', sa.Boolean(), nullable=False, primary_key=False),
        sa.Column('snapshot', sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(['hero_id'], ['heroes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete=None),
        sa.UniqueConstraint('hero_id', 'kind', name='uq_registration_hero_kind'),
    )
    op.create_index('ix_hero_registrations_user_id', 'hero_registrations', ['user_id'], unique=False)
    op.create_table('coop_commands',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('battle_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('user_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('key', sa.String(length=64), nullable=False, primary_key=False),
        sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(['battle_id'], ['coop_battles.id'], ondelete=None),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete=None),
        sa.UniqueConstraint('battle_id', 'user_id', 'key', name='uq_coop_command'),
    )
    op.create_index('ix_coop_commands_battle_id', 'coop_commands', ['battle_id'], unique=False)
    op.create_table('coop_rewards',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('battle_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('user_id', sa.Integer(), nullable=False, primary_key=False),
        sa.Column('receipt', sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, primary_key=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete=None),
        sa.ForeignKeyConstraint(['battle_id'], ['coop_battles.id'], ondelete=None),
        sa.UniqueConstraint('battle_id', 'user_id', name='uq_coop_reward'),
    )

def downgrade():
    # Never silently discard seven heroes or multiplayer history.
    raise RuntimeError('Destructive downgrade is unsupported; restore the pre-migration backup.')

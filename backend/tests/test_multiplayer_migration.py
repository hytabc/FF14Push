"""Exercise the upgrade against an actual pre-DLC schema, not create_all(new metadata)."""
import importlib.util
from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

@pytest.mark.asyncio
async def test_sqlite_upgrade_preserves_existing_assets(tmp_path):
    engine=sa.create_engine('sqlite:///'+str(tmp_path/'old.db'))
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE users (id INTEGER PRIMARY KEY, gold BIGINT NOT NULL)')
        conn.exec_driver_sql('CREATE TABLE heroes (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, level INTEGER NOT NULL)')
        conn.exec_driver_sql('CREATE UNIQUE INDEX ix_heroes_user_id ON heroes(user_id)')
        conn.exec_driver_sql('CREATE TABLE items (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, category VARCHAR(16), equipped_slot VARCHAR(16))')
        for name in ['battle_sessions','raid_sessions','activity_sessions']:
            conn.exec_driver_sql(f'CREATE TABLE {name} (id INTEGER PRIMARY KEY, user_id INTEGER, active BOOLEAN, ended_at DATETIME)')
            conn.exec_driver_sql(f'INSERT INTO {name} VALUES(1,1,1,NULL)')
        conn.exec_driver_sql('INSERT INTO users VALUES(1,123456)')
        conn.exec_driver_sql('INSERT INTO heroes VALUES(7,1,42)')
        conn.exec_driver_sql("INSERT INTO items VALUES(1,1,'weapon','mainHand'),(2,1,'doh_tool','dohMainHand'),(3,1,'armor',NULL)")
        path=Path(__file__).resolve().parents[1]/'alembic/versions/j7b9d1f3a5c7_multiplayer.py'
        spec=importlib.util.spec_from_file_location('dlc_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with Operations.context(MigrationContext.configure(conn)):module.upgrade()
        assert conn.execute(sa.text('SELECT gold,active_hero_id FROM users')).one()==(123456,7)
        assert conn.execute(sa.text('SELECT id,equipped_hero_id FROM items ORDER BY id')).all()==[(1,7),(2,None),(3,None)]
        for name in ['battle_sessions','raid_sessions','activity_sessions']:
            assert conn.execute(sa.text(f'SELECT active FROM {name}')).scalar()==0
        conn.exec_driver_sql('INSERT INTO heroes VALUES(8,1,1)')
        assert conn.execute(sa.text('SELECT COUNT(*) FROM heroes')).scalar()==2
        assert 'coop_battles' in sa.inspect(conn).get_table_names()
    engine.dispose()

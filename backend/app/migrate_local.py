"""Upgrade pre-DLC create_all SQLite databases without deleting user data.
Stop API/worker first: DATABASE_URL=sqlite+aiosqlite:///./dev.db python -m app.migrate_local
"""
import asyncio,importlib.util,sqlite3
from pathlib import Path
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.database import engine
from app.models import Base


def upgrade_connection(connection):
    inspector=sa.inspect(connection)
    if 'users' not in inspector.get_table_names():
        Base.metadata.create_all(connection);return
    if 'active_hero_id' in {c['name'] for c in inspector.get_columns('users')}:
        Base.metadata.create_all(connection);return
    path=Path(__file__).resolve().parents[1]/'alembic/versions/j7b9d1f3a5c7_multiplayer.py'
    spec=importlib.util.spec_from_file_location('roster_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()

async def main():
    if engine.url.get_backend_name()!='sqlite':
        raise RuntimeError('Production PostgreSQL: use alembic upgrade head instead')
    database=engine.url.database
    if database and database!=':memory:' and Path(database).exists():
        backup=Path(database+'.before-dlc')
        if backup.exists():raise RuntimeError('Backup already exists; retain it and choose a new backup path before retrying')
        with sqlite3.connect(database) as source,sqlite3.connect(str(backup)) as target:source.backup(target)
    async with engine.begin() as connection:await connection.run_sync(upgrade_connection)
    await engine.dispose()
    print('Local roster schema ready; previous database retained as .before-dlc')

if __name__=='__main__':asyncio.run(main())

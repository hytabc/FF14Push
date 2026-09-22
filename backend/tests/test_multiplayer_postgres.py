"""Opt-in real PostgreSQL migration and concurrency integration.
DLC_TEST_DATABASE_URL must point at a DISPOSABLE database; this test recreates its public schema.
"""
import asyncio,os,subprocess
import pytest
from sqlalchemy import text,select
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from app.models import User,Hero,Item
from app.services.roster import lock_user

@pytest.mark.asyncio
async def test_postgres_migration_and_eight_hero_serialization():
    url=os.environ.get('DLC_TEST_DATABASE_URL')
    if not url:pytest.skip('DLC_TEST_DATABASE_URL not configured (requires disposable PostgreSQL database)')
    if os.environ.get('DLC_TEST_ALLOW_RESET')!='yes':pytest.fail('Set DLC_TEST_ALLOW_RESET=yes only for the disposable database')
    engine=create_async_engine(url);sessions=async_sessionmaker(engine,expire_on_commit=False)
    async with engine.begin() as c:
        await c.execute(text('DROP SCHEMA public CASCADE'));await c.execute(text('CREATE SCHEMA public'))
    env={**os.environ,'DATABASE_URL':url}
    await asyncio.to_thread(subprocess.run,['.venv/bin/alembic','upgrade','i6a8c0e2f4b6'],env=env,check=True,capture_output=True)
    async with engine.begin() as c:
        await c.execute(text("INSERT INTO users (id,username,password_hash,nickname,gold,created_at) VALUES (1,'migration_test','x','旧玩家',54321,NOW())"))
        await c.execute(text("INSERT INTO heroes (id,user_id,name,level,exp,talent,attr_bias,strength,agility,intellect,current_region_id,region_kill_count,is_initial,created_at) VALUES(1,1,'旧英雄',42,123,'rare','str',40,30,30,1,0,true,NOW())"))
    await asyncio.to_thread(subprocess.run,['.venv/bin/alembic','upgrade','head'],env=env,check=True,capture_output=True)
    async with sessions() as db:
        user=await db.get(User,1);assert user.gold==54321 and user.active_hero_id==1
        hero=await db.get(Hero,1);assert hero.level==42 and hero.exp==123
        # Explicit seed used id=1, advance SERIAL before concurrent inserts.
        await db.execute(text("SELECT setval(pg_get_serial_sequence('heroes','id'), 1)"));await db.commit()
    async def recruit_once(index):
        async with sessions() as db:
            user=await lock_user(db,1)
            ids=(await db.scalars(select(Hero.id).where(Hero.user_id==user.id))).all()
            if len(ids)>=8:return False
            db.add(Hero(user_id=1,name=f'并发{index}',talent='common',attr_bias='str',strength=33,agility=33,intellect=34))
            await db.commit();return True
    assert sum(await asyncio.gather(*(recruit_once(i) for i in range(16))))==7
    async with sessions() as db:assert len((await db.scalars(select(Hero))).all())==8
    await engine.dispose()

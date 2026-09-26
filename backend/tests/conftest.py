"""pytest 全局夹具：使用 SQLite 内存库跑接口测试。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import Base

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def _disable_egg_heroes(monkeypatch):
    """默认关闭彩蛋英雄随机：0.5% 概率会让既有资质/太古断言偶发失败。

    专门测试彩蛋生成时再自行把 `eggChance` 打开。
    """
    from app.services.game_config import CONFIG

    monkeypatch.setitem(CONFIG.egg_heroes, "eggChance", 0.0)


@pytest.fixture(autouse=True)
def _reset_live_ranking_cache():
    """实时榜（钓鱼/生活/远征）的聚合缓存与 `/game/config` 的响应缓存都是**进程级**的。

    生产由写入侧 `invalidate_live_rankings()` / 配置不变性保证；测试里每个用例用的是全新内存库，
    必须显式清空，否则上一个用例的状态会串进下一个用例。
    """
    from app.api.v1 import game as game_module
    from app.services import ishgard as ishgard_module
    from app.services import world_boss as world_boss_module
    from app.services.ranking import invalidate_live_rankings

    invalidate_live_rankings()
    world_boss_module.invalidate_contribution_rows()
    ishgard_module.invalidate_board_cache()
    game_module._CONFIG_RESPONSE = None
    yield
    invalidate_live_rankings()
    world_boss_module.invalidate_contribution_rows()
    ishgard_module.invalidate_board_cache()
    game_module._CONFIG_RESPONSE = None


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def client(session_factory):
    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(client):
    """已注册并登录的客户端。"""
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": "tester", "password": "secret123", "nickname": "光之战士"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["accessToken"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


@pytest.fixture
def anyio_backend():
    return "asyncio"

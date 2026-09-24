"""种田：田地扩张、真实时间生长、金币/经验种子收获与满级确认。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import FarmPlot, Hero, User
from app.services import dohdol_util, farm
from app.services.game_config import CONFIG

API = "/api/v1"


async def _user(session_factory) -> User:
    async with session_factory() as db:
        return (await db.execute(select(User))).scalars().first()


async def _set_gold(session_factory, amount: int) -> None:
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.gold = amount
        await db.commit()


async def _give_seed(session_factory, seed_id: str, count: int) -> None:
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        await dohdol_util.stack_add(db, user.id, dohdol_util.STACK_SEED, seed_id, count)
        await db.commit()


async def _age_plot(session_factory, index: int, seconds: int) -> None:
    async with session_factory() as db:
        row = (
            await db.execute(select(FarmPlot).where(FarmPlot.index == index))
        ).scalar_one()
        row.planted_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        await db.commit()


async def _set_hero_level(session_factory, level: int) -> int:
    async with session_factory() as db:
        hero = (await db.execute(select(Hero))).scalars().first()
        hero.level = level
        await db.commit()
        return int(hero.id)


async def _hero_level(session_factory) -> int:
    async with session_factory() as db:
        hero = (await db.execute(select(Hero))).scalars().first()
        return int(hero.level)


@pytest.mark.asyncio
async def test_initial_state(auth_client):
    data = (await auth_client.get(f"{API}/farm/state")).json()
    assert data["unlocked"] == 2
    assert data["initialPlots"] == 2
    assert data["maxPlots"] == 12
    assert len(data["plots"]) == 12
    assert [p["locked"] for p in data["plots"][:3]] == [False, False, True]
    assert data["expansionCost"] == CONFIG.farm["expansionCosts"][0]
    assert data["stages"] == 5
    assert data["stageSeconds"] == 600
    assert {s["id"] for s in data["seeds"]} == {"seed_gold", "seed_exp"}
    assert all(s["count"] == 0 for s in data["seeds"])


@pytest.mark.asyncio
async def test_expand_deducts_gold_and_caps(auth_client, session_factory):
    await _set_gold(session_factory, 10_000)
    too_poor = await auth_client.post(f"{API}/farm/expand")
    assert too_poor.status_code == 400
    assert "金币不足" in too_poor.json()["detail"]

    await _set_gold(session_factory, 10_000_000_000)
    gold_before = 10_000_000_000
    for step in range(10):  # 2 → 12
        resp = await auth_client.post(f"{API}/farm/expand")
        assert resp.status_code == 200, resp.text
        cost = CONFIG.farm["expansionCosts"][step]
        body = resp.json()
        assert body["cost"] == cost
        assert body["state"]["unlocked"] == 3 + step
        gold_before -= cost
        assert body["state"]["gold"] == gold_before
    assert (await auth_client.post(f"{API}/farm/expand")).status_code == 400


@pytest.mark.asyncio
async def test_plant_requires_seed_and_unlocked_plot(auth_client, session_factory):
    resp = await auth_client.post(f"{API}/farm/plant", json={"plotIndex": 0, "seedId": "seed_gold"})
    assert resp.status_code == 400
    assert "种子不足" in resp.json()["detail"]

    await _give_seed(session_factory, "seed_gold", 1)
    locked = await auth_client.post(f"{API}/farm/plant", json={"plotIndex": 2, "seedId": "seed_gold"})
    assert locked.status_code == 400
    assert "尚未解锁" in locked.json()["detail"]


@pytest.mark.asyncio
async def test_gold_seed_harvest(auth_client, session_factory):
    await _give_seed(session_factory, "seed_gold", 1)
    resp = await auth_client.post(f"{API}/farm/plant", json={"plotIndex": 0, "seedId": "seed_gold"})
    assert resp.status_code == 200, resp.text
    plot = resp.json()["state"]["plots"][0]
    assert plot["seedId"] == "seed_gold"
    assert plot["ready"] is False
    assert plot["stage"] == 0
    assert plot["remainingMs"] > 0

    # 未成熟不能收
    assert (await auth_client.post(f"{API}/farm/harvest", json={"plotIndex": 0})).status_code == 400

    # 同一块地不能重复种
    await _give_seed(session_factory, "seed_gold", 1)
    assert (
        await auth_client.post(f"{API}/farm/plant", json={"plotIndex": 0, "seedId": "seed_gold"})
    ).status_code == 400

    await _age_plot(session_factory, 0, 50 * 60)  # 5 阶段 × 10min
    state = (await auth_client.get(f"{API}/farm/state")).json()
    assert state["plots"][0]["ready"] is True
    assert state["plots"][0]["stage"] == 5

    gold_before = (await auth_client.get(f"{API}/game/state")).json()["user"]["gold"]
    resp = await auth_client.post(f"{API}/farm/harvest", json={"plotIndex": 0})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["type"] == "gold"
    assert body["result"]["amount"] == 10000000
    assert body["state"]["plots"][0]["seedId"] is None
    assert (await auth_client.get(f"{API}/game/state")).json()["user"]["gold"] == gold_before + 10000000


@pytest.mark.asyncio
async def test_stage_progress_is_monotonic(auth_client, session_factory):
    await _give_seed(session_factory, "seed_gold", 1)
    await auth_client.post(f"{API}/farm/plant", json={"plotIndex": 0, "seedId": "seed_gold"})
    for seconds, expected in ((0, 0), (600, 1), (1250, 2), (2940, 4), (3000, 5)):
        await _age_plot(session_factory, 0, seconds)
        plot = (await auth_client.get(f"{API}/farm/state")).json()["plots"][0]
        assert plot["stage"] == expected, seconds
        assert plot["ready"] is (seconds >= 3000), seconds


@pytest.mark.asyncio
async def test_exp_seed_levels_chosen_hero(auth_client, session_factory):
    hero_id = await _set_hero_level(session_factory, 10)
    await _give_seed(session_factory, "seed_exp", 1)
    await auth_client.post(f"{API}/farm/plant", json={"plotIndex": 1, "seedId": "seed_exp"})
    await _age_plot(session_factory, 1, 50 * 60)

    # 未指定英雄 → 拒绝
    assert (await auth_client.post(f"{API}/farm/harvest", json={"plotIndex": 1})).status_code == 400

    resp = await auth_client.post(
        f"{API}/farm/harvest", json={"plotIndex": 1, "heroId": hero_id}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["levelsGained"] == 1
    assert await _hero_level(session_factory) == 11


@pytest.mark.asyncio
async def test_exp_seed_max_level_needs_confirm(auth_client, session_factory):
    from app.services.progression import LEVEL_CAP

    hero_id = await _set_hero_level(session_factory, LEVEL_CAP)
    await _give_seed(session_factory, "seed_exp", 1)
    await auth_client.post(f"{API}/farm/plant", json={"plotIndex": 0, "seedId": "seed_exp"})
    await _age_plot(session_factory, 0, 50 * 60)

    resp = await auth_client.post(f"{API}/farm/harvest", json={"plotIndex": 0, "heroId": hero_id})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "hero_max_level"
    # 未确认：作物仍在
    assert (await auth_client.get(f"{API}/farm/state")).json()["plots"][0]["seedId"] == "seed_exp"

    resp = await auth_client.post(
        f"{API}/farm/harvest", json={"plotIndex": 0, "heroId": hero_id, "confirm": True}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["noEffect"] is True
    assert body["result"]["levelsGained"] == 0
    assert await _hero_level(session_factory) == LEVEL_CAP
    assert body["state"]["plots"][0]["seedId"] is None


@pytest.mark.asyncio
async def test_harvest_empty_plot_rejected(auth_client):
    assert (await auth_client.post(f"{API}/farm/harvest", json={"plotIndex": 0})).status_code == 400


@pytest.mark.asyncio
async def test_farm_helpers_expose_config():
    assert farm.initial_plots() == 2
    assert farm.max_plots() == 12
    assert farm.stages() == 5
    assert farm.total_seconds() == 3000
    assert farm.expansion_costs() == [int(c) for c in CONFIG.farm["expansionCosts"]]

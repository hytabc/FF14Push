"""品阶概率来源：远征 / 高难通关（难度加权·仅首通）与通用归一化。"""

from __future__ import annotations

import pytest

from app.models import CoopProgress, RaidProgress, User
from app.services.game_config import CONFIG
from app.services.luck_sources import (
    coop_clear_ref,
    coop_clear_score,
    luck_progress,
    raid_clear_ref,
    raid_clear_score,
)
from app.services.multiplayer_config import DUNGEONS, MULTIPLAYER


async def _user(session, name: str) -> User:
    user = User(username=name, password_hash="x", nickname=name)
    session.add(user)
    await session.flush()
    return user


def test_difficulty_tables_cover_every_difficulty() -> None:
    coop_weights = MULTIPLAYER["difficultyWeights"]
    raid_weights = CONFIG.raids["difficultyWeights"]
    assert {d["difficulty"] for d in DUNGEONS.values()} <= set(coop_weights)
    assert {r["difficulty"] for r in CONFIG.raids["raids"]} <= set(raid_weights)
    # 难度越高权重越高
    assert list(coop_weights.values()) == sorted(coop_weights.values())
    assert raid_weights["hard"] > raid_weights["normal"]


def test_refs_are_difficulty_weight_sums() -> None:
    coop_weights = MULTIPLAYER["difficultyWeights"]
    raid_weights = CONFIG.raids["difficultyWeights"]
    assert coop_clear_ref() == pytest.approx(
        sum(coop_weights[d["difficulty"]] for d in DUNGEONS.values())
    )
    assert raid_clear_ref() == pytest.approx(
        sum(raid_weights[r["difficulty"]] for r in CONFIG.raids["raids"])
    )
    assert coop_clear_ref() > 0 and raid_clear_ref() > 0


async def test_coop_score_counts_first_clear_only(session_factory) -> None:
    """远征：每个副本只按是否通关计一次，重复刷不叠加。"""
    weights = MULTIPLAYER["difficultyWeights"]
    async with session_factory() as session:
        user = await _user(session, "luck-coop")
        session.add_all(
            [
                CoopProgress(user_id=user.id, dungeon_id="ultimate_1", clears=7),
                CoopProgress(user_id=user.id, dungeon_id="normal_1", clears=1),
                CoopProgress(user_id=user.id, dungeon_id="normal_2", clears=0),
            ]
        )
        await session.flush()
        assert await coop_clear_score(session, user.id) == pytest.approx(
            weights["ultimate"] + weights["normal"]
        )


async def test_raid_score_counts_first_clear_only(session_factory) -> None:
    """高难：每个副本只按是否通关计一次，重复刷不叠加。"""
    weights = CONFIG.raids["difficultyWeights"]
    async with session_factory() as session:
        user = await _user(session, "luck-raid")
        session.add_all(
            [
                RaidProgress(user_id=user.id, raid_id="raid_h1", cleared=True, clear_count=9),
                RaidProgress(user_id=user.id, raid_id="raid_1", cleared=True, clear_count=1),
                RaidProgress(user_id=user.id, raid_id="raid_2", cleared=False, clear_count=0),
            ]
        )
        await session.flush()
        assert await raid_clear_score(session, user.id) == pytest.approx(
            weights["hard"] + weights["normal"]
        )


async def test_full_clear_reaches_ref(session_factory) -> None:
    """全通 → 该项恰好等于 ref（「全满 = 上限」）。"""
    async with session_factory() as session:
        user = await _user(session, "luck-all")
        session.add_all(
            [CoopProgress(user_id=user.id, dungeon_id=did, clears=1) for did in DUNGEONS]
        )
        session.add_all(
            [
                RaidProgress(user_id=user.id, raid_id=r["id"], cleared=True)
                for r in CONFIG.raids["raids"]
            ]
        )
        await session.flush()
        assert await coop_clear_score(session, user.id) == pytest.approx(coop_clear_ref())
        assert await raid_clear_score(session, user.id) == pytest.approx(raid_clear_ref())


def test_luck_progress_clamps_each_source_at_ref() -> None:
    sources = {"a": {"weight": 0.6, "ref": 10}, "b": {"weight": 0.4, "ref": 5}}
    progress, factors = luck_progress(sources, {"a": 999, "b": 5})
    assert progress == pytest.approx(1.0)
    assert sum(f["weight"] for f in factors) == pytest.approx(1.0)
    for factor in factors:
        assert 0.0 <= factor["norm"] <= 1.0

    # 缺省值视为 0；超出 ref 会被夹住，不会溢出
    assert luck_progress(sources, {})[0] == pytest.approx(0.0)
    assert luck_progress(sources, {"a": 5})[0] == pytest.approx(0.6 * 0.5)

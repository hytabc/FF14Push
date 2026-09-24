"""挖宝：入场扣费、逐层结算、门、宝箱、猜大小与互斥。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import TreasureRun, User
from app.services.game_config import CONFIG
from app.services.regions_util import boss_stats

API = "/api/v1"


async def _set_gold(session_factory, amount: int) -> None:
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.gold = amount
        await db.commit()


async def _gold(client) -> int:
    return (await client.get(f"{API}/game/state")).json()["user"]["gold"]


async def _age_floor(session_factory, run_id: int, ms: int = 5000) -> None:
    async with session_factory() as db:
        row = (
            await db.execute(select(TreasureRun).where(TreasureRun.id == run_id))
        ).scalar_one()
        row.floor_started_at = datetime.now(timezone.utc) - timedelta(milliseconds=ms)
        await db.commit()


def _force_random(monkeypatch, value: float) -> None:
    """控制服务端「随机数」（事件触发 / 门是否选对）。rng 实例（宝箱内容）不受影响。"""
    monkeypatch.setattr("app.services.treasure.random.random", lambda: value)


def _force_cards(monkeypatch, *values: int) -> None:
    seq = list(values)
    calls = {"i": 0}

    def fake(_a, _b):
        value = seq[min(calls["i"], len(seq) - 1)]
        calls["i"] += 1
        return value

    monkeypatch.setattr("app.services.treasure.random.randint", fake)


async def _start(client, session_factory, gold: int = 5_000_000) -> int:
    await _set_gold(session_factory, gold)
    resp = await client.post(f"{API}/treasure/start")
    assert resp.status_code == 200, resp.text
    return int(resp.json()["run"]["runId"])


async def _clear(client, session_factory, run_id: int):
    await _age_floor(session_factory, run_id)
    return await client.post(f"{API}/treasure/floor/clear", json={"runId": run_id})


async def _open(client, run_id: int):
    return await client.post(f"{API}/treasure/chest/open", json={"runId": run_id})


async def _door(client, run_id: int, door: int = 0):
    return await client.post(f"{API}/treasure/door/choose", json={"runId": run_id, "door": door})


@pytest.mark.asyncio
async def test_state_has_config_and_no_run(auth_client):
    data = (await auth_client.get(f"{API}/treasure/state")).json()
    assert data["run"] is None
    assert data["config"]["entryCost"] == 1_000_000
    assert data["config"]["floors"] == 5


@pytest.mark.asyncio
async def test_start_requires_gold(auth_client, session_factory):
    await _set_gold(session_factory, 10)
    resp = await auth_client.post(f"{API}/treasure/start")
    assert resp.status_code == 400
    assert "金币不足" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_start_deducts_and_matches_region40_boss(auth_client, session_factory):
    await _set_gold(session_factory, 5_000_000)
    resp = await auth_client.post(f"{API}/treasure/start")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cost"] == 1_000_000
    assert body["gold"] == 4_000_000
    run = body["run"]
    assert run["floor"] == 1
    assert run["status"] == "fighting"
    # 第 1 层 = 难度 0 的地区 40 关底 BOSS
    assert run["boss"]["id"] == boss_stats(40, 0)["id"] == "boss_r40"
    assert run["boss"]["hp"] == pytest.approx(boss_stats(40, 0)["hp"])

    # 第 5 层 = 难度 4
    assert boss_stats(40, 4)["hp"] > boss_stats(40, 0)["hp"]


@pytest.mark.asyncio
async def test_floor_clear_enforces_min_server_time(auth_client, session_factory):
    run_id = await _start(auth_client, session_factory)
    resp = await auth_client.post(f"{API}/treasure/floor/clear", json={"runId": run_id})
    assert resp.status_code == 400  # 未等待最短战斗时长
    await _age_floor(session_factory, run_id)
    assert (await _clear(auth_client, session_factory, run_id)).status_code == 200


@pytest.mark.asyncio
async def test_fast_floor_clear_is_accepted(auth_client, session_factory):
    """强练度玩家一两次出手即可打完本层（客户端一次出手最快约 0.75s）。

    最短计时若高于该物理下限，合法通关会被误报成「战斗时长异常」，
    客户端只能卡在无法结算的状态。这里只等 0.6s 也必须能正常结算。
    """
    run_id = await _start(auth_client, session_factory)
    await _age_floor(session_factory, run_id, 600)
    resp = await auth_client.post(f"{API}/treasure/floor/clear", json={"runId": run_id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["run"]["status"] == "cleared"


@pytest.mark.asyncio
async def test_wrong_door_ends_run_but_keeps_rewards(auth_client, session_factory, monkeypatch):
    run_id = await _start(auth_client, session_factory, gold=20_000_000)
    _force_random(monkeypatch, 0.9)  # 不触发事件
    await _clear(auth_client, session_factory, run_id)
    chest = (await _open(auth_client, run_id)).json()
    gold_after_chest = chest["gold"]
    assert chest["goldGained"] >= 0
    assert chest["run"]["status"] == "cleared"

    _force_random(monkeypatch, 0.9)  # 0.9 < 0.5 为假 → 选错门
    resp = await _door(auth_client, run_id, 1)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["correct"] is False
    assert body["run"]["status"] == "ended"
    assert body["run"]["endedReason"] == "wrong_door"
    # 已开箱奖励保留
    assert await _gold(auth_client) == gold_after_chest


@pytest.mark.asyncio
async def test_chest_requires_cleared_and_door_requires_chest(auth_client, session_factory, monkeypatch):
    run_id = await _start(auth_client, session_factory)
    assert (await _open(auth_client, run_id)).status_code == 400  # 未通关
    _force_random(monkeypatch, 0.9)
    await _clear(auth_client, session_factory, run_id)
    assert (await _door(auth_client, run_id)).status_code == 400  # 未开箱
    assert (await _open(auth_client, run_id)).status_code == 200
    assert (await _open(auth_client, run_id)).status_code == 400  # 不能重复开


@pytest.mark.asyncio
async def test_correct_door_advances_floor(auth_client, session_factory, monkeypatch):
    run_id = await _start(auth_client, session_factory)
    _force_random(monkeypatch, 0.9)
    await _clear(auth_client, session_factory, run_id)
    await _open(auth_client, run_id)
    _force_random(monkeypatch, 0.1)  # 0.1 < 0.5 → 选对
    body = (await _door(auth_client, run_id)).json()
    assert body["correct"] is True
    assert body["run"]["floor"] == 2
    assert body["run"]["status"] == "fighting"
    assert body["run"]["chestOpened"] is False
    assert body["run"]["boss"]["hp"] == pytest.approx(boss_stats(40, 1)["hp"])


@pytest.mark.asyncio
async def test_gamble_win_increases_and_lose_clears(auth_client, session_factory, monkeypatch):
    run_id = await _start(auth_client, session_factory)
    _force_random(monkeypatch, 0.0)  # 必然触发事件
    _force_cards(monkeypatch, 3)  # 首张牌 = 3
    body = (await _clear(auth_client, session_factory, run_id)).json()
    assert body["event"] is not None
    assert body["event"]["card"] == 3
    assert body["run"]["eventActive"] is True

    # 猜大，下一张 6 → 猜对，倍率 +50%
    _force_cards(monkeypatch, 6)
    win = (
        await auth_client.post(f"{API}/treasure/gamble", json={"runId": run_id, "guess": "high"})
    ).json()
    assert win["result"] == "win"
    assert win["multiplier"] == pytest.approx(1.5)
    assert win["cleared"] is False

    # 猜大，下一张 2 → 猜错，奖励清零并结束事件
    _force_cards(monkeypatch, 2)
    lose = (
        await auth_client.post(f"{API}/treasure/gamble", json={"runId": run_id, "guess": "high"})
    ).json()
    assert lose["result"] == "lose"
    assert lose["multiplier"] == 0.0
    assert lose["cleared"] is True
    assert lose["run"]["eventActive"] is False


@pytest.mark.asyncio
async def test_gamble_tie_keeps_reward(auth_client, session_factory, monkeypatch):
    run_id = await _start(auth_client, session_factory)
    _force_random(monkeypatch, 0.0)
    _force_cards(monkeypatch, 4)
    await _clear(auth_client, session_factory, run_id)
    _force_cards(monkeypatch, 4)  # 平局
    tie = (
        await auth_client.post(f"{API}/treasure/gamble", json={"runId": run_id, "guess": "high"})
    ).json()
    assert tie["result"] == "tie"
    assert tie["multiplier"] == pytest.approx(1.0)
    assert tie["cleared"] is False
    assert tie["guessesUsed"] == 1


@pytest.mark.asyncio
async def test_lost_gamble_clears_chest(auth_client, session_factory, monkeypatch):
    run_id = await _start(auth_client, session_factory)
    _force_random(monkeypatch, 0.0)
    _force_cards(monkeypatch, 5)
    await _clear(auth_client, session_factory, run_id)
    _force_cards(monkeypatch, 3)  # 猜大却变小 → 猜错清零
    await auth_client.post(f"{API}/treasure/gamble", json={"runId": run_id, "guess": "high"})
    # 事件已结束，可以开箱；倍率 0 → 无奖励
    resp = await _open(auth_client, run_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["goldGained"] == 0
    assert body["rewards"] == []


@pytest.mark.asyncio
async def test_gamble_limited_to_max_guesses(auth_client, session_factory, monkeypatch):
    run_id = await _start(auth_client, session_factory)
    _force_random(monkeypatch, 0.0)
    # 首张牌 1（事件生成），随后 2/3/4/5/6 依次变大 → 每次「猜大」都赢
    _force_cards(monkeypatch, 1, 2, 3, 4, 5, 6)
    await _clear(auth_client, session_factory, run_id)
    for step in range(5):
        body = (
            await auth_client.post(f"{API}/treasure/gamble", json={"runId": run_id, "guess": "high"})
        ).json()
        assert body["result"] == "win", step
        assert body["guessesUsed"] == step + 1
    assert body["finished"] is True
    assert body["run"]["eventActive"] is False
    assert body["multiplier"] == pytest.approx(1.0 + 0.5 * 5)


@pytest.mark.asyncio
async def test_chest_rewards_and_multiplier(auth_client, session_factory, monkeypatch):
    run_id = await _start(auth_client, session_factory, gold=20_000_000)
    _force_random(monkeypatch, 0.0)
    _force_cards(monkeypatch, 2)
    await _clear(auth_client, session_factory, run_id)
    _force_cards(monkeypatch, 8)  # 猜大赢一次 → 倍率 1.5
    await auth_client.post(f"{API}/treasure/gamble", json={"runId": run_id, "guess": "high"})
    await auth_client.post(f"{API}/treasure/gamble/stop", json={"runId": run_id})

    before = await _gold(auth_client)
    body = (await _open(auth_client, run_id)).json()
    assert body["multiplier"] == pytest.approx(1.5)
    assert body["rewards"], "宝箱至少应产出一条奖励"
    for reward in body["rewards"]:
        assert reward["kind"] in {"gold", "exp", "potion", "materia", "seed"}
    assert body["gold"] == before + body["goldGained"]


@pytest.mark.asyncio
async def test_fifth_floor_grants_bonus_and_completes(auth_client, session_factory, monkeypatch):
    run_id = await _start(auth_client, session_factory, gold=50_000_000)
    for floor in range(1, 6):
        _force_random(monkeypatch, 0.9)  # 不触发事件
        assert (await _clear(auth_client, session_factory, run_id)).status_code == 200
        body = (await _open(auth_client, run_id)).json()
        assert isinstance(body.get("newTitles"), list), "开箱响应应带彩蛋称号槽位"
        if floor < 5:
            _force_random(monkeypatch, 0.1)  # 门选对
            door = (await _door(auth_client, run_id)).json()
            assert door["correct"] is True and door["run"]["floor"] == floor + 1
        else:
            assert body["completed"] is True
            assert body["bonusGold"] > 0
            assert body["run"]["status"] == "ended"
            assert body["run"]["endedReason"] == "completed"
            assert any(r["kind"] == "bonusGold" for r in body["rewards"])


@pytest.mark.asyncio
async def test_retry_resets_floor_timer(auth_client, session_factory):
    run_id = await _start(auth_client, session_factory)
    # 未到最短时长直接重试 → 重置计时后可结算
    resp = await auth_client.post(f"{API}/treasure/retry", json={"runId": run_id})
    assert resp.status_code == 200
    assert resp.json()["run"]["floor"] == 1
    await _age_floor(session_factory, run_id)
    assert (await _clear(auth_client, session_factory, run_id)).status_code == 200


@pytest.mark.asyncio
async def test_abandon_ends_run(auth_client, session_factory):
    run_id = await _start(auth_client, session_factory)
    body = (await auth_client.post(f"{API}/treasure/abandon", json={"runId": run_id})).json()
    assert body["run"]["status"] == "ended"
    assert body["run"]["endedReason"] == "abandoned"
    assert (await auth_client.get(f"{API}/treasure/state")).json()["run"] is None


@pytest.mark.asyncio
async def test_other_activity_ends_run(auth_client, session_factory):
    """互斥：开始地区战斗会结束进行中的挖宝（已入账奖励不受影响）。"""
    run_id = await _start(auth_client, session_factory)
    resp = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
    assert resp.status_code == 200, resp.text
    assert (await auth_client.get(f"{API}/treasure/state")).json()["run"] is None


@pytest.mark.asyncio
async def test_egg_gold_bonus_applies_to_chest_gold(auth_client, session_factory, monkeypatch):
    """彩蛋被动「金主」：挖宝金币奖励 +10%（含下底附赠）。"""
    from app.services import treasure as treasure_svc

    # 固定金币基数与奖励种类，让断言可复现。
    monkeypatch.setattr(treasure_svc, "roll_gold", lambda *a, **k: 1000)
    monkeypatch.setattr(treasure_svc, "_pick_kind", lambda _rng: "gold")

    async def gold_gained(bonus: float) -> int:
        monkeypatch.setattr(treasure_svc, "treasure_gold_bonus", lambda _egg_id: bonus)
        run_id = await _start(auth_client, session_factory, gold=20_000_000)
        _force_random(monkeypatch, 0.9)  # 不触发猜大小
        await _clear(auth_client, session_factory, run_id)
        body = (await _open(auth_client, run_id)).json()
        assert body["rewards"] and all(r["kind"] == "gold" for r in body["rewards"])
        return int(body["goldGained"])

    baseline = await gold_gained(0.0)
    boosted = await gold_gained(0.1)
    assert baseline > 0
    assert boosted == pytest.approx(baseline * 1.1, abs=2)


@pytest.mark.asyncio
async def test_cannot_touch_other_players_run(auth_client, session_factory):
    run_id = await _start(auth_client, session_factory)
    assert (
        await auth_client.post(f"{API}/treasure/chest/open", json={"runId": run_id + 9999})
    ).status_code == 404

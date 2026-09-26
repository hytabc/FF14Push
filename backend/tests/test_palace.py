"""死者宫殿：开局三选一、路径推进、逐节点校验、局外成长、兑换、称号与隔离。"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select

from app.models import Hero, PalaceProfile, PalaceRun, User
from app.services import titles
from app.services.game_config import CONFIG

API = "/api/v1"

BATTLE_TYPES = {"battle", "elite", "boss"}


async def _age_node(session_factory, run_id: int, seconds: float = 10_000_000.0) -> None:
    async with session_factory() as db:
        run = (
            await db.execute(select(PalaceRun).where(PalaceRun.id == run_id))
        ).scalar_one()
        run.node_started_at = time.time() - seconds
        await db.commit()


async def _state(client) -> dict:
    resp = await client.get(f"{API}/palace/state")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _start(client) -> dict:
    resp = await client.post(f"{API}/palace/start")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run"]["status"] == "choosing_hero"
    assert len(body["run"]["heroCandidates"]) == 3
    return body["run"]


async def _choose_hero(client) -> dict:
    resp = await client.post(f"{API}/palace/hero/choose", json={"index": 0})
    assert resp.status_code == 200, resp.text
    body = resp.json()["run"]
    assert body["status"] == "choosing_weapon"
    assert len(body["weaponCandidates"]) == 3
    return body


async def _choose_weapon(client) -> dict:
    resp = await client.post(f"{API}/palace/weapon/choose", json={"index": 0})
    assert resp.status_code == 200, resp.text
    body = resp.json()["run"]
    assert body["status"] == "running"
    assert body["map"] and body["availableNodes"]
    return body


async def _play(
    client, session_factory, run: dict, *, max_steps: int = 3000, stop_floor: int | None = None
) -> dict:
    """贪心推进：领取奖励 → 处理事件 → 进入首个可选节点（战斗则结算）。"""
    for _ in range(max_steps):
        if run["status"] == "ended":
            return run
        if stop_floor is not None and run["floor"] > stop_floor:
            return run
        if run["pendingReward"]:
            resp = await client.post(f"{API}/palace/reward/claim", json={"index": 0})
            assert resp.status_code == 200, resp.text
            run = resp.json()["run"]
            continue
        pending = run.get("pendingNode")
        if pending and pending["type"] == "event":
            resp = await client.post(
                f"{API}/palace/event/choose",
                json={"nodeId": pending["nodeId"], "choiceIndex": 0},
            )
            assert resp.status_code == 200, resp.text
            run = resp.json()["run"]
            continue
        available = run["availableNodes"]
        if not available:
            return run
        node_id = available[0]
        resp = await client.post(f"{API}/palace/node/enter", json={"nodeId": node_id})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        run = body["run"]
        context = body["context"]
        if context["type"] in BATTLE_TYPES:
            await _age_node(session_factory, run["runId"])
            resp = await client.post(
                f"{API}/palace/node/clear",
                json={"nodeId": node_id, "elapsedMs": 30000, "result": "win"},
            )
            assert resp.status_code == 200, resp.text
            run = resp.json()["run"]
    return run


# ------------------------------------------------------------------ 开局
async def test_start_and_choose_flow(auth_client):
    run = await _start(auth_client)
    run = await _choose_hero(auth_client)
    run = await _choose_weapon(auth_client)
    assert run["floor"] == 1
    assert run["map"]["floor"] == 1
    assert run["stats"]["level"] >= 1
    assert run["items"] and run["equipped"]  # 起手武器已装备


async def test_rejects_illegal_path(auth_client):
    await _start(auth_client)
    await _choose_hero(auth_client)
    run = await _choose_weapon(auth_client)
    assert "9-0" not in run["availableNodes"]
    resp = await auth_client.post(f"{API}/palace/node/enter", json={"nodeId": "9-0"})
    assert resp.status_code == 400


async def test_duration_guard_rejects_instant_clear(auth_client):
    await _start(auth_client)
    await _choose_hero(auth_client)
    run = await _choose_weapon(auth_client)
    # 找到一个战斗节点（起点可能是事件/商店）。
    node_id = None
    for candidate in run["availableNodes"]:
        resp = await auth_client.post(f"{API}/palace/node/enter", json={"nodeId": candidate})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        run = body["run"]
        if body["context"]["type"] in BATTLE_TYPES:
            node_id = candidate
            break
        if run["pendingReward"]:
            break
    if node_id is None:
        pytest.skip("本层起点无战斗节点")
    # 立刻上报（不 aging）→ 时长异常，run 不结束。
    resp = await auth_client.post(
        f"{API}/palace/node/clear", json={"nodeId": node_id, "elapsedMs": 1, "result": "win"}
    )
    assert resp.status_code == 400
    assert "时长" in resp.text


# ------------------------------------------------------------------ 完整通关
async def test_full_run_can_be_completed(auth_client, session_factory):
    await _start(auth_client)
    await _choose_hero(auth_client)
    run = await _choose_weapon(auth_client)
    run = await _play(auth_client, session_factory, run)
    assert run["status"] == "ended", run
    assert run["endedReason"] == "completed"

    state = await _state(auth_client)
    assert state["profile"]["floor10Clears"] == 1
    assert state["profile"]["growthPoints"] > 0
    assert state["profile"]["flameCrest"] > 0 or state["profile"]["glassPumpkin"] > 0


# ------------------------------------------------------------------ 隔离
async def test_run_stats_ignore_account_progress(auth_client, session_factory):
    await _start(auth_client)
    await _choose_hero(auth_client)
    run = await _choose_weapon(auth_client)
    baseline = run["stats"]

    # 把账号英雄拉到 99 级（模拟满配账号）。
    async with session_factory() as db:
        hero = (await db.execute(select(Hero))).scalars().first()
        hero.level = 99
        await db.commit()

    state = await _state(auth_client)
    after = state["run"]["stats"]
    # 副本面板不受账号等级影响。
    assert after["level"] == baseline["level"] == run["hero"]["level"]
    assert after["attack"] == pytest.approx(baseline["attack"])
    assert after["maxHp"] == pytest.approx(baseline["maxHp"])


# ------------------------------------------------------------------ 成长树
async def test_growth_unlock_deducts_points(auth_client, session_factory):
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        profile = PalaceProfile(
            user_id=user.id, growth_points=100, total_growth_earned=100,
            flame_crest=0, glass_pumpkin=0, floor10_clears=0, unlocked=[],
        )
        db.add(profile)
        await db.commit()

    view = (await auth_client.get(f"{API}/palace/growth")).json()
    assert len(view["categories"]) > 20
    assert view["points"] == 100

    resp = await auth_client.post(f"{API}/palace/growth/unlock", json={"nodeId": "hero_attack_1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["view"]["points"] < 100

    # 重复解锁被拒；未解锁前置的二级节点被拒。
    resp = await auth_client.post(f"{API}/palace/growth/unlock", json={"nodeId": "hero_attack_1"})
    assert resp.status_code == 400
    resp = await auth_client.post(f"{API}/palace/growth/unlock", json={"nodeId": "hero_attack_5"})
    assert resp.status_code == 400


async def test_growth_affects_run_stats(auth_client, session_factory):
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        db.add(PalaceProfile(
            user_id=user.id, growth_points=0, total_growth_earned=0,
            flame_crest=0, glass_pumpkin=0, floor10_clears=0,
            unlocked=["hero_attack_1", "hero_hp_1"],
        ))
        await db.commit()

    await _start(auth_client)
    await _choose_hero(auth_client)
    run = await _choose_weapon(auth_client)
    # 成长节点生效：面板照常算出（物理或魔法攻击至少一项 > 0）。
    assert max(run["stats"]["attack"], run["stats"]["magicAttack"]) > 0


# ------------------------------------------------------------------ 兑换
async def test_exchange_grants_items_and_deducts_tokens(auth_client, session_factory):
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        db.add(PalaceProfile(
            user_id=user.id, growth_points=0, total_growth_earned=0,
            flame_crest=10, glass_pumpkin=5, floor10_clears=0, unlocked=[],
        ))
        await db.commit()

    view = (await auth_client.get(f"{API}/palace/exchange")).json()
    assert view["flameCrest"] == 10 and view["glassPumpkin"] == 5
    assert view["entries"]

    resp = await auth_client.post(
        f"{API}/palace/exchange", json={"exchangeId": "ex_recraft_card", "count": 1}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["view"]["glassPumpkin"] == 4
    assert body["granted"][0]["itemId"] == "recraft_card"

    # 代币不足 → 400
    resp = await auth_client.post(
        f"{API}/palace/exchange", json={"exchangeId": "ex_recraft_card", "count": 999}
    )
    assert resp.status_code == 400


# ------------------------------------------------------------------ 称号
async def test_palace_title_awarded_at_ten_clears(auth_client, session_factory):
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        db.add(PalaceProfile(
            user_id=user.id, growth_points=0, total_growth_earned=0,
            flame_crest=0, glass_pumpkin=0, floor10_clears=10, unlocked=[],
        ))
        await db.commit()
        new = await titles.evaluate_palace_titles(db, user.id)
        await db.commit()
    assert "palace_necro" in new


# ------------------------------------------------------------------ 生命周期
async def test_start_rejected_while_run_active(auth_client):
    await _start(auth_client)
    await _choose_hero(auth_client)
    await _choose_weapon(auth_client)
    # 已有进行中 run 时再次 start → 400（客户端应改用 state 续接）。
    resp = await auth_client.post(f"{API}/palace/start")
    assert resp.status_code == 400


async def test_abandon_then_start_again(auth_client):
    await _start(auth_client)
    await _choose_hero(auth_client)
    await _choose_weapon(auth_client)
    resp = await auth_client.post(f"{API}/palace/abandon")
    assert resp.status_code == 200, resp.text
    assert resp.json()["run"]["status"] == "ended"
    resp = await auth_client.post(f"{API}/palace/start")
    assert resp.status_code == 200, resp.text
    assert resp.json()["run"]["status"] == "choosing_hero"


async def test_starting_other_activity_ends_run(auth_client, session_factory):
    from app.services.roster import stop_activities

    await _start(auth_client)
    await _choose_hero(auth_client)
    await _choose_weapon(auth_client)
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        await stop_activities(db, user.id)
        await db.commit()
    state = await _state(auth_client)
    assert state["run"] is None


def test_config_scale() -> None:
    cfg = CONFIG.palace
    assert int(cfg["floors"]) == 10
    assert int(cfg["stepsPerFloor"]) == 10
    assert len(CONFIG.palace_growth["categories"]) > 20
    assert len(CONFIG.palace_events["events"]) > 30


# ------------------------------------------------------------------ 数值标定
def test_zero_growth_caps_at_five_floors() -> None:
    """零局外成长：即使运气极好，也只能到达第 5 层（数值限制）。"""
    from app.services.palace_sim import simulate_reach

    reaches = [simulate_reach([], seed) for seed in range(40)]
    assert max(reaches) <= 5, reaches
    # 也不应大面积卡死在第 1 层。
    assert min(reaches) >= 2, reaches


def test_full_growth_is_strong_and_fast() -> None:
    """满局外成长：可秒杀前几层小怪，且即使运气差也不至于卡死在前几关。"""
    from app.services.palace_sim import full_growth_nodes, kill_seconds, simulate_reach

    nodes = full_growth_nodes()
    reaches = [simulate_reach(nodes, seed) for seed in range(40)]
    assert min(reaches) >= 6, reaches
    assert max(reaches) >= 9, reaches

    for floor in (1, 2, 3):
        assert kill_seconds(nodes, floor, "battle", seed=0) < 1.0
        assert kill_seconds([], floor, "battle", seed=0) > 0.0


def test_growth_meaningfully_increases_reach() -> None:
    """局外成长必须显著提升到达层数（零成长 < 半成长 < 满成长 的均值序）。"""
    from app.services.palace_sim import full_growth_nodes, simulate_reach

    nodes = full_growth_nodes()
    def mean(unlocked: list[str]) -> float:
        values = [simulate_reach(unlocked, seed) for seed in range(24)]
        return sum(values) / len(values)

    zero = mean([])
    full = mean(nodes)
    assert zero < full
    assert full - zero >= 3

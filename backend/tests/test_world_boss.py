"""世界BOSS：引擎、全局血量 / 刷新、总伤害榜与奖励结算回归测试。"""

from __future__ import annotations

import time

from sqlalchemy import select

from app.models import Hero, User
from app.models.world_boss import (
    SESSION_ENDED,
    SESSION_RUNNING,
    STATUS_ALIVE,
    STATUS_DEAD,
    WorldBoss,
    WorldBossContribution,
    WorldBossReward,
    WorldBossSession,
)
from app.services.game_config import CONFIG
from app.services.loot import base_items_for_category
from app.services.world_boss import (
    BOSS_ID,
    claim_reward,
    ensure_world_boss,
    hero_slots,
    hero_breakdown,
    leaderboard_view,
    level_multiplier,
    merge_party,
    phase_for_ratio,
    rank_bonus_items,
    reward_items,
    roll_world_boss,
    tier_for_damage,
    unclaimed_cycle,
)
from app.services.worldboss_engine import advance, damage_hero, new_state
from app.worldboss_worker import tick_worldboss

API = "/api/v1"
WB = CONFIG.worldboss


def _hero_snapshot(index: int, level: int = 100, multiplier: float = 1.0) -> dict:
    return {
        "heroId": 1000 + index,
        "name": f"hero-{index}",
        "jobId": "PLD",
        "level": level,
        "role": "dps",
        "levelMultiplier": multiplier,
        "stats": {
            "max_hp": 144112,
            "max_mp": 1500,
            "mp_regen": 14,
            "hp_regen": 50,
            "attack": 38060,
            "magic_attack": 1000,
            "crit_rate_pct": 20,
            "crit_damage_pct": 160,
            "det_bonus_pct": 10,
            "attack_speed_pct": 10,
            "phys_def": 5002,
            "magic_def": 3600,
            "main_attr": "str",
        },
        "skills": [
            {"id": "s1", "name": "skill", "potency": 200, "cd": 3, "mpCost": 50, "priority": 1, "effects": []}
        ],
        "skillMultiplier": 1.0,
        "healing": 4000,
        "dps": 74000,
    }


async def _seed_player(sessions, username: str, level: int = 100) -> tuple[int, int]:
    async with sessions() as db:
        user = User(username=username, password_hash="x", nickname=username, gold=0)
        db.add(user)
        await db.flush()
        hero = Hero(user_id=user.id, name=username, level=level, talent="common", attr_bias="balanced")
        db.add(hero)
        await db.flush()
        user.active_hero_id = hero.id
        await db.commit()
        return user.id, hero.id


# ---------------------------------------------------------------- 引擎


def test_engine_is_deterministic_and_runs_skills():
    cfg = WB
    state = new_state(cfg, [_hero_snapshot(i) for i in range(8)], seed=7)
    advance(state, cfg, 30_000)
    again = new_state(cfg, [_hero_snapshot(i) for i in range(8)], seed=7)
    advance(again, cfg, 30_000)
    assert state["damageDealt"] == again["damageDealt"] > 0
    assert state["boss"]["skillCasts"] >= 4, "6 秒间隔、30 秒应释放多次技能"
    pool_ids = {s["id"] for s in cfg["boss"]["skillPool"]}
    casts = [e.get("skillId") for e in state["events"] if e["kind"] == "bossSkill"]
    assert casts and set(casts) <= pool_ids


def test_engine_death_and_independent_revive():
    cfg = WB
    state = new_state(cfg, [_hero_snapshot(i) for i in range(8)], seed=3)
    advance(state, cfg, 20_000)
    dead = [h for h in state["heroes"] if h["hp"] <= 0]
    assert dead, "低防英雄应被 BOSS 击杀"
    for hero in dead:
        assert hero["deadUntil"] - state["elapsedMs"] <= int(cfg["boss"]["reviveSeconds"]) * 1000 + 100
    advance(state, cfg, int(cfg["boss"]["reviveSeconds"]) * 1000 + 200)
    assert any(h["hp"] > 0 for h in state["heroes"]), "到点后英雄应独立复活"


def test_damage_hero_never_leaves_sub_one_hp():
    """小数伤害不应让英雄残留 (0,1) 生命值——否则会出现「显示 0 血却仍可战斗」。"""
    cfg = WB
    state = new_state(cfg, [_hero_snapshot(i) for i in range(8)], seed=1)
    hero = state["heroes"][0]
    hero["hp"] = 100.0
    damage_hero(state, hero, 99.5, "test")
    assert hero["hp"] == 0
    assert hero["deaths"] == 1
    assert hero["deadUntil"] > state["elapsedMs"]


def test_level_multiplier_curve():
    assert level_multiplier(80) == 0.1
    assert level_multiplier(100) == 1.0
    assert 0.5 < level_multiplier(90) < 0.6


def test_phase_for_ratio_boundaries():
    assert phase_for_ratio(1.0)["id"] == 1
    assert phase_for_ratio(0.6)["id"] == 1
    assert phase_for_ratio(0.59)["id"] == 2
    assert phase_for_ratio(0.3)["id"] == 2
    assert phase_for_ratio(0.29)["id"] == 3
    assert phase_for_ratio(0.0)["id"] == 3


def test_engine_phase_escalation():
    """血量越低：BOSS 防御越厚（英雄输出折算）、技能威力越高。"""
    cfg = WB
    high = new_state(cfg, [_hero_snapshot(i) for i in range(8)], seed=5)
    high["bossHpRatio"] = 0.9
    advance(high, cfg, 10_000)
    assert high["phase"] == 1 and high["defenseMultiplier"] == 1.0
    assert high["skillPotencyMultiplier"] == 1.0

    low = new_state(cfg, [_hero_snapshot(i) for i in range(8)], seed=5)
    low["bossHpRatio"] = 0.1
    advance(low, cfg, 10_000)
    assert low["phase"] == 3 and low["defenseMultiplier"] > 1.0
    assert low["skillPotencyMultiplier"] > high["skillPotencyMultiplier"]
    assert low["damageDealt"] < high["damageDealt"] * 0.6, "P3 防御提升应显著压低英雄输出"

    # 阶段切换会写入日志事件
    events = [e for e in low["events"] if e["kind"] == "phase"]
    assert events and events[-1]["phase"] == 3


# ---------------------------------------------------------------- 全局血量 / 刷新


async def test_seed_worker_damages_and_kills_boss(session_factory):
    uid, _ = await _seed_player(session_factory, "wb_player")
    async with session_factory() as db:
        boss = await ensure_world_boss(db)
        assert boss.status == STATUS_ALIVE and boss.hp == boss.max_hp == 2_000_000_000
        boss.hp = 500_000  # 便于在测试中击杀
        state = new_state(WB, [_hero_snapshot(i) for i in range(8)], seed=11)
        db.add(
            WorldBossSession(
                boss_id=BOSS_ID,
                cycle=boss.cycle,
                user_id=uid,
                status=SESSION_RUNNING,
                state=state,
                sequence=1,
                damage=0,
                heartbeat_at=time.time(),
                lease_until=0,
                updated_at=time.time() - 1,
                created_at=time.time(),
            )
        )
        await db.commit()

    now = time.time()
    for step in range(40):
        await tick_worldboss(session_factory, "test", now + step)
        async with session_factory() as db:
            boss = await db.get(WorldBoss, BOSS_ID)
            if boss.status == STATUS_DEAD:
                break

    async with session_factory() as db:
        boss = await db.get(WorldBoss, BOSS_ID)
        contribution = await db.scalar(select(WorldBossContribution).where(WorldBossContribution.user_id == uid))
        sessions = (await db.scalars(select(WorldBossSession).where(WorldBossSession.user_id == uid))).all()
    assert boss.status == STATUS_DEAD
    assert boss.hp == 0
    assert boss.respawn_at and boss.respawn_at > boss.killed_at
    assert int(boss.kills) == 1, "周期内击杀只累加击杀数，不换轮"
    assert 0 < boss.respawn_at - boss.killed_at <= 300, "击杀后应是短暂休整"
    assert int(contribution.damage) > 0
    assert contribution.party and contribution.party[0]["damage"] >= 0
    assert all(s.status == SESSION_RUNNING for s in sessions), "击杀不结束会话，可继续讨伐下一个化身"


async def test_intra_period_kill_revives_without_new_cycle(session_factory):
    """周期内击杀后的短休整复活：满血、alive，但 cycle 不变（可反复讨伐）。"""
    async with session_factory() as db:
        boss = await ensure_world_boss(db)
        boss.status = STATUS_DEAD
        boss.hp = 0
        boss.kills = 3
        boss.respawn_at = time.time() - 1
        boss.period_ends_at = time.time() + 3600  # 周期尚未结束
        cycle_before = boss.cycle
        await db.commit()

    async with session_factory() as db:
        changed = await roll_world_boss(db)
        await db.commit()
        boss = await db.get(WorldBoss, BOSS_ID)
    assert changed is True
    assert boss.status == STATUS_ALIVE
    assert boss.hp == boss.max_hp
    assert boss.cycle == cycle_before, "周期内复活不换轮"
    assert int(boss.kills) == 3


async def test_period_rollover_starts_new_cycle_and_ends_sessions(session_factory):
    """周期到时：cycle+1、满血、kills 归零，并结束上一周期全部会话。"""
    uid, _ = await _seed_player(session_factory, "wb_roll")
    now = time.time()
    async with session_factory() as db:
        boss = await ensure_world_boss(db)
        cycle_before = boss.cycle
        boss.status = STATUS_ALIVE
        boss.hp = boss.max_hp // 2
        boss.kills = 2
        boss.period_ends_at = now - 1
        db.add(
            WorldBossSession(
                boss_id=BOSS_ID,
                cycle=cycle_before,
                user_id=uid,
                status=SESSION_RUNNING,
                state=new_state(WB, [_hero_snapshot(0)], seed=1),
                sequence=1,
                damage=0,
                heartbeat_at=now,
                lease_until=0,
                updated_at=now,
                created_at=now,
            )
        )
        await db.commit()

    async with session_factory() as db:
        changed = await roll_world_boss(db)
        await db.commit()
        boss = await db.get(WorldBoss, BOSS_ID)
        sessions = (await db.scalars(select(WorldBossSession).where(WorldBossSession.user_id == uid))).all()
    assert changed is True
    assert boss.status == STATUS_ALIVE
    assert boss.hp == boss.max_hp
    assert boss.cycle == cycle_before + 1
    assert int(boss.kills) == 0
    assert all(s.status == SESSION_ENDED for s in sessions), "换轮后上一周期会话应全部结束"


# ---------------------------------------------------------------- 档位奖励


def test_reward_items_tiers_and_rank_bonus():
    """奖励 = 档位（周期累计伤害）+ 名次加成（仅前 10 名）。"""
    # 未达门槛：无档位、无奖励
    assert tier_for_damage(4_999_999) == (0, 0)
    assert reward_items(1, 4_999_999) == 0
    # 保底档：达标即有 1 件
    assert tier_for_damage(5_000_000)[1] == 1
    assert reward_items(50, 5_000_000) == 1
    # 档位随伤害递增
    assert tier_for_damage(50_000_000)[1] == 2
    assert tier_for_damage(200_000_000)[1] == 4
    assert tier_for_damage(600_000_000)[1] == 7
    assert tier_for_damage(1_500_000_000)[1] == 10
    assert tier_for_damage(9_999_999_999)[1] == 10, "超出顶档仍取顶档"
    # 名次加成仅前 10 名
    assert rank_bonus_items(1) == 10 and rank_bonus_items(10) == 1
    assert rank_bonus_items(11) == 0 and rank_bonus_items(0) == 0
    # 强者第 1 名打满顶档 = 20
    assert reward_items(1, 2_000_000_000) == 20
    # 第 2 名低贡献者 = 档位 1 + 加成 9
    assert reward_items(2, 10_000_000) == 10


# ---------------------------------------------------------------- 榜单 / 奖励


def test_merge_party_and_hero_breakdown():
    """分英雄伤害按 heroId 跨会话累加（增量而非覆盖），占比按总伤害计算。"""
    meta = {
        "5": {"slot": 0, "heroId": 5, "name": "光之战士", "jobId": "PLD", "level": 100},
        "7": {"slot": 1, "heroId": 7, "name": "白魔", "jobId": "WHM", "level": 100},
    }
    party = merge_party([], {"5": 300, "7": 100}, meta)
    party = merge_party(party, {"5": 100}, meta)  # 再次上阵后的增量
    by_id = {p["heroId"]: p["damage"] for p in party}
    assert by_id == {5: 400, 7: 100}

    heroes = hero_breakdown({"damage": 500, "party": party})
    assert [h["heroId"] for h in heroes] == [5, 7], "按伤害降序"
    assert heroes[0]["pct"] == 80.0 and heroes[1]["pct"] == 20.0


async def test_leaderboard_includes_hero_breakdown(auth_client, session_factory):
    uid, _ = await _seed_player(session_factory, "lb_heroes")
    async with session_factory() as db:
        boss = await ensure_world_boss(db)
        db.add(
            WorldBossContribution(
                boss_id=BOSS_ID,
                cycle=boss.cycle,
                user_id=uid,
                damage=10_000_000,
                party=[
                    {"slot": 0, "heroId": 1, "name": "A", "jobId": "DRG", "level": 100, "damage": 7_000_000},
                    {"slot": 1, "heroId": 2, "name": "B", "jobId": "WHM", "level": 100, "damage": 3_000_000},
                ],
                updated_at=0,
                created_at=0,
            )
        )
        await db.commit()
        cycle = boss.cycle

    async with session_factory() as db:
        board = await leaderboard_view(db, cycle, uid, 1, 50)
    entry = board["entries"][0]
    assert [h["heroId"] for h in entry["heroes"]] == [1, 2]
    assert entry["heroes"][0]["pct"] == 70.0
    assert entry["heroes"][1]["pct"] == 30.0
    assert board["me"]["heroes"][0]["damage"] == 7_000_000


async def test_leaderboard_threshold_and_order(auth_client, session_factory):
    uid, _ = await _seed_player(session_factory, "lb_self")
    rival, _ = await _seed_player(session_factory, "lb_rival")
    below, _ = await _seed_player(session_factory, "lb_below")
    async with session_factory() as db:
        boss = await ensure_world_boss(db)
        for user_id, damage in ((uid, 8_000_000), (rival, 20_000_000), (below, 1_000_000)):
            db.add(
                WorldBossContribution(
                    boss_id=BOSS_ID, cycle=boss.cycle, user_id=user_id, damage=damage, party=[], updated_at=0, created_at=0
                )
            )
        await db.commit()
        cycle = boss.cycle

    async with session_factory() as db:
        board = await leaderboard_view(db, cycle, uid, 1, 50)
    ids = [e["userId"] for e in board["entries"]]
    assert ids == [rival, uid], "低于门槛者不入榜，且按伤害降序"
    assert board["me"]["rank"] == 2 and board["me"]["items"] == reward_items(2, 8_000_000)
    assert all(e["damage"] >= 5_000_000 for e in board["entries"])


async def test_reward_claim_idempotent_and_grants_exclusive(session_factory):
    uid, _ = await _seed_player(session_factory, "reward_player")
    async with session_factory() as db:
        boss = await ensure_world_boss(db)
        # 结算单位是周期：已换轮（contribution.cycle < boss.cycle）即可领取，与 BOSS 存亡无关。
        boss.status = STATUS_ALIVE
        boss.cycle = 2
        db.add(
            WorldBossContribution(
                boss_id=BOSS_ID, cycle=1, user_id=uid, damage=2_000_000_000, party=[], updated_at=0, created_at=0
            )
        )
        await db.commit()
        assert await unclaimed_cycle(db, uid, boss) == 1

    async with session_factory() as db:
        receipt = await claim_reward(db, uid)
        await db.commit()
    assert receipt["rank"] == 1 and receipt["items"] == 20
    assert receipt["tier"] == 5 and receipt["tierItems"] == 10 and receipt["rankBonus"] == 10
    granted = receipt["grants"]["items"]
    assert len(granted) == 20
    exclusive_ids = {b.id for b in CONFIG.exclusive_items}
    for item in granted:
        assert item["rarity"] == "mythic"
        assert item["levelReq"] == 100
        assert item["baseId"] in exclusive_ids
        assert item["exclusive"] is True

    async with session_factory() as db:
        again = await claim_reward(db, uid)
        await db.commit()
        stored = (await db.scalars(select(WorldBossReward).where(WorldBossReward.user_id == uid))).all()
    assert again == receipt, "重复领取应返回同一回执"
    assert len(stored) == 1


async def test_claim_requires_settled_cycle(session_factory):
    uid, _ = await _seed_player(session_factory, "reward_open")
    async with session_factory() as db:
        boss = await ensure_world_boss(db)
        boss.status = STATUS_ALIVE
        boss.cycle = 1
        db.add(
            WorldBossContribution(
                boss_id=BOSS_ID, cycle=1, user_id=uid, damage=9_000_000, party=[], updated_at=0, created_at=0
            )
        )
        await db.commit()
        assert await unclaimed_cycle(db, uid, boss) is None, "未结算周期不可领取"


# ---------------------------------------------------------------- 接口


async def test_enter_rejects_low_level_and_over_capacity(auth_client, session_factory):
    roster = (await auth_client.get(f"{API}/heroes")).json()
    hero_id = roster["activeHeroId"]
    async with session_factory() as db:
        hero = await db.get(Hero, hero_id)
        hero.level = 100
        await db.commit()

    ok = await auth_client.post(f"{API}/worldboss/enter", json={"heroIds": [hero_id]})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["boss"]["maxHp"] == 2_000_000_000
    assert body["boss"]["phase"] == 1 and body["boss"]["defenseMultiplier"] == 1.0
    assert body["boss"]["periodSeconds"] == 5 * 3600
    assert body["boss"]["periodEndsAt"] is not None
    assert body["boss"]["kills"] == 0
    assert [p["id"] for p in body["phases"]] == [1, 2, 3]
    assert body["rules"]["heroSlots"] == hero_slots() == 8
    assert body["reward"]["tiers"] and body["reward"]["rankBonus"]["1"] == 10
    assert body["session"] and len(body["session"]["heroes"]) == 1

    # 重复上阵自己会在进入前清掉旧会话（幂等重进）
    again = await auth_client.post(f"{API}/worldboss/enter", json={"heroIds": [hero_id]})
    assert again.status_code == 200
    assert (await auth_client.post(f"{API}/worldboss/leave")).json()["ok"] is True

    # 等级不足会被拒
    async with session_factory() as db:
        hero = await db.get(Hero, hero_id)
        hero.level = 50
        await db.commit()
    low = await auth_client.post(f"{API}/worldboss/enter", json={"heroIds": [hero_id]})
    assert low.status_code == 400


async def test_enter_allowed_during_respawn_break(auth_client, session_factory):
    """BOSS 处于周期内短休整（dead）时也允许进场，不再返回 409。"""
    roster = (await auth_client.get(f"{API}/heroes")).json()
    hero_id = roster["activeHeroId"]
    async with session_factory() as db:
        hero = await db.get(Hero, hero_id)
        hero.level = 100
        boss = await ensure_world_boss(db)
        boss.status = STATUS_DEAD
        boss.hp = 0
        boss.kills = 1
        boss.respawn_at = time.time() + 30
        boss.period_ends_at = time.time() + 3600
        await db.commit()

    resp = await auth_client.post(f"{API}/worldboss/enter", json={"heroIds": [hero_id]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["boss"]["status"] == STATUS_DEAD
    assert resp.json()["boss"]["kills"] == 1
    assert (await auth_client.post(f"{API}/worldboss/leave")).json()["ok"] is True


async def test_exclusive_items_not_in_loot_pools():
    """绝境龙神不可抽奖 / 合成 / 生产获取：不在任何候选池里。"""
    for category in ("weapon", "armor", "accessory"):
        assert all(not b.exclusive for b in base_items_for_category(category))
    assert all(not b.exclusive for b in CONFIG.base_items)

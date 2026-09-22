"""远征通关记录（coop_records）与「远征榜」回归测试。"""

from __future__ import annotations

from copy import deepcopy
import time

from sqlalchemy import select

from app.models import Hero, User
from app.models.multiplayer import CoopBattle, CoopMember, CoopRecord, CoopRoom
from app.services.coop_engine import advance, new_battle
from app.services.coop_records import build_party, record_clear
from app.services.multiplayer_config import DUNGEONS, MULTIPLAYER as CFG

API = "/api/v1"


def _seats(dungeon: dict, controllers: list[int]) -> list[dict]:
    roles = (
        ["tank", "healer", "dps", "dps", "tank", "healer", "dps", "dps"]
        if dungeon["seats"] == 8
        else ["tank", "dps"]
    )
    seats = []
    for i, role in enumerate(roles):
        snap = deepcopy(CFG["references"][dungeon["referenceTier"]][role])
        snap["heroId"] = 1000 + i
        snap["ownerId"] = controllers[i % len(controllers)]
        snap["name"] = f"{role}-{i}"
        seats.append(
            {
                "slot": i,
                "controllerId": controllers[i % len(controllers)],
                "registrationId": None,
                "snapshot": snap,
            }
        )
    return seats


def _finished_state(
    dungeon_id: str, controllers: list[int], clear_ms: int, had_clone: bool = False
) -> dict:
    dungeon = DUNGEONS[dungeon_id]
    state = new_battle(dungeon, _seats(dungeon, controllers), "solo", CFG)
    state["elapsedMs"] = clear_ms
    state["status"] = "cleared"
    state["hadClone"] = had_clone
    for i, hero in enumerate(state["heroes"]):
        hero["damage"] = 1000 + i * 10
        hero["damageTaken"] = 500 + i
        hero["healing"] = 300 + i
        hero["minHpRatio"] = 0.4 + i * 0.01
        hero["dangerMs"] = 1000
        hero["clone"] = had_clone
    return state


async def _seed_player(sessions, username: str) -> int:
    """建一个带英雄的普通账号。"""
    async with sessions() as db:
        user = User(username=username, password_hash="x", nickname=username, gold=0)
        db.add(user)
        await db.flush()
        hero = Hero(user_id=user.id, name=username, level=1, talent="common", attr_bias="balanced")
        db.add(hero)
        await db.flush()
        user.active_hero_id = hero.id
        await db.commit()
        return user.id


async def _add_record(
    sessions,
    uid: int,
    dungeon_id: str,
    clear_ms: int,
    mode: str = "solo",
    had_clone: bool = False,
    code: str = "REC0001",
) -> int:
    state = _finished_state(dungeon_id, [uid], clear_ms, had_clone)
    async with sessions() as db:
        room = CoopRoom(
            code=code,
            owner_id=uid,
            dungeon_id=dungeon_id,
            mode=mode,
            status="cleared",
            public=False,
            created_at=time.time(),
        )
        db.add(room)
        await db.flush()
        battle = CoopBattle(
            room_id=room.id,
            status="cleared",
            state=state,
            config=deepcopy(CFG),
            sequence=0,
            command_cursor=0,
            updated_at=time.time(),
            lease_until=0,
        )
        db.add(battle)
        await db.flush()
        db.add(
            CoopRecord(
                battle_id=battle.id,
                room_id=room.id,
                user_id=uid,
                dungeon_id=dungeon_id,
                mode=mode,
                had_clone=had_clone,
                clear_ms=clear_ms,
                party=build_party(state, {uid: f"player{uid}"}),
                created_at=time.time(),
            )
        )
        await db.commit()
        return battle.id


async def test_record_clear_from_engine_state_and_idempotent(auth_client, session_factory):
    """真实引擎跑通的通关状态能落库，分角色战斗信息完整，且重复写入幂等。"""
    uid = (await auth_client.get(f"{API}/auth/me")).json()["id"]
    dungeon = DUNGEONS["normal_1"]
    state = new_battle(dungeon, _seats(dungeon, [uid]), "solo", CFG)
    advance(state, dungeon, CFG, dungeon["enrageSeconds"] * 1000)
    assert state["status"] == "cleared", state["reason"]

    async with session_factory() as db:
        room = CoopRoom(
            code="ENGINE01",
            owner_id=uid,
            dungeon_id="normal_1",
            mode="solo",
            status="cleared",
            public=False,
            created_at=time.time(),
        )
        db.add(room)
        await db.flush()
        battle = CoopBattle(
            room_id=room.id,
            status="cleared",
            state=state,
            config=deepcopy(CFG),
            sequence=0,
            command_cursor=0,
            updated_at=time.time(),
            lease_until=0,
        )
        db.add(battle)
        await db.flush()
        await record_clear(db, room, battle, time.time())
        await db.commit()
        battle_id, room_id = battle.id, room.id

    async with session_factory() as db:
        rows = (await db.scalars(select(CoopRecord).where(CoopRecord.battle_id == battle_id))).all()
        assert len(rows) == 1
        rec = rows[0]
        assert rec.dungeon_id == "normal_1" and rec.mode == "solo"
        assert rec.clear_ms == state["elapsedMs"] > 0
        assert len(rec.party) == 2
        assert sum(m["damage"] for m in rec.party) > 0
        assert all(
            {"damage", "damageTaken", "healing", "deaths", "minHpRatio"} <= set(m)
            for m in rec.party
        )

        # 幂等：同一场战斗重复记录不新增行
        battle2 = await db.get(CoopBattle, battle_id)
        room2 = await db.get(CoopRoom, room_id)
        await record_clear(db, room2, battle2, time.time() + 1)
        await db.commit()
        again = (await db.scalars(select(CoopRecord).where(CoopRecord.battle_id == battle_id))).all()
        assert len(again) == 1


async def test_coop_board_orders_filters_and_has_dungeon_list(auth_client, session_factory):
    uid = (await auth_client.get(f"{API}/auth/me")).json()["id"]
    rival = await _seed_player(session_factory, "rival")
    await _add_record(session_factory, uid, "normal_1", 100_000, code="BOARDA1")
    await _add_record(session_factory, rival, "normal_1", 90_000, mode="online", code="BOARDB1")
    # 另一个副本的记录不应出现在 normal_1 榜
    await _add_record(session_factory, uid, "normal_2", 5_000, code="BOARDC2")

    body = (
        await auth_client.get(f"{API}/ranking", params={"board": "coop", "dungeon": "normal_1"})
    ).json()
    assert body["board"] == "coop" and body["dungeon"] == "normal_1"
    assert "coop" in body["boards"]
    assert len(body["dungeons"]) == len(CFG["dungeons"])
    entries = body["entries"]
    assert [e["userId"] for e in entries] == [rival, uid], "应按通关时长升序"
    assert entries[0]["value"] == 90_000 and entries[0]["payload"]["mode"] == "online"
    assert entries[1]["value"] == 100_000
    assert entries[1]["payload"]["party"] and entries[1]["payload"]["party"][0]["damage"] >= 0
    assert body["me"]["rank"] == 2

    only_uid = (
        await auth_client.get(f"{API}/ranking", params={"board": "coop", "dungeon": "normal_2"})
    ).json()
    assert [e["userId"] for e in only_uid["entries"]] == [uid]

    # 未指定 / 非法副本时回退到配置里的第一个副本
    default_body = (await auth_client.get(f"{API}/ranking", params={"board": "coop"})).json()
    assert default_body["dungeon"] == next(iter(DUNGEONS))
    bad = (
        await auth_client.get(f"{API}/ranking", params={"board": "coop", "dungeon": "nope"})
    ).json()
    assert bad["dungeon"] == next(iter(DUNGEONS))


async def test_coop_board_hides_banned(auth_client, session_factory):
    uid = (await auth_client.get(f"{API}/auth/me")).json()["id"]
    rival = await _seed_player(session_factory, "rival_banned")
    await _add_record(session_factory, uid, "normal_1", 100_000, code="BAN00001")
    await _add_record(session_factory, rival, "normal_1", 80_000, code="BAN00002")

    async with session_factory() as db:
        user = await db.get(User, rival)
        user.banned = True
        await db.commit()

    body = (
        await auth_client.get(f"{API}/ranking", params={"board": "coop", "dungeon": "normal_1"})
    ).json()
    assert all(e["userId"] != rival for e in body["entries"]), "封禁账号不应上榜"


async def test_coop_worker_records_clear(auth_client, session_factory):
    """worker 观察到通关状态时自动写入记录，并把房间状态置为 cleared。"""
    from app.coop_worker import tick_rooms

    uid = (await auth_client.get(f"{API}/auth/me")).json()["id"]
    # 战斗状态已终局（cleared），但尚未持久化为房间状态——worker 应落库并记录。
    state = _finished_state("normal_1", [uid], 42_000)
    async with session_factory() as db:
        room = CoopRoom(
            code="WORKER01",
            owner_id=uid,
            dungeon_id="normal_1",
            mode="solo",
            status="running",
            public=False,
            created_at=time.time(),
        )
        db.add(room)
        await db.flush()
        db.add(CoopMember(room_id=room.id, user_id=uid, ready=True, heartbeat_at=time.time()))
        db.add(
            CoopBattle(
                room_id=room.id,
                status="running",
                state=state,
                config=deepcopy(CFG),
                sequence=0,
                command_cursor=0,
                updated_at=time.time(),
                lease_until=0,
            )
        )
        await db.commit()
        room_id = room.id

    await tick_rooms(session_factory, "test", time.time())

    async with session_factory() as db:
        room = await db.get(CoopRoom, room_id)
        records = (await db.scalars(select(CoopRecord).where(CoopRecord.room_id == room_id))).all()
    assert room.status == "cleared"
    assert len(records) == 1 and records[0].clear_ms == 42_000

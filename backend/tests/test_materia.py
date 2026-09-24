"""魔晶石镶嵌：孔位顺序、成败、取出返还、合成与属性注入。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import User
from app.services import dohdol_util, materia
from app.services.game_config import CONFIG

API = "/api/v1"


async def _uid(session_factory) -> int:
    async with session_factory() as db:
        return int((await db.execute(select(User))).scalars().first().id)


async def _give(session_factory, item_id: str, count: int) -> None:
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        await dohdol_util.stack_add(db, user.id, dohdol_util.STACK_MATERIA, item_id, count)
        await db.commit()


async def _stock(session_factory, item_id: str) -> int:
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        row = await dohdol_util.stack_row(db, user.id, dohdol_util.STACK_MATERIA, item_id)
        return int(row.count) if row else 0


def _socket(client, slot, index, materia_id):
    return client.post(
        f"{API}/materia/socket", json={"slot": slot, "index": index, "materiaId": materia_id}
    )


@pytest.mark.asyncio
async def test_state_lists_all_slots_and_stock(auth_client):
    data = (await auth_client.get(f"{API}/materia/state")).json()
    assert data["socketsPerSlot"] == 5
    assert data["successChance"] == [1.0, 0.6, 0.35, 0.15, 0.05]
    assert data["mergeFrom"] == 5
    assert len(data["slots"]) == 11
    assert all(len(s["sockets"]) == 5 for s in data["slots"])
    for slot in data["slots"]:
        for i, socket in enumerate(slot["sockets"]):
            assert socket["chance"] == data["successChance"][i]
            assert socket["materia"] is None
    # 6 种 × 5 级 = 30 件，初始全为 0
    assert len(data["stock"]) == 30
    assert all(entry["count"] == 0 for entry in data["stock"])
    assert data["bonus"] == {}


@pytest.mark.asyncio
async def test_first_socket_always_succeeds_and_consumes(auth_client, session_factory):
    await _give(session_factory, "m_str_1", 1)
    resp = await _socket(auth_client, "head", 0, "m_str_1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["chance"] == 1.0
    # 第 1 孔同样消耗 1 个
    assert await _stock(session_factory, "m_str_1") == 0
    state = (await auth_client.get(f"{API}/materia/state")).json()
    assert state["slots"][1]["sockets"][0]["materia"]["id"] == "m_str_1"


@pytest.mark.asyncio
async def test_must_fill_in_order(auth_client, session_factory):
    await _give(session_factory, "m_crit_1", 4)
    resp = await _socket(auth_client, "head", 2, "m_crit_1")
    assert resp.status_code == 400
    assert "顺序" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_failure_consumes_materia(auth_client, session_factory, monkeypatch):
    await _give(session_factory, "m_crit_1", 2)
    await _socket(auth_client, "head", 0, "m_crit_1")
    # 第 2 孔成功率 60%：强制失败
    monkeypatch.setattr("app.services.materia.random.random", lambda: 0.99)
    resp = await _socket(auth_client, "head", 1, "m_crit_1")
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert await _stock(session_factory, "m_crit_1") == 0  # 失败也消耗
    state = (await auth_client.get(f"{API}/materia/state")).json()
    assert state["slots"][1]["sockets"][1]["materia"] is None


@pytest.mark.asyncio
async def test_remove_returns_materia(auth_client, session_factory):
    await _give(session_factory, "m_det_2", 1)
    await _socket(auth_client, "body", 0, "m_det_2")
    assert await _stock(session_factory, "m_det_2") == 0
    resp = await auth_client.post(f"{API}/materia/remove", json={"slot": "body", "index": 0})
    assert resp.status_code == 200, resp.text
    assert resp.json()["removed"]["id"] == "m_det_2"
    assert await _stock(session_factory, "m_det_2") == 1
    state = (await auth_client.get(f"{API}/materia/state")).json()
    assert state["slots"][2]["sockets"][0]["materia"] is None


@pytest.mark.asyncio
async def test_remove_missing_socket_404(auth_client):
    assert (await auth_client.post(f"{API}/materia/remove", json={"slot": "head", "index": 0})).status_code == 404


@pytest.mark.asyncio
async def test_unknown_materia_rejected(auth_client):
    assert (await _socket(auth_client, "head", 0, "m_ghost_1")).status_code == 400


@pytest.mark.asyncio
async def test_socket_without_stock_rejected(auth_client):
    assert (await _socket(auth_client, "head", 0, "m_str_1")).status_code == 400


@pytest.mark.asyncio
async def test_merge_five_into_next_level(auth_client, session_factory):
    await _give(session_factory, "m_crit_1", 5)
    resp = await auth_client.post(f"{API}/materia/merge", json={"materiaId": "m_crit_1"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["produced"]["id"] == "m_crit_2"
    assert await _stock(session_factory, "m_crit_1") == 0
    assert await _stock(session_factory, "m_crit_2") == 1


@pytest.mark.asyncio
async def test_merge_requires_five(auth_client, session_factory):
    await _give(session_factory, "m_crit_1", 4)
    resp = await auth_client.post(f"{API}/materia/merge", json={"materiaId": "m_crit_1"})
    assert resp.status_code == 400
    assert await _stock(session_factory, "m_crit_1") == 4


@pytest.mark.asyncio
async def test_merge_max_level_rejected(auth_client, session_factory):
    await _give(session_factory, "m_crit_5", 5)
    resp = await auth_client.post(f"{API}/materia/merge", json={"materiaId": "m_crit_5"})
    assert resp.status_code == 400
    assert await _stock(session_factory, "m_crit_5") == 5


@pytest.mark.asyncio
async def test_socket_mods_injected_into_stats(auth_client, session_factory):
    """镶嵌后 /game/state 的面板与战力应上升（socket_mods 注入 compute_stats）。"""
    before = (await auth_client.get(f"{API}/game/state")).json()
    base_crit = before["hero"]["stats"]["critValue"]
    base_power = before["power"]

    await _give(session_factory, "m_crit_5", 1)
    assert (await _socket(auth_client, "mainHand", 0, "m_crit_5")).json()["success"] is True

    after = (await auth_client.get(f"{API}/game/state")).json()
    assert after["hero"]["stats"]["critValue"] > base_crit + 100
    assert after["power"] > base_power


@pytest.mark.asyncio
async def test_socket_mods_helper_sums_by_stat(auth_client, session_factory, monkeypatch):
    # 第 2 孔成功率仅 60%，不固定随机数时该断言会随机失败（同 test_full_slot_rejected 的做法）。
    monkeypatch.setattr("app.services.materia.random.random", lambda: 0.0)  # 全部成功
    await _give(session_factory, "m_crit_1", 1)
    await _give(session_factory, "m_crit_3", 1)
    await _socket(auth_client, "legs", 0, "m_crit_1")
    await _socket(auth_client, "legs", 1, "m_crit_3")
    uid = await _uid(session_factory)
    async with session_factory() as db:
        mods = await materia.socket_mods(db, uid)
    assert mods["crit"] == pytest.approx(20 + 70)  # 武略壹型 + 叁型
    assert set(mods) == {"crit"}


@pytest.mark.asyncio
async def test_full_slot_rejected(auth_client, session_factory, monkeypatch):
    monkeypatch.setattr("app.services.materia.random.random", lambda: 0.0)  # 全部成功
    await _give(session_factory, "m_str_1", 5)
    for index in range(5):
        resp = await _socket(auth_client, "feet", index, "m_str_1")
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
    # 已满：再镶第 1 孔被拒
    assert (await _socket(auth_client, "feet", 0, "m_str_1")).status_code == 400
    # 空库存也拒绝
    await _give(session_factory, "m_str_1", 1)
    resp = await _socket(auth_client, "feet", 0, "m_str_1")
    assert resp.status_code == 400
    assert "已镶嵌" in resp.json()["detail"]
    # 全满时无法新增孔位
    await auth_client.post(f"{API}/materia/remove", json={"slot": "feet", "index": 0})
    assert (await _socket(auth_client, "feet", 0, "m_str_1")).status_code == 200

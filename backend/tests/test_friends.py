"""好友系统：好友码、在线状态、好友关系与金币转账（10% 手续费）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import CoinTransfer, User
from app.services import friends

API = "/api/v1"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, username: str, nickname: str) -> str:
    resp = await client.post(
        f"{API}/auth/register",
        json={"username": username, "password": "secret123", "nickname": nickname},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["accessToken"]


async def _me(client, token: str) -> dict:
    resp = await client.get(f"{API}/auth/me", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _set_gold(session_factory, username: str, gold: int) -> None:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one()
        user.gold = gold
        await db.commit()


async def _set_last_seen(session_factory, username: str, when: datetime | None) -> None:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one()
        user.last_seen_at = when
        await db.commit()


async def test_register_assigns_unique_friend_codes(client) -> None:
    alice = await _register(client, "alice", "爱丽丝")
    bob = await _register(client, "bob", "鲍勃")
    code_a = (await _me(client, alice))["friendCode"]
    code_b = (await _me(client, bob))["friendCode"]
    assert len(code_a) == 8 and len(code_b) == 8
    assert code_a != code_b


async def test_friend_request_accept_flow_and_presence(client) -> None:
    alice = await _register(client, "alice", "爱丽丝")
    bob = await _register(client, "bob", "鲍勃")
    alice_id = (await _me(client, alice))["id"]
    bob_id = (await _me(client, bob))["id"]
    bob_code = (await _me(client, bob))["friendCode"]

    # 申请：alice → bob
    resp = await client.post(f"{API}/friends/request", json={"code": bob_code}, headers=_auth(alice))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending"

    # bob 侧看到 incoming，alice 侧看到 outgoing
    bob_list = (await client.get(f"{API}/friends", headers=_auth(bob))).json()
    assert [e["userId"] for e in bob_list["incoming"]] == [alice_id]
    assert bob_list["friends"] == []
    alice_list = (await client.get(f"{API}/friends", headers=_auth(alice))).json()
    assert [e["userId"] for e in alice_list["outgoing"]] == [bob_id]

    # bob 同意
    resp = await client.post(f"{API}/friends/accept", json={"userId": alice_id}, headers=_auth(bob))
    assert resp.status_code == 200, resp.text

    # 双方互为好友且在线（两人都刚访问过 /friends，last_seen 已刷新）
    alice_list = (await client.get(f"{API}/friends", headers=_auth(alice))).json()
    assert [e["userId"] for e in alice_list["friends"]] == [bob_id]
    assert alice_list["friends"][0]["online"] is True
    bob_list = (await client.get(f"{API}/friends", headers=_auth(bob))).json()
    assert [e["userId"] for e in bob_list["friends"]] == [alice_id]
    assert bob_list["friends"][0]["online"] is True
    assert bob_list["feePct"] == 0.10


async def test_presence_goes_offline(client, session_factory) -> None:
    alice = await _register(client, "alice", "爱丽丝")
    bob = await _register(client, "bob", "鲍勃")
    alice_id = (await _me(client, alice))["id"]
    bob_code = (await _me(client, bob))["friendCode"]
    await client.post(f"{API}/friends/request", json={"code": bob_code}, headers=_auth(alice))
    await client.post(f"{API}/friends/accept", json={"userId": alice_id}, headers=_auth(bob))

    await _set_last_seen(session_factory, "bob", datetime.now(timezone.utc) - timedelta(minutes=10))
    alice_list = (await client.get(f"{API}/friends", headers=_auth(alice))).json()
    bob_entry = next(e for e in alice_list["friends"])
    assert bob_entry["online"] is False
    assert bob_entry["lastSeenSecondsAgo"] >= 500

    # 心跳恢复在线
    resp = await client.get(f"{API}/friends/heartbeat", headers=_auth(bob))
    assert resp.status_code == 200, resp.text
    assert resp.json()["onlineSeconds"] == friends.ONLINE_SECONDS
    alice_list = (await client.get(f"{API}/friends", headers=_auth(alice))).json()
    assert alice_list["friends"][0]["online"] is True


async def test_transfer_charges_ten_percent_fee(client, session_factory) -> None:
    alice = await _register(client, "alice", "爱丽丝")
    bob = await _register(client, "bob", "鲍勃")
    alice_id = (await _me(client, alice))["id"]
    bob_id = (await _me(client, bob))["id"]
    bob_code = (await _me(client, bob))["friendCode"]
    await client.post(f"{API}/friends/request", json={"code": bob_code}, headers=_auth(alice))
    await client.post(f"{API}/friends/accept", json={"userId": alice_id}, headers=_auth(bob))

    await _set_gold(session_factory, "alice", 1000)
    resp = await client.post(
        f"{API}/friends/transfer", json={"userId": bob_id, "amount": 1000}, headers=_auth(alice)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fee"] == 100 and body["net"] == 900
    assert (await _me(client, alice))["gold"] == 0
    assert (await _me(client, bob))["gold"] == 900

    async with session_factory() as db:
        row = (await db.execute(select(CoinTransfer))).scalars().one()
        assert (row.amount, row.fee, row.net) == (1000, 100, 900)


async def test_transfer_guards(client, session_factory) -> None:
    alice = await _register(client, "alice", "爱丽丝")
    bob = await _register(client, "bob", "鲍勃")
    carol = await _register(client, "carol", "卡洛儿")
    alice_id = (await _me(client, alice))["id"]
    alice_code = (await _me(client, alice))["friendCode"]
    bob_id = (await _me(client, bob))["id"]
    carol_id = (await _me(client, carol))["id"]
    bob_code = (await _me(client, bob))["friendCode"]

    # 不能加自己
    resp = await client.post(f"{API}/friends/request", json={"code": alice_code}, headers=_auth(alice))
    assert resp.status_code == 400
    # 不存在的好友码
    resp = await client.post(f"{API}/friends/request", json={"code": "ZZZZZZZZ"}, headers=_auth(alice))
    assert resp.status_code == 404

    await _set_gold(session_factory, "alice", 10_000)

    # 未成为好友前不能转账
    resp = await client.post(
        f"{API}/friends/transfer", json={"userId": bob_id, "amount": 100}, headers=_auth(alice)
    )
    assert resp.status_code == 400

    await client.post(f"{API}/friends/request", json={"code": bob_code}, headers=_auth(alice))
    await client.post(f"{API}/friends/accept", json={"userId": alice_id}, headers=_auth(bob))

    # 给自己转账
    resp = await client.post(
        f"{API}/friends/transfer", json={"userId": alice_id, "amount": 100}, headers=_auth(alice)
    )
    assert resp.status_code == 400
    # 转给非好友
    resp = await client.post(
        f"{API}/friends/transfer", json={"userId": carol_id, "amount": 100}, headers=_auth(alice)
    )
    assert resp.status_code == 400
    # 余额不足
    resp = await client.post(
        f"{API}/friends/transfer", json={"userId": bob_id, "amount": 20_000}, headers=_auth(alice)
    )
    assert resp.status_code == 400
    # 超单笔上限
    resp = await client.post(
        f"{API}/friends/transfer",
        json={"userId": bob_id, "amount": friends.max_amount() + 1},
        headers=_auth(alice),
    )
    assert resp.status_code == 400


async def test_transfer_daily_limit(client, session_factory) -> None:
    alice = await _register(client, "alice", "爱丽丝")
    bob = await _register(client, "bob", "鲍勃")
    alice_id = (await _me(client, alice))["id"]
    bob_id = (await _me(client, bob))["id"]
    bob_code = (await _me(client, bob))["friendCode"]
    await client.post(f"{API}/friends/request", json={"code": bob_code}, headers=_auth(alice))
    await client.post(f"{API}/friends/accept", json={"userId": alice_id}, headers=_auth(bob))

    await _set_gold(session_factory, "alice", friends.daily_limit() + 1000)
    # 用满当日额度（受单笔上限约束，故取 min(dailyLimit, maxAmount)）
    chunk = min(friends.daily_limit(), friends.max_amount())
    resp = await client.post(
        f"{API}/friends/transfer", json={"userId": bob_id, "amount": chunk}, headers=_auth(alice)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["remainingToday"] == friends.daily_limit() - chunk

    # 额度用尽后再转 1 金币被拒
    resp = await client.post(
        f"{API}/friends/transfer", json={"userId": bob_id, "amount": 1}, headers=_auth(alice)
    )
    assert resp.status_code == 400


async def test_remove_friend(client) -> None:
    alice = await _register(client, "alice", "爱丽丝")
    bob = await _register(client, "bob", "鲍勃")
    alice_id = (await _me(client, alice))["id"]
    bob_id = (await _me(client, bob))["id"]
    bob_code = (await _me(client, bob))["friendCode"]
    await client.post(f"{API}/friends/request", json={"code": bob_code}, headers=_auth(alice))
    await client.post(f"{API}/friends/accept", json={"userId": alice_id}, headers=_auth(bob))

    resp = await client.post(f"{API}/friends/remove", json={"userId": bob_id}, headers=_auth(alice))
    assert resp.status_code == 200, resp.text
    alice_list = (await client.get(f"{API}/friends", headers=_auth(alice))).json()
    assert alice_list["friends"] == []

"""反多开：同设备注册上限 + 关联账号（同设备 / 同 IP）之间的转账与交易板额度。"""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog, StackItem, User
from app.services import devices

API = "/api/v1"
DEV_A = "fp-aaaa1111bbbb2222"
DEV_B = "fp-cccc3333dddd4444"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, username: str, device: str | None = None, keep_cookie: bool = False):
    headers = {"X-Device-Id": device} if device else None
    if device and not keep_cookie:
        # httpx 客户端会保留响应 Cookie：显式指定设备时先清空，使本请求的设备身份即请求头，
        # 等价于「换了一台设备」。验证「服务端设备 Cookie 防换指纹绕过」时传 keep_cookie=True。
        client.cookies.clear()
    return await client.post(
        f"{API}/auth/register",
        json={"username": username, "password": "secret123", "nickname": username},
        headers=headers,
    )


async def _register_token(client, username: str, device: str | None = None) -> str:
    resp = await _register(client, username, device)
    assert resp.status_code == 201, resp.text
    return resp.json()["accessToken"]


async def _user_id(session_factory, username: str) -> int:
    async with session_factory() as db:
        return int((await db.execute(select(User.id).where(User.username == username))).scalar_one())


async def _set_gold(session_factory, username: str, gold: int) -> None:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one()
        user.gold = gold
        await db.commit()


async def _become_friends(client, token_a: str, token_b: str) -> None:
    me_a = (await client.get(f"{API}/auth/me", headers=_auth(token_a))).json()
    me_b = (await client.get(f"{API}/auth/me", headers=_auth(token_b))).json()
    # b 用 a 的好友码发起申请，a 同意（accept 的 userId 是申请方 id）
    resp = await client.post(
        f"{API}/friends/request", json={"code": me_a["friendCode"]}, headers=_auth(token_b)
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"{API}/friends/accept", json={"userId": me_b["id"]}, headers=_auth(token_a)
    )
    assert resp.status_code == 200, resp.text


async def _seed_stack(session_factory, username: str, item_id: str, count: int) -> None:
    uid = await _user_id(session_factory, username)
    async with session_factory() as db:
        db.add(StackItem(user_id=uid, kind="material", item_id=item_id, count=count))
        await db.commit()


async def _list_stack(client, token: str, item_id: str, count: int, price: int) -> int:
    resp = await client.post(
        f"{API}/market/list",
        json={
            "entries": [
                {
                    "type": "stack",
                    "stackKind": "material",
                    "stackItemId": item_id,
                    "count": count,
                    "unitPrice": price,
                }
            ]
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["listings"][0]["id"])


def _device_cap() -> int:
    return devices.max_accounts_per_device()


def _linked_transfer_cap() -> int:
    return devices.linked_transfer_daily_limit()


def _linked_market_cap() -> int:
    return devices.linked_market_daily_limit()


# ------------------------------------------------------------------ 注册上限
async def test_same_device_registration_capped(client) -> None:
    cap = _device_cap()
    for i in range(cap):
        resp = await _register(client, f"dev_user_{i}", DEV_A)
        assert resp.status_code == 201, resp.text

    blocked = await _register(client, "dev_user_extra", DEV_A)
    assert blocked.status_code == 400
    assert "设备" in blocked.json()["detail"]

    # 另一台设备不受影响
    other = await _register(client, "dev_user_other", DEV_B)
    assert other.status_code == 201, other.text


async def test_registration_without_device_header_is_not_capped(client) -> None:
    """未携带设备指纹时不启用该上限（前端始终携带；此处保证脚本/老客户端不误伤）。"""
    for i in range(_device_cap() + 1):
        resp = await _register(client, f"no_dev_{i}")
        assert resp.status_code == 201, resp.text


async def test_login_records_device_linkage(client, session_factory) -> None:
    """注册后同设备登录另一账号 → 视为关联。"""
    await _register_token(client, "link_a", DEV_A)
    await _register_token(client, "link_b", DEV_A)
    id_a = await _user_id(session_factory, "link_a")
    id_b = await _user_id(session_factory, "link_b")
    async with session_factory() as db:
        assert await devices.are_linked(db, id_a, id_b) is True


# ------------------------------------------------------------------ 关联判定
async def test_are_linked_by_ip_only(client, session_factory) -> None:
    """不同设备但同一真实 IP → 关联；IP 不同 → 不关联。"""
    await _register_token(client, "ip_a")
    await _register_token(client, "ip_b")
    id_a = await _user_id(session_factory, "ip_a")
    id_b = await _user_id(session_factory, "ip_b")

    async with session_factory() as db:
        a = (await db.execute(select(User).where(User.id == id_a))).scalar_one()
        b = (await db.execute(select(User).where(User.id == id_b))).scalar_one()
        a.last_ip = "203.0.113.7"
        b.last_ip = "203.0.113.7"
        await db.commit()
    async with session_factory() as db:
        assert await devices.are_linked(db, id_a, id_b) is True

    async with session_factory() as db:
        b = (await db.execute(select(User).where(User.id == id_b))).scalar_one()
        b.last_ip = "198.51.100.9"
        await db.commit()
    async with session_factory() as db:
        assert await devices.are_linked(db, id_a, id_b) is False


def test_sentinel_ip_and_device_normalization() -> None:
    assert devices.is_real_ip("203.0.113.7") is True
    assert devices.is_real_ip("testclient") is False
    assert devices.is_real_ip("127.0.0.1") is False
    assert devices.is_real_ip(None) is False
    assert devices.normalize_device_id("  dev-1  ") == "dev-1"
    assert devices.normalize_device_id("") is None
    assert devices.normalize_device_id("x" * 200) == "x" * 64


# ------------------------------------------------------------------ 好友转账额度
async def test_linked_accounts_transfer_capped(client, session_factory) -> None:
    cap = _linked_transfer_cap()
    alice = await _register_token(client, "tr_alice", DEV_A)
    bob = await _register_token(client, "tr_bob", DEV_A)
    await _become_friends(client, alice, bob)
    await _set_gold(session_factory, "tr_alice", cap * 3)
    await _set_gold(session_factory, "tr_bob", cap * 3)
    id_alice = await _user_id(session_factory, "tr_alice")
    id_bob = await _user_id(session_factory, "tr_bob")

    # 累计到刚好等于上限：允许
    resp = await client.post(
        f"{API}/friends/transfer",
        json={"userId": id_bob, "amount": cap // 2},
        headers=_auth(alice),
    )
    assert resp.status_code == 200, resp.text
    # 反向累计（bob → alice）同样计入该 pair，超出上限即拒绝
    resp = await client.post(
        f"{API}/friends/transfer",
        json={"userId": id_alice, "amount": cap // 2},
        headers=_auth(bob),
    )
    assert resp.status_code == 200, resp.text
    # 此时 pair 已用满，再多转 1 金币即拒绝
    resp = await client.post(
        f"{API}/friends/transfer",
        json={"userId": id_bob, "amount": 1},
        headers=_auth(alice),
    )
    assert resp.status_code == 400
    assert "关联账号" in resp.json()["detail"]


async def test_unlinked_accounts_transfer_not_capped(client, session_factory) -> None:
    cap = _linked_transfer_cap()
    alice = await _register_token(client, "free_alice", DEV_A)
    bob = await _register_token(client, "free_bob", DEV_B)
    await _become_friends(client, alice, bob)
    await _set_gold(session_factory, "free_alice", cap * 3)
    id_bob = await _user_id(session_factory, "free_bob")

    # 非关联账号不受「关联额度」限制：单笔即可超过该额度
    resp = await client.post(
        f"{API}/friends/transfer",
        json={"userId": id_bob, "amount": cap + 1000},
        headers=_auth(alice),
    )
    assert resp.status_code == 200, resp.text


# ------------------------------------------------------------------ 交易板额度
async def test_linked_accounts_market_buy_capped(client, session_factory) -> None:
    cap = _linked_market_cap()
    alice = await _register_token(client, "mk_alice", DEV_A)
    bob = await _register_token(client, "mk_bob", DEV_A)
    await _set_gold(session_factory, "mk_bob", cap * 5)

    await _seed_stack(session_factory, "mk_alice", "g_ore", 2)
    over = await _list_stack(client, alice, "g_ore", 1, cap + 1)
    resp = await client.post(f"{API}/market/buy", json={"listingId": over}, headers=_auth(bob))
    assert resp.status_code == 400
    assert "关联账号" in resp.json()["detail"]

    # 单笔恰为上限 → 允许
    at_cap = await _list_stack(client, alice, "g_ore", 1, cap)
    resp = await client.post(f"{API}/market/buy", json={"listingId": at_cap}, headers=_auth(bob))
    assert resp.status_code == 200, resp.text

    # 该 pair 24h 累计已用满 → 再来一笔即拒绝
    await _seed_stack(session_factory, "mk_alice", "g_ore", 1)
    again = await _list_stack(client, alice, "g_ore", 1, 1)
    resp = await client.post(f"{API}/market/buy", json={"listingId": again}, headers=_auth(bob))
    assert resp.status_code == 400
    assert "关联账号" in resp.json()["detail"]


async def test_unlinked_market_buy_not_capped(client, session_factory) -> None:
    cap = _linked_market_cap()
    alice = await _register_token(client, "mk2_alice", DEV_A)
    bob = await _register_token(client, "mk2_bob", DEV_B)
    await _set_gold(session_factory, "mk2_bob", cap * 5)

    await _seed_stack(session_factory, "mk2_alice", "g_ore", 1)
    listing = await _list_stack(client, alice, "g_ore", 1, cap + 1)
    resp = await client.post(f"{API}/market/buy", json={"listingId": listing}, headers=_auth(bob))
    assert resp.status_code == 200, resp.text


async def test_linked_accounts_buy_order_fill_capped(client, session_factory) -> None:
    """收购单路径：关联账号之间的单笔成交额受上限限制。"""
    cap = _linked_market_cap()
    buyer = await _register_token(client, "bo_buyer", DEV_A)
    seller = await _register_token(client, "bo_seller", DEV_A)
    await _set_gold(session_factory, "bo_buyer", cap * 5)

    resp = await client.post(
        f"{API}/market/buy-orders",
        json={"kind": "material", "itemId": "g_ore", "quantity": 1, "unitPrice": cap + 1},
        headers=_auth(buyer),
    )
    assert resp.status_code == 200, resp.text
    order_id = int(resp.json()["order"]["id"])

    await _seed_stack(session_factory, "bo_seller", "g_ore", 1)
    resp = await client.post(
        f"{API}/market/buy-orders/fill",
        json={"orderId": order_id, "count": 1},
        headers=_auth(seller),
    )
    assert resp.status_code == 400
    assert "关联账号" in resp.json()["detail"]


async def test_market_linked_buy_writes_audit(client, session_factory) -> None:
    """关联账号的成交写入审计日志留痕（reason=market_linked）。"""
    cap = _linked_market_cap()
    alice = await _register_token(client, "au_alice", DEV_A)
    bob = await _register_token(client, "au_bob", DEV_A)
    await _set_gold(session_factory, "au_bob", cap)
    await _seed_stack(session_factory, "au_alice", "g_ore", 1)
    listing = await _list_stack(client, alice, "g_ore", 1, 10)
    resp = await client.post(f"{API}/market/buy", json={"listingId": listing}, headers=_auth(bob))
    assert resp.status_code == 200, resp.text

    async with session_factory() as db:
        rows = (
            await db.execute(select(AuditLog).where(AuditLog.reason == "market_linked"))
        ).scalars().all()
        assert len(rows) == 1

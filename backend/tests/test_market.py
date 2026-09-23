"""市场交易板：上架托管 / 成交抽费 / 下架与到期退回 / 反作弊回归。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import Item, MarketListing, StackItem, User
from app.models.base import utcnow
from app.models.market import STATUS_ACTIVE, STATUS_EXPIRED, STATUS_SOLD
from app.services import market
from app.services.game_config import CONFIG

API = "/api/v1"


async def _register(client, username: str) -> str:
    resp = await client.post(
        f"{API}/auth/register",
        json={"username": username, "password": "secret123", "nickname": username},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["accessToken"]


def _auth(client, token: str) -> None:
    client.headers.update({"Authorization": f"Bearer {token}"})


async def _user_id(session_factory, username: str) -> int:
    async with session_factory() as db:
        return int((await db.execute(select(User.id).where(User.username == username))).scalar_one())


async def _set_gold(session_factory, user_id: int, gold: int) -> None:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        user.gold = gold
        await db.commit()


async def _set_banned(session_factory, user_id: int, banned: bool) -> None:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        user.banned = banned
        await db.commit()


async def _seed_item(session_factory, user_id: int, **over) -> int:
    async with session_factory() as db:
        item = Item(
            user_id=user_id,
            base_id=over.get("base_id", "w_sword_shield_1"),
            name=over.get("name", "测试剑盾"),
            category=over.get("category", "weapon"),
            slot=over.get("slot", "mainHand"),
            rarity=over.get("rarity", "rare"),
            level_req=over.get("level_req", 1),
            high_quality=over.get("high_quality", False),
            base_attrs=over.get("base_attrs", [{"attr": "attack", "value": 12.0}]),
            sub_attrs=over.get("sub_attrs", []),
            terms=over.get(
                "terms",
                [
                    {
                        "id": "t_atk",
                        "name": "力量增幅",
                        "type": "buff",
                        "stat": "attackPct",
                        "trigger": "passive",
                        "value": 8.0,
                        "quality": "common",
                        "desc": "",
                    }
                ],
            ),
            refine_count=over.get("refine_count", 0),
            enchant_count=over.get("enchant_count", 0),
            source="test",
        )
        db.add(item)
        await db.commit()
        return int(item.id)


async def _seed_stack(session_factory, user_id: int, kind: str, item_id: str, count: int) -> None:
    async with session_factory() as db:
        db.add(StackItem(user_id=user_id, kind=kind, item_id=item_id, count=count))
        await db.commit()


async def test_equipment_list_escrows_and_cancel_returns_it(client, session_factory):
    token = await _register(client, "mkt_esc")
    uid = await _user_id(session_factory, "mkt_esc")
    item_id = await _seed_item(session_factory, uid)
    _auth(client, token)

    resp = await client.post(
        f"{API}/market/list",
        json={"entries": [{"type": "equipment", "itemId": item_id, "unitPrice": 500}]},
    )
    assert resp.status_code == 200, resp.text
    listing_id = resp.json()["listings"][0]["id"]

    # 上架即托管：装备行消失
    async with session_factory() as db:
        assert (await db.execute(select(Item).where(Item.id == item_id))).scalar_one_or_none() is None

    resp = await client.post(f"{API}/market/cancel", json={"listingId": listing_id})
    assert resp.status_code == 200, resp.text

    async with session_factory() as db:
        items = (
            await db.execute(
                select(Item).where(Item.user_id == uid, Item.base_id == "w_sword_shield_1")
            )
        ).scalars().all()
        assert len(items) == 1
        assert items[0].rarity == "rare"
        assert len(items[0].terms) == 1
        assert items[0].equipped_slot is None
        row = (await db.execute(select(MarketListing).where(MarketListing.id == listing_id))).scalar_one()
        assert row.status == "cancelled"


async def test_buy_transfers_gold_and_item_with_fee(client, session_factory):
    token_a = await _register(client, "mkt_sell")
    uid_a = await _user_id(session_factory, "mkt_sell")
    item_id = await _seed_item(session_factory, uid_a, rarity="epic")
    _auth(client, token_a)
    listing_id = (
        await client.post(
            f"{API}/market/list",
            json={"entries": [{"type": "equipment", "itemId": item_id, "unitPrice": 1000}]},
        )
    ).json()["listings"][0]["id"]

    token_b = await _register(client, "mkt_buy")
    uid_b = await _user_id(session_factory, "mkt_buy")
    await _set_gold(session_factory, uid_b, 5000)
    _auth(client, token_b)

    resp = await client.post(f"{API}/market/buy", json={"listingId": listing_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1000
    assert body["fee"] == market.fee_of(1000) == 100
    assert body["gold"] == 4000
    assert body["sellerGold"] == 900  # 1000 - 100 手续费

    async with session_factory() as db:
        buyer_items = (
            await db.execute(
                select(Item).where(Item.user_id == uid_b, Item.base_id == "w_sword_shield_1")
            )
        ).scalars().all()
        assert len(buyer_items) == 1 and buyer_items[0].rarity == "epic"
        seller_items = (
            await db.execute(
                select(Item).where(Item.user_id == uid_a, Item.base_id == "w_sword_shield_1")
            )
        ).scalars().all()
        assert seller_items == []
        seller = (await db.execute(select(User).where(User.id == uid_a))).scalar_one()
        assert int(seller.gold) == 900
        row = (await db.execute(select(MarketListing).where(MarketListing.id == listing_id))).scalar_one()
        assert row.status == STATUS_SOLD and row.buyer_id == uid_b and row.fee == 100


async def test_buy_guards_self_and_insufficient_gold(client, session_factory):
    token_a = await _register(client, "mkt_g_a")
    uid_a = await _user_id(session_factory, "mkt_g_a")
    item_id = await _seed_item(session_factory, uid_a)
    _auth(client, token_a)
    listing_id = (
        await client.post(
            f"{API}/market/list",
            json={"entries": [{"type": "equipment", "itemId": item_id, "unitPrice": 1000}]},
        )
    ).json()["listings"][0]["id"]

    # 不能购买自己的寄售
    assert (await client.post(f"{API}/market/buy", json={"listingId": listing_id})).status_code == 400

    # 他人金币不足
    token_b = await _register(client, "mkt_g_b")
    _auth(client, token_b)
    assert (await client.post(f"{API}/market/buy", json={"listingId": listing_id})).status_code == 400

    async with session_factory() as db:
        row = (await db.execute(select(MarketListing).where(MarketListing.id == listing_id))).scalar_one()
        assert row.status == STATUS_ACTIVE


async def test_stack_listing_buy_and_cancel(client, session_factory):
    token_a = await _register(client, "mkt_s_a")
    uid_a = await _user_id(session_factory, "mkt_s_a")
    await _seed_stack(session_factory, uid_a, "material", "g_ore", 10)
    _auth(client, token_a)

    resp = await client.post(
        f"{API}/market/list",
        json={
            "entries": [
                {"type": "stack", "stackKind": "material", "stackItemId": "g_ore", "count": 4, "unitPrice": 30}
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    listing = resp.json()["listings"][0]
    assert listing["quantity"] == 4 and listing["totalPrice"] == 120

    # 上架即从库存扣除
    async with session_factory() as db:
        row = (
            await db.execute(
                select(StackItem).where(StackItem.user_id == uid_a, StackItem.item_id == "g_ore")
            )
        ).scalar_one()
        assert row.count == 6

    # 数量不足 / 类型不匹配
    too_many = await client.post(
        f"{API}/market/list",
        json={"entries": [{"type": "stack", "stackKind": "material", "stackItemId": "g_ore", "count": 99, "unitPrice": 1}]},
    )
    assert too_many.status_code == 400
    bad_kind = await client.post(
        f"{API}/market/list",
        json={"entries": [{"type": "stack", "stackKind": "potion", "stackItemId": "g_ore", "count": 1, "unitPrice": 1}]},
    )
    assert bad_kind.status_code == 400

    token_b = await _register(client, "mkt_s_b")
    uid_b = await _user_id(session_factory, "mkt_s_b")
    await _set_gold(session_factory, uid_b, 1000)
    _auth(client, token_b)

    resp = await client.post(f"{API}/market/buy", json={"listingId": listing["id"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 120

    async with session_factory() as db:
        buyer = (
            await db.execute(
                select(StackItem).where(
                    StackItem.user_id == uid_b, StackItem.item_id == "g_ore", StackItem.kind == "material"
                )
            )
        ).scalar_one()
        assert buyer.count == 4
        seller = (await db.execute(select(User).where(User.id == uid_a))).scalar_one()
        assert int(seller.gold) == 120 - market.fee_of(120)


async def test_expired_listing_returns_escrow(client, session_factory):
    token = await _register(client, "mkt_exp")
    uid = await _user_id(session_factory, "mkt_exp")
    item_id = await _seed_item(session_factory, uid)
    _auth(client, token)
    listing_id = (
        await client.post(
            f"{API}/market/list",
            json={"entries": [{"type": "equipment", "itemId": item_id, "unitPrice": 100}]},
        )
    ).json()["listings"][0]["id"]

    async with session_factory() as db:
        row = (await db.execute(select(MarketListing).where(MarketListing.id == listing_id))).scalar_one()
        row.expires_at = utcnow() - timedelta(seconds=1)
        await db.commit()

    # 浏览触发惰性结算
    resp = await client.get(f"{API}/market/listings")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    async with session_factory() as db:
        row = (await db.execute(select(MarketListing).where(MarketListing.id == listing_id))).scalar_one()
        assert row.status == STATUS_EXPIRED
        items = (
            await db.execute(
                select(Item).where(Item.user_id == uid, Item.base_id == "w_sword_shield_1")
            )
        ).scalars().all()
        assert len(items) == 1


async def test_other_players_listings_browsable_and_banned_hidden(client, session_factory):
    token_a = await _register(client, "mkt_b_a")
    uid_a = await _user_id(session_factory, "mkt_b_a")
    item_id = await _seed_item(session_factory, uid_a)
    _auth(client, token_a)
    await client.post(
        f"{API}/market/list",
        json={"entries": [{"type": "equipment", "itemId": item_id, "unitPrice": 250}]},
    )

    token_b = await _register(client, "mkt_b_b")
    _auth(client, token_b)
    body = (await client.get(f"{API}/market/listings")).json()
    assert body["total"] == 1
    assert body["listings"][0]["unitPrice"] == 250
    assert body["listings"][0]["sellerNickname"] == "mkt_b_a"
    assert body["feePct"] == 0.10

    # 卖家被封 → 不再展示
    await _set_banned(session_factory, uid_a, True)
    assert (await client.get(f"{API}/market/listings")).json()["total"] == 0


def test_market_config_and_fee_math():
    cfg = CONFIG.economy["market"]
    assert 0 < float(cfg["feePct"]) < 1
    assert int(cfg["listingDays"]) >= 1
    assert market.fee_of(1000) == 100
    assert market.net_of(1000) == 900
    for price in (1, 7, 99, 12345):
        assert 0 <= market.fee_of(price) <= price
        assert market.net_of(price) == price - market.fee_of(price)
    # 往返（买入 → 再上架卖出）必然净亏，封堵市场与系统回收间的套利
    assert market.net_of(1000) < 1000

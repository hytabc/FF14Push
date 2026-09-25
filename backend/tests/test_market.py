"""市场交易板：上架托管 / 成交抽费 / 下架与到期退回 / 反作弊回归。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import DohDolProgress, Hero, Item, MarketBuyOrder, MarketListing, StackItem, User
from app.models.base import utcnow
from app.models.market import (
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
    STATUS_FILLED,
    STATUS_SOLD,
)
from app.services import dohdol_util, market, reference
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


async def _set_hero_level(session_factory, user_id: int, level: int) -> None:
    async with session_factory() as db:
        hero = (
            await db.execute(select(Hero).where(Hero.user_id == user_id).order_by(Hero.id))
        ).scalars().first()
        hero.level = level
        await db.commit()


async def _set_dohdol_level(session_factory, user_id: int, kind: str, level: int) -> None:
    async with session_factory() as db:
        row = (
            await db.execute(
                select(DohDolProgress).where(
                    DohDolProgress.user_id == user_id, DohDolProgress.kind == kind
                )
            )
        ).scalar_one()
        row.level = level
        await db.commit()


async def _list_one(client, item_id: int, price: int) -> int:
    resp = await client.post(
        f"{API}/market/list",
        json={"entries": [{"type": "equipment", "itemId": item_id, "unitPrice": price}]},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["listings"][0]["id"])


def _mk_listing(kind: str, category: str | None = None, level_req: int | None = None) -> MarketListing:
    return MarketListing(kind=kind, category=category, level_req=level_req)


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


async def test_mine_shows_who_bought_sold_listing(client, session_factory):
    """卖家「已结束记录」需能看出物品被谁买走。"""
    token_a = await _register(client, "mkt_who_a")
    uid_a = await _user_id(session_factory, "mkt_who_a")
    item_id = await _seed_item(session_factory, uid_a)
    _auth(client, token_a)
    listing_id = (
        await client.post(
            f"{API}/market/list",
            json={"entries": [{"type": "equipment", "itemId": item_id, "unitPrice": 1000}]},
        )
    ).json()["listings"][0]["id"]

    # 在售时没有买家
    mine = (await client.get(f"{API}/market/mine")).json()
    active = next(l for l in mine["active"] if l["id"] == listing_id)
    assert active["buyerId"] is None and active["buyerNickname"] is None

    token_b = await _register(client, "mkt_who_b")
    uid_b = await _user_id(session_factory, "mkt_who_b")
    await _set_gold(session_factory, uid_b, 5000)
    _auth(client, token_b)
    assert (await client.post(f"{API}/market/buy", json={"listingId": listing_id})).status_code == 200

    _auth(client, token_a)
    mine = (await client.get(f"{API}/market/mine")).json()
    sold = next(l for l in mine["closed"] if l["id"] == listing_id)
    assert sold["status"] == STATUS_SOLD
    assert sold["buyerId"] == uid_b
    assert sold["buyerNickname"] == "mkt_who_b"


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


async def test_listings_scalar_filters(client, session_factory):
    """部位 / 等级区间 / 价格区间筛选下推到 SQL，total 随之收敛。"""
    token_a = await _register(client, "mkt_f_a")
    uid_a = await _user_id(session_factory, "mkt_f_a")
    _auth(client, token_a)

    main = await _seed_item(session_factory, uid_a, slot="mainHand", level_req=80)
    body = await _seed_item(
        session_factory,
        uid_a,
        base_id="a_body_1",
        name="测试上衣",
        category="armor",
        slot="body",
        level_req=30,
    )
    await _list_one(client, main, 5000)
    await _list_one(client, body, 100)

    token_b = await _register(client, "mkt_f_b")
    _auth(client, token_b)

    async def browse(**params) -> list[str]:
        resp = await client.get(f"{API}/market/listings", params={"kind": "equipment", **params})
        assert resp.status_code == 200, resp.text
        return sorted(l["name"] for l in resp.json()["listings"])

    both = sorted(["测试剑盾", "测试上衣"])
    assert await browse() == both
    assert await browse(slot="body") == ["测试上衣"]
    assert await browse(levelMin=50) == ["测试剑盾"]
    assert await browse(levelMax=50) == ["测试上衣"]
    assert await browse(priceMin=1000) == ["测试剑盾"]
    assert await browse(priceMax=1000) == ["测试上衣"]
    # 条件为 AND：部位命中但等级不命中 → 空
    assert await browse(slot="body", levelMin=50) == []

    resp = await client.get(f"{API}/market/listings", params={"kind": "equipment", "slot": "body"})
    assert resp.json()["total"] == 1


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


# ------------------------------------------------------------------ 购买等级门槛
def test_purchase_level_requirement_mapping():
    assert market.requirement_of(_mk_listing("equipment", "weapon", 60)) == ("combat", 60)
    assert market.requirement_of(_mk_listing("equipment", "armor", 20)) == ("combat", 20)
    assert market.requirement_of(_mk_listing("equipment", "accessory", 5)) == ("combat", 5)
    assert market.requirement_of(_mk_listing("equipment", "doh_tool", 30)) == ("doh", 30)
    assert market.requirement_of(_mk_listing("equipment", "doh_gear", 30)) == ("doh", 30)
    assert market.requirement_of(_mk_listing("equipment", "dol_tool", 30)) == ("dol", 30)
    assert market.requirement_of(_mk_listing("equipment", "dol_gear", 30)) == ("dol", 30)
    # 1 级无门槛；素材 / 消耗品不受限
    assert market.requirement_of(_mk_listing("equipment", "weapon", 1)) is None
    assert market.requirement_of(_mk_listing("material")) is None
    assert market.requirement_of(_mk_listing("potion")) is None
    assert market.requirement_of(_mk_listing("food")) is None

    doh_gear = _mk_listing("equipment", "doh_gear", 30)
    assert market.meets_requirement(doh_gear, {"combat": 100, "doh": 29, "dol": 100}) is False
    assert market.meets_requirement(doh_gear, {"combat": 100, "doh": 30, "dol": 1}) is True
    assert "生产职业等级" in market.requirement_error(doh_gear)

    combat = _mk_listing("equipment", "weapon", 60)
    assert market.meets_requirement(combat, {"combat": 59, "doh": 100, "dol": 100}) is False
    assert market.meets_requirement(combat, {"combat": 60, "doh": 1, "dol": 1}) is True

    material = _mk_listing("material")
    assert market.meets_requirement(material, {"combat": 1, "doh": 1, "dol": 1}) is True


async def test_buy_combat_equipment_requires_hero_level(client, session_factory):
    token_a = await _register(client, "mkt_lv_sell")
    uid_a = await _user_id(session_factory, "mkt_lv_sell")
    item_id = await _seed_item(session_factory, uid_a, category="weapon", level_req=60)
    _auth(client, token_a)
    listing_id = await _list_one(client, item_id, 1000)

    token_b = await _register(client, "mkt_lv_buy")
    uid_b = await _user_id(session_factory, "mkt_lv_buy")
    await _set_gold(session_factory, uid_b, 5000)
    _auth(client, token_b)

    # 英雄仅 1 级 → 拒绝
    resp = await client.post(f"{API}/market/buy", json={"listingId": listing_id})
    assert resp.status_code == 400
    assert "等级" in resp.json()["detail"]

    # 账号内任一英雄达标即可购买
    await _set_hero_level(session_factory, uid_b, 60)
    resp = await client.post(f"{API}/market/buy", json={"listingId": listing_id})
    assert resp.status_code == 200, resp.text


async def test_buy_dohdol_equipment_requires_matching_job_level(client, session_factory):
    token_a = await _register(client, "mkt_dh_sell")
    uid_a = await _user_id(session_factory, "mkt_dh_sell")
    item_id = await _seed_item(
        session_factory, uid_a, base_id="dh_dohGear", category="doh_gear", slot="head", level_req=50
    )
    _auth(client, token_a)
    listing_id = await _list_one(client, item_id, 800)

    token_b = await _register(client, "mkt_dh_buy")
    uid_b = await _user_id(session_factory, "mkt_dh_buy")
    await _set_gold(session_factory, uid_b, 5000)
    _auth(client, token_b)

    # 战斗等级再高也不能替代生产等级
    await _set_hero_level(session_factory, uid_b, 100)
    assert (await client.post(f"{API}/market/buy", json={"listingId": listing_id})).status_code == 400

    # 采集等级达标也不行，必须是生产等级
    await _set_dohdol_level(session_factory, uid_b, "dol", 100)
    assert (await client.post(f"{API}/market/buy", json={"listingId": listing_id})).status_code == 400

    # 生产等级达标 → 成交
    await _set_dohdol_level(session_factory, uid_b, "doh", 50)
    resp = await client.post(f"{API}/market/buy", json={"listingId": listing_id})
    assert resp.status_code == 200, resp.text


async def test_listings_expose_purchase_level_requirement(client, session_factory):
    token_a = await _register(client, "mkt_req_a")
    uid_a = await _user_id(session_factory, "mkt_req_a")
    equip_id = await _seed_item(session_factory, uid_a, level_req=40)
    await _seed_stack(session_factory, uid_a, "material", "g_ore", 5)
    _auth(client, token_a)
    resp = await client.post(
        f"{API}/market/list",
        json={
            "entries": [
                {"type": "equipment", "itemId": equip_id, "unitPrice": 500},
                {"type": "stack", "stackKind": "material", "stackItemId": "g_ore", "count": 5, "unitPrice": 20},
            ]
        },
    )
    assert resp.status_code == 200, resp.text

    token_b = await _register(client, "mkt_req_b")
    uid_b = await _user_id(session_factory, "mkt_req_b")
    _auth(client, token_b)

    body = (await client.get(f"{API}/market/listings")).json()
    by_kind = {row["kind"]: row for row in body["listings"]}
    assert by_kind["equipment"]["requiredKind"] == "combat"
    assert by_kind["equipment"]["levelMet"] is False
    # 素材不受等级限制
    assert by_kind["material"]["requiredKind"] is None
    assert by_kind["material"]["levelMet"] is True

    # 英雄达标后 levelMet 转为 True
    await _set_hero_level(session_factory, uid_b, 40)
    body = (await client.get(f"{API}/market/listings")).json()
    equip = next(row for row in body["listings"] if row["kind"] == "equipment")
    assert equip["levelMet"] is True


async def test_fish_is_separated_from_materials(client, session_factory):
    """交易板把「鱼获」与「素材」分开过滤：kind=fish 只看鱼，kind=material 排除鱼。"""
    token_a = await _register(client, "mkt_fish_a")
    uid_a = await _user_id(session_factory, "mkt_fish_a")
    await _seed_stack(session_factory, uid_a, "material", "f1_1", 5)
    await _seed_stack(session_factory, uid_a, "material", "g_ore", 5)
    _auth(client, token_a)
    resp = await client.post(
        f"{API}/market/list",
        json={
            "entries": [
                {"type": "stack", "stackKind": "material", "stackItemId": "f1_1", "count": 5, "unitPrice": 10},
                {"type": "stack", "stackKind": "material", "stackItemId": "g_ore", "count": 5, "unitPrice": 10},
            ]
        },
    )
    assert resp.status_code == 200, resp.text

    token_b = await _register(client, "mkt_fish_b")
    _auth(client, token_b)

    fish = (await client.get(f"{API}/market/listings", params={"kind": "fish"})).json()
    assert {row["itemKey"] for row in fish["listings"]} == {"f1_1"}

    mats = (await client.get(f"{API}/market/listings", params={"kind": "material"})).json()
    keys = {row["itemKey"] for row in mats["listings"]}
    assert "f1_1" not in keys and "g_ore" in keys


# ------------------------------------------------------------------ 魔晶石 / 种子交易
async def test_materia_listing_and_buy(client, session_factory):
    """魔晶石可在交易板上架 / 购买（此前被 schema 与 sellable_kind 双重拦截）。"""
    token_a = await _register(client, "mkt_m_a")
    uid_a = await _user_id(session_factory, "mkt_m_a")
    await _seed_stack(session_factory, uid_a, "materia", "m_crit_1", 5)
    _auth(client, token_a)

    resp = await client.post(
        f"{API}/market/list",
        json={
            "entries": [
                {
                    "type": "stack",
                    "stackKind": "materia",
                    "stackItemId": "m_crit_1",
                    "count": 3,
                    "unitPrice": 200,
                }
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    listing = resp.json()["listings"][0]
    assert listing["kind"] == "materia" and listing["quantity"] == 3
    assert listing["referencePrice"] == reference.stack_reference("materia", "m_crit_1")
    assert listing["referencePrice"] > 0  # 魔晶石按挖宝来源成本折算，参考价为正

    token_b = await _register(client, "mkt_m_b")
    uid_b = await _user_id(session_factory, "mkt_m_b")
    await _set_gold(session_factory, uid_b, 5000)
    _auth(client, token_b)

    # 可按魔晶石分类浏览到
    browse = (await client.get(f"{API}/market/listings", params={"kind": "materia"})).json()
    assert any(row["id"] == listing["id"] for row in browse["listings"])

    assert (
        await client.post(f"{API}/market/buy", json={"listingId": listing["id"]})
    ).status_code == 200
    async with session_factory() as db:
        buyer = (
            await db.execute(
                select(StackItem).where(
                    StackItem.user_id == uid_b,
                    StackItem.kind == "materia",
                    StackItem.item_id == "m_crit_1",
                )
            )
        ).scalar_one()
        assert int(buyer.count) == 3
        seller = (
            await db.execute(
                select(StackItem).where(
                    StackItem.user_id == uid_a,
                    StackItem.kind == "materia",
                    StackItem.item_id == "m_crit_1",
                )
            )
        ).scalar_one()
        assert int(seller.count) == 2


async def test_seed_listing_and_buy(client, session_factory):
    """种子可在交易板上架：系统回收价为 0，参考价按挖宝来源成本折算为正。"""
    token_a = await _register(client, "mkt_seed_a")
    uid_a = await _user_id(session_factory, "mkt_seed_a")
    await _seed_stack(session_factory, uid_a, "seed", "seed_gold", 4)
    _auth(client, token_a)

    resp = await client.post(
        f"{API}/market/list",
        json={
            "entries": [
                {
                    "type": "stack",
                    "stackKind": "seed",
                    "stackItemId": "seed_gold",
                    "count": 2,
                    "unitPrice": 5000,
                }
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    listing = resp.json()["listings"][0]
    assert listing["kind"] == "seed" and listing["quantity"] == 2
    assert listing["referencePrice"] == reference.stack_reference("seed", "seed_gold")
    assert listing["referencePrice"] > 0  # 回收价为 0，参考价按挖宝来源成本折算为正

    token_b = await _register(client, "mkt_seed_b")
    uid_b = await _user_id(session_factory, "mkt_seed_b")
    await _set_gold(session_factory, uid_b, 50_000)
    _auth(client, token_b)
    assert (
        await client.post(f"{API}/market/buy", json={"listingId": listing["id"]})
    ).status_code == 200
    async with session_factory() as db:
        row = (
            await db.execute(
                select(StackItem).where(
                    StackItem.user_id == uid_b,
                    StackItem.kind == "seed",
                    StackItem.item_id == "seed_gold",
                )
            )
        ).scalar_one()
        assert int(row.count) == 2


# ------------------------------------------------------------------ 收购单（求购）
async def test_buy_order_escrows_and_partial_fill(client, session_factory):
    """收购单：发布全额托管金币 → 卖家部分成交（得 amount - fee）→ 补满后自动完成。"""
    token_b = await _register(client, "mkt_bo_buyer")
    uid_b = await _user_id(session_factory, "mkt_bo_buyer")
    await _set_gold(session_factory, uid_b, 10_000)
    _auth(client, token_b)

    resp = await client.post(
        f"{API}/market/buy-orders",
        json={"kind": "material", "itemId": "g_ore", "quantity": 4, "unitPrice": 100},
    )
    assert resp.status_code == 200, resp.text
    order_id = resp.json()["order"]["id"]
    assert resp.json()["order"]["remaining"] == 4
    assert resp.json()["gold"] == 9600  # 4 × 100 全额托管

    token_s = await _register(client, "mkt_bo_seller")
    uid_s = await _user_id(session_factory, "mkt_bo_seller")
    await _seed_stack(session_factory, uid_s, "material", "g_ore", 5)
    await _set_gold(session_factory, uid_s, 0)
    _auth(client, token_s)

    fee = market.fee_of(200)
    fill = (
        await client.post(f"{API}/market/buy-orders/fill", json={"orderId": order_id, "count": 2})
    ).json()
    assert fill["count"] == 2 and fill["total"] == 200 and fill["fee"] == fee
    assert fill["gold"] == 200 - fee
    assert fill["remaining"] == 2 and fill["status"] == STATUS_ACTIVE

    # 超出剩余量的部分被截断到剩余量，正好补满 → 完成
    fill2 = (
        await client.post(f"{API}/market/buy-orders/fill", json={"orderId": order_id, "count": 99})
    ).json()
    assert fill2["count"] == 2 and fill2["remaining"] == 0
    assert fill2["status"] == STATUS_FILLED

    async with session_factory() as db:
        buyer = (
            await db.execute(
                select(StackItem).where(
                    StackItem.user_id == uid_b,
                    StackItem.kind == "material",
                    StackItem.item_id == "g_ore",
                )
            )
        ).scalar_one()
        assert int(buyer.count) == 4
        seller = (
            await db.execute(
                select(StackItem).where(
                    StackItem.user_id == uid_s,
                    StackItem.kind == "material",
                    StackItem.item_id == "g_ore",
                )
            )
        ).scalar_one()
        assert int(seller.count) == 1
        row = (
            await db.execute(select(MarketBuyOrder).where(MarketBuyOrder.id == order_id))
        ).scalar_one()
        assert row.status == STATUS_FILLED and int(row.filled) == 4


async def test_buy_order_cancel_refunds_unfilled(client, session_factory):
    """取消收购单只退还未成交部分的托管金币。"""
    token_b = await _register(client, "mkt_bo_cancel")
    uid_b = await _user_id(session_factory, "mkt_bo_cancel")
    await _set_gold(session_factory, uid_b, 10_000)
    _auth(client, token_b)
    order_id = (
        await client.post(
            f"{API}/market/buy-orders",
            json={"kind": "material", "itemId": "g_ore", "quantity": 4, "unitPrice": 100},
        )
    ).json()["order"]["id"]

    token_s = await _register(client, "mkt_bo_cancel_s")
    uid_s = await _user_id(session_factory, "mkt_bo_cancel_s")
    await _seed_stack(session_factory, uid_s, "material", "g_ore", 1)
    _auth(client, token_s)
    assert (
        await client.post(f"{API}/market/buy-orders/fill", json={"orderId": order_id, "count": 1})
    ).status_code == 200

    _auth(client, token_b)
    cancel = await client.post(f"{API}/market/buy-orders/cancel", json={"orderId": order_id})
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["refund"] == 300  # 托管 400，已成交 100
    assert cancel.json()["gold"] == 10_000 - 400 + 300

    mine = (await client.get(f"{API}/market/buy-orders/mine")).json()
    assert all(order["id"] != order_id for order in mine["active"])
    closed = next(order for order in mine["closed"] if order["id"] == order_id)
    assert closed["status"] == STATUS_CANCELLED and closed["filled"] == 1


async def test_buy_order_expiry_refunds_unfilled(client, session_factory):
    """到期收购单在浏览时惰性过期，并退还未成交部分的托管金币。"""
    token_b = await _register(client, "mkt_bo_exp")
    uid_b = await _user_id(session_factory, "mkt_bo_exp")
    await _set_gold(session_factory, uid_b, 10_000)
    _auth(client, token_b)
    order_id = (
        await client.post(
            f"{API}/market/buy-orders",
            json={"kind": "material", "itemId": "g_ore", "quantity": 4, "unitPrice": 100},
        )
    ).json()["order"]["id"]

    async with session_factory() as db:
        row = (
            await db.execute(select(MarketBuyOrder).where(MarketBuyOrder.id == order_id))
        ).scalar_one()
        row.expires_at = utcnow() - timedelta(seconds=1)
        await db.commit()

    assert (await client.get(f"{API}/market/buy-orders")).status_code == 200

    async with session_factory() as db:
        row = (
            await db.execute(select(MarketBuyOrder).where(MarketBuyOrder.id == order_id))
        ).scalar_one()
        assert row.status == STATUS_EXPIRED
    state = (await client.get(f"{API}/game/state")).json()
    assert state["user"]["gold"] == 10_000  # 全额退还


async def test_buy_order_rejects_self_and_insufficient_stock(client, session_factory):
    """收购单反作弊与边界：不能自卖自单、库存不足、类型不匹配、托管金币不足。"""
    token_b = await _register(client, "mkt_bo_self")
    uid_b = await _user_id(session_factory, "mkt_bo_self")
    await _set_gold(session_factory, uid_b, 10_000)
    _auth(client, token_b)
    order_id = (
        await client.post(
            f"{API}/market/buy-orders",
            json={"kind": "material", "itemId": "g_ore", "quantity": 2, "unitPrice": 100},
        )
    ).json()["order"]["id"]

    # 不能卖给自己发布的收购单
    await _seed_stack(session_factory, uid_b, "material", "g_ore", 2)
    assert (
        await client.post(f"{API}/market/buy-orders/fill", json={"orderId": order_id, "count": 1})
    ).status_code == 400

    # 他人库存不足
    token_s = await _register(client, "mkt_bo_low")
    _auth(client, token_s)
    assert (
        await client.post(f"{API}/market/buy-orders/fill", json={"orderId": order_id, "count": 1})
    ).status_code == 400

    # 物品类型与声明不符
    assert (
        await client.post(
            f"{API}/market/buy-orders",
            json={"kind": "seed", "itemId": "g_ore", "quantity": 1, "unitPrice": 10},
        )
    ).status_code == 400

    # 托管金币不足
    assert (
        await client.post(
            f"{API}/market/buy-orders",
            json={"kind": "material", "itemId": "g_ore", "quantity": 9999, "unitPrice": 100},
        )
    ).status_code == 400

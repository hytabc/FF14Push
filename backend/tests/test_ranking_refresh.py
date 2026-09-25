"""排行榜全量刷新：改造后必须与「把全部装备交给 stats」的旧口径逐位等价。

旧口径 = `compute_stats(hero, user.items)`（该账号**全部**装备，含背包）。
新实现（`_refresh_all_rankings`）只加载 `equipped_slot IS NOT NULL` 的装备并分批处理。
等价性依据：`stats.aggregate_equipment` 跳过未装备装备，`stats.hero_items` 只保留
`equipped_hero_id in (None, hero.id)` 的行——背包里的装备对面板没有任何贡献。

同时校验「分批」不改变结果（批大小 1 与批大小 500 结果一致）。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Hero, Item, RankingEntry, User
from app.services.game_config import CONFIG
from app.services.ranking import refresh_all_rankings
from app.services.stats import compute_stats
from app.services.valuation import hero_power

# 从真实配置里取底材 id（武器需真实 id 才能解析出 weaponType / jobId）。
_WEAPON = next(b for b in CONFIG.base_items if b.category == "weapon" and b.slot == "mainHand")
_ARMOR = next(b for b in CONFIG.base_items if b.category == "armor")
_ACCESSORY = next(b for b in CONFIG.base_items if b.category == "accessory")


def _item(
    user_id: int,
    *,
    base_id: str,
    slot: str,
    category: str,
    equipped_slot: str | None = None,
    equipped_hero_id: int | None = None,
    base_attrs: list[dict] | None = None,
    sub_attrs: list[dict] | None = None,
    terms: list[dict] | None = None,
) -> Item:
    return Item(
        user_id=user_id,
        base_id=base_id,
        name="测试装备",
        category=category,
        slot=slot,
        rarity="legendary",
        level_req=100,
        base_attrs=base_attrs or [],
        sub_attrs=sub_attrs or [],
        terms=terms or [],
        equipped_slot=equipped_slot,
        equipped_hero_id=equipped_hero_id,
        source="chest",
    )


async def _seed_user(sessions, username: str, attack: int) -> tuple[int, int]:
    """建一个 100 级账号：1 件已装备武器 + 1 件已装备饰品 + 2 件背包垃圾。"""
    async with sessions() as db:
        user = User(username=username, password_hash="x", nickname=username, gold=1234)
        db.add(user)
        await db.flush()
        hero = Hero(user_id=user.id, name=username, level=100, talent="common", attr_bias="balanced")
        db.add(hero)
        await db.flush()
        user.active_hero_id = hero.id
        db.add_all(
            [
                _item(
                    user.id,
                    base_id=_WEAPON.id,
                    slot="mainHand",
                    category="weapon",
                    equipped_slot="mainHand",
                    equipped_hero_id=hero.id,
                    base_attrs=[{"attr": "attack", "value": attack}],
                    sub_attrs=[{"attr": "crit", "value": 300 + attack % 97}],
                    terms=[{"type": "buff", "stat": "det", "value": 50, "quality": "common"}],
                ),
                _item(
                    user.id,
                    base_id=_ACCESSORY.id,
                    slot=_ACCESSORY.slot,
                    category="accessory",
                    equipped_slot=_ACCESSORY.slot,
                    equipped_hero_id=hero.id,
                    base_attrs=[{"attr": "dex", "value": 200}],
                ),
                # 背包垃圾：属性给得极大，若被误计入会立刻体现为战力不同。
                _item(
                    user.id,
                    base_id=_ARMOR.id,
                    slot=_ARMOR.slot,
                    category="armor",
                    base_attrs=[{"attr": "hp", "value": 9_999_999}],
                    sub_attrs=[{"attr": "crit", "value": 9_999}],
                ),
                _item(
                    user.id,
                    base_id=_ARMOR.id,
                    slot=_ARMOR.slot,
                    category="armor",
                    base_attrs=[{"attr": "attack", "value": 9_999_999}],
                ),
            ]
        )
        await db.commit()
        return int(user.id), int(hero.id)


async def test_refresh_power_matches_full_inventory(session_factory):
    """只加载已装备装备的结果，必须等于「把全部装备交给 stats」的结果。"""
    uid, hero_id = await _seed_user(session_factory, "rank_eq", attack=1500)

    # 旧口径：该账号全部装备（含背包）交给 stats。
    async with session_factory() as db:
        user = await db.get(User, uid)
        hero = await db.get(Hero, hero_id)
        all_items = (await db.execute(select(Item).where(Item.user_id == uid))).scalars().all()
        expected_power = hero_power(compute_stats(hero, all_items))

    async with session_factory() as db:
        await refresh_all_rankings(db)
        await db.commit()

    async with session_factory() as db:
        row = await db.scalar(
            select(RankingEntry).where(
                RankingEntry.board == "power", RankingEntry.user_id == uid
            )
        )
    assert row is not None, "刷新后应写入战力榜行"
    assert row.value == expected_power, "只加载已装备装备不得改变战力结果"


async def test_refresh_excludes_bag_items(session_factory):
    """背包里的高属性装备不得进入战力（防止把背包算进排名）。"""
    uid, hero_id = await _seed_user(session_factory, "rank_bag", attack=800)

    async with session_factory() as db:
        hero = await db.get(Hero, hero_id)
        equipped_only = [
            item
            for item in (await db.execute(select(Item).where(Item.user_id == uid))).scalars().all()
            if item.equipped_slot is not None
        ]
        equipped_power = hero_power(compute_stats(hero, equipped_only))

    async with session_factory() as db:
        await refresh_all_rankings(db)
        await db.commit()

    async with session_factory() as db:
        row = await db.scalar(
            select(RankingEntry).where(
                RankingEntry.board == "power", RankingEntry.user_id == uid
            )
        )
    assert row is not None
    assert row.value == equipped_power


async def test_refresh_is_chunk_invariant(session_factory, monkeypatch):
    """分批大小不改变结果（批大小 1 与默认批大小结果逐位一致）。"""
    from app.services import ranking as ranking_module

    for index in range(3):
        await _seed_user(session_factory, f"rank_chunk_{index}", attack=700 + index * 111)

    async with session_factory() as db:
        await refresh_all_rankings(db)
        await db.commit()
    async with session_factory() as db:
        single_batch = {
            (row.user_id, row.board): row.value
            for row in (await db.execute(select(RankingEntry))).scalars().all()
        }

    monkeypatch.setattr(ranking_module, "REFRESH_USER_CHUNK", 1)
    async with session_factory() as db:
        await refresh_all_rankings(db)
        await db.commit()
    async with session_factory() as db:
        small_batch = {
            (row.user_id, row.board): row.value
            for row in (await db.execute(select(RankingEntry))).scalars().all()
        }

    assert single_batch == small_batch
    assert single_batch, "应写入榜单行"

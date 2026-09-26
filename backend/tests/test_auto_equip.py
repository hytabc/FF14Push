"""一键最强：武器锚点、职能限制、逐栏位最优、跨英雄取用可选项。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Hero, Item, User
from app.services.game_config import CONFIG
from app.services.slots_util import role_of_base

API = "/api/v1"


def _find(pred) -> object:
    for base in CONFIG.base_item_by_id.values():
        if pred(base):
            return base
    raise AssertionError("未找到匹配的底材")


def _weapon(role: str):
    return _find(lambda b: b.category == "weapon" and b.job_id and CONFIG.job_by_id[b.job_id]["role"] == role)


def _armor_in_slot(slot: str, role: str | None):
    if role is None:
        return _find(lambda b: b.category == "armor" and b.slot == slot and role_of_base(b) is None)
    return _find(lambda b: b.category == "armor" and b.slot == slot and role_of_base(b) == role)


def _ring(role: str):
    return _find(lambda b: b.category == "accessory" and b.slot == "ring" and role_of_base(b) == role)


async def _make_hero(session_factory, name: str = "主英雄") -> tuple[int, int]:
    async with session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        hero = Hero(
            user_id=user.id, name=name, level=50, exp=0, talent="common",
            attr_bias="balanced", strength=100, agility=100, intellect=100,
        )
        db.add(hero)
        await db.flush()
        user.active_hero_id = hero.id
        await db.commit()
        return int(user.id), int(hero.id)


async def _add_hero(session_factory, user_id: int, name: str) -> int:
    async with session_factory() as db:
        hero = Hero(
            user_id=user_id, name=name, level=50, exp=0, talent="common",
            attr_bias="balanced", strength=100, agility=100, intellect=100,
        )
        db.add(hero)
        await db.flush()
        hid = int(hero.id)
        await db.commit()
        return hid


async def _add_items(session_factory, user_id: int, specs: list[dict]) -> list[int]:
    """按规格插入装备：战力由 base_attrs 的数值决定（同一种属性，便于按 score 排序）。"""
    ids: list[int] = []
    async with session_factory() as db:
        for spec in specs:
            base = spec["base"]
            item = Item(
                user_id=user_id, base_id=base.id, name=spec.get("name", "测试"),
                category=base.category, slot=base.slot, rarity="common", level_req=1,
                base_attrs=[{"attr": "attack", "value": float(spec["score"])}],
                sub_attrs=[], terms=[],
                equipped_hero_id=spec.get("hero"), equipped_slot=spec.get("slot"),
                source="test",
            )
            db.add(item)
            await db.flush()
            ids.append(int(item.id))
        await db.commit()
    return ids


@pytest.mark.asyncio
async def test_auto_equip_requires_weapon(auth_client, session_factory):
    await _make_hero(session_factory)
    resp = await auth_client.post(f"{API}/inventory/auto-equip", json={"includeEquipped": False})
    assert resp.status_code == 400
    assert "武器" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_picks_best_compatible_and_keeps_weapon(auth_client, session_factory):
    user_id, hero_id = await _make_hero(session_factory)
    weapon = _weapon("tank")
    armor = _armor_in_slot("head", "tank")
    healer = _armor_in_slot("head", "healer")
    ring = _ring("tank")

    await _add_items(session_factory, user_id, [
        {"base": weapon, "score": 1, "hero": hero_id, "slot": "mainHand", "name": "锚定武器"},
        {"base": armor, "score": 10, "name": "坦克甲-弱"},
        {"base": armor, "score": 30, "name": "坦克甲-强"},
        {"base": healer, "score": 999, "name": "治疗甲（不应装备）"},
        {"base": ring, "score": 5, "name": "戒指A"},
        {"base": ring, "score": 8, "name": "戒指B"},
    ])

    resp = await auth_client.post(f"{API}/inventory/auto-equip", json={"includeEquipped": False})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    equipped = {row["slot"]: row["item"]["name"] for row in body["equipped"]}

    # 主手武器为职业锚点：不在「一键最强」的更换结果里
    assert "mainHand" not in equipped
    assert equipped["head"] == "坦克甲-强"  # 同职能中取战力最高
    assert "治疗甲（不应装备）" not in equipped.values()  # 职能不符不装备
    assert {equipped["ring1"], equipped["ring2"]} == {"戒指A", "戒指B"}  # 两戒指各取一件不同装备
    assert body["fromOthers"] == 0

    state = (await auth_client.get(f"{API}/game/state")).json()
    assert state["loadout"]["mainHand"]["name"] == "锚定武器"
    assert state["loadout"]["head"]["name"] == "坦克甲-强"


@pytest.mark.asyncio
async def test_other_hero_gear_only_when_allowed(auth_client, session_factory):
    user_id, hero_id = await _make_hero(session_factory)
    other_hero_id = await _add_hero(session_factory, user_id, "副英雄")
    weapon = _weapon("tank")
    armor = _armor_in_slot("head", "tank")

    await _add_items(session_factory, user_id, [
        {"base": weapon, "score": 1, "hero": hero_id, "slot": "mainHand", "name": "锚定武器"},
        {"base": armor, "score": 20, "name": "背包甲"},
        {"base": armor, "score": 50, "hero": other_hero_id, "slot": "head", "name": "副英雄甲"},
    ])

    # 默认：不动其他英雄的装备
    resp = await auth_client.post(f"{API}/inventory/auto-equip", json={"includeEquipped": False})
    assert resp.status_code == 200, resp.text
    state = (await auth_client.get(f"{API}/game/state")).json()
    assert state["loadout"]["head"]["name"] == "背包甲"

    # 打开选项后预览：指向副英雄的甲，并标注来源英雄
    preview = (
        await auth_client.post(f"{API}/inventory/auto-equip/preview", json={"includeEquipped": True})
    ).json()
    change = next(c for c in preview["changes"] if c["slot"] == "head")
    assert change["next"]["name"] == "副英雄甲"
    assert change["next"]["equippedHeroId"] == other_hero_id
    assert change["current"]["name"] == "背包甲"
    assert preview["fromOthers"] == 1

    # 执行：从副英雄卸下并装到当前英雄
    resp = await auth_client.post(f"{API}/inventory/auto-equip", json={"includeEquipped": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["fromOthers"] == 1
    state = (await auth_client.get(f"{API}/game/state")).json()
    assert state["loadout"]["head"]["name"] == "副英雄甲"
    assert state["loadout"]["mainHand"]["name"] == "锚定武器"

    async with session_factory() as db:
        moved = (
            await db.execute(select(Item).where(Item.name == "副英雄甲"))
        ).scalar_one()
        assert moved.equipped_hero_id == hero_id
        assert moved.equipped_slot == "head"


@pytest.mark.asyncio
async def test_no_changes_when_already_best(auth_client, session_factory):
    user_id, hero_id = await _make_hero(session_factory)
    weapon = _weapon("tank")
    armor = _armor_in_slot("head", "tank")
    await _add_items(session_factory, user_id, [
        {"base": weapon, "score": 1, "hero": hero_id, "slot": "mainHand", "name": "锚定武器"},
        {"base": armor, "score": 30, "name": "最强甲"},
    ])
    await auth_client.post(f"{API}/inventory/auto-equip", json={"includeEquipped": False})
    preview = (
        await auth_client.post(f"{API}/inventory/auto-equip/preview", json={"includeEquipped": False})
    ).json()
    assert preview["changes"] == []

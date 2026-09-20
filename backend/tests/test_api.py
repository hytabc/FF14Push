"""接口集成测试：走通 MVP 闭环与各系统。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Item, User

API = "/api/v1"

CONFIG_REFINE_COST = {
    "common": 200, "uncommon": 1000, "rare": 5000,
    "epic": 25000, "legendary": 120000, "mythic": 600000,
}
CONFIG_ENCHANT_COST = {
    "common": 1000, "uncommon": 5000, "rare": 25000,
    "epic": 120000, "legendary": 600000, "mythic": 3000000,
}


async def _gold(client) -> int:
    return (await client.get(f"{API}/game/state")).json()["user"]["gold"]


async def _ensure_gold(client, target: int, max_reports: int = 60) -> int:
    """刷够目标金币（打怪是唯一金币来源）。"""
    current = await _gold(client)
    if current >= target:
        return current
    started = await client.post(f"{API}/battle/session/start", json={"regionId": 1})
    assert started.status_code == 200, started.text
    session_id = started.json()["sessionId"]
    for _ in range(max_reports):
        resp = await client.post(
            f"{API}/battle/session/report",
            json={
                "sessionId": session_id,
                "regionId": 1,
                "elapsedMs": 20000,
                "kills": [{"monsterId": "normal", "gold": 20, "exp": 5} for _ in range(4)],
            },
        )
        assert resp.status_code == 200, resp.text
        current = resp.json()["gold"]
        if current >= target:
            break
    await client.post(f"{API}/battle/session/stop", json={"sessionId": session_id})
    return current


async def _set_gold(client, session_factory, amount: int) -> None:
    """直接设置金币（金币只能打怪获得，测试里免去慢速刷取）。"""
    me = (await client.get(f"{API}/auth/me")).json()
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.id == me["id"]))).scalar_one()
        user.gold = amount
        await db.commit()


async def _seed_items(session_factory, user_id: int, count: int, rarity: str = "common",
                      category: str = "weapon", base_id: str = "w_sword_shield_0",
                      slot: str = "mainHand") -> None:
    async with session_factory() as db:
        for _ in range(count):
            db.add(
                Item(
                    user_id=user_id,
                    base_id=base_id,
                    name="测试底材",
                    category=category,
                    slot=slot,
                    rarity=rarity,
                    level_req=1,
                    base_attrs=[{"attr": "attack", "value": 12.0}],
                    sub_attrs=[],
                    terms=[],
                    equipped_slot=None,
                    source="test",
                )
            )
        await db.commit()


async def _open_one(client, session_factory, chest_id: str = "weaponBox") -> dict:
    await _set_gold(client, session_factory, 5000)
    resp = await client.post(f"{API}/chest/open", json={"chestId": chest_id, "count": 1})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _farm(client, region_id: int, reports: int = 3, elapsed_ms: int = 15000) -> dict:
    """开一个会话并连续上报，返回最后一次上报结果。"""
    started = await client.post(f"{API}/battle/session/start", json={"regionId": region_id})
    assert started.status_code == 200, started.text
    session_id = started.json()["sessionId"]
    spawn = started.json()["spawnInterval"]

    last = {}
    for _ in range(reports):
        resp = await client.post(
            f"{API}/battle/session/report",
            json={
                "sessionId": session_id,
                "regionId": region_id,
                "elapsedMs": elapsed_ms,
                "kills": [
                    {"monsterId": "normal", "gold": 20, "exp": 30, "dropped": False}
                    for _ in range(max(1, int(elapsed_ms / 1000 / spawn)))
                ],
                "killCount": 0,
            },
        )
        assert resp.status_code == 200, resp.text
        last = resp.json()
    return {"sessionId": session_id, **last}


class TestAuth:
    async def test_register_and_me(self, client) -> None:
        resp = await client.post(
            f"{API}/auth/register",
            json={"username": "hero1", "password": "secret123", "nickname": "小光"},
        )
        assert resp.status_code == 201
        token = resp.json()["accessToken"]

        me = await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["nickname"] == "小光"
        assert me.json()["hasHero"] is True

    async def test_duplicate_username(self, auth_client) -> None:
        resp = await auth_client.post(
            f"{API}/auth/register", json={"username": "tester", "password": "secret123"}
        )
        assert resp.status_code == 409

    async def test_bad_login(self, client) -> None:
        resp = await client.post(f"{API}/auth/login", json={"username": "nobody", "password": "x"})
        assert resp.status_code == 401

    async def test_requires_token(self, client) -> None:
        resp = await client.get(f"{API}/game/state")
        assert resp.status_code == 401


class TestInitialState:
    async def test_state_after_register(self, auth_client) -> None:
        resp = await auth_client.get(f"{API}/game/state")
        assert resp.status_code == 200
        state = resp.json()

        assert state["user"]["gold"] == 0
        assert state["hero"]["level"] == 1
        assert state["hero"]["talent"] == "common"
        assert state["hero"]["attrBias"] == "balanced"
        assert state["items"] == []
        assert state["currentRegion"]["id"] == 1
        assert state["regionProgress"]["1"]["unlocked"] is True
        assert state["regionProgress"]["2"]["unlocked"] is False

    async def test_eleven_loadout_slots(self, auth_client) -> None:
        state = (await auth_client.get(f"{API}/game/state")).json()
        cfg = (await auth_client.get(f"{API}/game/config")).json()
        assert len(cfg["slots"]) == 11
        assert state["loadout"] == {}

    async def test_config_endpoint_exposes_shared_data(self, auth_client) -> None:
        cfg = (await auth_client.get(f"{API}/game/config")).json()
        assert len(cfg["jobs"]) == 21
        assert len(cfg["baseItems"]) == 180
        assert len(cfg["regions"]["regions"]) == 40
        assert len(cfg["tutorial"]["steps"]) == 15


class TestBattleLoop:
    async def test_farming_grants_gold_and_exp(self, auth_client) -> None:
        result = await _farm(auth_client, 1, reports=4)
        assert result["gold"] > 0
        assert result["expGained"] > 0
        assert result["killCount"] > 0

    async def test_reject_absurd_report(self, auth_client) -> None:
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session_id = started.json()["sessionId"]
        resp = await auth_client.post(
            f"{API}/battle/session/report",
            json={
                "sessionId": session_id,
                "regionId": 1,
                "elapsedMs": 1000,
                "kills": [{"monsterId": "normal", "gold": 999999, "exp": 999999} for _ in range(200)],
            },
        )
        assert resp.status_code == 422
        assert "rejected" in str(resp.json()["detail"])

    async def test_gold_is_clamped_to_region_cap(self, auth_client) -> None:
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session = started.json()["sessionId"]
        await auth_client.post(
            f"{API}/battle/session/report",
            json={"sessionId": session, "regionId": 1, "elapsedMs": 20000, "kills": []},
        )
        resp = await auth_client.post(
            f"{API}/battle/session/report",
            json={
                "sessionId": session,
                "regionId": 1,
                "elapsedMs": 20000,
                "kills": [{"monsterId": "normal", "gold": 100000, "exp": 100000} for _ in range(3)],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["goldGained"] < 1000

    async def test_locked_region_rejected(self, auth_client) -> None:
        resp = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 20})
        assert resp.status_code == 403

    async def test_death_resets_progress(self, auth_client) -> None:
        await _farm(auth_client, 1, reports=2)
        before = (await auth_client.get(f"{API}/game/state")).json()["hero"]["regionKillCount"]
        resp = await auth_client.post(f"{API}/battle/death")
        assert resp.status_code == 200
        after = (await auth_client.get(f"{API}/game/state")).json()["hero"]["regionKillCount"]
        assert after == 0
        assert isinstance(before, int)

    async def test_boss_clear_unlocks_next_region(self, auth_client) -> None:
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session = started.json()["sessionId"]

        cleared = None
        for _ in range(12):
            resp = await auth_client.post(
                f"{API}/battle/session/report",
                json={
                    "sessionId": session,
                    "regionId": 1,
                    "elapsedMs": 20000,
                    "kills": [{"monsterId": "normal", "gold": 20, "exp": 30} for _ in range(4)],
                },
            )
            assert resp.status_code == 200, resp.text
            if resp.json()["killCount"] >= resp.json()["killsRequired"]:
                cleared = await auth_client.post(
                    f"{API}/battle/session/report",
                    json={
                        "sessionId": session,
                        "regionId": 1,
                        "elapsedMs": 1000,
                        "kills": [],
                        "bossKilled": True,
                        "bossFightMs": 21000,
                    },
                )
                break
        assert cleared is not None, "未能积累到 BOSS 出现条件"
        body = cleared.json()
        assert body["boss"]["firstClear"] is True
        assert body["boss"]["items"], "BOSS 应掉落宝箱装备"

        regions = (await auth_client.get(f"{API}/region")).json()
        by_id = {r["id"]: r for r in regions["regions"]}
        assert by_id[1]["cleared"] is True
        assert by_id[2]["unlocked"] is True

    async def test_stop_session(self, auth_client) -> None:
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session = started.json()["sessionId"]
        resp = await auth_client.post(f"{API}/battle/session/stop", json={"sessionId": session})
        assert resp.status_code == 200
        assert "离线收益" in resp.json()["message"]

    async def test_switch_region_resets_counter(self, auth_client) -> None:
        await _farm(auth_client, 1, reports=3)
        await auth_client.post(f"{API}/region/enter", json={"regionId": 1})
        state = (await auth_client.get(f"{API}/game/state")).json()
        assert state["hero"]["regionKillCount"] == 0


class TestEconomy:
    async def test_open_chest_needs_gold(self, auth_client) -> None:
        resp = await auth_client.post(f"{API}/chest/open", json={"chestId": "weaponBox", "count": 1})
        assert resp.status_code == 400

    async def test_open_chest_returns_items(self, auth_client, session_factory) -> None:
        await _set_gold(auth_client, session_factory, 1000)
        resp = await auth_client.post(f"{API}/chest/open", json={"chestId": "weaponBox", "count": 10})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["items"]) == 10
        for item in body["items"]:
            assert item["category"] == "weapon"
            assert item["rarity"] in ("common", "uncommon", "rare", "epic", "legendary", "mythic")
            assert item["sellPriceMin"] <= item["sellPriceMax"]
        assert body["pity"]["sinceRare"] < 10

    async def test_equip_and_unequip(self, auth_client, session_factory) -> None:
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        assert item["levelReq"] <= 1

        resp = await auth_client.post(f"{API}/inventory/equip", json={"itemId": item["id"], "slot": "mainHand"})
        assert resp.status_code == 200, resp.text
        assert (await auth_client.get(f"{API}/game/state")).json()["loadout"]["mainHand"]["id"] == item["id"]

        resp = await auth_client.post(f"{API}/inventory/unequip", json={"slot": "mainHand"})
        assert resp.status_code == 200
        assert "mainHand" not in (await auth_client.get(f"{API}/game/state")).json()["loadout"]

    async def test_weapon_sets_job(self, auth_client, session_factory) -> None:
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        resp = await auth_client.post(
            f"{API}/inventory/equip", json={"itemId": item["id"], "slot": "mainHand"}
        )
        assert resp.status_code == 200, resp.text
        state = (await auth_client.get(f"{API}/game/state")).json()
        assert state["hero"]["jobId"] != "adventurer"
        assert state["hero"]["stats"]["attack"] > 0 or state["hero"]["stats"]["magicAttack"] > 0

    async def test_sell_items(self, auth_client, session_factory) -> None:
        opened = await _open_one(auth_client, session_factory)
        ids = [i["id"] for i in opened["items"]]
        gold_mid = await _gold(auth_client)

        resp = await auth_client.post(f"{API}/inventory/sell", json={"itemIds": ids})
        assert resp.status_code == 200, resp.text
        assert resp.json()["goldGained"] > 0
        assert resp.json()["gold"] > gold_mid

    async def test_sell_equipped_is_rejected(self, auth_client, session_factory) -> None:
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        await auth_client.post(f"{API}/inventory/equip", json={"itemId": item["id"], "slot": "mainHand"})
        resp = await auth_client.post(f"{API}/inventory/sell", json={"itemIds": [item["id"]]})
        assert resp.status_code == 400
        assert "卸下" in resp.json()["detail"]

    async def test_wrong_slot_is_rejected(self, auth_client, session_factory) -> None:
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        resp = await auth_client.post(f"{API}/inventory/equip", json={"itemId": item["id"], "slot": "head"})
        assert resp.status_code == 400

    async def test_craft_preview_and_execute(self, auth_client, session_factory) -> None:
        me = (await auth_client.get(f"{API}/auth/me")).json()
        await _seed_items(session_factory, me["id"], 16, rarity="common")
        await _set_gold(auth_client, session_factory, 200)

        preview = await auth_client.post(
            f"{API}/economy/craft/preview", json={"category": "weapon", "auto": True}
        )
        assert preview.status_code == 200
        assert preview.json()["required"] == 16
        assert preview.json()["plan"]["steps"][0]["crafts"] == 1

        craft = await auth_client.post(f"{API}/economy/craft", json={"category": "weapon", "auto": True})
        assert craft.status_code == 200, craft.text
        body = craft.json()
        assert body["consumed"] == 16
        assert body["fee"] == 200
        assert len(body["produced"]) == 1
        assert body["produced"][0]["rarity"] == "uncommon"
        assert body["gold"] == 0

    async def test_craft_without_enough_items(self, auth_client, session_factory) -> None:
        me = (await auth_client.get(f"{API}/auth/me")).json()
        await _seed_items(session_factory, me["id"], 15, rarity="common")
        await _set_gold(auth_client, session_factory, 500)
        resp = await auth_client.post(f"{API}/economy/craft", json={"category": "weapon", "auto": True})
        assert resp.status_code == 400
        assert "没有可合成" in resp.json()["detail"]

    async def test_craft_needs_fee(self, auth_client, session_factory) -> None:
        me = (await auth_client.get(f"{API}/auth/me")).json()
        await _seed_items(session_factory, me["id"], 16, rarity="common")
        await _set_gold(auth_client, session_factory, 10)
        resp = await auth_client.post(f"{API}/economy/craft", json={"category": "weapon", "auto": True})
        assert resp.status_code == 400
        assert "手续费不足" in resp.json()["detail"]

    async def test_refine_only_rerolls_attrs(self, auth_client, session_factory) -> None:
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        await _set_gold(auth_client, session_factory, 700000)

        resp = await auth_client.post(f"{API}/economy/refine", json={"itemId": item["id"]})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cost"] == CONFIG_REFINE_COST[item["rarity"]]
        assert body["after"]["rarity"] == item["rarity"]
        assert body["after"]["terms"] == item["terms"]  # 重造不改变词条
        assert body["after"]["refineCount"] == 1

    async def test_enchant_rerolls_terms(self, auth_client, session_factory) -> None:
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        await _set_gold(auth_client, session_factory, 3100000)

        resp = await auth_client.post(
            f"{API}/economy/enchant", json={"itemId": item["id"], "autoUntilRare": False}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cost"] == CONFIG_ENCHANT_COST[item["rarity"]]
        assert body["after"]["enchantCount"] == 1
        assert 0 <= len(body["after"]["terms"]) <= 4


class TestTavern:
    async def test_refresh_and_recruit(self, auth_client) -> None:
        info = await auth_client.get(f"{API}/tavern")
        assert info.status_code == 200
        candidate = info.json()["candidate"]
        assert candidate["totalPoints"] > 0
        assert candidate["recruitCost"] > 0
        assert candidate["attrBias"] in ("str", "dex", "int", "balanced")

        refreshed = await auth_client.post(f"{API}/tavern/refresh", json={"useGold": False})
        assert refreshed.status_code == 200

    async def test_recruit_requires_gold(self, auth_client) -> None:
        resp = await auth_client.post(f"{API}/tavern/recruit", json={"confirm": True})
        assert resp.status_code == 400

    async def test_initial_hero_cannot_be_dismissed(self, auth_client) -> None:
        resp = await auth_client.post(f"{API}/tavern/dismiss")
        assert resp.status_code == 400


class TestCodexAndRanking:
    async def test_equipment_codex_unlocks_on_obtain(self, auth_client, session_factory) -> None:
        await _open_one(auth_client, session_factory)
        body = (await auth_client.get(f"{API}/codex?category=equipment")).json()
        assert body["progress"]["equipment"]["unlocked"] == 1
        unlocked = [e for e in body["entries"] if e["unlocked"]]
        assert len(unlocked) == 1
        assert unlocked[0]["totalCount"] == 1
        assert unlocked[0]["unlockedRarities"]

    async def test_codex_progress_after_battle(self, auth_client) -> None:
        await _farm(auth_client, 1, reports=5)
        resp = await auth_client.get(f"{API}/codex?category=monster")
        assert resp.status_code == 200
        body = resp.json()
        assert body["progress"]["monster"]["unlocked"] > 0
        unlocked = [e for e in body["entries"] if e["unlocked"]]
        assert unlocked

    async def test_equipment_codex_closed_until_drop(self, auth_client) -> None:
        resp = await auth_client.get(f"{API}/codex?category=equipment")
        body = resp.json()
        assert body["progress"]["equipment"]["total"] == 180
        assert all(not e["unlocked"] for e in body["entries"])

    async def test_term_codex_tracks_three_qualities(self, auth_client) -> None:
        body = (await auth_client.get(f"{API}/codex?category=term")).json()
        assert body["progress"]["term"]["total"] == len(body["entries"]) * 3
        for entry in body["entries"]:
            assert set(entry["qualities"]) == {"common", "rare", "ancient"}

    async def test_ranking_boards(self, auth_client) -> None:
        await auth_client.post(f"{API}/ranking/refresh")
        for board in ("level", "stage", "power", "gold"):
            resp = await auth_client.get(f"{API}/ranking?board={board}")
            assert resp.status_code == 200, board
            body = resp.json()
            assert body["board"] == board
            assert body["loggedIn"] is True
            assert body["me"] is not None

    async def test_ranking_viewable_without_login(self, client) -> None:
        resp = await client.get(f"{API}/ranking?board=level")
        assert resp.status_code == 200
        assert resp.json()["loggedIn"] is False


class TestTutorial:
    async def test_steps_and_reward(self, auth_client) -> None:
        info = await auth_client.get(f"{API}/tutorial")
        assert info.status_code == 200
        assert info.json()["totalSteps"] == 15
        assert info.json()["currentStep"] == 1

        assert (await auth_client.post(f"{API}/tutorial/step", json={"step": 5})).status_code == 200
        assert (await auth_client.post(f"{API}/tutorial/step", json={"step": 3})).status_code == 400

        done = await auth_client.post(f"{API}/tutorial/complete")
        assert done.status_code == 200
        body = done.json()
        assert body["granted"] is True
        assert body["goldGained"] == 500
        assert len(body["items"]) == 3
        assert (await auth_client.post(f"{API}/tutorial/complete")).json()["granted"] is False

    async def test_skip_grants_no_reward(self, auth_client) -> None:
        assert (await auth_client.post(f"{API}/tutorial/skip")).status_code == 200
        body = (await auth_client.post(f"{API}/tutorial/complete")).json()
        assert body["granted"] is False
        assert "不发放奖励" in body["message"]

    async def test_restart(self, auth_client) -> None:
        await auth_client.post(f"{API}/tutorial/skip")
        body = (await auth_client.post(f"{API}/tutorial/restart")).json()
        assert body["currentStep"] == 1
        assert body["skipped"] is False


class TestSettings:
    async def test_auto_sell_toggle(self, auth_client) -> None:
        resp = await auth_client.post(
            f"{API}/settings/auto-sell", json={"enabled": True, "rarities": ["common"]}
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

        bad = await auth_client.post(
            f"{API}/settings/auto-sell", json={"enabled": True, "rarities": ["nope"]}
        )
        assert bad.json()["ok"] is False

"""接口集成测试：走通 MVP 闭环与各系统。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.main import app
from app.models import RaidSession, BattleSession, Hero, Item, ItemTag, RegionProgress, TavernState, User
from app.services.admin import ensure_admin_user
from app.services.game_config import CONFIG
from app.services.ranking import refresh_all_rankings
from app.services.recruiting import recruit_cost

API = "/api/v1"

# 开局赠送并装备的起始武器（见 auth._bootstrap_new_user）
STARTER_BASE_ID = str(CONFIG.heroes["initialHero"]["starterWeapon"])

CONFIG_REFINE_COST = {r: int(CONFIG.rarities[r]["refineCost"]) for r in CONFIG.rarity_order}
CONFIG_ENCHANT_COST = {r: int(CONFIG.rarities[r]["enchantCost"]) for r in CONFIG.rarity_order}

# 重造 / 附魔单次消耗上限（需求：控制在 5 万以内）
MAX_REFINE_OR_ENCHANT_COST = 50_000


async def _gold(client) -> int:
    return (await client.get(f"{API}/game/state")).json()["user"]["gold"]


async def _age_session(session_factory, session_id: int, ms: int) -> None:
    """把会话的「上次上报时间」往前拨 ms 毫秒。

    服务端只认自己的时钟计算上报窗口（客户端改时间 / 加速插件一律无效），
    所以测试不能再靠上报里的 elapsedMs 买窗口，必须真的让服务端看到时间间隔。
    """
    async with session_factory() as db:
        row = (
            await db.execute(select(BattleSession).where(BattleSession.id == session_id))
        ).scalar_one()
        row.last_report_at = datetime.now(timezone.utc) - timedelta(milliseconds=ms)
        await db.commit()


async def _report(
    client,
    session_factory,
    session_id: int,
    region_id: int,
    kills: list[dict],
    elapsed_ms: int = 15000,
    **extra,
):
    """先「让时间过去」再上报。"""
    await _age_session(session_factory, session_id, elapsed_ms)
    return await client.post(
        f"{API}/battle/session/report",
        json={
            "sessionId": session_id,
            "regionId": region_id,
            "elapsedMs": elapsed_ms,
            "kills": kills,
            **extra,
        },
    )


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


async def _seed_gear(session_factory, user_id: int, specs: list[dict]) -> None:
    """按规格插入装备，用于合成规则测试（可指定底材 / 品阶 / 等级 / 高品质）。"""
    async with session_factory() as db:
        for spec in specs:
            db.add(
                Item(
                    user_id=user_id,
                    base_id=spec.get("base_id", "w_sword_shield_0"),
                    name="测试底材",
                    category=spec.get("category", "weapon"),
                    slot=spec.get("slot", "mainHand"),
                    rarity=spec.get("rarity", "common"),
                    level_req=spec.get("level_req", 1),
                    high_quality=spec.get("high_quality", False),
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


async def _farm(client, session_factory, region_id: int, reports: int = 3, elapsed_ms: int = 15000) -> dict:
    """开一个会话并连续上报，返回最后一次上报结果。"""
    started = await client.post(f"{API}/battle/session/start", json={"regionId": region_id})
    assert started.status_code == 200, started.text
    session_id = started.json()["sessionId"]

    last = {}
    for _ in range(reports):
        resp = await _report(
            client,
            session_factory,
            session_id,
            region_id,
            [{"monsterId": "normal", "gold": 20, "exp": 30}],
            elapsed_ms,
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

    async def test_nickname_strips_html_metacharacters(self, client) -> None:
        """昵称去除尖括号与控制字符，避免存储型 XSS，同时保留普通文字。"""
        resp = await client.post(
            f"{API}/auth/register",
            json={
                "username": "xssuser",
                "password": "secret123",
                "nickname": "<script>alert(1)</script>光\x00之战士",
            },
        )
        assert resp.status_code == 201, resp.text
        token = resp.json()["accessToken"]
        me = (await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})).json()
        assert "<" not in me["nickname"] and ">" not in me["nickname"]
        assert "\x00" not in me["nickname"]
        assert "script" in me["nickname"].lower()  # 只去掉元字符，不吞掉正文
        assert "光" in me["nickname"] and "之战士" in me["nickname"]

    async def test_bad_login(self, client) -> None:
        resp = await client.post(f"{API}/auth/login", json={"username": "nobody", "password": "x"})
        assert resp.status_code == 401

    async def test_change_nickname_persists_and_updates_ranking(self, auth_client, session_factory) -> None:
        other = await auth_client.post(
            f"{API}/auth/register",
            json={"username": "other", "password": "secret123", "nickname": "旁观者"},
        )
        assert other.status_code == 201
        async with session_factory() as db:
            await refresh_all_rankings(db)
            await db.commit()

        resp = await auth_client.post(f"{API}/auth/change-nickname", json={"nickname": "  <新>光\x00战士  "})
        assert resp.status_code == 200, resp.text
        assert resp.json()["nickname"] == "新光战士"
        me = (await auth_client.get(f"{API}/auth/me")).json()
        assert me["nickname"] == "新光战士"
        assert me["username"] == "tester"
        state = (await auth_client.get(f"{API}/game/state")).json()
        assert state["user"]["nickname"] == "新光战士"
        from app.models import RankingEntry
        async with session_factory() as db:
            rows = (await db.execute(select(RankingEntry).where(RankingEntry.user_id == me["id"]))).scalars().all()
            assert rows and all(row.nickname == "新光战士" for row in rows)
            other_user = (await db.execute(select(User).where(User.username == "other"))).scalar_one()
            assert other_user.nickname == "旁观者"

    @pytest.mark.parametrize("nickname", ["", "   ", "<>\n\x00", "名" * 33, None])
    async def test_change_nickname_rejects_invalid_input(self, auth_client, nickname) -> None:
        resp = await auth_client.post(f"{API}/auth/change-nickname", json={"nickname": nickname})
        assert resp.status_code in (400, 422)
        assert (await auth_client.get(f"{API}/auth/me")).json()["nickname"] == "光之战士"

    async def test_change_nickname_requires_token(self, client) -> None:
        resp = await client.post(f"{API}/auth/change-nickname", json={"nickname": "新昵称"})
        assert resp.status_code == 401

    async def test_requires_token(self, client) -> None:
        resp = await client.get(f"{API}/game/state")
        assert resp.status_code == 401

    async def test_change_password_flow(self, auth_client) -> None:
        wrong = await auth_client.post(
            f"{API}/auth/change-password",
            json={"currentPassword": "nope", "newPassword": "newsecret1", "confirmPassword": "newsecret1"},
        )
        assert wrong.status_code == 400

        mismatch = await auth_client.post(
            f"{API}/auth/change-password",
            json={"currentPassword": "secret123", "newPassword": "newsecret1", "confirmPassword": "newsecret2"},
        )
        assert mismatch.status_code == 400

        ok = await auth_client.post(
            f"{API}/auth/change-password",
            json={"currentPassword": "secret123", "newPassword": "newsecret1", "confirmPassword": "newsecret1"},
        )
        assert ok.status_code == 200, ok.text

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as fresh:
            old = await fresh.post(
                f"{API}/auth/login", json={"username": "tester", "password": "secret123"}
            )
            assert old.status_code == 401
            new = await fresh.post(
                f"{API}/auth/login", json={"username": "tester", "password": "newsecret1"}
            )
            assert new.status_code == 200, new.text


class TestInitialState:
    async def test_state_after_register(self, auth_client) -> None:
        resp = await auth_client.get(f"{API}/game/state")
        assert resp.status_code == 200
        state = resp.json()

        assert state["user"]["gold"] == 0
        assert state["hero"]["level"] == 1
        assert state["hero"]["talent"] == "common"
        assert state["hero"]["attrBias"] == "balanced"
        # 开局赠送并装备起始武器（重锚定后裸英雄会卡死在新手阶段）
        assert len(state["items"]) == 1
        starter = state["items"][0]
        assert starter["baseId"] == STARTER_BASE_ID
        assert starter["source"] == "starter"
        assert starter["equippedSlot"] == "mainHand"
        assert state["currentRegion"]["id"] == 1
        assert state["regionProgress"]["1"]["unlocked"] is True
        assert state["regionProgress"]["2"]["unlocked"] is False

    async def test_eleven_loadout_slots(self, auth_client) -> None:
        state = (await auth_client.get(f"{API}/game/state")).json()
        cfg = (await auth_client.get(f"{API}/game/config")).json()
        assert len(cfg["slots"]) == 11
        # 起始武器占用主手，其余栏位为空
        assert set(state["loadout"]) == {"mainHand"}
        assert state["loadout"]["mainHand"]["baseId"] == STARTER_BASE_ID

    async def test_config_endpoint_exposes_shared_data(self, auth_client) -> None:
        cfg = (await auth_client.get(f"{API}/game/config")).json()
        assert len(cfg["jobs"]) == 21
        assert len(cfg["baseItems"]) == len(CONFIG.base_items)
        assert len(cfg["regions"]["regions"]) == 40
        assert len(cfg["tutorial"]["steps"]) == 15


class TestBattleLoop:
    async def test_farming_grants_gold_and_exp(self, auth_client, session_factory) -> None:
        result = await _farm(auth_client, session_factory, 1, reports=4)
        assert result["gold"] > 0
        assert result["expGained"] > 0
        assert result["killCount"] > 0

    async def test_lower_level_hero_gets_double_battle_exp(self, auth_client, session_factory):
        async with session_factory() as db:
            hero = (await db.scalars(select(Hero))).first()
            hero.level = 10
            hero.exp = 0
            user_id = hero.user_id
            await db.commit()
        base = await _farm(auth_client, session_factory, 1, reports=1)
        async with session_factory() as db:
            db.add(Hero(user_id=user_id, name="最高等级英雄", level=60,
                        talent="common", attr_bias="balanced"))
            await db.commit()
        boosted = await _farm(auth_client, session_factory, 1, reports=1)
        assert base['expGained'] > 0
        assert boosted['expGained'] == base['expGained'] * 2

    async def test_exp_gain_term_boosts_exp(self, auth_client, session_factory) -> None:
        """经验获取效率词条：服务端按百分比加成结算经验。"""
        base = await _farm(auth_client, session_factory, 1, reports=4)
        assert base["expGained"] > 0

        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            item = (await db.execute(select(Item).where(Item.user_id == me["id"]))).scalars().first()
            item.terms = [
                {
                    "id": "expGain",
                    "name": "经验获取效率",
                    "type": "buff",
                    "stat": "expGainPct",
                    "trigger": "常驻",
                    "value": 50.0,
                    "quality": "common",
                    "desc": "击败怪物获得的经验 +{v}%",
                }
            ]
            item.equipped_slot = "head"
            await db.commit()

        boosted = await _farm(auth_client, session_factory, 1, reports=4)
        # 击杀数会因随机浮动略有差异，用比例判断即可（50% 加成远大于抖动）
        assert boosted["expGained"] > base["expGained"] * 1.2

    async def test_monster_kills_grant_no_equipment(self, auth_client, session_factory) -> None:
        """装备只能通过抽箱获取：打怪不产装备，伪造 dropped 也一样。"""
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session_id = started.json()["sessionId"]
        resp = await _report(
            auth_client,
            session_factory,
            session_id,
            1,
            [{"monsterId": "normal", "gold": 20, "exp": 30, "dropped": True} for _ in range(3)],
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["goldGained"] > 0
        assert body["items"] == []
        assert body["autoSold"] == []
        # 打怪不产装备：背包里始终只有开局的起始武器
        items = (await auth_client.get(f"{API}/game/state")).json()["items"]
        assert [i["baseId"] for i in items] == [STARTER_BASE_ID]

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

    async def test_single_kill_in_short_window_is_accepted(self, auth_client) -> None:
        """客户端只在有击杀时才上报，单次窗口只有 1 只怪不应被判超速。

        额度按整只发放，这里额度不足 1 只，击杀会在后续上报由 kill_credit 补发，
        关键是不能再返回 422「数据校验未通过」。
        """
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session_id = started.json()["sessionId"]
        resp = await auth_client.post(
            f"{API}/battle/session/report",
            json={
                "sessionId": session_id,
                "regionId": 1,
                "elapsedMs": 1500,
                "kills": [{"monsterId": "normal", "gold": 15, "exp": 20}],
            },
        )
        assert resp.status_code == 200, resp.text

    async def test_idle_gap_is_covered_by_server_elapsed(self, auth_client, session_factory) -> None:
        """上报窗口以服务端真实间隔为准：空闲 15 秒后的多只击杀应被接受并入账。"""
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session_id = started.json()["sessionId"]
        await _age_session(session_factory, session_id, 15_000)

        resp = await auth_client.post(
            f"{API}/battle/session/report",
            json={
                "sessionId": session_id,
                "regionId": 1,
                "elapsedMs": 1500,
                "kills": [{"monsterId": "normal", "gold": 15, "exp": 20} for _ in range(3)],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["goldGained"] > 0

    async def test_background_gap_is_credited(self, auth_client, session_factory) -> None:
        """页面切到后台约 2 分钟后回来：整段窗口的击杀都应入账（窗口上限放宽到 catchUpSeconds）。"""
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session_id = started.json()["sessionId"]
        await _age_session(session_factory, session_id, 120_000)

        resp = await auth_client.post(
            f"{API}/battle/session/report",
            json={
                "sessionId": session_id,
                "regionId": 1,
                "elapsedMs": 1500,
                "kills": [{"monsterId": "normal", "gold": 15, "exp": 20} for _ in range(10)],
            },
        )
        assert resp.status_code == 200, resp.text
        # 10 只全部入账（旧的 20 秒上限只认约 7 只，金币会明显偏低）
        assert 140 <= resp.json()["goldGained"] <= 150

    async def test_client_elapsed_cannot_buy_window(self, auth_client) -> None:
        """防加速：客户端谎报超长 elapsedMs 换不来击杀额度（窗口只认服务端时钟）。

        改前这里取 max(客户端 elapsedMs, 服务端间隔)，谎报 20s 就能凭空拿到 20s 的额度，
        等于把游戏加速；现在必须被服务端真实间隔拦下。
        """
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session_id = started.json()["sessionId"]
        resp = await auth_client.post(
            f"{API}/battle/session/report",
            json={
                "sessionId": session_id,
                "regionId": 1,
                "elapsedMs": 20000,
                "kills": [{"monsterId": "normal", "gold": 20, "exp": 30} for _ in range(4)],
            },
        )
        assert resp.status_code == 422, resp.text
        assert "rejected" in str(resp.json()["detail"])

    async def test_gold_is_clamped_to_region_cap(self, auth_client, session_factory) -> None:
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session = started.json()["sessionId"]
        resp = await _report(
            auth_client,
            session_factory,
            session,
            1,
            [{"monsterId": "normal", "gold": 100000, "exp": 100000} for _ in range(3)],
        )
        assert resp.status_code == 200
        assert resp.json()["goldGained"] < 1000

    async def test_locked_region_rejected(self, auth_client) -> None:
        resp = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 20})
        assert resp.status_code == 403

    async def test_death_resets_progress(self, auth_client, session_factory) -> None:
        await _farm(auth_client, session_factory, 1, reports=2)
        before = (await auth_client.get(f"{API}/game/state")).json()["hero"]["regionKillCount"]
        resp = await auth_client.post(f"{API}/battle/death")
        assert resp.status_code == 200
        after = (await auth_client.get(f"{API}/game/state")).json()["hero"]["regionKillCount"]
        assert after == 0
        assert isinstance(before, int)

    async def test_boss_clear_unlocks_next_region(self, auth_client, session_factory) -> None:
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session = started.json()["sessionId"]

        cleared = None
        for _ in range(100):
            resp = await _report(
                auth_client,
                session_factory,
                session,
                1,
                [{"monsterId": "normal", "gold": 20, "exp": 30} for _ in range(3)],
            )
            assert resp.status_code == 200, resp.text
            if resp.json()["killCount"] >= resp.json()["killsRequired"]:
                cleared = await _report(
                    auth_client,
                    session_factory,
                    session,
                    1,
                    [],
                    elapsed_ms=1000,
                    bossKilled=True,
                    bossFightMs=21000,
                )
                break
        assert cleared is not None, "未能积累到 BOSS 出现条件"
        body = cleared.json()
        assert body["boss"]["firstClear"] is True
        assert body["boss"]["items"], "BOSS 应掉落宝箱装备"

        regions = (await auth_client.get(f"{API}/region")).json()
        by_id = {r["id"]: r for r in regions["regions"]}
        assert by_id[1]["cleared"] is True
        assert by_id[2]["unlocked"] is False
        # 地区不再要求机制试炼：未解锁只因战力/装备/主攻/双防或前一地区 BOSS
        assert by_id[2]["missingConditions"]
        assert "试炼" not in by_id[2]["lockedHint"]

    async def test_stop_session(self, auth_client) -> None:
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session = started.json()["sessionId"]
        resp = await auth_client.post(f"{API}/battle/session/stop", json={"sessionId": session})
        assert resp.status_code == 200
        assert "离线收益" in resp.json()["message"]

    async def test_switch_region_resets_counter(self, auth_client, session_factory) -> None:
        await _farm(auth_client, session_factory, 1, reports=3)
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
            assert item["score"] >= 0
        assert body["pity"]["sinceRare"] < 10

    async def test_chest_level_band_gate(self, auth_client, session_factory) -> None:
        await _set_gold(auth_client, session_factory, 100_000)
        # 1 级英雄不能抽 20 级档位
        locked = await auth_client.post(
            f"{API}/chest/open", json={"chestId": "weaponBox", "count": 1, "level": 20}
        )
        assert locked.status_code == 400
        assert "等级" in locked.json()["detail"]

        # 非档位等级直接拒绝
        bad = await auth_client.post(
            f"{API}/chest/open", json={"chestId": "weaponBox", "count": 1, "level": 37}
        )
        assert bad.status_code == 400

        # 1 级档位可用，产出 1 级底材
        ok = await auth_client.post(
            f"{API}/chest/open", json={"chestId": "weaponBox", "count": 10, "level": 1}
        )
        assert ok.status_code == 200, ok.text
        for item in ok.json()["items"]:
            assert item["levelReq"] <= 1

    async def test_chest_price_scales_with_band(self, auth_client, session_factory) -> None:
        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            hero = (await db.execute(select(Hero).where(Hero.user_id == me["id"]))).scalar_one()
            hero.level = 40
            await db.commit()
        await _set_gold(auth_client, session_factory, 100_000)

        base = next(c["price"] for c in CONFIG.chests["chests"] if c["id"] == "weaponBox")
        mult40 = next(
            float(b["priceMultiplier"]) for b in CONFIG.chests["levelBands"] if b["level"] == 40
        )

        low = await auth_client.post(
            f"{API}/chest/open", json={"chestId": "weaponBox", "count": 1, "level": 1}
        )
        assert low.status_code == 200, low.text
        assert low.json()["cost"] == base

        high = await auth_client.post(
            f"{API}/chest/open", json={"chestId": "weaponBox", "count": 1, "level": 40}
        )
        assert high.status_code == 200, high.text
        assert high.json()["cost"] == int(base * mult40)

    async def test_drop_rate_rises_with_cleared_regions(self, auth_client, session_factory) -> None:
        before = (await auth_client.get(f"{API}/game/state")).json()
        assert before["clearedRegions"] == 0
        assert before["dropRateMultiplier"] == 1.0

        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            row = (
                await db.execute(
                    select(RegionProgress).where(
                        RegionProgress.user_id == me["id"], RegionProgress.region_id == 1
                    )
                )
            ).scalar_one()
            row.cleared = True
            await db.commit()

        after = (await auth_client.get(f"{API}/game/state")).json()
        assert after["clearedRegions"] == 1
        assert after["dropRateMultiplier"] > 1.0

    async def test_chest_band_scales_contents_with_selected_level(
        self, auth_client, session_factory
    ) -> None:
        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            hero = (await db.execute(select(Hero).where(Hero.user_id == me["id"]))).scalar_one()
            hero.level = 40
            await db.commit()
        await _set_gold(auth_client, session_factory, 1_000_000)

        high = await auth_client.post(
            f"{API}/chest/open", json={"chestId": "weaponBox", "count": 10, "level": 40}
        )
        assert high.status_code == 200, high.text
        assert any(item["levelReq"] == 40 for item in high.json()["items"])

        low = await auth_client.post(
            f"{API}/chest/open", json={"chestId": "weaponBox", "count": 10, "level": 1}
        )
        assert low.status_code == 200, low.text
        assert all(item["levelReq"] <= 1 for item in low.json()["items"])

    async def test_equip_ignores_level_requirement(self, auth_client, session_factory) -> None:
        """装备不再有等级门槛：低等级英雄也能穿戴高等级装备。"""
        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            db.add(
                Item(
                    user_id=me["id"],
                    base_id="w_sword_shield_0",
                    name="高等级武器",
                    category="weapon",
                    slot="mainHand",
                    rarity="common",
                    level_req=95,
                    base_attrs=[{"attr": "attack", "value": 10.0}],
                    sub_attrs=[],
                    terms=[],
                    equipped_slot=None,
                    source="test",
                )
            )
            await db.commit()
            item_id = (
                await db.execute(
                    select(Item).where(Item.user_id == me["id"], Item.level_req == 95)
                )
            ).scalar_one().id

        resp = await auth_client.post(
            f"{API}/inventory/equip", json={"itemId": item_id, "slot": "mainHand"}
        )
        assert resp.status_code == 200, resp.text
        loadout = (await auth_client.get(f"{API}/game/state")).json()["loadout"]
        assert loadout["mainHand"]["id"] == item_id

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

    async def test_craft_output_uses_worst_material(self, auth_client, session_factory) -> None:
        """产物以最差素材为准：等级取最低、装备种类也取最差那件。"""
        me = (await auth_client.get(f"{API}/auth/me")).json()
        specs = [{"base_id": "w_sword_shield_0", "level_req": 1}]
        specs += [{"base_id": "w_sword_shield_2", "level_req": 40}] * 15
        await _seed_gear(session_factory, me["id"], specs)
        await _set_gold(auth_client, session_factory, 1000)

        resp = await auth_client.post(f"{API}/economy/craft", json={"category": "weapon", "auto": True})
        assert resp.status_code == 200, resp.text
        item = resp.json()["produced"][0]
        assert item["rarity"] == "uncommon"
        assert item["levelReq"] == 1, "产物等级应取素材最低"
        assert item["baseId"] == "w_sword_shield_0", "产物种类应取最差素材"

    async def test_craft_output_quality_is_worst(self, auth_client, session_factory) -> None:
        """1 件普通 + 15 件高品质 → 产物仍为普通（非高品质）。"""
        me = (await auth_client.get(f"{API}/auth/me")).json()
        specs = [{"high_quality": False}] + [{"high_quality": True}] * 15
        await _seed_gear(session_factory, me["id"], specs)
        await _set_gold(auth_client, session_factory, 1000)

        resp = await auth_client.post(f"{API}/economy/craft", json={"category": "weapon", "auto": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["produced"][0]["highQuality"] is False

    async def test_craft_all_high_quality_keeps_quality(self, auth_client, session_factory) -> None:
        """全为高品质时产物保留高品质。"""
        me = (await auth_client.get(f"{API}/auth/me")).json()
        await _seed_gear(session_factory, me["id"], [{"high_quality": True}] * 16)
        await _set_gold(auth_client, session_factory, 1000)

        resp = await auth_client.post(f"{API}/economy/craft", json={"category": "weapon", "auto": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["produced"][0]["highQuality"] is True

    async def test_craft_rejects_dedicated_category(self, auth_client, session_factory) -> None:
        """合成仅支持战斗职业装备，专用装备大类被拒绝。"""
        me = (await auth_client.get(f"{API}/auth/me")).json()
        await _seed_gear(
            session_factory,
            me["id"],
            [{"category": "doh_tool", "slot": "dohTool", "base_id": "dh_dohTool_0"}] * 16,
        )
        await _set_gold(auth_client, session_factory, 1000)

        resp = await auth_client.post(f"{API}/economy/craft", json={"category": "doh_tool", "auto": True})
        assert resp.status_code == 400
        assert "未知装备大类" in resp.json()["detail"]

    async def test_refine_cost_escalates(self, auth_client, session_factory) -> None:
        """同一件装备重造越多次越贵，防止无限重造刷属性。"""
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        await _set_gold(auth_client, session_factory, 10_000_000)

        base = CONFIG_REFINE_COST[item["rarity"]]
        growth = float(CONFIG.economy["refine"]["costGrowthPerRefine"])

        first = await auth_client.post(f"{API}/economy/refine", json={"itemId": item["id"]})
        assert first.status_code == 200, first.text
        assert first.json()["cost"] == base
        assert first.json()["after"]["refineCost"] == base + int(base * growth)

        second = await auth_client.post(f"{API}/economy/refine", json={"itemId": item["id"]})
        assert second.status_code == 200, second.text
        assert second.json()["cost"] == base + int(base * growth)
        assert second.json()["cost"] > first.json()["cost"]

    async def test_refine_rerolls_attrs_and_terms(self, auth_client, session_factory) -> None:
        """彻底随机重造：属性与词条一起重掷，品阶/类型保持不变。"""
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        await _set_gold(auth_client, session_factory, 700000)

        resp = await auth_client.post(f"{API}/economy/refine", json={"itemId": item["id"]})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cost"] == CONFIG_REFINE_COST[item["rarity"]]
        assert body["after"]["rarity"] == item["rarity"]
        assert body["after"]["refineCount"] == 1
        # 词条会被重掷（数量/种类/数值），但仍是合法词条结构
        assert 0 <= len(body["after"]["terms"]) <= 4
        for term in body["after"]["terms"]:
            assert term["type"] in ("buff", "debuff")

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

    async def test_item_exposes_both_mode_prices(self, auth_client, session_factory) -> None:
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        assert item["refineCostBasedOnCurrent"] > item["refineCost"]
        assert item["enchantCostBasedOnCurrent"] > item["enchantCost"]

    async def test_item_attrs_expose_range(self, auth_client, session_factory) -> None:
        """装备详情需要「当前值【区间】」：基础属性与副属性均带 min/max。"""
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        assert item["baseAttrs"], "起始/开箱装备应有基础属性"
        for entry in item["baseAttrs"]:
            assert entry["min"] <= entry["value"] <= entry["max"]
        for entry in item["subAttrs"]:
            assert entry["min"] <= entry["max"]

    async def test_refine_based_on_current_costs_more_and_stays_in_range(
        self, auth_client, session_factory
    ) -> None:
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        await _set_gold(auth_client, session_factory, 50_000_000)

        base = CONFIG_REFINE_COST[item["rarity"]]
        mult = float(CONFIG.economy["refine"]["basedOnCurrentCostMultiplier"])

        for index in range(5):
            resp = await auth_client.post(
                f"{API}/economy/refine", json={"itemId": item["id"], "mode": "basedOnCurrent"}
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            if index == 0:
                assert body["cost"] == int(base * mult)
            after = body["after"]
            # 种类不变；普通品质数值仍落在其可达区间内
            assert [a["attr"] for a in after["baseAttrs"]] == [a["attr"] for a in item["baseAttrs"]]
            assert [a["attr"] for a in after["subAttrs"]] == [a["attr"] for a in item["subAttrs"]]
            assert [t["id"] for t in after["terms"]] == [t["id"] for t in item["terms"]]
            for entry in after["baseAttrs"] + after["subAttrs"]:
                if entry.get("quality") in (None, "common"):
                    assert entry["min"] - 1e-6 <= entry["value"] <= entry["max"] + 1e-6

    async def test_enchant_based_on_current_costs_more(self, auth_client, session_factory) -> None:
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        await _set_gold(auth_client, session_factory, 50_000_000)

        base = CONFIG_ENCHANT_COST[item["rarity"]]
        mult = float(CONFIG.economy["enchant"]["basedOnCurrentCostMultiplier"])
        resp = await auth_client.post(
            f"{API}/economy/enchant", json={"itemId": item["id"], "mode": "basedOnCurrent"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["cost"] == int(base * mult)


class TestItemTags:
    """装备颜色标签：自建命名标签、贴到装备、按标签筛选（筛选在前端，这里验证数据往返）。"""

    async def _make_tag(self, auth_client, name: str = "保留", color: str = "red") -> dict:
        resp = await auth_client.post(f"{API}/tags", json={"name": name, "color": color})
        assert resp.status_code == 200, resp.text
        return resp.json()["tag"]

    async def test_create_list_and_state(self, auth_client) -> None:
        tag = await self._make_tag(auth_client)
        assert tag["name"] == "保留" and tag["color"] == "red"

        listed = (await auth_client.get(f"{API}/tags")).json()["tags"]
        assert [t["id"] for t in listed] == [tag["id"]]

        state = (await auth_client.get(f"{API}/game/state")).json()
        assert [t["id"] for t in state["tags"]] == [tag["id"]]

    async def test_validation(self, auth_client) -> None:
        await self._make_tag(auth_client, name="保留", color="red")

        dup = await auth_client.post(f"{API}/tags", json={"name": "保留", "color": "blue"})
        assert dup.status_code == 400

        blank = await auth_client.post(f"{API}/tags", json={"name": "   ", "color": "red"})
        assert blank.status_code == 400

        bad_color = await auth_client.post(f"{API}/tags", json={"name": "新", "color": "mauve"})
        assert bad_color.status_code == 400

    async def test_update_and_delete(self, auth_client) -> None:
        tag = await self._make_tag(auth_client)

        upd = await auth_client.post(
            f"{API}/tags/{tag['id']}", json={"name": "核心", "color": "green"}
        )
        assert upd.status_code == 200, upd.text
        assert upd.json()["tag"]["name"] == "核心"
        assert upd.json()["tag"]["color"] == "green"

        assert (await auth_client.delete(f"{API}/tags/{tag['id']}")).status_code == 200
        assert (await auth_client.get(f"{API}/tags")).json()["tags"] == []

    async def test_assign_filters_foreign_ids_and_delete_cleans_items(
        self, auth_client, session_factory
    ) -> None:
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        tag = await self._make_tag(auth_client, name="待强化", color="blue")

        # 未知 tagId 会被过滤，只保留本人标签
        resp = await auth_client.post(
            f"{API}/inventory/tags", json={"itemId": item["id"], "tagIds": [tag["id"], 999999]}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["item"]["tagIds"] == [tag["id"]]

        state = (await auth_client.get(f"{API}/game/state")).json()
        stored = next(i for i in state["items"] if i["id"] == item["id"])
        assert stored["tagIds"] == [tag["id"]]

        # 删除标签后应自动从装备上移除
        assert (await auth_client.delete(f"{API}/tags/{tag['id']}")).status_code == 200
        state = (await auth_client.get(f"{API}/game/state")).json()
        stored = next(i for i in state["items"] if i["id"] == item["id"])
        assert stored["tagIds"] == []

    async def test_cannot_touch_others_tag(self, auth_client, session_factory) -> None:
        async with session_factory() as db:
            other_user = User(username="other", password_hash="x", nickname="他人")
            db.add(other_user)
            await db.flush()
            other_tag = ItemTag(user_id=other_user.id, name="他人标签", color="red")
            db.add(other_tag)
            await db.flush()
            other_id = other_tag.id
            await db.commit()

        assert (
            await auth_client.post(f"{API}/tags/{other_id}", json={"name": "改"})
        ).status_code == 404
        assert (await auth_client.delete(f"{API}/tags/{other_id}")).status_code == 404


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
        body = refreshed.json()
        assert body["cost"] == 0
        assert body["freeRefreshAvailable"] is False
        assert body["nextFreeRefreshAt"]

    async def test_free_refresh_cooldown_does_not_charge_gold(self, auth_client, session_factory) -> None:
        await _set_gold(auth_client, session_factory, 1000)

        first = await auth_client.post(f"{API}/tavern/refresh", json={"useGold": False})
        assert first.status_code == 200
        assert first.json()["gold"] == 1000

        second = await auth_client.post(f"{API}/tavern/refresh", json={"useGold": False})
        assert second.status_code == 400
        assert "冷却" in second.json()["detail"]

        me = (await auth_client.get(f"{API}/auth/me")).json()
        assert me["gold"] == 1000

    async def test_gold_refresh_charges_fee(self, auth_client, session_factory) -> None:
        await _set_gold(auth_client, session_factory, 1000)
        resp = await auth_client.post(f"{API}/tavern/refresh", json={"useGold": True})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cost"] == int(CONFIG.talents["refreshCost"])
        assert body["gold"] == 1000 - int(CONFIG.talents["refreshCost"])

    async def test_ancient_pity_threshold_and_counter_exposed(self, auth_client) -> None:
        """太古保底进度对外可见：新账号从 0 开始，阈值为配置值。"""
        info = (await auth_client.get(f"{API}/tavern")).json()
        pity = info["ancientPity"]
        assert pity["threshold"] == int(CONFIG.talents["ancientPityCount"])
        assert 0 <= pity["count"] <= pity["threshold"]

    async def test_ancient_pity_guarantees_ancient_candidate(self, auth_client, session_factory) -> None:
        """保底计数满时，下一个候选必定带太古属性（神话资质、总点数 220-260），且计数归零。"""
        threshold = int(CONFIG.talents["ancientPityCount"])
        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            row = (
                await db.execute(select(TavernState).where(TavernState.user_id == me["id"]))
            ).scalar_one()
            row.ancient_pity = threshold - 1
            await db.commit()

        resp = await auth_client.post(f"{API}/tavern/refresh", json={"useGold": False})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        candidate = body["candidate"]
        assert candidate["ancientAttr"] in ("str", "dex", "int")
        assert candidate["talent"] == "mythic"
        spec = CONFIG.talents["talents"]["mythic"]
        assert int(spec["pointMin"]) <= candidate["totalPoints"] <= int(spec["pointMax"])
        assert body["ancientPity"]["count"] == 0

    async def test_ancient_candidate_always_mythic(self, auth_client, session_factory) -> None:
        """带太古属性的候选即便落库时资质非神话，展示 / 计费 / 创建英雄三处都按神话。"""
        me = (await auth_client.get(f"{API}/auth/me")).json()
        await _set_gold(auth_client, session_factory, 10_000_000)
        async with session_factory() as db:
            row = (
                await db.execute(select(TavernState).where(TavernState.user_id == me["id"]))
            ).scalar_one()
            row.candidate = {
                "name": "旧候选",
                "talent": "common",
                "attrBias": "balanced",
                "attrBiasLabel": "均衡型",
                "strength": 120,
                "agility": 90,
                "intellect": 80,
                "ancientAttr": "str",
                "totalPoints": 240,
                "recruitCost": 1,
                "recommendedJobs": [],
            }
            await db.commit()

        info = (await auth_client.get(f"{API}/tavern")).json()
        assert info["candidate"]["talent"] == "mythic"
        assert info["candidate"]["recruitCost"] == recruit_cost("mythic", 1)

        resp = await auth_client.post(f"{API}/tavern/recruit", json={"confirm": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["hero"]["talent"] == "mythic"

    async def test_shown_recruit_cost_matches_charge_after_level_up(self, auth_client, session_factory) -> None:
        """候选生成后英雄升级，页面显示价仍须等于招募时的实际扣费。"""
        await _set_gold(auth_client, session_factory, 10_000_000)

        info = (await auth_client.get(f"{API}/tavern")).json()
        assert info["candidate"]["recruitCost"] == info["recruitCost"]
        low_cost = info["recruitCost"]

        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            hero = (await db.execute(select(Hero).where(Hero.user_id == me["id"]))).scalar_one()
            hero.level = 30
            await db.commit()

        info2 = (await auth_client.get(f"{API}/tavern")).json()
        assert info2["candidate"]["recruitCost"] == info2["recruitCost"]
        assert info2["recruitCost"] > low_cost

        resp = await auth_client.post(f"{API}/tavern/recruit", json={"confirm": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["cost"] == info2["recruitCost"]

    async def test_recruit_requires_gold(self, auth_client) -> None:
        resp = await auth_client.post(f"{API}/tavern/recruit", json={"confirm": True})
        assert resp.status_code == 400

    async def test_ten_pull_costs_and_recruit_one(self, auth_client, session_factory) -> None:
        await _set_gold(auth_client, session_factory, 1_000_000)
        cost = int(CONFIG.talents["tenPullCost"])

        resp = await auth_client.post(f"{API}/tavern/ten-pull")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cost"] == cost
        assert len(body["candidates"]) == 10
        assert body["gold"] == 1_000_000 - cost

        # 结果落库，可在状态接口恢复
        info = (await auth_client.get(f"{API}/tavern")).json()
        assert len(info["multiCandidates"]) == 10
        assert info["tenPullCost"] == cost

        pick = info["multiCandidates"][4]
        bought = await auth_client.post(
            f"{API}/tavern/ten-pull/recruit", json={"index": 4, "confirm": True}
        )
        assert bought.status_code == 200, bought.text
        assert bought.json()["cost"] == pick["recruitCost"]

        me = (await auth_client.get(f"{API}/auth/me")).json()
        assert me["gold"] == 1_000_000 - cost - pick["recruitCost"]

        after = (await auth_client.get(f"{API}/tavern")).json()
        assert after["multiCandidates"] == []

    async def test_ten_pull_requires_gold(self, auth_client) -> None:
        resp = await auth_client.post(f"{API}/tavern/ten-pull")
        assert resp.status_code == 400

    async def test_ten_pull_recruit_index_and_clear(self, auth_client, session_factory) -> None:
        await _set_gold(auth_client, session_factory, 100_000)
        await auth_client.post(f"{API}/tavern/ten-pull")

        bad = await auth_client.post(
            f"{API}/tavern/ten-pull/recruit", json={"index": 99, "confirm": True}
        )
        assert bad.status_code == 400

        cleared = await auth_client.post(f"{API}/tavern/ten-pull/clear")
        assert cleared.status_code == 200
        info = (await auth_client.get(f"{API}/tavern")).json()
        assert info["multiCandidates"] == []

    async def test_initial_hero_cannot_be_dismissed(self, auth_client) -> None:
        hero_id = (await auth_client.get(f"{API}/game/state")).json()["hero"]["id"]
        resp = await auth_client.post(f"{API}/tavern/dismiss", json={"heroId": hero_id})
        assert resp.status_code == 400

    async def test_dismiss_recruited_hero_keeps_initial_hero(self, auth_client, session_factory) -> None:
        await _set_gold(auth_client, session_factory, 1_000_000)
        recruited = await auth_client.post(f"{API}/tavern/recruit", json={"confirm": True})
        assert recruited.status_code == 200, recruited.text

        dismissed = await auth_client.post(f"{API}/tavern/dismiss", json={"heroId": recruited.json()["hero"]["id"]})
        assert dismissed.status_code == 200, dismissed.text

        state = await auth_client.get(f"{API}/game/state")
        assert state.status_code == 200, state.text
        hero = state.json()["hero"]
        assert hero["name"] == "冒险者"
        assert hero["level"] == 1
        assert hero["jobId"] == "PLD"
        assert hero["isInitial"] is True
        assert hero["currentRegionId"] == 1


class TestRaid:
    # 高难副本门槛：全神话 + 太古词条/件（极* 2 个，绝·巴哈姆特零式 3 个）
    MYTHIC_MIX = ["mythic"] * 11

    async def _gear_up(
        self,
        auth_client,
        session_factory,
        level: int = 100,
        mix: list[str] | None = None,
        ancient: int = 0,
    ) -> None:
        """把英雄拉到指定等级并穿满全部栏位，品阶按 mix 分配，每件带 ancient 个太古词条。"""
        rarities = mix if mix is not None else self.MYTHIC_MIX
        terms = [
            {
                "id": f"strBoost{index}",
                "name": "力量增幅",
                "type": "buff",
                "stat": "attackPct",
                "trigger": "passive",
                "value": 5.0,
                "quality": "ancient",
                "desc": "攻击力 +{v}%",
            }
            for index in range(ancient)
        ]
        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            hero = (await db.execute(select(Hero).where(Hero.user_id == me["id"]))).scalar_one()
            hero.level = level
            # 先卸下开局自带的起始武器，否则会混进品阶检查
            for owned in (await db.execute(select(Item).where(Item.user_id == me["id"]))).scalars().all():
                owned.equipped_slot = None
            for index, slot in enumerate(CONFIG.slots):
                db.add(
                    Item(
                        user_id=me["id"],
                        base_id=STARTER_BASE_ID,
                        name=f"测试装备·{slot['id']}",
                        category=slot["category"],
                        slot=slot["id"],
                        rarity=rarities[index % len(rarities)],
                        level_req=1,
                        base_attrs=[{"attr": "attack", "value": 12000.0}, {"attr":"physDef","value":5000.0}, {"attr":"magicDef","value":5000.0}, {"attr":"hp","value":100000.0}],
                        sub_attrs=[{"attr": "crit", "value": 2000.0, "type": "flat", "quality": "common"}],
                        terms=[dict(t) for t in terms],
                        equipped_slot=slot["id"],
                    )
                )
            await db.commit()

    async def test_gate_rejects_underleveled_hero(self, auth_client) -> None:
        resp = await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})
        assert resp.status_code == 400
        assert "等级" in resp.json()["detail"]

    async def test_gate_requires_all_slots(self, auth_client, session_factory) -> None:
        # 等级够但没穿满：应被栏位门槛拦下
        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            hero = (await db.execute(select(Hero).where(Hero.user_id == me["id"]))).scalar_one()
            hero.level = 100
            await db.commit()
        resp = await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})
        assert resp.status_code == 400
        assert "栏位" in resp.json()["detail"]

    async def test_list_reports_eligibility(self, auth_client, session_factory) -> None:
        await self._gear_up(auth_client, session_factory, ancient=2)
        body = (await auth_client.get(f"{API}/raid")).json()
        raid = next(r for r in body["raids"] if r["id"] == "raid_1")
        assert raid["eligible"] is True
        assert raid["blockedReason"] is None
        assert raid["cleared"] is False
        assert raid["dualBoss"] is False
        assert raid["difficulty"] == "normal"
        assert raid["requiredLevel"] == 20
        assert raid["minAncientTermsPerItem"] == 2

    async def test_hard_equipment_gate_rejects_rare_mix(self, auth_client, session_factory) -> None:
        """高难：全部装备品阶不得低于神话。全蓝应被拦下。"""
        await self._gear_up(auth_client, session_factory, mix=["rare"] * 11, ancient=2)
        resp = await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})
        assert resp.status_code == 400
        assert "神话" in resp.json()["detail"]

    async def test_hard_equipment_gate_requires_ancient_terms(self, auth_client, session_factory) -> None:
        """高难：每件装备至少 2 个太古词条。"""
        await self._gear_up(auth_client, session_factory, ancient=0)
        resp = await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})
        assert resp.status_code == 400
        assert "太古" in resp.json()["detail"]

    async def test_hard_gate_rejects_normal_gear(self, auth_client, session_factory) -> None:
        """高难度高难：装备品阶不得低于神话。"""
        await self._gear_up(auth_client, session_factory, mix=["legendary"] * 11, ancient=2)
        resp = await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})
        assert resp.status_code == 400
        assert "神话" in resp.json()["detail"]

    async def test_hard_gate_rejects_half_mythic_only(self, auth_client, session_factory) -> None:
        """高难度高难：混入传说件应被拦下。"""
        await self._gear_up(
            auth_client, session_factory, mix=["mythic"] * 5 + ["legendary"] * 6, ancient=2
        )
        resp = await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})
        assert resp.status_code == 400
        assert "神话" in resp.json()["detail"]

    async def test_hard_gate_requires_ancient_terms(self, auth_client, session_factory) -> None:
        """高难度高难：每件装备至少 2 个太古词条（绝·究极神兵）。"""
        await self._gear_up(auth_client, session_factory, ancient=0)
        resp = await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})
        assert resp.status_code == 400
        assert "太古" in resp.json()["detail"]

    async def test_hard_raid_eligible_with_full_requirement(self, auth_client, session_factory) -> None:
        await self._gear_up(auth_client, session_factory, ancient=2)
        body = (await auth_client.get(f"{API}/raid")).json()
        raid = next(r for r in body["raids"] if r["id"] == "raid_h1")
        assert raid["eligible"] is True, raid["blockedReason"]
        assert raid["difficulty"] == "hard"
        assert raid["requiredLevel"] == 100
        assert raid["minAncientTermsPerItem"] == 2

        started = await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})
        assert started.status_code == 200, started.text

    async def test_hard_raid_enforces_level_gate(self, auth_client, session_factory) -> None:
        """高难度高难同样按等级开放：未满级无法进入。"""
        await self._gear_up(auth_client, session_factory, level=50, ancient=2)
        body = (await auth_client.get(f"{API}/raid")).json()
        raid = next(r for r in body["raids"] if r["id"] == "raid_h1")
        assert raid["eligible"] is False
        assert "等级" in (raid["blockedReason"] or "")

        started = await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})
        assert started.status_code == 400
        assert "等级" in started.json()["detail"]

    async def test_normal_raid_allows_underleveled_hero(self, auth_client, session_factory) -> None:
        await self._gear_up(auth_client, session_factory, level=50)
        resp = await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_3"})
        assert resp.status_code == 200
        assert "penalty" in resp.json()

    async def test_all_raid_bosses_have_at_least_10_skills(self, auth_client, session_factory) -> None:
        """每个副本的每个 BOSS 都带共享技能池（≥10 个技能）+ 共享 CD。"""
        await self._gear_up(auth_client, session_factory, ancient=3)
        for raid_id in ("raid_1", "raid_4", "raid_h1", "raid_h2"):
            started = await auth_client.post(f"{API}/raid/session/start", json={"raidId": raid_id})
            assert started.status_code == 200, started.text
            body = started.json()
            for boss in body["bosses"]:
                assert len(boss["skills"]) >= 10, (raid_id, boss["name"], boss["skills"])
                assert float(boss["skillInterval"]) > 0

    async def test_normal_raid_bosses_also_use_skill_pool(self, auth_client, session_factory) -> None:
        """极*（普通高难）BOSS 同样启用技能池，不再只有绝* 才有技能。"""
        await self._gear_up(auth_client, session_factory, ancient=2)
        started = await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_1"})
        assert started.status_code == 200, started.text
        body = started.json()
        assert body["difficulty"] == "normal"
        for boss in body["bosses"]:
            assert len(boss["skills"]) >= 10

    async def test_raid_rejects_fabricated_fast_clear(self, auth_client, session_factory) -> None:
        """服务端时间不足时，客户端虚报通关不能获得奖励。"""
        await self._gear_up(auth_client, session_factory, ancient=2)
        started = (await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_1"})).json()
        resp = await auth_client.post(
            f"{API}/raid/session/report",
            json={
                "sessionId": started["sessionId"],
                "raidId": "raid_1",
                "cleared": True,
                "died": False,
                "elapsedMs": 1000,
                "fightMs": 1000,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["cleared"] is False
        assert "invalid_duration" in resp.json()["failures"]

    async def test_hard_raid_drops_chooseable_chest(self, auth_client, session_factory) -> None:
        """高难副本通关掉落自选种类宝箱：通关不直接给装备，自选后一次性开箱。"""
        await self._gear_up(auth_client, session_factory, ancient=2)
        started = (await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})).json()
        async with session_factory() as db:
            session = await db.get(RaidSession,started['sessionId'])
            session.started_at = datetime.now(timezone.utc)-timedelta(seconds=120)
            await db.commit()
        box_count = int(CONFIG.raid_by_id["raid_h1"]["reward"]["boxCount"])

        resp = await auth_client.post(
            f"{API}/raid/session/report",
            json={
                "sessionId": started["sessionId"],
                "raidId": "raid_h1",
                "cleared": True,
                "died": False,
                "elapsedMs": 1000,
                "fightMs": 120000,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["items"] == []  # 高难宝箱不直接发装备
        assert body["pendingChest"]["count"] == box_count
        assert "head" in body["pendingChest"]["slots"]

        listing = (await auth_client.get(f"{API}/raid")).json()
        assert listing["chest"]["count"] == box_count

        bad = await auth_client.post(f"{API}/raid/chest/claim", json={"slot": "nope"})
        assert bad.status_code == 400

        claim = await auth_client.post(f"{API}/raid/chest/claim", json={"slot": "head"})
        assert claim.status_code == 200, claim.text
        got = claim.json()
        assert got["count"] == box_count
        assert got["slot"] == "head"
        assert len(got["items"]) + len(got["autoSold"]) == box_count
        for item in got["items"]:
            assert item["slot"] == "head"
        assert got["pendingChest"] == 0

        again = await auth_client.post(f"{API}/raid/chest/claim", json={"slot": "head"})
        assert again.status_code == 400

    async def test_first_clear_full_reward_then_repeat_gold_and_exp(self, auth_client, session_factory) -> None:
        await self._gear_up(auth_client, session_factory, ancient=2)
        cfg = CONFIG.raid_by_id["raid_1"]
        reward = cfg["reward"]

        async def clear_once() -> dict:
            started = (await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_1"})).json()
            async with session_factory() as db:
                session = await db.get(RaidSession,started['sessionId'])
                session.started_at = datetime.now(timezone.utc)-timedelta(seconds=90)
                await db.commit()
            resp = await auth_client.post(
                f"{API}/raid/session/report",
                json={
                    "sessionId": started["sessionId"],
                    "raidId": "raid_1",
                    "cleared": True,
                    "died": False,
                    "elapsedMs": 10_000_000,
                    "fightMs": 90_000,
                },
            )
            assert resp.status_code == 200, resp.text
            return resp.json()

        before = (await auth_client.get(f"{API}/auth/me")).json()["gold"]
        first = await clear_once()
        assert first["cleared"] is True
        assert first["firstClear"] is True
        assert first["goldGained"] == int(reward["firstGold"])
        assert len(first["items"]) == int(reward["boxCount"])
        assert first["gold"] == before + int(reward["firstGold"])
        assert first["expGained"] >= int(reward["firstExp"])

        second = await clear_once()
        assert second["firstClear"] is False
        assert second["goldGained"] == int(reward["repeatGold"])
        assert second["items"] == []
        assert second["gold"] == first["gold"] + int(reward["repeatGold"])
        # 重刷也会获得经验（高难副本的 repeatExp 更高）
        assert int(reward["repeatExp"]) > 0
        assert second["expGained"] >= int(reward["repeatExp"])

    async def test_hard_raid_repeat_exp_exceeds_normal(self, auth_client, session_factory) -> None:
        """高难副本的重刷经验必须高于同等级的普通副本。"""
        normal = CONFIG.raid_by_id["raid_4"]["reward"]["repeatExp"]  # Lv.80 普通
        hard = CONFIG.raid_by_id["raid_h1"]["reward"]["repeatExp"]  # Lv.80 高难
        assert int(hard) > int(normal)

    async def test_death_grants_nothing(self, auth_client, session_factory) -> None:
        await self._gear_up(auth_client, session_factory, ancient=2)
        started = (await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_1"})).json()
        before = (await auth_client.get(f"{API}/auth/me")).json()["gold"]
        resp = await auth_client.post(
            f"{API}/raid/session/report",
            json={
                "sessionId": started["sessionId"],
                "raidId": "raid_1",
                "cleared": False,
                "died": True,
                "elapsedMs": 5000,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["cleared"] is False
        assert (await auth_client.get(f"{API}/auth/me")).json()["gold"] == before


class TestAdmin:
    ADMIN_USER = "admin"
    ADMIN_PASS = "admin-secret-123"

    @pytest.fixture(autouse=True)
    def _admin_env(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USERNAME", self.ADMIN_USER)
        monkeypatch.setenv("ADMIN_PASSWORD", self.ADMIN_PASS)
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    async def _ensure_admin(self, session_factory) -> None:
        async with session_factory() as db:
            await ensure_admin_user(db)

    async def _login_as_admin(self, client) -> None:
        resp = await client.post(
            f"{API}/auth/login", json={"username": self.ADMIN_USER, "password": self.ADMIN_PASS}
        )
        assert resp.status_code == 200, resp.text
        client.headers.update({"Authorization": f"Bearer {resp.json()['accessToken']}"})

    async def test_admin_account_created_and_flagged(self, client, session_factory) -> None:
        await self._ensure_admin(session_factory)
        await self._login_as_admin(client)

        me = (await client.get(f"{API}/auth/me")).json()
        assert me["username"] == self.ADMIN_USER
        assert me["isAdmin"] is True
        assert me["hasHero"] is False  # 管理员不创建英雄 → 不上榜

    async def test_admin_username_is_reserved(self, client, session_factory) -> None:
        await self._ensure_admin(session_factory)
        resp = await client.post(
            f"{API}/auth/register",
            json={"username": self.ADMIN_USER, "password": "whatever123"},
        )
        assert resp.status_code == 409

    async def test_normal_user_is_not_admin(self, auth_client) -> None:
        me = (await auth_client.get(f"{API}/auth/me")).json()
        assert me["isAdmin"] is False
        # 非管理员调用管理接口 → 403
        assert (await auth_client.get(f"{API}/admin/users")).status_code == 403

    async def test_admin_can_reset_user_password(self, client, session_factory, auth_client) -> None:
        await self._ensure_admin(session_factory)
        target = (await auth_client.get(f"{API}/auth/me")).json()

        await self._login_as_admin(client)
        found = (await client.get(f"{API}/admin/users", params={"query": "tester"})).json()
        assert any(u["id"] == target["id"] for u in found["users"])

        resp = await client.post(
            f"{API}/admin/reset-password", json={"userId": target["id"], "newPassword": "brand-new-pass"}
        )
        assert resp.status_code == 200, resp.text

        # 旧密码失效、新密码可登录
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as fresh:
            old = await fresh.post(
                f"{API}/auth/login", json={"username": "tester", "password": "secret123"}
            )
            assert old.status_code == 401
            new = await fresh.post(
                f"{API}/auth/login", json={"username": "tester", "password": "brand-new-pass"}
            )
            assert new.status_code == 200, new.text

    async def test_admin_cannot_reset_own_password(self, client, session_factory) -> None:
        await self._ensure_admin(session_factory)
        await self._login_as_admin(client)
        me = (await client.get(f"{API}/auth/me")).json()
        resp = await client.post(
            f"{API}/admin/reset-password", json={"userId": me["id"], "newPassword": "irrelevant123"}
        )
        assert resp.status_code == 400
        assert "环境变量" in resp.json()["detail"]

    async def test_admin_cannot_change_own_password(self, client, session_factory) -> None:
        await self._ensure_admin(session_factory)
        await self._login_as_admin(client)
        resp = await client.post(
            f"{API}/auth/change-password",
            json={
                "currentPassword": self.ADMIN_PASS,
                "newPassword": "newadmin123",
                "confirmPassword": "newadmin123",
            },
        )
        assert resp.status_code == 400
        assert "环境变量" in resp.json()["detail"]

    async def test_admin_hidden_from_ranking(self, client, session_factory, auth_client) -> None:
        # 让普通玩家有成绩，并给管理员也塞一个英雄，验证仍被排除
        await self._ensure_admin(session_factory)
        async with session_factory() as db:
            admin = (await db.execute(select(User).where(User.username == self.ADMIN_USER))).scalar_one()
            db.add(
                Hero(
                    user_id=admin.id,
                    name="管理员英雄",
                    level=99,
                    talent="mythic",
                    attr_bias="balanced",
                    current_region_id=1,
                )
            )
            await db.commit()
            await refresh_all_rankings(db)
            await db.commit()

        entries = (await client.get(f"{API}/ranking", params={"board": "level"})).json()["entries"]
        assert entries, "排行榜不应为空"
        assert all(e["username"] != self.ADMIN_USER for e in entries)

    async def test_admin_cannot_ban_admin(self, client, session_factory) -> None:
        await self._ensure_admin(session_factory)
        await self._login_as_admin(client)
        me = (await client.get(f"{API}/auth/me")).json()
        resp = await client.post(f"{API}/admin/ban", json={"userId": me["id"], "banned": True})
        assert resp.status_code == 400
        assert "管理员" in resp.json()["detail"]

    async def test_normal_user_cannot_ban(self, auth_client) -> None:
        resp = await auth_client.post(f"{API}/admin/ban", json={"userId": 1, "banned": True})
        assert resp.status_code == 403

    async def test_ban_blocks_login_and_kills_existing_session(
        self, client, session_factory, auth_client
    ) -> None:
        """封号后：旧令牌下一次请求即被拒（强制下线），且无法再登录；对外只回传机器码。"""
        await self._ensure_admin(session_factory)
        me = (await auth_client.get(f"{API}/auth/me")).json()
        tester_token = auth_client.headers["Authorization"].split(" ", 1)[1]

        await self._login_as_admin(client)  # 复用同一 client，Authorization 换成管理员
        banned = await client.post(f"{API}/admin/ban", json={"userId": me["id"], "banned": True})
        assert banned.status_code == 200, banned.text
        assert banned.json()["banned"] is True

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as fresh:
            fresh.headers.update({"Authorization": f"Bearer {tester_token}"})
            session_blocked = await fresh.get(f"{API}/auth/me")
            assert session_blocked.status_code == 403
            assert session_blocked.json()["detail"] == {"code": "banned"}

            relogin = await fresh.post(
                f"{API}/auth/login", json={"username": "tester", "password": "secret123"}
            )
            assert relogin.status_code == 403
            assert relogin.json()["detail"] == {"code": "banned"}

            # 密码是否正确都不改变结果，避免暴露账号状态
            wrong_pass = await fresh.post(
                f"{API}/auth/login", json={"username": "tester", "password": "nope"}
            )
            assert wrong_pass.status_code == 401

    async def test_unban_restores_login(self, client, session_factory, auth_client) -> None:
        await self._ensure_admin(session_factory)
        me = (await auth_client.get(f"{API}/auth/me")).json()
        await self._login_as_admin(client)

        await client.post(f"{API}/admin/ban", json={"userId": me["id"], "banned": True})
        unbanned = await client.post(f"{API}/admin/ban", json={"userId": me["id"], "banned": False})
        assert unbanned.status_code == 200
        assert unbanned.json()["banned"] is False

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as fresh:
            ok = await fresh.post(
                f"{API}/auth/login", json={"username": "tester", "password": "secret123"}
            )
            assert ok.status_code == 200, ok.text

    async def test_banned_user_hidden_from_ranking(self, client, session_factory, auth_client) -> None:
        await self._ensure_admin(session_factory)
        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            await refresh_all_rankings(db)
            await db.commit()

        before = (await client.get(f"{API}/ranking", params={"board": "level"})).json()["entries"]
        assert any(e["userId"] == me["id"] for e in before), "封禁前应在榜上"

        await self._login_as_admin(client)
        await client.post(f"{API}/admin/ban", json={"userId": me["id"], "banned": True})

        # 即使缓存未刷新，也应在查询期被过滤掉
        hidden = (await client.get(f"{API}/ranking", params={"board": "level"})).json()["entries"]
        assert all(e["userId"] != me["id"] for e in hidden)

        # 缓存刷新后依然不在榜
        async with session_factory() as db:
            await refresh_all_rankings(db)
            await db.commit()
        refreshed = (await client.get(f"{API}/ranking", params={"board": "level"})).json()["entries"]
        assert all(e["userId"] != me["id"] for e in refreshed)

    async def test_ranking_exposes_login_username(self, client, session_factory, auth_client) -> None:
        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            await refresh_all_rankings(db)
            await db.commit()

        entries = (await client.get(f"{API}/ranking", params={"board": "level"})).json()["entries"]
        mine = next(e for e in entries if e["userId"] == me["id"])
        assert mine["username"] == me["username"]


class TestCodexAndRanking:
    async def test_equipment_codex_unlocks_on_obtain(self, auth_client, session_factory) -> None:
        before = (await auth_client.get(f"{API}/codex?category=equipment")).json()
        # 开局起始武器已解锁 1 条
        assert before["progress"]["equipment"]["unlocked"] == 1

        item = await _open_one(auth_client, session_factory)
        body = (await auth_client.get(f"{API}/codex?category=equipment")).json()
        unlocked = [e for e in body["entries"] if e["unlocked"]]
        expected = {STARTER_BASE_ID, *[i["baseId"] for i in item["items"]]}
        assert {e["baseId"] for e in unlocked} == expected
        assert body["progress"]["equipment"]["unlocked"] == len(expected)

    async def test_codex_progress_after_battle(self, auth_client, session_factory) -> None:
        await _farm(auth_client, session_factory, 1, reports=5)
        resp = await auth_client.get(f"{API}/codex?category=monster")
        assert resp.status_code == 200
        body = resp.json()
        assert body["progress"]["monster"]["unlocked"] > 0
        unlocked = [e for e in body["entries"] if e["unlocked"]]
        assert unlocked

    async def test_equipment_codex_closed_until_obtain(self, auth_client) -> None:
        resp = await auth_client.get(f"{API}/codex?category=equipment")
        body = resp.json()
        assert body["progress"]["equipment"]["total"] == len(CONFIG.base_items)
        # 开局只有起始武器已解锁，其余（含更高品阶）保持剪影
        unlocked = [e for e in body["entries"] if e["unlocked"]]
        assert [e["baseId"] for e in unlocked] == [STARTER_BASE_ID]
        assert unlocked[0]["unlockedRarities"] == ["common"]

    async def test_term_codex_tracks_three_qualities(self, auth_client) -> None:
        body = (await auth_client.get(f"{API}/codex?category=term")).json()
        assert body["progress"]["term"]["total"] == len(body["entries"]) * 3
        for entry in body["entries"]:
            assert set(entry["qualities"]) == {"common", "rare", "ancient"}
        # 词条图鉴同时收录战斗装备与生产/采集专用装备的词条
        assert {e["source"] for e in body["entries"]} == {"combat", "production"}

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

    async def test_playtime_tracked_and_ranked(self, auth_client, session_factory) -> None:
        me = (await auth_client.get(f"{API}/auth/me")).json()
        await _farm(auth_client, session_factory, 1, reports=3, elapsed_ms=15000)

        # 服务端累计：3 次上报窗口（每次 15s）都应计入
        async with session_factory() as db:
            user = (await db.execute(select(User).where(User.id == me["id"]))).scalar_one()
            assert user.play_ms >= 30_000, user.play_ms

        await auth_client.post(f"{API}/ranking/refresh")

        playtime = (await auth_client.get(f"{API}/ranking", params={"board": "playtime"})).json()
        assert playtime["board"] == "playtime"
        row = next(e for e in playtime["entries"] if e["userId"] == me["id"])
        assert row["payload"]["playSeconds"] >= 30

        # 其余榜单的行内也带游玩时间
        level = (await auth_client.get(f"{API}/ranking", params={"board": "level"})).json()
        level_row = next(e for e in level["entries"] if e["userId"] == me["id"])
        assert level_row["payload"]["playSeconds"] >= 30

        profile = (await auth_client.get(f"{API}/ranking/players/{me['id']}")).json()
        assert profile["playSeconds"] >= 30


class TestPlayerProfile:
    """排行榜点击查看他人「当前装备」：需登录、仅已装备栏位、不含私有标签。"""

    async def _make_player(
        self, session_factory, username: str, *, banned: bool = False, with_hero: bool = True
    ) -> int:
        async with session_factory() as db:
            user = User(username=username, password_hash="x", nickname="对手", banned=banned)
            db.add(user)
            await db.flush()
            if with_hero:
                db.add(
                    Hero(
                        user_id=user.id, name="对手英雄", level=42, exp=0, talent="rare",
                        attr_bias="balanced", strength=100, agility=80, intellect=60,
                        current_region_id=1, region_kill_count=0, is_initial=False,
                    )
                )
            db.add(
                Item(
                    user_id=user.id, base_id="w_sword_shield_0", name="剑", category="weapon",
                    slot="mainHand", rarity="rare", level_req=1,
                    base_attrs=[{"attr": "attack", "value": 50.0}], sub_attrs=[], terms=[],
                    equipped_slot="mainHand" if with_hero else None, source="chest", tag_ids=[7],
                )
            )
            db.add(
                Item(
                    user_id=user.id, base_id="a_head_0", name="头盔", category="armor",
                    slot="head", rarity="rare", level_req=1,
                    base_attrs=[{"attr": "physDef", "value": 30.0}], sub_attrs=[], terms=[],
                    equipped_slot="head" if with_hero else None, source="chest", tag_ids=[],
                )
            )
            # 背包里未装备的物品不应出现在他人视角
            db.add(
                Item(
                    user_id=user.id, base_id="a_head_0", name="背包头盔", category="armor",
                    slot="head", rarity="rare", level_req=1,
                    base_attrs=[{"attr": "physDef", "value": 30.0}], sub_attrs=[], terms=[],
                    equipped_slot=None, source="chest", tag_ids=[],
                )
            )
            await db.flush()
            user.active_hero_id = await db.scalar(select(Hero.id).where(Hero.user_id == user.id))
            await db.commit()
            return user.id

    async def test_view_other_player_gear(self, auth_client, session_factory) -> None:
        pid = await self._make_player(session_factory, "rival")
        resp = await auth_client.get(f"{API}/ranking/players/{pid}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["userId"] == pid
        assert body["nickname"] == "对手"
        assert body["hero"]["level"] == 42
        assert body["power"] > 0
        # 只含已装备栏位，不含背包
        assert set(body["loadout"].keys()) == {"mainHand", "head"}
        # 物主私有的标签不外泄
        assert all(item["tagIds"] == [] for item in body["loadout"].values())

    async def test_missing_player_is_404(self, auth_client) -> None:
        assert (await auth_client.get(f"{API}/ranking/players/999999")).status_code == 404

    async def test_banned_and_hero_less_are_hidden(self, auth_client, session_factory) -> None:
        banned_id = await self._make_player(session_factory, "rival_banned", banned=True)
        assert (await auth_client.get(f"{API}/ranking/players/{banned_id}")).status_code == 404

        no_hero_id = await self._make_player(session_factory, "rival_nohero", with_hero=False)
        assert (await auth_client.get(f"{API}/ranking/players/{no_hero_id}")).status_code == 404

    async def test_requires_login(self, auth_client) -> None:
        token = auth_client.headers.get("Authorization")
        auth_client.headers.pop("Authorization", None)
        try:
            resp = await auth_client.get(f"{API}/ranking/players/1")
        finally:
            if token:
                auth_client.headers["Authorization"] = token
        assert resp.status_code == 401


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

    async def test_replay_after_restart_grants_no_reward(self, auth_client) -> None:
        first = (await auth_client.post(f"{API}/tutorial/complete")).json()
        assert first["granted"] is True
        gold_after_first = first["gold"]

        restarted = (await auth_client.post(f"{API}/tutorial/restart")).json()
        assert restarted["currentStep"] == 1
        assert restarted["rewarded"] is True

        again = (await auth_client.post(f"{API}/tutorial/complete")).json()
        assert again["granted"] is False
        assert again["completed"] is True

        me = (await auth_client.get(f"{API}/auth/me")).json()
        assert me["gold"] == gold_after_first


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


class TestRedeem:
    @pytest.fixture(autouse=True)
    def _reset_settings(self):
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    async def test_disabled_without_env_code(self, auth_client, monkeypatch) -> None:
        monkeypatch.setenv("REDEEM_CODE", "")
        monkeypatch.setenv("REDEEM_GOLD", "0")
        # 环境变量在测试体内才设置，必须重新取配置（夹具阶段可能已被预热）
        get_settings.cache_clear()

        state = (await auth_client.get(f"{API}/redeem")).json()
        assert state == {"enabled": False, "canRedeem": False, "rewardGold": 0}
        assert (await auth_client.post(f"{API}/redeem", json={"code": "whatever"})).status_code == 400

    async def test_redeem_grants_gold_once(self, auth_client, monkeypatch) -> None:
        monkeypatch.setenv("REDEEM_CODE", "EORZEA2026")
        monkeypatch.setenv("REDEEM_GOLD", "12345")
        get_settings.cache_clear()

        state = (await auth_client.get(f"{API}/redeem")).json()
        assert state == {"enabled": True, "canRedeem": True, "rewardGold": 12345}

        wrong = await auth_client.post(f"{API}/redeem", json={"code": "wrong-code"})
        assert wrong.status_code == 400
        assert "无效" in wrong.json()["detail"]

        before = (await auth_client.get(f"{API}/auth/me")).json()["gold"]
        ok = await auth_client.post(f"{API}/redeem", json={"code": "EORZEA2026"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["goldGained"] == 12345
        assert ok.json()["gold"] == before + 12345

        again = await auth_client.post(f"{API}/redeem", json={"code": "EORZEA2026"})
        assert again.status_code == 400
        assert "已经兑换过" in again.json()["detail"]

        assert (await auth_client.get(f"{API}/auth/me")).json()["gold"] == before + 12345
        assert (await auth_client.get(f"{API}/redeem")).json()["canRedeem"] is False

    async def test_redeem_ignores_client_supplied_amount(self, auth_client, monkeypatch) -> None:
        """奖励数额只认服务端配置：请求体里塞金币/数额字段一律无效。"""
        monkeypatch.setenv("REDEEM_CODE", "TAMPER")
        monkeypatch.setenv("REDEEM_GOLD", "500")
        get_settings.cache_clear()

        before = (await auth_client.get(f"{API}/auth/me")).json()["gold"]
        resp = await auth_client.post(
            f"{API}/redeem", json={"code": "TAMPER", "gold": 10**9, "rewardGold": 10**9}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["goldGained"] == 500
        assert (await auth_client.get(f"{API}/auth/me")).json()["gold"] == before + 500


class TestAbuseGuards:
    """反滥用：多开与刷取的服务端边界（数值均为可配置的显式上限）。"""

    @pytest.fixture(autouse=True)
    def _reset_settings(self):
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    async def test_register_rate_limited_per_ip(self, client, monkeypatch) -> None:
        """同一 IP 每小时建号数达到上限后拒绝（防批量注册小号）。"""
        monkeypatch.setenv("REGISTER_PER_IP_PER_HOUR", "2")
        monkeypatch.setenv("REGISTER_PER_IP_PER_DAY", "0")  # 关掉日限，单独验证小时限
        get_settings.cache_clear()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as fresh:
            codes = [
                (
                    await fresh.post(
                        f"{API}/auth/register",
                        json={"username": f"reg{i}", "password": "secret123"},
                    )
                ).status_code
                for i in range(3)
            ]
        assert codes == [201, 201, 429]

    async def test_login_rate_limited_per_ip(self, client, monkeypatch) -> None:
        """同一 IP 的登录尝试达到上限后拒绝（防撞库 / 脚本批量登录）。"""
        monkeypatch.setenv("LOGIN_PER_IP_PER_5MIN", "2")
        get_settings.cache_clear()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as fresh:
            await fresh.post(
                f"{API}/auth/register", json={"username": "loginuser", "password": "secret123"}
            )
            codes = [
                (
                    await fresh.post(
                        f"{API}/auth/login", json={"username": "loginuser", "password": "secret123"}
                    )
                ).status_code
                for _ in range(3)
            ]
        assert codes == [200, 200, 429]

    async def test_redeem_rate_limited_per_ip(self, auth_client, monkeypatch) -> None:
        monkeypatch.setenv("REDEEM_CODE", "RATE1")
        monkeypatch.setenv("REDEEM_GOLD", "100")
        monkeypatch.setenv("REDEEM_PER_IP_PER_HOUR", "1")
        get_settings.cache_clear()

        first = await auth_client.post(f"{API}/redeem", json={"code": "bad"})
        assert first.status_code == 400
        assert "无效" in first.json()["detail"]

        second = await auth_client.post(f"{API}/redeem", json={"code": "bad"})
        assert second.status_code == 429

    async def test_redeem_capped_per_ip(self, client, monkeypatch) -> None:
        """同一 IP 能兑换同一码的账号数有上限：多开小号无法换来无上限金币。"""
        monkeypatch.setenv("REDEEM_CODE", "CAPTEST")
        monkeypatch.setenv("REDEEM_GOLD", "1000")
        monkeypatch.setenv("REDEEM_ACCOUNTS_PER_IP", "2")
        monkeypatch.setenv("REDEEM_PER_IP_PER_HOUR", "0")  # 关掉频率限制，单独验证次数上限
        get_settings.cache_clear()

        tokens: list[str] = []
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as fresh:
            for i in range(3):
                reg = await fresh.post(
                    f"{API}/auth/register",
                    json={"username": f"alt{i}", "password": "secret123"},
                )
                assert reg.status_code == 201, reg.text
                tokens.append(reg.json()["accessToken"])

        statuses: list[int] = []
        for token in tokens:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as fresh:
                fresh.headers.update({"Authorization": f"Bearer {token}"})
                statuses.append(
                    (await fresh.post(f"{API}/redeem", json={"code": "CAPTEST"})).status_code
                )

        assert statuses == [200, 200, 429], "第 3 个小号必须被同 IP 兑换上限拦下"

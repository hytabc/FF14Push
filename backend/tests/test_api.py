"""接口集成测试：走通 MVP 闭环与各系统。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.v1.battle import _settle_boss
from app.core.config import get_settings
from app.main import app
from app.models import RaidSession, BattleSession, Hero, Item, ItemTag, RegionProgress, TavernState, User
from app.schemas.game import BattleReportRequest
from app.services.admin import ensure_admin_user
from app.services.economy import enchant_cost, refine_cost
from app.services.game_config import CONFIG
from app.services.ranking import refresh_all_rankings
from app.services.recruiting import recruit_cost

API = "/api/v1"

# 开局赠送并装备的起始武器（见 auth._bootstrap_new_user）
STARTER_BASE_ID = str(CONFIG.heroes["initialHero"]["starterWeapon"])



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

    async def test_gathering_region_unlock_follows_account_progress(
        self, auth_client, session_factory
    ) -> None:
        """切换低等级英雄不应把已通关的生产 / 采集地区重新锁上。

        采集 / 生产 / 钓鱼地区按账号「通关的最远地区」解锁（与 start_gather / start_fish
        的服务端门槛同源），与当前上场英雄面板无关；战斗列表仍按英雄面板判定（走 /region）。
        """
        state = (await auth_client.get(f"{API}/game/state")).json()
        user_id = state["user"]["id"]

        async with session_factory() as db:
            existing: dict[int, RegionProgress] = {}
            for row in (
                await db.execute(select(RegionProgress).where(RegionProgress.user_id == user_id))
            ).scalars().all():
                existing.setdefault(row.region_id, row)
            # 账号已通关到第 5 区（跨英雄共享的账号级进度；周目 0）。
            for region_id in range(1, 6):
                row = existing.get(region_id)
                if row is None:
                    db.add(
                        RegionProgress(
                            user_id=user_id, difficulty=0, region_id=region_id,
                            unlocked=True, cleared=True,
                        )
                    )
                else:
                    row.unlocked = True
                    row.cleared = True
            # 新增一个 1 级英雄，并切换为上场英雄（低等级、弱面板）。
            lv1 = Hero(
                user_id=user_id, name="一级小号", level=1, exp=0,
                talent="common", attr_bias="balanced",
            )
            db.add(lv1)
            await db.commit()
            lv1_id = lv1.id

        switched = await auth_client.post(f"{API}/heroes/switch", json={"heroId": lv1_id})
        assert switched.status_code == 200, switched.text
        assert (await auth_client.get(f"{API}/game/state")).json()["hero"]["level"] == 1

        progress = (await auth_client.get(f"{API}/game/state")).json()["regionProgress"]
        # 已通关地区 + 最远通关的下一区都可采集；更远的仍未解锁（与服务端门槛一致）。
        for region_id in range(1, 7):
            assert progress[str(region_id)]["unlocked"] is True, region_id
        assert progress["7"]["unlocked"] is False

        blocked = await auth_client.post(
            f"{API}/gather/session/start", json={"jobId": "MIN", "regionId": 7}
        )
        assert blocked.status_code == 400
        assert "尚未解锁" in blocked.json()["detail"]

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
        # 金币明细：各档差额之和等于实际入账，供前端日志展示。
        calc = result["goldCalculation"]
        assert calc["base"] + calc["penaltyBonus"] + calc["potionBonus"] == result["goldGained"]

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
        detail = body["expCalculation"]
        assert detail["base"] + detail["efficiencyBonus"] + detail["catchUpBonus"] == body["expGained"]
        assert detail["totalBonusPct"] == round((body["expGained"] / detail["base"] - 1) * 100, 2)
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
        gold_before = 0
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
                gold_before = (await auth_client.get(f"{API}/game/state")).json()["user"]["gold"]
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
        # BOSS 金币：必须实际入账，并返回明细（供前端日志展示）。
        assert body["boss"]["gold"] > 0, "BOSS 应掉落金币"
        assert body["gold"] >= gold_before + body["boss"]["gold"]
        boss_calc = body["boss"]["goldCalculation"]
        assert boss_calc["base"] + boss_calc["penaltyBonus"] + boss_calc["potionBonus"] == body["boss"]["gold"]

        regions = (await auth_client.get(f"{API}/region")).json()
        by_id = {r["id"]: r for r in regions["regions"]}
        assert by_id[1]["cleared"] is True
        assert by_id[2]["unlocked"] is False
        # 地区不再要求机制试炼：未解锁只因战力/装备/主攻/双防或前一地区 BOSS
        assert by_id[2]["missingConditions"]
        assert "试炼" not in by_id[2]["lockedHint"]

    async def test_boss_settles_when_kill_batch_is_truncated(self, auth_client, session_factory) -> None:
        """服务端按窗口额度取整会截断爆发击杀，使计数滞后于客户端。

        旧逻辑按截断后的计数判定，会把 BOSS 结算静默丢弃，客户端停在 cleared
        阶段不再产生事件，从而永远无法进入下一地区。缺口恰好不超过本批上报的击杀数。
        """
        started = await auth_client.post(f"{API}/battle/session/start", json={"regionId": 1})
        session_id = started.json()["sessionId"]
        current = (await auth_client.get(f"{API}/region/current")).json()
        required = current["killsRequired"]

        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            hero = (await db.execute(select(Hero).where(Hero.user_id == me["id"]))).scalar_one()
            hero.region_kill_count = required - 1
            await db.commit()

        # 窗口仅 1 秒：额度不足 1 只，本批击杀会被截断为 0（旧逻辑据此丢弃 BOSS 结算）
        resp = await _report(
            auth_client,
            session_factory,
            session_id,
            1,
            [{"monsterId": "normal", "gold": 20, "exp": 30}],
            elapsed_ms=1000,
            bossKilled=True,
            bossFightMs=1000,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["boss"] is not None, "击杀被截断不应导致 BOSS 结算被丢弃"
        assert body["boss"]["firstClear"] is True
        assert body["killCount"] == 0

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

    async def test_chest_band_uses_roster_max_level(self, auth_client, session_factory) -> None:
        """档位解锁按角色库（名册）内最高等级，而非当前上场英雄。"""
        me = (await auth_client.get(f"{API}/auth/me")).json()
        await _set_gold(auth_client, session_factory, 10_000_000)

        # 名册只有 1 级的上场英雄：100 级档位不可用。
        locked = await auth_client.post(
            f"{API}/chest/open", json={"chestId": "weaponBox", "count": 1, "level": 100}
        )
        assert locked.status_code == 400

        # 名册内新增 100 级英雄（不作为上场英雄）：档位随之解锁。
        async with session_factory() as db:
            db.add(
                Hero(
                    user_id=me["id"],
                    name="满级英雄",
                    level=100,
                    talent="common",
                    attr_bias="balanced",
                )
            )
            await db.commit()

        ok = await auth_client.post(
            f"{API}/chest/open", json={"chestId": "weaponBox", "count": 1, "level": 100}
        )
        assert ok.status_code == 200, ok.text

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

    async def test_locked_draw_count_requires_unlock(self, auth_client, session_factory) -> None:
        """50/100 连抽在解锁前被拒绝。"""
        await _set_gold(auth_client, session_factory, 10_000_000_000)
        locked = await auth_client.post(f"{API}/chest/open", json={"chestId": "weaponBox", "count": 50})
        assert locked.status_code == 400
        assert "解锁" in locked.json()["detail"]

    async def test_unlock_draw_count_deducts_gold_and_enables_draw(
        self, auth_client, session_factory
    ) -> None:
        cost50 = next(
            int(d["unlockCost"]) for d in CONFIG.chests["drawCounts"] if int(d["count"]) == 50
        )
        await _set_gold(auth_client, session_factory, cost50 + 1_000_000)

        unlocked = await auth_client.post(f"{API}/chest/unlock", json={"count": 50})
        assert unlocked.status_code == 200, unlocked.text
        body = unlocked.json()
        assert 50 in body["unlocked"]
        assert body["gold"] == 1_000_000

        # 重复解锁直接拒绝
        again = await auth_client.post(f"{API}/chest/unlock", json={"count": 50})
        assert again.status_code == 400

        # 解锁后可正常抽取 50 连
        draw = await auth_client.post(f"{API}/chest/open", json={"chestId": "weaponBox", "count": 50})
        assert draw.status_code == 200, draw.text
        got = draw.json()
        assert len(got["items"]) + len(got["autoSold"]) == 50

        # 状态里持久化解锁档位
        state = (await auth_client.get(f"{API}/game/state")).json()
        assert 50 in state["settings"]["chestUnlocks"]

    async def test_draw_count_100_unlock_cost(self, auth_client, session_factory) -> None:
        cost100 = next(
            int(d["unlockCost"]) for d in CONFIG.chests["drawCounts"] if int(d["count"]) == 100
        )
        assert cost100 == 20_000_000
        await _set_gold(auth_client, session_factory, cost100)
        resp = await auth_client.post(f"{API}/chest/unlock", json={"count": 100})
        assert resp.status_code == 200, resp.text
        assert resp.json()["gold"] == 0

    async def test_unlock_count_without_cost_rejected(self, auth_client, session_factory) -> None:
        resp = await auth_client.post(f"{API}/chest/unlock", json={"count": 1})
        assert resp.status_code == 400

    async def test_auto_sold_draw_items_return_full_payload(
        self, auth_client, session_factory
    ) -> None:
        """自动出售的物品也要返回完整数据（供抽奖动画与结果页展示）。"""
        cost50 = next(
            int(d["unlockCost"]) for d in CONFIG.chests["drawCounts"] if int(d["count"]) == 50
        )
        await _set_gold(auth_client, session_factory, cost50 + 10_000_000)
        unlocked = await auth_client.post(f"{API}/chest/unlock", json={"count": 50})
        assert unlocked.status_code == 200, unlocked.text
        resp = await auth_client.post(f"{API}/settings/auto-sell", json={"enabled": True, "rarities": ["common", "uncommon"]})
        assert resp.status_code == 200, resp.text

        draw = await auth_client.post(f"{API}/chest/open", json={"chestId": "weaponBox", "count": 50})
        assert draw.status_code == 200, draw.text
        got = draw.json()
        assert len(got["items"]) + len(got["autoSold"]) == 50
        assert got["autoSold"], "50 连抽应当出现被自动出售的普通/优秀装备"
        for sold in got["autoSold"]:
            assert sold["autoSold"] is True
            assert sold["price"] > 0
            # 完整物品字段（动画/卡片需要 baseId、rarity、subAttrs 等）
            for key in ("baseId", "name", "rarity", "category", "subAttrs", "sellPriceMin"):
                assert key in sold

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
            hero.level = 100
            await db.commit()
        await _set_gold(auth_client, session_factory, 1_000_000)

        high = await auth_client.post(
            f"{API}/chest/open", json={"chestId": "weaponBox", "count": 10, "level": 40}
        )
        assert high.status_code == 200, high.text
        assert all(item["levelReq"] == 40 for item in high.json()["items"])

        # 80 级档位覆盖拥挤的 80-100 子区间：可出 Lv80/85/90/95，且不低于 80
        top = await auth_client.post(
            f"{API}/chest/open", json={"chestId": "weaponBox", "count": 10, "level": 80}
        )
        assert top.status_code == 200, top.text
        top_levels = {item["levelReq"] for item in top.json()["items"]}
        assert top_levels <= {80, 85, 90, 95}

        low = await auth_client.post(
            f"{API}/chest/open", json={"chestId": "weaponBox", "count": 10, "level": 1}
        )
        assert low.status_code == 200, low.text
        assert all(item["levelReq"] == 1 for item in low.json()["items"])

    async def test_chest_band_20_never_drops_low_level_gear(
        self, auth_client, session_factory
    ) -> None:
        """20 级档位只出 Lv20：修复「20 级箱子偶尔抽出 1 级（铁制）装备」。"""
        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            hero = (await db.execute(select(Hero).where(Hero.user_id == me["id"]))).scalar_one()
            hero.level = 20
            await db.commit()
        await _set_gold(auth_client, session_factory, 1_000_000)

        for _ in range(5):
            resp = await auth_client.post(
                f"{API}/chest/open", json={"chestId": "weaponBox", "count": 10, "level": 20}
            )
            assert resp.status_code == 200, resp.text
            assert all(item["levelReq"] == 20 for item in resp.json()["items"])

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

    async def test_role_restricted_gear(self, auth_client, session_factory) -> None:
        """职能限制：防具/饰品需与当前武器职能一致；换武器自动卸下不符装备。"""
        me = (await auth_client.get(f"{API}/auth/me")).json()
        tank_weapon = next(b for b in CONFIG.base_items if b.slot == "mainHand" and b.job_id == "PLD")
        healer_weapon = next(b for b in CONFIG.base_items if b.slot == "mainHand" and b.job_id == "WHM")
        tank_armor = next(b for b in CONFIG.base_items if b.slot == "head" and b.role == "tank")
        healer_armor = next(b for b in CONFIG.base_items if b.slot == "head" and b.role == "healer")
        await _seed_items(session_factory, me["id"], 1, category="weapon", base_id=tank_weapon.id, slot="mainHand")
        await _seed_items(session_factory, me["id"], 1, category="weapon", base_id=healer_weapon.id, slot="mainHand")
        await _seed_items(session_factory, me["id"], 1, category="armor", base_id=tank_armor.id, slot="head")
        await _seed_items(session_factory, me["id"], 1, category="armor", base_id=healer_armor.id, slot="head")

        state = (await auth_client.get(f"{API}/game/state")).json()
        by_base: dict[str, dict] = {it["baseId"]: it for it in state["items"]}

        # 先装备坦克武器 → 英雄职能 = 坦克
        resp = await auth_client.post(
            f"{API}/inventory/equip", json={"itemId": by_base[tank_weapon.id]["id"], "slot": "mainHand"}
        )
        assert resp.status_code == 200, resp.text
        # 坦克防具可穿
        resp = await auth_client.post(
            f"{API}/inventory/equip", json={"itemId": by_base[tank_armor.id]["id"], "slot": "head"}
        )
        assert resp.status_code == 200, resp.text
        # 治疗防具被拒（职能不符）
        resp = await auth_client.post(
            f"{API}/inventory/equip", json={"itemId": by_base[healer_armor.id]["id"], "slot": "head"}
        )
        assert resp.status_code == 400 and "职能" in resp.json()["detail"], resp.text
        # 换成治疗武器 → 自动卸下不符职能的坦克防具
        resp = await auth_client.post(
            f"{API}/inventory/equip", json={"itemId": by_base[healer_weapon.id]["id"], "slot": "mainHand"}
        )
        assert resp.status_code == 200, resp.text
        unequipped_ids = {u["id"] for u in resp.json().get("unequipped", [])}
        assert by_base[tank_armor.id]["id"] in unequipped_ids
        assert "head" not in (await auth_client.get(f"{API}/game/state")).json()["loadout"]

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

        rarity, level = item["rarity"], item["levelReq"]
        first_cost = refine_cost(rarity, 0, "random", level)
        second_cost = refine_cost(rarity, 1, "random", level)

        first = await auth_client.post(f"{API}/economy/refine", json={"itemId": item["id"]})
        assert first.status_code == 200, first.text
        assert first.json()["cost"] == first_cost
        assert first.json()["after"]["refineCost"] == second_cost

        second = await auth_client.post(f"{API}/economy/refine", json={"itemId": item["id"]})
        assert second.status_code == 200, second.text
        assert second.json()["cost"] == second_cost
        assert second.json()["cost"] > first.json()["cost"]

    async def test_refine_rerolls_attrs_and_terms(self, auth_client, session_factory) -> None:
        """彻底随机重造：属性与词条一起重掷，品阶/类型保持不变。"""
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        await _set_gold(auth_client, session_factory, 700000)

        resp = await auth_client.post(f"{API}/economy/refine", json={"itemId": item["id"]})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cost"] == refine_cost(item["rarity"], 0, "random", item["levelReq"])
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
        assert body["cost"] == enchant_cost(item["rarity"], "random", item["levelReq"])
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

        expected = refine_cost(item["rarity"], 0, "basedOnCurrent", item["levelReq"])

        for index in range(5):
            resp = await auth_client.post(
                f"{API}/economy/refine", json={"itemId": item["id"], "mode": "basedOnCurrent"}
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            if index == 0:
                assert body["cost"] == expected
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

        expected = enchant_cost(item["rarity"], "basedOnCurrent", item["levelReq"])
        resp = await auth_client.post(
            f"{API}/economy/enchant", json={"itemId": item["id"], "mode": "basedOnCurrent"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["cost"] == expected

    async def test_refine_times_charges_cumulative_and_counts(self, auth_client, session_factory) -> None:
        """一次请求连做多次重造：按逐次递增价累计，次数一次加满。"""
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        await _set_gold(auth_client, session_factory, 50_000_000)

        expected = sum(
            refine_cost(item["rarity"], index, "random", item["levelReq"]) for index in range(10)
        )

        resp = await auth_client.post(f"{API}/economy/refine", json={"itemId": item["id"], "times": 10})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["times"] == 10
        assert body["cost"] == expected
        assert body["after"]["refineCount"] == 10
        assert body["gold"] == 50_000_000 - expected

    async def test_refine_times_stops_when_gold_runs_out(self, auth_client, session_factory) -> None:
        """金币只够两次时连做 10 次：提前停在 2 次，不超支、不报错。"""
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]

        level = item["levelReq"]
        afford = refine_cost(item["rarity"], 0, "random", level) + refine_cost(
            item["rarity"], 1, "random", level
        )
        await _set_gold(auth_client, session_factory, afford)

        resp = await auth_client.post(f"{API}/economy/refine", json={"itemId": item["id"], "times": 10})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["times"] == 2
        assert body["cost"] == afford
        assert body["gold"] == 0
        assert body["after"]["refineCount"] == 2

    async def test_refine_times_rejects_when_unaffordable(self, auth_client, session_factory) -> None:
        """连一次都付不起时仍返回 400。"""
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        await _set_gold(auth_client, session_factory, 0)

        resp = await auth_client.post(f"{API}/economy/refine", json={"itemId": item["id"], "times": 5})
        assert resp.status_code == 400
        assert "金币不足" in resp.json()["detail"]

    async def test_enchant_times_charges_flat_unit_price(self, auth_client, session_factory) -> None:
        """附魔连做多次：单价 × 次数，次数一次加满；基于当前同样支持连做。"""
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        await _set_gold(auth_client, session_factory, 50_000_000)
        unit = enchant_cost(item["rarity"], "random", item["levelReq"])

        resp = await auth_client.post(f"{API}/economy/enchant", json={"itemId": item["id"], "times": 5})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["times"] == 5
        assert body["attempts"] == 5
        assert body["cost"] == unit * 5
        assert body["after"]["enchantCount"] == 5

        based = await auth_client.post(
            f"{API}/economy/enchant",
            json={"itemId": item["id"], "mode": "basedOnCurrent", "times": 3},
        )
        assert based.status_code == 200, based.text
        assert based.json()["times"] == 3
        assert based.json()["after"]["enchantCount"] == 8

    async def test_times_above_cap_is_rejected(self, auth_client, session_factory) -> None:
        opened = await _open_one(auth_client, session_factory)
        item = opened["items"][0]
        await _set_gold(auth_client, session_factory, 50_000_000)
        resp = await auth_client.post(f"{API}/economy/refine", json={"itemId": item["id"], "times": 51})
        assert resp.status_code == 422


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

    async def test_cannot_dismiss_last_hero(self, auth_client) -> None:
        hero_id = (await auth_client.get(f"{API}/game/state")).json()["hero"]["id"]
        resp = await auth_client.post(f"{API}/tavern/dismiss", json={"heroId": hero_id})
        assert resp.status_code == 400

    async def test_can_dismiss_initial_hero_when_others_remain(self, auth_client, session_factory) -> None:
        initial_id = (await auth_client.get(f"{API}/game/state")).json()["hero"]["id"]
        await _set_gold(auth_client, session_factory, 1_000_000)
        recruited = await auth_client.post(f"{API}/tavern/recruit", json={"confirm": True})
        assert recruited.status_code == 200, recruited.text
        new_id = recruited.json()["hero"]["id"]

        dismissed = await auth_client.post(f"{API}/tavern/dismiss", json={"heroId": initial_id})
        assert dismissed.status_code == 200, dismissed.text

        state = (await auth_client.get(f"{API}/game/state")).json()
        assert [h["id"] for h in state["heroes"]] == [new_id]
        assert state["hero"]["id"] == new_id  # 初始英雄可解雇，出战英雄自动改派

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
        assert hero["jobId"] == CONFIG.base_item_by_id[STARTER_BASE_ID].job_id
        assert hero["isInitial"] is True
        assert hero["currentRegionId"] == 1


class TestRaid:
    # 高难副本门槛：绝* 已取消装备词缀 / 品质限制，只保留等级、栏位与战力门槛。
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

    async def test_hard_raid_ignores_equipment_quality_and_ancient_terms(
        self, auth_client, session_factory
    ) -> None:
        """最后两关（绝*）已取消装备词缀与品质限制：全蓝、无太古词条也能进入。"""
        await self._gear_up(auth_client, session_factory, mix=["rare"] * 11, ancient=0)
        started = await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})
        assert started.status_code == 200, started.text
        await auth_client.post(f"{API}/raid/session/stop", json={"sessionId": started.json()["sessionId"]})

        body = (await auth_client.get(f"{API}/raid")).json()
        raid = next(r for r in body["raids"] if r["id"] == "raid_h1")
        assert raid["minEquipRarity"] == "common"
        assert raid["minAncientTermsPerItem"] == 0

    async def test_hard_raid_eligible_with_full_requirement(self, auth_client, session_factory) -> None:
        await self._gear_up(auth_client, session_factory, ancient=0)
        body = (await auth_client.get(f"{API}/raid")).json()
        raid = next(r for r in body["raids"] if r["id"] == "raid_h1")
        assert raid["eligible"] is True, raid["blockedReason"]
        assert raid["difficulty"] == "hard"
        assert raid["requiredLevel"] == 100
        assert raid["minEquipRarity"] == "common"
        assert raid["minAncientTermsPerItem"] == 0

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
        started = (await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})).json()
        async with session_factory() as db:
            # 固定服务端计时起点：否则测试机负载高时 start → report 的真实间隔可能超过
            # minimumFightMs（≈438ms），这条「虚报」反而会被当成合法通关而随机失败。
            session = await db.get(RaidSession, started["sessionId"])
            session.started_at = datetime.now(timezone.utc) - timedelta(milliseconds=50)
            await db.commit()
        resp = await auth_client.post(
            f"{API}/raid/session/report",
            json={
                "sessionId": started["sessionId"],
                "raidId": "raid_h1",
                "cleared": True,
                "died": False,
                "elapsedMs": 1000,
                "fightMs": 1000,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["cleared"] is False
        assert "invalid_duration" in resp.json()["failures"]

    async def test_hard_raid_fast_clear_is_accepted(self, auth_client, session_factory) -> None:
        """强练度玩家远快于理论时长，合法快速通关不能被判为 invalid_duration。

        实测强练度英雄约 1.5s 打完 raid_h1；旧的 durationTolerance=0.5（≈1.74s 下限）
        会把这种通关判成「战斗时长校验」失败而拿不到通关。
        """
        await self._gear_up(auth_client, session_factory, ancient=2)
        started = (await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_h1"})).json()
        async with session_factory() as db:
            session = await db.get(RaidSession, started["sessionId"])
            session.started_at = datetime.now(timezone.utc) - timedelta(milliseconds=1500)
            await db.commit()
        resp = await auth_client.post(
            f"{API}/raid/session/report",
            json={
                "sessionId": started["sessionId"],
                "raidId": "raid_h1",
                "cleared": True,
                "died": False,
                "elapsedMs": 1500,
                "fightMs": 1500,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cleared"] is True, body
        assert "invalid_duration" not in body.get("failures", [])

    async def test_list_reports_challenge_level_and_daily_limit(self, auth_client, session_factory) -> None:
        """列表展示目标等级与每日奖励次数。"""
        await self._gear_up(auth_client, session_factory, ancient=2)
        body = (await auth_client.get(f"{API}/raid")).json()
        raid = next(r for r in body["raids"] if r["id"] == "raid_3")
        assert raid["challengeLevel"] == int(CONFIG.raid_by_id["raid_3"]["challengeLevel"])
        assert raid["challengeLevel"] > raid["requiredLevel"]
        assert raid["dailyRewardClears"] == int(CONFIG.raid_by_id["raid_3"]["dailyRewardClears"])
        assert raid["rewardedToday"] == 0

    async def test_daily_reward_limit_blocks_further_rewards(self, auth_client, session_factory) -> None:
        """每个副本每天奖励通关次数有限：超出后仍记录通关，但不再产出金币/经验/宝箱。"""
        await self._gear_up(auth_client, session_factory, ancient=2)
        limit = int(CONFIG.raid_by_id["raid_1"]["dailyRewardClears"])

        async def clear_once() -> dict:
            started = (await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_1"})).json()
            async with session_factory() as db:
                session = await db.get(RaidSession, started["sessionId"])
                session.started_at = datetime.now(timezone.utc) - timedelta(seconds=90)
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

        for index in range(limit):
            body = await clear_once()
            assert body["cleared"] is True
            assert body["rewardLimited"] is False
            assert body["remainingToday"] == limit - index - 1

        over = await clear_once()
        assert over["cleared"] is True
        assert over["rewardLimited"] is True
        assert over["goldGained"] == 0
        assert over["expGained"] == 0
        assert over["items"] == []
        assert over["remainingToday"] == 0

        listing = (await auth_client.get(f"{API}/raid")).json()
        raid = next(r for r in listing["raids"] if r["id"] == "raid_1")
        assert raid["rewardedToday"] == limit
        assert raid["clearCount"] == limit + 1  # 无奖励通关也计入通关次数

    async def test_raid_exp_includes_egg_passive_bonus(self, auth_client, session_factory) -> None:
        """副本结算与地区一致：彩蛋「豆芽精」+25% 经验被动同样作用于副本通关经验。"""
        await self._gear_up(auth_client, session_factory, ancient=2)

        async def clear_once() -> int:
            started = (await auth_client.post(f"{API}/raid/session/start", json={"raidId": "raid_1"})).json()
            async with session_factory() as db:
                session = await db.get(RaidSession, started["sessionId"])
                session.started_at = datetime.now(timezone.utc) - timedelta(seconds=90)
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
            return int(resp.json()["expGained"])

        await clear_once()  # 首通（口径不同，忽略）
        plain = await clear_once()  # 重刷：无彩蛋被动
        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            hero = (await db.execute(select(Hero).where(Hero.user_id == me["id"]))).scalar_one()
            hero.egg_id = "liangshisi"
            # 升级会改变追赶经验口径，重置回满级避免干扰
            hero.level = 100
            hero.exp = 0
            await db.commit()
        boosted = await clear_once()  # 重刷：彩蛋 +25%
        assert boosted > plain, f"彩蛋经验被动未生效：plain={plain} boosted={boosted}"

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
        assert body["progress"]["equipment"]["total"] == (
            len(CONFIG.base_items)
            + len(CONFIG.dohdol_equipment["items"])
            + len(CONFIG.exclusive_items)
        )
        # 开局只有起始武器已解锁，其余（含更高品阶）保持剪影
        unlocked = [e for e in body["entries"] if e["unlocked"]]
        assert [e["baseId"] for e in unlocked] == [STARTER_BASE_ID]
        assert unlocked[0]["unlockedRarities"] == ["common"]

    async def test_equipment_codex_groups_cover_combat_and_dohdol(self, auth_client) -> None:
        body = (await auth_client.get(f"{API}/codex?category=equipment")).json()
        groups = {e["jobGroup"] for e in body["entries"]}
        assert {"combat", "doh", "dol"} <= groups
        # 世界BOSS 专属系列：归入战斗装备，来源仅世界BOSS，且带 exclusive 标记
        exclusive = [e for e in body["entries"] if e.get("exclusive")]
        assert len(exclusive) == len(CONFIG.exclusive_items)
        assert all(e["sources"] == ["worldBoss"] and e["jobGroup"] == "combat" for e in exclusive)
        # 专用装备条目不能带战斗专属字段
        dedicated = [e for e in body["entries"] if e["jobGroup"] in {"doh", "dol"}]
        assert dedicated
        assert all(e["weaponType"] is None and e["jobId"] is None for e in dedicated)

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


class TestBattleDifficulty:
    """地区战斗难度：默认 0、仅限已解锁、周目制按难度隔离地区进度。"""

    async def test_default_difficulty_zero(self, auth_client) -> None:
        state = (await auth_client.get(f"{API}/game/state")).json()
        assert state["difficulty"] == {"level": 0, "unlocked": 0, "maxLevel": 15}

    async def test_locked_difficulty_rejected(self, auth_client) -> None:
        res = await auth_client.post(f"{API}/battle/difficulty", json={"level": 1})
        assert res.status_code == 400

    async def test_switch_scopes_progress_per_difficulty(self, auth_client, session_factory) -> None:
        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            user = (await db.execute(select(User).where(User.id == me["id"]))).scalar_one()
            user.battle_difficulty_max = 1  # 模拟已在难度 0 通关最后一个地区
            for rid in (1, 2, 3):
                row = (
                    await db.execute(
                        select(RegionProgress).where(
                            RegionProgress.user_id == me["id"],
                            RegionProgress.difficulty == 0,
                            RegionProgress.region_id == rid,
                        )
                    )
                ).scalar_one()
                row.cleared = True
            await db.commit()

        # 难度 1 是全新周目：落回地区 1，地区 2 仍锁定
        res = await auth_client.post(f"{API}/battle/difficulty", json={"level": 1})
        assert res.status_code == 200, res.text
        assert res.json() == {"difficulty": 1, "unlocked": 1, "maxLevel": 15, "currentRegionId": 1}

        listing = (await auth_client.get(f"{API}/region")).json()
        assert listing["difficulty"]["level"] == 1
        by_id = {r["id"]: r for r in listing["regions"]}
        assert by_id[1]["unlocked"] is True and by_id[1]["cleared"] is False
        assert by_id[2]["unlocked"] is False

        # 切回难度 0：保留进度，落在已通关最高地区 +1
        back = await auth_client.post(f"{API}/battle/difficulty", json={"level": 0})
        assert back.status_code == 200
        assert back.json()["currentRegionId"] == 4
        assert (await auth_client.get(f"{API}/game/state")).json()["difficulty"]["level"] == 0

    async def test_reclearing_last_region_unlocks_difficulty(
        self, auth_client, session_factory
    ) -> None:
        """旧存档（第 40 区已通关、firstClear=False）再次击败最后一个地区 BOSS 也应解锁下一难度。"""
        import random

        me = (await auth_client.get(f"{API}/auth/me")).json()
        last = max(CONFIG.region_by_id)
        async with session_factory() as db:
            user = (await db.execute(select(User).where(User.id == me["id"]))).scalar_one()
            hero = (await db.execute(select(Hero).where(Hero.user_id == me["id"]))).scalar_one()
            items = (await db.execute(select(Item).where(Item.user_id == me["id"]))).scalars().all()
            row = (
                await db.execute(
                    select(RegionProgress).where(
                        RegionProgress.user_id == me["id"],
                        RegionProgress.difficulty == 0,
                        RegionProgress.region_id == last,
                    )
                )
            ).scalar_one()
            row.cleared = True  # 模拟功能上线前已通关（不会再触发 firstClear）
            hero.current_region_id = last
            hero.region_kill_count = int(CONFIG.region_by_id[last]["killsRequired"])
            await db.commit()

            payload = BattleReportRequest(sessionId=0, regionId=last, elapsedMs=1000, bossKilled=True)
            result = await _settle_boss(db, user, hero, items, payload, random.Random(1), {}, 5000, 0)
            await db.commit()

        assert result is not None
        assert result["firstClear"] is False
        assert result["unlockedDifficulty"] == 1
        assert (await auth_client.get(f"{API}/game/state")).json()["difficulty"]["unlocked"] == 1

    async def test_stage_board_ranks_difficulty_first(self, auth_client, session_factory) -> None:
        """关卡榜以难度为主序：难度 1 第 20 关排在难度 0 第 40 关之上。"""
        me = (await auth_client.get(f"{API}/auth/me")).json()
        async with session_factory() as db:
            now = datetime.now(timezone.utc)
            row40 = (
                await db.execute(
                    select(RegionProgress).where(
                        RegionProgress.user_id == me["id"],
                        RegionProgress.difficulty == 0,
                        RegionProgress.region_id == 40,
                    )
                )
            ).scalar_one()
            row40.cleared = True
            row40.cleared_at = now
            # 难度 1 只通关到第 20 关
            db.add(
                RegionProgress(
                    user_id=me["id"],
                    difficulty=1,
                    region_id=20,
                    unlocked=True,
                    cleared=True,
                    cleared_at=now,
                )
            )
            await db.commit()
            await refresh_all_rankings(db)
            await db.commit()

        entries = (await auth_client.get(f"{API}/ranking", params={"board": "stage"})).json()["entries"]
        mine = next(e for e in entries if e["userId"] == me["id"])
        # 编码 value = 难度 × 1000 + 地区 → 1×1000+20 > 0×1000+40
        assert mine["value"] == 1 * 1000 + 20
        assert entries == sorted(entries, key=lambda e: e["value"], reverse=True)


async def test_game_state_includes_stat_breakdown(auth_client) -> None:
    """英雄页「面板属性」的「如何计算」依赖 /game/state 的 statBreakdown（与结算同源）。"""
    state = (await auth_client.get(f"{API}/game/state")).json()
    breakdown = state["statBreakdown"]
    stats = state["hero"]["stats"]
    assert breakdown["level"] == state["hero"]["level"]
    assert breakdown["mainAttr"] == stats["mainAttr"]
    # 三维总量 = (英雄自身 + 装备折算) × 均衡型核心加成（coreAttrPct，仅 str/dex/int）。
    core_pct = float((breakdown.get("biasBonus") or {}).get("coreAttrPct", 0.0)) / 100.0
    for attr in ("str", "dex", "int", "vit"):
        scale = 1.0 + core_pct if attr in ("str", "dex", "int") else 1.0
        assert abs(
            breakdown["core"]["total"][attr]
            - (breakdown["core"]["hero"][attr] + breakdown["core"]["equip"][attr]) * scale
        ) < 0.02
    rebuilt_hp = (breakdown["panelBase"]["maxHp"] + breakdown["equipFlat"]["hp"]) * (
        1 + breakdown["termMods"].get("maxHpPct", 0) / 100
    )
    assert abs(rebuilt_hp - stats["maxHp"]) < 0.05

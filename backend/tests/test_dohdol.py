"""生产 / 采集 DLC：共享数据一致性 + 接口集成测试。"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import ActiveConsumable, DohDolProgress, FishRecord, StackItem
from app.services import dohdol_util
from app.services.game_config import CONFIG
from app.services.item_factory import generate_crafted_item


def _backdate(session, seconds: float) -> None:
    """把会话的 last_report_at 往回调，模拟「已经过了一段时间」。"""
    session.last_report_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)


class TestSharedData:
    def test_jobs(self):
        jobs = CONFIG.dohdol_jobs["jobs"]
        assert len(jobs) == 11
        doh = [j for j in jobs if j["kind"] == "doh"]
        dol = [j for j in jobs if j["kind"] == "dol"]
        assert len(doh) == 8
        assert len(dol) == 3
        assert {j["id"] for j in dol} == {"MIN", "BTN", "FSH"}

    def test_materials_and_gather_nodes(self):
        ids = [m["id"] for m in CONFIG.materials["materials"]]
        assert len(ids) == len(set(ids)), "材料 id 必须唯一"
        for node in CONFIG.gather_nodes["nodes"]:
            assert node["regionId"] in CONFIG.region_by_id
            assert CONFIG.dohdol_job_by_id[node["jobId"]]["kind"] == "dol"
            for y in node["yields"]:
                assert y["materialId"] in CONFIG.material_by_id
                assert y["min"] <= y["max"]

    def test_region_material_variety(self):
        """每个地区至少 2 件专属材料，且专属材料跨地区不重复；每地区可采 ≥3 种。"""
        uniques = [m for m in CONFIG.materials["materials"] if m.get("regionId")]
        names = [m["name"] for m in uniques]
        assert len(names) == len(set(names)), "地区专属材料名称不应重复"
        assert len(uniques) == len(CONFIG.region_by_id) * 2

        per_region: dict[int, set[str]] = {}
        for node in CONFIG.gather_nodes["nodes"]:
            bucket = per_region.setdefault(node["regionId"], set())
            for y in node["yields"]:
                bucket.add(y["materialId"])
        for region_id, bucket in per_region.items():
            assert len(bucket) >= 3, f"地区 {region_id} 可采材料不足 3 种"

    def test_recipe_outputs_have_names(self):
        """配方产物名必须解析为中文名，不能回落成 id（如 f_expGainPct）。"""
        for r in CONFIG.recipes["recipes"]:
            out = r["output"]
            key = out.get("itemId") or out.get("baseId")
            assert dohdol_util.material_name(key) != key, f"配方 {r['id']} 产物名未解析：{key}"

    def test_recipes_reference_valid(self):
        for r in CONFIG.recipes["recipes"]:
            assert CONFIG.dohdol_job_by_id[r["jobId"]]["kind"] == "doh"
            assert r["requiredLevel"] >= 1
            for inp in r["inputs"]:
                assert inp["itemId"] in CONFIG.material_by_id
            out = r["output"]
            if out["kind"] == "equipment":
                assert out["baseId"] in CONFIG.base_item_by_id or out["baseId"] in CONFIG.dohdol_item_by_id
            elif out["kind"] == "consumable":
                assert out["itemId"] in CONFIG.consumable_by_id
            else:
                assert out["itemId"] in CONFIG.material_by_id

    def test_dohdol_equipment(self):
        ids = [i["id"] for i in CONFIG.dohdol_equipment["items"]]
        assert len(ids) == len(set(ids))
        for item in CONFIG.dohdol_equipment["items"]:
            assert item["bonus"], "专用装备必须有加成"
            assert item["category"] in {c["id"] for c in CONFIG.dohdol_equipment["categories"]}

    def test_fish(self):
        assert len(CONFIG.fish["regions"]) == 40
        king_names: list[str] = []
        emperor_names: list[str] = []
        for region in CONFIG.fish["regions"]:
            normal_ids = {f["id"] for f in region["normal"]}
            assert region["normal"], "钓场必须有普通鱼"
            for key in ("king", "emperor"):
                assert set(region[key]["prereqFishIds"]).issubset(normal_ids)
                assert region[key]["chance"] > 0
            assert region["emperor"]["chance"] < region["king"]["chance"], "鱼皇概率必须低于鱼王"
            king_names.append(region["king"]["name"])
            emperor_names.append(region["emperor"]["name"])
        # 鱼王 / 鱼皇每个地区各一条，名称互不重复
        assert len(set(king_names)) == 40
        assert len(set(emperor_names)) == 40
        # 鱼名参考 FF14，不应再是「地区名+鱼王」这种拼出来的名字
        for region in CONFIG.fish["regions"]:
            assert not region["king"]["name"].startswith(region["name"])
            assert not region["emperor"]["name"].startswith(region["name"])

    def test_consumables_and_titles(self):
        kinds = {c["kind"] for c in CONFIG.consumables["items"]}
        assert kinds == {"potion", "food"}
        for c in CONFIG.consumables["items"]:
            assert c["effects"]
        assert len(CONFIG.titles["titles"]) == 2


class TestCraftedItem:
    def test_high_quality_combat_equipment(self):
        rng = random.Random(1234)
        item = generate_crafted_item("w_bow_2", rng)
        assert item["highQuality"] is True
        ancients = [t for t in item["terms"] if t.get("quality") == "ancient"]
        assert ancients, "制造装备必带太古词条"

    def test_dohdol_equipment_bonus(self):
        rng = random.Random(99)
        item = generate_crafted_item("dh_dohTool_0", rng)
        assert item["highQuality"] is True
        assert item["category"] == "doh_tool"
        assert item["baseAttrs"]


class TestGatherApi:
    @pytest.mark.asyncio
    async def test_gather_flow(self, auth_client, session_factory):
        resp = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "MIN", "regionId": 1})
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 20)
            await db.commit()

        rep = await auth_client.post("/api/v1/gather/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        data = rep.json()
        assert data["actions"] > 0
        assert data["gained"], "应有采集产出"

    @pytest.mark.asyncio
    async def test_activities_mutually_exclusive(self, auth_client, session_factory):
        resp = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "BTN", "regionId": 1})
        session_id = resp.json()["sessionId"]

        # 开始战斗应结束采集会话
        battle = await auth_client.post("/api/v1/battle/session/start", json={"regionId": 1})
        assert battle.status_code == 200, battle.text

        rep = await auth_client.post("/api/v1/gather/session/report", json={"sessionId": session_id})
        assert rep.status_code == 404

    @pytest.mark.asyncio
    async def test_gather_level_requirement(self, auth_client):
        # 高等级地区（需要较高采集等级）应被拒绝
        resp = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "MIN", "regionId": 40})
        assert resp.status_code == 400


class TestProduceApi:
    @pytest.mark.asyncio
    async def test_produce_material(self, auth_client, session_factory):
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="material", item_id="g_wood", count=9))
            await db.commit()

        resp = await auth_client.post(
            "/api/v1/produce/session/start", json={"jobId": "CRP", "recipeId": "r_h_plank"}
        )
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 20)
            await db.commit()

        rep = await auth_client.post("/api/v1/produce/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        assert rep.json()["crafts"] == 3

        async with session_factory() as db:
            plank = (
                await db.execute(select(StackItem).where(StackItem.item_id == "h_plank"))
            ).scalar_one()
            assert plank.count == 3

    @pytest.mark.asyncio
    async def test_produce_equipment_high_quality(self, auth_client, session_factory):
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            for item_id in ("h_plank", "h_ingot"):
                db.add(StackItem(user_id=user_id, kind="material", item_id=item_id, count=10))
            await db.commit()

        resp = await auth_client.post(
            "/api/v1/produce/session/start", json={"jobId": "CRP", "recipeId": "r_dh_dohTool_0"}
        )
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 20)
            await db.commit()

        rep = await auth_client.post("/api/v1/produce/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        items = rep.json()["items"]
        assert items, "应产出专用装备"
        assert items[0]["highQuality"] is True

        # 专用装备不进战斗装备图鉴
        before = (await auth_client.get("/api/v1/game/state")).json()["codex"]["equipment"]["unlocked"]
        rep2 = await auth_client.post("/api/v1/produce/session/report", json={"sessionId": session_id})
        assert rep2.status_code == 200
        after = (await auth_client.get("/api/v1/game/state")).json()["codex"]["equipment"]["unlocked"]
        assert after == before

    @pytest.mark.asyncio
    async def test_recipe_level_gate(self, auth_client):
        resp = await auth_client.post(
            "/api/v1/produce/session/start", json={"jobId": "CRP", "recipeId": "r_w_bow_2"}
        )
        assert resp.status_code == 400


class TestFishApi:
    @pytest.mark.asyncio
    async def test_fish_flow(self, auth_client, session_factory):
        resp = await auth_client.post("/api/v1/fish/session/start", json={"regionId": 1})
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 60)
            await db.commit()

        rep = await auth_client.post("/api/v1/fish/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        data = rep.json()
        assert data["casts"] > 0
        assert data["caught"], "应有鱼获"

        async with session_factory() as db:
            records = (await db.execute(select(FishRecord))).scalars().all()
            assert records


class TestConsumableApi:
    @pytest.mark.asyncio
    async def test_use_consumable(self, auth_client, session_factory):
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="potion", item_id="p_expGainPct", count=2))
            await db.commit()

        resp = await auth_client.post("/api/v1/consumable/use", json={"itemId": "p_expGainPct"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["kind"] == "potion"

        # 生效中：再次使用同一药水应刷新，而非叠加成两条
        resp2 = await auth_client.post("/api/v1/consumable/use", json={"itemId": "p_expGainPct"})
        assert resp2.status_code == 200
        async with session_factory() as db:
            rows = (await db.execute(select(ActiveConsumable))).scalars().all()
            assert len(rows) == 1


class TestSellApi:
    @pytest.mark.asyncio
    async def test_sell_material(self, auth_client, session_factory):
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="material", item_id="g_ore", count=5))
            await db.commit()

        before = (await auth_client.get("/api/v1/game/state")).json()["user"]["gold"]
        resp = await auth_client.post(
            "/api/v1/dohdol/sell", json={"kind": "material", "itemId": "g_ore", "count": 3}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["goldGained"] == body["unitPrice"] * 3
        assert body["gold"] == before + body["goldGained"]

        async with session_factory() as db:
            row = (await db.execute(select(StackItem).where(StackItem.item_id == "g_ore"))).scalar_one()
            assert row.count == 2

    @pytest.mark.asyncio
    async def test_sell_fish_and_guards(self, auth_client, session_factory):
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="material", item_id="f1_1", count=2))
            await db.commit()

        resp = await auth_client.post(
            "/api/v1/dohdol/sell", json={"kind": "material", "itemId": "f1_1", "count": 1}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["goldGained"] > 0

        # 类型不匹配 / 未知物品 / 数量不足
        bad_kind = await auth_client.post(
            "/api/v1/dohdol/sell", json={"kind": "potion", "itemId": "f1_1", "count": 1}
        )
        assert bad_kind.status_code == 400
        unknown = await auth_client.post(
            "/api/v1/dohdol/sell", json={"kind": "material", "itemId": "nope", "count": 1}
        )
        assert unknown.status_code == 404
        too_many = await auth_client.post(
            "/api/v1/dohdol/sell", json={"kind": "material", "itemId": "f1_1", "count": 99}
        )
        assert too_many.status_code == 400


class TestFishingRanking:
    async def _fish_once(self, auth_client, session_factory):
        start = await auth_client.post("/api/v1/fish/session/start", json={"regionId": 1})
        session_id = start.json()["sessionId"]
        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 60)
            await db.commit()
        await auth_client.post("/api/v1/fish/session/report", json={"sessionId": session_id})

    @pytest.mark.asyncio
    async def test_fishing_boards_are_live_without_refresh(self, auth_client, session_factory):
        """刚钓完就能看到（钓鱼榜实时聚合，不等 5 分钟缓存刷新）。"""
        await self._fish_once(auth_client, session_factory)

        species_board = await auth_client.get("/api/v1/ranking", params={"board": "fish_species"})
        assert species_board.status_code == 200, species_board.text
        entries = species_board.json()["entries"]
        assert entries, "钓鱼种类榜应有记录（且不依赖缓存刷新）"
        assert entries[0]["value"] >= 1

        count_board = await auth_client.get("/api/v1/ranking", params={"board": "fish_count"})
        assert count_board.status_code == 200, count_board.text
        assert count_board.json()["entries"][0]["value"] >= 1

    @pytest.mark.asyncio
    async def test_species_board_breaks_down_by_kind(self, auth_client, session_factory):
        """种类榜要包含普通鱼，并区分普通 / 鱼王 / 鱼皇。"""
        await self._fish_once(auth_client, session_factory)
        await auth_client.post("/api/v1/ranking/refresh", json={})

        board = await auth_client.get("/api/v1/ranking", params={"board": "fish_species"})
        payload = board.json()["entries"][0]["payload"]
        assert payload["fishNormal"] >= 1, "普通鱼种类必须计入种类榜"
        assert payload["fishSpecies"] == payload["fishNormal"] + payload["fishKing"] + payload["fishEmperor"]
        assert payload["fishKing"] >= 0 and payload["fishEmperor"] >= 0

        # 榜单是 5 个缓存榜（含游玩时间）+ 2 个钓鱼榜
        assert board.json()["boards"] == [
            "level", "stage", "power", "gold", "playtime", "fish_species", "fish_count",
        ]

    @pytest.mark.asyncio
    async def test_no_fish_no_fishing_entry(self, auth_client):
        """没钓鱼的玩家不应出现在钓鱼榜上。"""
        await auth_client.post("/api/v1/ranking/refresh", json={})
        board = await auth_client.get("/api/v1/ranking", params={"board": "fish_species"})
        assert board.status_code == 200
        assert board.json()["entries"] == []


class TestActivityCycle:
    @pytest.mark.asyncio
    async def test_cycle_reported_for_progress_bars(self, auth_client):
        # 采集：开始与上报都带 cycle（供前端画进度条）
        start = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "MIN", "regionId": 1})
        assert start.status_code == 200, start.text
        body = start.json()
        assert body["cycle"]["seconds"] > 0
        assert body["cycle"]["credit"] == 0
        assert body["cycle"]["at"] > 0, "cycle.at 用于前端半 RTT 校正"

        rep = await auth_client.post("/api/v1/gather/session/report", json={"sessionId": body["sessionId"]})
        assert rep.status_code == 200, rep.text
        assert rep.json()["cycle"]["seconds"] > 0

        await auth_client.post("/api/v1/gather/session/stop", json={"sessionId": body["sessionId"]})

        # 生产
        pstart = await auth_client.post(
            "/api/v1/produce/session/start", json={"jobId": "CRP", "recipeId": "r_h_plank"}
        )
        assert pstart.status_code == 200, pstart.text
        assert pstart.json()["cycle"]["seconds"] > 0

        # 钓鱼
        fstart = await auth_client.post("/api/v1/fish/session/start", json={"regionId": 1})
        assert fstart.status_code == 200, fstart.text
        assert fstart.json()["cycle"]["seconds"] > 0


class TestDohDolState:
    @pytest.mark.asyncio
    async def test_state_block(self, auth_client):
        resp = await auth_client.get("/api/v1/game/state")
        assert resp.status_code == 200, resp.text
        dohdol = resp.json()["dohdol"]
        assert dohdol["progress"]["doh"]["level"] == 1
        assert dohdol["progress"]["dol"]["level"] == 1
        assert dohdol["recipes"], "应下发配方"
        assert dohdol["fishStats"]["kingTotal"] == 40
        # 配方产物名已解析（不再显示 f_expGainPct 这类 id）
        for r in dohdol["recipes"]:
            key = r["output"]["itemId"] or r["output"]["baseId"]
            assert r["output"]["name"] != key, r["id"]


class TestMaterialAndFishCodex:
    @pytest.mark.asyncio
    async def test_material_codex_unlocks_on_gather(self, auth_client, session_factory):
        before = (await auth_client.get("/api/v1/codex?category=material")).json()
        assert before["progress"]["material"]["unlocked"] == 0
        assert before["progress"]["material"]["total"] > 0

        start = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "MIN", "regionId": 1})
        assert start.status_code == 200, start.text
        session_id = start.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 20)
            await db.commit()

        rep = await auth_client.post("/api/v1/gather/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        gained_ids = {g["itemId"] for g in rep.json()["gained"]}
        assert gained_ids, "应有采集产出"

        body = (await auth_client.get("/api/v1/codex?category=material")).json()
        unlocked = {e["itemId"] for e in body["entries"] if e["unlocked"]}
        assert gained_ids <= unlocked, "采集到的材料应解锁材料图鉴"
        assert body["progress"]["material"]["unlocked"] == len(unlocked)

    @pytest.mark.asyncio
    async def test_fish_codex_unlocks_on_catch(self, auth_client, session_factory):
        start = await auth_client.post("/api/v1/fish/session/start", json={"regionId": 1})
        assert start.status_code == 200, start.text
        session_id = start.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 60)
            await db.commit()

        rep = await auth_client.post("/api/v1/fish/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        caught_ids = {c["id"] for c in rep.json()["caught"]}
        assert caught_ids, "应有鱼获"

        body = (await auth_client.get("/api/v1/codex?category=fish")).json()
        unlocked = {e["fishId"] for e in body["entries"] if e["unlocked"]}
        assert caught_ids <= unlocked, "钓到的鱼应解锁鱼获图鉴"

        # 鱼获单独成册：不应进入材料图鉴
        material = (await auth_client.get("/api/v1/codex?category=material")).json()
        assert caught_ids.isdisjoint({e["itemId"] for e in material["entries"]})

    @pytest.mark.asyncio
    async def test_unknown_codex_category_rejected(self, auth_client):
        resp = await auth_client.get("/api/v1/codex?category=bogus")
        assert resp.status_code == 422

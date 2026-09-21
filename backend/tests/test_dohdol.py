"""生产 / 采集 DLC：共享数据一致性 + 接口集成测试。"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import ActiveConsumable, DohDolProgress, FishRecord, StackItem
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
        for region in CONFIG.fish["regions"]:
            normal_ids = {f["id"] for f in region["normal"]}
            assert region["normal"], "钓场必须有普通鱼"
            for key in ("king", "emperor"):
                assert set(region[key]["prereqFishIds"]).issubset(normal_ids)
                assert region[key]["chance"] > 0
            assert region["emperor"]["chance"] < region["king"]["chance"], "鱼皇概率必须低于鱼王"

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

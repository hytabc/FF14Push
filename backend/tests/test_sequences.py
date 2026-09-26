"""生产 / 采集自定义序列库（保存 / 覆盖 / 读取 / 蓝图ID分享）。"""

from __future__ import annotations

API = "/api/v1"


def _gather(material_id: str = "m_copper_ore", target: int = 10, step_id: str = "step-1") -> dict:
    return {
        "kind": "gather",
        "id": step_id,
        "materialId": material_id,
        "name": "铜矿",
        "jobId": "miner",
        "regionId": 1,
        "target": target,
        "blocked": None,
        "requiredLevel": 1,
    }


def _produce(recipe_id: str = "r_bronze_ingot", target: int = 2, step_id: str = "step-2") -> dict:
    return {
        "kind": "produce",
        "id": step_id,
        "recipeId": recipe_id,
        "name": "青铜锭",
        "jobId": "armorer",
        "target": target,
    }


def _payload(name: str, *, steps: list[dict] | None = None, loop_mode: str = "once", loop_total: int = 3) -> dict:
    return {
        "name": name,
        "steps": steps if steps is not None else [_gather(), _produce()],
        "loopMode": loop_mode,
        "loopTotal": loop_total,
    }


async def _save(client, name: str, **kwargs):
    return await client.post(f"{API}/sequences", json=_payload(name, **kwargs))


async def _register_other(client, username: str) -> str:
    resp = await client.post(
        f"{API}/auth/register",
        json={"username": username, "password": "secret123", "nickname": username},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["accessToken"]


def _use(client, token: str) -> None:
    client.headers.update({"Authorization": f"Bearer {token}"})


class TestSequenceLibrary:
    async def test_requires_auth(self, client):
        assert (await client.get(f"{API}/sequences")).status_code == 401

    async def test_save_and_list(self, auth_client):
        resp = await _save(auth_client, "挖矿流", loop_mode="count", loop_total=4)
        assert resp.status_code == 200, resp.text
        seq = resp.json()["sequence"]
        assert seq["name"] == "挖矿流"
        assert len(seq["shareCode"]) == 8
        assert seq["loopMode"] == "count"
        assert seq["loopTotal"] == 4
        assert seq["stepCount"] == 2
        assert seq["steps"][0]["materialId"] == "m_copper_ore"

        listed = (await auth_client.get(f"{API}/sequences")).json()["sequences"]
        assert [s["name"] for s in listed] == ["挖矿流"]
        assert listed[0]["shareCode"] == seq["shareCode"]

    async def test_only_own_sequences(self, auth_client):
        await _save(auth_client, "我的序列")
        mine = (await auth_client.get(f"{API}/sequences")).json()["sequences"]
        assert [s["name"] for s in mine] == ["我的序列"]

        other = await _register_other(auth_client, "other1")
        _use(auth_client, other)
        assert (await auth_client.get(f"{API}/sequences")).json()["sequences"] == []

    async def test_max_five(self, auth_client):
        for i in range(5):
            assert (await _save(auth_client, f"序列{i}")).status_code == 200
        resp = await _save(auth_client, "序列5")
        assert resp.status_code == 400
        assert "上限" in resp.json()["detail"]
        assert len((await auth_client.get(f"{API}/sequences")).json()["sequences"]) == 5

    async def test_same_name_overwrites(self, auth_client):
        first = (await _save(auth_client, "同名")).json()["sequence"]
        again = await _save(auth_client, "同名", steps=[_gather(target=99, step_id="step-x")])
        assert again.status_code == 200, again.text
        seq = again.json()["sequence"]
        assert seq["id"] == first["id"]
        assert seq["shareCode"] == first["shareCode"]
        assert seq["steps"][0]["target"] == 99

        listed = (await auth_client.get(f"{API}/sequences")).json()["sequences"]
        assert len(listed) == 1

    async def test_overwrite_slot(self, auth_client):
        first = (await _save(auth_client, "槽位")).json()["sequence"]
        resp = await auth_client.post(
            f"{API}/sequences/{first['id']}",
            json={"steps": [_produce(target=7)], "loopMode": "infinite", "loopTotal": 1},
        )
        assert resp.status_code == 200, resp.text
        seq = resp.json()["sequence"]
        assert seq["shareCode"] == first["shareCode"]
        assert seq["loopMode"] == "infinite"
        assert seq["steps"] == [_produce(target=7)]

    async def test_overwrite_rename_conflict(self, auth_client):
        a = (await _save(auth_client, "甲")).json()["sequence"]
        await _save(auth_client, "乙")
        resp = await auth_client.post(
            f"{API}/sequences/{a['id']}",
            json={"steps": [_gather()], "loopMode": "once", "loopTotal": 3, "name": "乙"},
        )
        assert resp.status_code == 400
        assert "已存在" in resp.json()["detail"]

    async def test_ownership_enforced(self, auth_client):
        seq = (await _save(auth_client, "私有")).json()["sequence"]
        other = await _register_other(auth_client, "other2")
        _use(auth_client, other)
        overwrite = await auth_client.post(
            f"{API}/sequences/{seq['id']}",
            json={"steps": [_gather()], "loopMode": "once", "loopTotal": 3},
        )
        assert overwrite.status_code == 404
        assert (await auth_client.delete(f"{API}/sequences/{seq['id']}")).status_code == 404

    async def test_invalid_steps_rejected(self, auth_client):
        bad_kind = _payload("坏")
        bad_kind["steps"] = [{**_gather(), "kind": "fishing"}]
        assert (await auth_client.post(f"{API}/sequences", json=bad_kind)).status_code == 400

        bad_target = _payload("坏")
        bad_target["steps"] = [{**_gather(), "target": 0}]
        assert (await auth_client.post(f"{API}/sequences", json=bad_target)).status_code == 400

        missing_material = _payload("坏")
        step = _gather()
        step.pop("materialId")
        missing_material["steps"] = [step]
        assert (await auth_client.post(f"{API}/sequences", json=missing_material)).status_code == 400

        too_many = _payload("坏")
        too_many["steps"] = [_gather(step_id=f"step-{i}") for i in range(51)]
        assert (await auth_client.post(f"{API}/sequences", json=too_many)).status_code == 422

    async def test_import_by_code_from_other_account(self, auth_client):
        seq = (await _save(auth_client, "分享源", loop_mode="count", loop_total=2)).json()["sequence"]
        code = seq["shareCode"]

        other = await _register_other(auth_client, "other3")
        _use(auth_client, other)
        resp = await auth_client.get(f"{API}/sequences/blueprint/{code.lower()}")
        assert resp.status_code == 200, resp.text
        imported = resp.json()["sequence"]
        assert imported["name"] == "分享源"
        assert imported["loopMode"] == "count"
        assert imported["loopTotal"] == 2
        assert imported["stepCount"] == 2
        # 不暴露来源账号 / 行 id
        assert "id" not in imported
        assert "userId" not in imported

    async def test_import_unknown_code(self, auth_client):
        assert (await auth_client.get(f"{API}/sequences/blueprint/ZZZZZZZZ")).status_code == 404

    async def test_delete_invalidates_blueprint(self, auth_client):
        seq = (await _save(auth_client, "待删")).json()["sequence"]
        assert (await auth_client.delete(f"{API}/sequences/{seq['id']}")).status_code == 200
        assert (
            await auth_client.get(f"{API}/sequences/blueprint/{seq['shareCode']}")
        ).status_code == 404
        assert (await auth_client.get(f"{API}/sequences")).json()["sequences"] == []

"""管理端发放金币补偿：`POST /admin/grant-gold` 与公开的「补偿公示」`GET /grants`。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AdminGrant, User
from app.services.admin import GRANT_MAX_AMOUNT, ensure_admin_user

API = "/api/v1"
ADMIN_USER = "admin"
ADMIN_PASS = "admin-secret-123"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, username: str) -> str:
    resp = await client.post(
        f"{API}/auth/register",
        json={"username": username, "password": "secret123", "nickname": f"昵称-{username}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["accessToken"]


async def _user_id(session_factory, username: str) -> int:
    async with session_factory() as db:
        return int((await db.execute(select(User.id).where(User.username == username))).scalar_one())


async def _gold_of(session_factory, username: str) -> int:
    async with session_factory() as db:
        return int((await db.execute(select(User.gold).where(User.username == username))).scalar_one())


async def _records(session_factory) -> list[AdminGrant]:
    async with session_factory() as db:
        rows = (await db.execute(select(AdminGrant).order_by(AdminGrant.id))).scalars().all()
        return list(rows)


def _grant_payload(user_id: int, amount: int, reason: str = "") -> dict:
    return {"userId": user_id, "amount": amount, "reason": reason}


class TestAdminGrant:
    @pytest.fixture(autouse=True)
    def _admin_env(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USER)
        monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASS)
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    async def _admin_headers(self, client, session_factory) -> dict[str, str]:
        async with session_factory() as db:
            await ensure_admin_user(db)
        # 管理员从「另一台设备」登录：清掉玩家注册留下的设备 Cookie，避免撞上同设备并发上限。
        client.cookies.clear()
        resp = await client.post(
            f"{API}/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
        )
        assert resp.status_code == 200, resp.text
        return _auth(resp.json()["accessToken"])

    async def test_normal_user_is_forbidden(self, auth_client) -> None:
        resp = await auth_client.post(f"{API}/admin/grant-gold", json=_grant_payload(1, 100))
        assert resp.status_code == 403

    async def test_grant_increases_gold_and_is_publicly_listed(self, client, session_factory) -> None:
        await _register(client, "grant_target")
        target_id = await _user_id(session_factory, "grant_target")
        admin = await self._admin_headers(client, session_factory)

        resp = await client.post(
            f"{API}/admin/grant-gold",
            json=_grant_payload(target_id, 12345, "服务器故障补偿"),
            headers=admin,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["gold"] == 12345
        assert await _gold_of(session_factory, "grant_target") == 12345

        # 公示公开：无需登录即可查看，且包含事由（对玩家公开）
        listed = (await client.get(f"{API}/grants")).json()
        assert listed["total"] == 1
        record = listed["records"][0]
        assert record["userId"] == target_id
        assert record["nickname"] == "昵称-grant_target"
        assert record["amount"] == 12345
        assert record["note"] == "服务器故障补偿"
        assert "adminId" not in record

    async def test_repeated_grants_accumulate_and_list_newest_first(self, client, session_factory) -> None:
        await _register(client, "grind")
        target_id = await _user_id(session_factory, "grind")
        admin = await self._admin_headers(client, session_factory)

        for amount in (100, 250):
            resp = await client.post(
                f"{API}/admin/grant-gold", json=_grant_payload(target_id, amount), headers=admin
            )
            assert resp.status_code == 200, resp.text

        assert await _gold_of(session_factory, "grind") == 350
        assert len(await _records(session_factory)) == 2
        listed = (await client.get(f"{API}/grants")).json()
        assert [r["amount"] for r in listed["records"]] == [250, 100]

    async def test_invalid_amount_is_rejected(self, client, session_factory) -> None:
        await _register(client, "amt")
        target_id = await _user_id(session_factory, "amt")
        admin = await self._admin_headers(client, session_factory)

        zero = await client.post(f"{API}/admin/grant-gold", json=_grant_payload(target_id, 0), headers=admin)
        assert zero.status_code == 422
        negative = await client.post(
            f"{API}/admin/grant-gold", json=_grant_payload(target_id, -5), headers=admin
        )
        assert negative.status_code == 422
        over = await client.post(
            f"{API}/admin/grant-gold",
            json=_grant_payload(target_id, GRANT_MAX_AMOUNT + 1),
            headers=admin,
        )
        assert over.status_code == 400
        assert await _gold_of(session_factory, "amt") == 0
        assert await _records(session_factory) == []

    async def test_missing_target_returns_404(self, client, session_factory) -> None:
        admin = await self._admin_headers(client, session_factory)
        resp = await client.post(f"{API}/admin/grant-gold", json=_grant_payload(999999, 100), headers=admin)
        assert resp.status_code == 404

    async def test_admin_target_is_rejected(self, client, session_factory) -> None:
        admin = await self._admin_headers(client, session_factory)
        admin_id = await _user_id(session_factory, ADMIN_USER)
        resp = await client.post(f"{API}/admin/grant-gold", json=_grant_payload(admin_id, 100), headers=admin)
        assert resp.status_code == 400


class TestAdminGrantDisabled:
    async def test_returns_503_when_admin_disabled(self, client, monkeypatch) -> None:
        monkeypatch.delenv("ADMIN_USERNAME", raising=False)
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
        get_settings.cache_clear()
        try:
            token = await _register(client, "nobody")
            resp = await client.post(
                f"{API}/admin/grant-gold", json=_grant_payload(1, 100), headers=_auth(token)
            )
            assert resp.status_code == 503
        finally:
            get_settings.cache_clear()

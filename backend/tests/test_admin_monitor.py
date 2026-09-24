"""管理端在线监控：`GET /admin/online` 的在线列表与「同设备 / 同 IP」关联分组。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import User
from app.models.base import utcnow
from app.services.admin import ensure_admin_user

API = "/api/v1"
ADMIN_USER = "admin"
ADMIN_PASS = "admin-secret-123"
DEV_A = "fp-online1111aaaa"
DEV_B = "fp-online2222bbbb"
REAL_IP = "203.0.113.7"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, username: str, device: str | None = None) -> str:
    headers = {"X-Device-Id": device} if device else None
    if device:
        # 显式指定设备时清空 Cookie，使设备身份只来自请求头（等价于「换设备」）。
        client.cookies.clear()
    resp = await client.post(
        f"{API}/auth/register",
        json={"username": username, "password": "secret123", "nickname": username},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["accessToken"]


async def _heartbeat(client, token: str, device: str | None = None) -> None:
    # 心跳会回写服务端签名的设备 Cookie；共享同一个 httpx 客户端时它会串到下一次请求，
    # 使不同设备的账号被「同设备」关联。这里每次先清空，让设备身份只取显式请求头。
    client.cookies.clear()
    headers = {**_auth(token)}
    if device:
        headers["X-Device-Id"] = device
    resp = await client.get(f"{API}/friends/heartbeat", headers=headers)
    assert resp.status_code == 200, resp.text


async def _patch_user(session_factory, username: str, **fields) -> None:
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one()
        for key, value in fields.items():
            setattr(user, key, value)
        await db.commit()


async def _set_ips(session_factory, username: str, ip: str = REAL_IP) -> None:
    await _patch_user(session_factory, username, reg_ip=ip, last_ip=ip)


async def _offline(session_factory, username: str) -> None:
    await _patch_user(session_factory, username, last_seen_at=utcnow() - timedelta(seconds=60))


def _accounts_of(data: dict) -> list[dict]:
    return [account for group in data["groups"] for account in group["accounts"]]


class TestAdminOnline:
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
        # 管理员从「另一台设备」登录：清掉玩家注册时留下的设备 Cookie，
        # 否则会带着玩家设备身份撞上「同设备并发在线上限」（409）。
        client.cookies.clear()
        resp = await client.post(
            f"{API}/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
        )
        assert resp.status_code == 200, resp.text
        return _auth(resp.json()["accessToken"])

    async def test_normal_user_is_forbidden(self, auth_client) -> None:
        assert (await auth_client.get(f"{API}/admin/online")).status_code == 403

    async def test_same_device_accounts_are_grouped(self, client, session_factory) -> None:
        token_a = await _register(client, "grp_a", DEV_A)
        token_b = await _register(client, "grp_b", DEV_A)
        admin = await self._admin_headers(client, session_factory)
        await _heartbeat(client, token_a, DEV_A)
        await _heartbeat(client, token_b, DEV_A)

        data = (await client.get(f"{API}/admin/online", headers=admin)).json()

        assert data["onlineCount"] == 2
        assert data["windowSeconds"] > 0
        groups = [g for g in data["groups"] if len(g["accounts"]) == 2]
        assert len(groups) == 1, data
        group = groups[0]
        assert group["onlineCount"] == 2
        assert {a["username"] for a in group["accounts"]} == {"grp_a", "grp_b"}
        assert any(d["deviceId"] == DEV_A for d in group["sharedDevices"])
        assert all(a["devices"] for a in group["accounts"])

    async def test_same_ip_accounts_are_grouped(self, client, session_factory) -> None:
        token_a = await _register(client, "ipa")
        token_b = await _register(client, "ipb")
        admin = await self._admin_headers(client, session_factory)
        await _heartbeat(client, token_a)
        await _heartbeat(client, token_b)
        # 心跳会把 last_ip 写成测试客户端哨兵值，真实 IP 在心跳后写入。
        await _set_ips(session_factory, "ipa")
        await _set_ips(session_factory, "ipb")

        data = (await client.get(f"{API}/admin/online", headers=admin)).json()

        group = next(g for g in data["groups"] if len(g["accounts"]) == 2)
        assert data["onlineCount"] == 2
        assert group["sharedDevices"] == []
        assert any(s["ip"] == REAL_IP for s in group["sharedIps"])
        assert {a["username"] for a in group["accounts"]} == {"ipa", "ipb"}

    async def test_unlinked_accounts_are_separate(self, client, session_factory) -> None:
        token_a = await _register(client, "solo_a", DEV_A)
        token_b = await _register(client, "solo_b", DEV_B)
        admin = await self._admin_headers(client, session_factory)
        await _heartbeat(client, token_a, DEV_A)
        await _heartbeat(client, token_b, DEV_B)

        data = (await client.get(f"{API}/admin/online", headers=admin)).json()

        assert data["onlineCount"] == 2
        assert len(data["groups"]) == 2
        assert all(len(g["accounts"]) == 1 for g in data["groups"])
        assert all(not g["sharedDevices"] and not g["sharedIps"] for g in data["groups"])

    async def test_stale_heartbeat_is_offline(self, client, session_factory) -> None:
        token = await _register(client, "stale", DEV_A)
        admin = await self._admin_headers(client, session_factory)
        await _heartbeat(client, token, DEV_A)

        await _offline(session_factory, "stale")

        data = (await client.get(f"{API}/admin/online", headers=admin)).json()
        assert data["onlineCount"] == 0
        assert data["groups"] == []

    async def test_offline_linked_account_stays_grouped(self, client, session_factory) -> None:
        token_a = await _register(client, "mix_a", DEV_A)
        token_b = await _register(client, "mix_b", DEV_A)
        admin = await self._admin_headers(client, session_factory)
        await _heartbeat(client, token_a, DEV_A)
        await _heartbeat(client, token_b, DEV_A)

        await _offline(session_factory, "mix_b")

        data = (await client.get(f"{API}/admin/online", headers=admin)).json()
        assert data["onlineCount"] == 1
        assert len(data["groups"]) == 1
        group = data["groups"][0]
        assert group["onlineCount"] == 1
        by_name = {a["username"]: a for a in group["accounts"]}
        assert by_name["mix_a"]["online"] is True
        assert by_name["mix_b"]["online"] is False
        # 在线账号排在被关联的离线账号之前。
        assert group["accounts"][0]["username"] == "mix_a"
        assert any(d["deviceId"] == DEV_A for d in group["sharedDevices"])


class TestAdminOnlineDisabled:
    async def test_returns_503_when_admin_disabled(self, client, monkeypatch) -> None:
        monkeypatch.delenv("ADMIN_USERNAME", raising=False)
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
        get_settings.cache_clear()
        try:
            token = await _register(client, "nobody")
            resp = await client.get(f"{API}/admin/online", headers=_auth(token))
            assert resp.status_code == 503
        finally:
            get_settings.cache_clear()

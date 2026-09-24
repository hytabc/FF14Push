"""多账号硬限制：同账号单端登录、同设备并发在线上限、注册收紧（IP / 设备 Cookie）。

对应实现：core/security.py（会话纪元）、core/deps.py（拦截）、services/devices.py（并发动线与关联判定）、
api/v1/auth.py 与 api/v1/friends.py（登记与拦截入口）。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import User, UserDevice
from app.models.base import utcnow
from app.services import devices

API = "/api/v1"
DEV_A = "fp-aaaabbbbccccdddd"
DEV_B = "fp-eeeeffff00001111"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, username: str, device: str | None = None, keep_cookie: bool = False):
    headers = {"X-Device-Id": device} if device else None
    if device and not keep_cookie:
        # 显式指定设备时清空 Cookie，使本请求设备身份即请求头（等价「换一台设备」）。
        client.cookies.clear()
    return await client.post(
        f"{API}/auth/register",
        json={"username": username, "password": "secret123", "nickname": username},
        headers=headers,
    )


async def _login(client, username: str, device: str | None = None):
    headers = {"X-Device-Id": device} if device else None
    return await client.post(
        f"{API}/auth/login", json={"username": username, "password": "secret123"}, headers=headers
    )


async def _user_id(session_factory, username: str) -> int:
    async with session_factory() as db:
        return int((await db.execute(select(User.id).where(User.username == username))).scalar_one())


# ------------------------------------------------------------------ 单端登录
async def test_single_session_replaces_old_token(client) -> None:
    """登录推进会话纪元：旧令牌被顶替（401 session_replaced），新令牌可用。"""
    reg = await _register(client, "sess_a")
    assert reg.status_code == 201, reg.text
    old_token = reg.json()["accessToken"]

    ok = await client.get(f"{API}/auth/me", headers=_auth(old_token))
    assert ok.status_code == 200, ok.text

    relogin = await _login(client, "sess_a")
    assert relogin.status_code == 200, relogin.text
    new_token = relogin.json()["accessToken"]

    stale = await client.get(f"{API}/auth/me", headers=_auth(old_token))
    assert stale.status_code == 401
    assert stale.json()["detail"] == {"code": "session_replaced"}

    fresh = await client.get(f"{API}/auth/me", headers=_auth(new_token))
    assert fresh.status_code == 200, fresh.text


async def test_logout_invalidates_token(client) -> None:
    """登出推进会话纪元 → 当前令牌立即失效。"""
    reg = await _register(client, "sess_out")
    token = reg.json()["accessToken"]

    out = await client.post(f"{API}/auth/logout", headers=_auth(token))
    assert out.status_code == 200, out.text

    after = await client.get(f"{API}/auth/me", headers=_auth(token))
    assert after.status_code == 401


# ------------------------------------------------------------------ 同设备并发在线
async def test_online_device_limit_blocks_extra_account(client) -> None:
    """同一设备并发在线超限：后到（上线更晚）的账号被暂停写请求，先到者不受影响。"""
    cap = devices.max_online_per_device()
    if cap <= 0:
        return  # 该限制被关闭时不适用

    a = await _register(client, "on_a", DEV_A)
    b = await _register(client, "on_b", DEV_A)
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
    token_a, token_b = a.json()["accessToken"], b.json()["accessToken"]

    # 两个账号都在同一设备上线：a 先注册（上线更早）→ 占住名额，b 被暂停。
    hb_a = await client.get(f"{API}/friends/heartbeat", headers=_auth(token_a))
    hb_b = await client.get(f"{API}/friends/heartbeat", headers=_auth(token_b))
    assert hb_a.json()["blocked"] is False
    assert hb_b.json()["blocked"] is True

    # b 的写请求被拒（409 device_limit）；a 的写请求正常。
    blocked = await client.post(
        f"{API}/battle/session/start", json={"regionId": 1}, headers=_auth(token_b)
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == {"code": "device_limit"}

    allowed = await client.post(
        f"{API}/battle/session/start", json={"regionId": 1}, headers=_auth(token_a)
    )
    assert allowed.status_code == 200, allowed.text


async def test_online_device_limit_recovers_after_incumbent_offline(
    client, session_factory
) -> None:
    """先到者离线后，被暂停的账号在下次心跳自动恢复。"""
    cap = devices.max_online_per_device()
    if cap <= 0:
        return

    a = await _register(client, "rec_a", DEV_A)
    b = await _register(client, "rec_b", DEV_A)
    token_a, token_b = a.json()["accessToken"], b.json()["accessToken"]
    await client.get(f"{API}/friends/heartbeat", headers=_auth(token_a))
    hb_b = await client.get(f"{API}/friends/heartbeat", headers=_auth(token_b))
    assert hb_b.json()["blocked"] is True

    # 模拟 a 长时间未心跳（离线）：把其设备记录的在线时间推到窗口外。
    id_a = await _user_id(session_factory, "rec_a")
    stale = utcnow() - timedelta(minutes=10)
    async with session_factory() as db:
        rows = (
            await db.execute(select(UserDevice).where(UserDevice.user_id == id_a))
        ).scalars().all()
        for row in rows:
            row.last_seen_at = stale
            row.online_since = stale
        await db.commit()

    recovered = await client.get(f"{API}/friends/heartbeat", headers=_auth(token_b))
    assert recovered.json()["blocked"] is False
    ok = await client.post(
        f"{API}/battle/session/start", json={"regionId": 1}, headers=_auth(token_b)
    )
    assert ok.status_code == 200, ok.text


# ------------------------------------------------------------------ 注册收紧
async def test_device_cookie_blocks_fingerprint_change(client) -> None:
    """服务端设备 Cookie 与指纹取并集：清 localStorage 换新指纹仍受同一设备上限约束。"""
    cap = devices.max_accounts_per_device()
    for i in range(cap):
        resp = await _register(client, f"ck_user_{i}", DEV_A)
        assert resp.status_code == 201, resp.text

    # 换一个全新的 X-Device-Id（等价于清 localStorage），但浏览器仍带服务端设备 Cookie。
    bypass = await _register(client, "ck_user_bypass", DEV_B, keep_cookie=True)
    assert bypass.status_code == 400
    assert "设备" in bypass.json()["detail"]


async def test_register_ip_cap(client, monkeypatch) -> None:
    """同一真实 IP 的注册上限（默认 5）生效。"""
    # 测试客户端默认来自 127.0.0.1（哨兵 IP，不启用该限制）：这里注入一个真实 IP，
    # 并把上限压到 2，避免触发「同一 IP 每小时 5 次」的频率限流。
    monkeypatch.setattr("app.api.v1.auth.client_ip", lambda request: "203.0.113.9")
    monkeypatch.setattr(devices, "max_accounts_per_ip", lambda: 2)

    for i in range(2):
        resp = await _register(client, f"ip_user_{i}", f"fp-ip{i:016d}")
        assert resp.status_code == 201, resp.text

    blocked = await _register(client, "ip_user_extra", "fp-ip0000000000000999")
    assert blocked.status_code == 400
    assert "同一网络" in blocked.json()["detail"]


async def test_register_ip_cap_disabled_for_sentinel_ip(client, monkeypatch) -> None:
    """哨兵 IP（本地回环 / testclient）不启用 IP 上限。"""
    monkeypatch.setattr(devices, "max_accounts_per_ip", lambda: 1)
    for i in range(3):
        resp = await _register(client, f"noip_{i}", f"fp-noip{i:016d}")
        assert resp.status_code == 201, resp.text

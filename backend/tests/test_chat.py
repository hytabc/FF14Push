"""聊天室：单一大厅实名文本聊天、管理员公告、滚动窗口（不保留记录）、限频与票据。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import ChatMessage, ChatTicket, User
from app.models.base import utcnow
from app.services import chat
from app.services.admin import ensure_admin_user

API = "/api/v1"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, username: str, nickname: str) -> str:
    resp = await client.post(
        f"{API}/auth/register",
        json={"username": username, "password": "secret123", "nickname": nickname},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["accessToken"]


async def _user_id(session_factory, username: str) -> int:
    async with session_factory() as db:
        return int((await db.execute(select(User.id).where(User.username == username))).scalar_one())


async def test_requires_login(client) -> None:
    assert (await client.get(f"{API}/chat/messages")).status_code == 401
    assert (await client.post(f"{API}/chat/messages", json={"text": "hi"})).status_code == 401
    assert (await client.post(f"{API}/chat/ticket")).status_code == 401


async def test_send_and_read(client) -> None:
    token = await _register(client, "alice", "爱丽丝")
    resp = await client.post(
        f"{API}/chat/messages", json={"text": "  你好，艾欧泽亚  "}, headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    msg = resp.json()["message"]
    assert msg["text"] == "你好，艾欧泽亚"  # 去空白后存储
    assert msg["kind"] == "normal"
    assert msg["nickname"] == "爱丽丝" and msg["username"] == "alice"
    assert msg["isAdmin"] is False and msg["createdAt"]

    listing = (await client.get(f"{API}/chat/messages", headers=_auth(token))).json()
    assert [m["id"] for m in listing["messages"]] == [msg["id"]]


async def test_text_validation(client) -> None:
    token = await _register(client, "bob", "鲍勃")
    blank = await client.post(f"{API}/chat/messages", json={"text": "   "}, headers=_auth(token))
    assert blank.status_code == 422
    long = await client.post(f"{API}/chat/messages", json={"text": "x" * 201}, headers=_auth(token))
    assert long.status_code == 422


async def test_rate_limit_blocks_21st(client) -> None:
    token = await _register(client, "carol", "卡罗尔")
    for i in range(20):
        resp = await client.post(
            f"{API}/chat/messages", json={"text": f"第 {i} 条"}, headers=_auth(token)
        )
        assert resp.status_code == 200, resp.text
    blocked = await client.post(f"{API}/chat/messages", json={"text": "刷屏"}, headers=_auth(token))
    assert blocked.status_code == 429
    assert "频繁" in blocked.json()["detail"]


async def test_retention_window_hides_and_purges(client, session_factory) -> None:
    token = await _register(client, "dave", "戴夫")
    uid = await _user_id(session_factory, "dave")
    async with session_factory() as db:
        db.add(
            ChatMessage(
                user_id=uid,
                kind="normal",
                text="远古消息",
                created_at=utcnow() - timedelta(seconds=chat.RETENTION_SECONDS + 100),
            )
        )
        await db.commit()

    # 窗口外的历史永不返回
    listing = (await client.get(f"{API}/chat/messages", headers=_auth(token))).json()
    assert listing["messages"] == []

    # 发言时清理过期行
    fresh = await client.post(f"{API}/chat/messages", json={"text": "新消息"}, headers=_auth(token))
    assert fresh.status_code == 200
    async with session_factory() as db:
        texts = (await db.execute(select(ChatMessage.text))).scalars().all()
    assert "远古消息" not in texts and "新消息" in texts


async def test_ticket_is_one_time_and_expires(client, session_factory) -> None:
    token = await _register(client, "erin", "艾琳")
    uid = await _user_id(session_factory, "erin")
    ticket = (await client.post(f"{API}/chat/ticket", headers=_auth(token))).json()["ticket"]
    assert ticket

    async with session_factory() as db:
        assert await chat.consume_ticket(db, ticket) == uid
        assert await chat.consume_ticket(db, ticket) is None  # 一次性

    async with session_factory() as db:
        db.add(ChatTicket(token="expired", user_id=uid, expires_at=0))
        await db.commit()
    async with session_factory() as db:
        assert await chat.consume_ticket(db, "expired") is None


async def test_banned_user_cannot_send(client, session_factory) -> None:
    token = await _register(client, "frank", "弗兰克")
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.username == "frank"))).scalar_one()
        user.banned = True
        await db.commit()
    resp = await client.post(f"{API}/chat/messages", json={"text": "hi"}, headers=_auth(token))
    assert resp.status_code == 403


class TestAnnounce:
    ADMIN_USER = "admin"
    ADMIN_PASS = "admin-secret-123"

    @pytest.fixture(autouse=True)
    def _admin_env(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USERNAME", self.ADMIN_USER)
        monkeypatch.setenv("ADMIN_PASSWORD", self.ADMIN_PASS)
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    async def _admin_token(self, client, session_factory) -> str:
        async with session_factory() as db:
            await ensure_admin_user(db)
        resp = await client.post(
            f"{API}/auth/login", json={"username": self.ADMIN_USER, "password": self.ADMIN_PASS}
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["accessToken"]

    async def test_normal_user_cannot_announce(self, client) -> None:
        token = await _register(client, "grace", "格蕾丝")
        resp = await client.post(
            f"{API}/chat/announce", json={"text": "假公告"}, headers=_auth(token)
        )
        assert resp.status_code == 403

    async def test_admin_announce_is_exempt_from_chat_rate_limit(self, client, session_factory) -> None:
        token = await self._admin_token(client, session_factory)
        for i in range(20):
            resp = await client.post(
                f"{API}/chat/messages", json={"text": f"管理员 {i}"}, headers=_auth(token)
            )
            assert resp.status_code == 200, resp.text
        assert (
            await client.post(f"{API}/chat/messages", json={"text": "超限"}, headers=_auth(token))
        ).status_code == 429

        announced = await client.post(
            f"{API}/chat/announce", json={"text": "全服公告：维护通知"}, headers=_auth(token)
        )
        assert announced.status_code == 200, announced.text
        msg = announced.json()["message"]
        assert msg["kind"] == "announcement" and msg["isAdmin"] is True

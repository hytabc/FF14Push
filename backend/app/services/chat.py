"""聊天室业务：单一大厅的滚动消息与 WebSocket 一次性票据。

「不保留聊天记录」的实现口径：
- 普通发言的读取都以 `created_at >= now - RETENTION_SECONDS` 过滤，窗口外的历史永不返回；
- 发言时顺带删除窗口外的**普通发言**行，表因此只保有滚动暂存量级。
- **管理员公告是例外**：公告长期保留（置顶展示、不会消失），不参与滚动窗口的读取与清理，
  单独以 `announcements()` 查询返回。
广播不做进程内队列：WS 连接各自按游标轮询数据库，天然兼容多 worker（与 `coop.py` 一致）。
"""

from __future__ import annotations

import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KIND_ANNOUNCEMENT, KIND_NORMAL, ChatMessage, ChatTicket, User
from app.models.base import utcnow
from app.services.admin import is_admin

# 只保留最近 10 分钟的消息（「不保留聊天记录」）。
RETENTION_SECONDS = 600
# 单次读取 / 推送的消息条数上限（防止窗口内极端刷屏）。
MAX_MESSAGES = 200
# 单条消息长度上限，需与 `schemas/game.ChatSendRequest` 保持一致。
MAX_TEXT_LEN = 200
# WebSocket 票据有效期（秒）。
TICKET_TTL_SECONDS = 30
# WS 轮询新消息的间隔（秒）。
POLL_SECONDS = 1.0

_WHITESPACE = re.compile(r"\s+")


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite 下 DateTime(timezone=True) 会返回 naive datetime，统一补上 UTC。"""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def clean_text(raw: str) -> str:
    """归一化发言：去不可见字符、折叠空白，校验非空与长度。"""
    text = "".join(ch for ch in raw if ch.isprintable())
    text = _WHITESPACE.sub(" ", text).strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="消息不能为空")
    if len(text) > MAX_TEXT_LEN:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"消息过长（最多 {MAX_TEXT_LEN} 字）",
        )
    return text


def serialize(row: ChatMessage, user: User) -> dict:
    admin = is_admin(user)
    return {
        "id": row.id,
        "kind": row.kind,
        "text": row.text,
        "createdAt": _as_utc(row.created_at).isoformat(),
        "userId": row.user_id,
        "nickname": user.nickname,
        # 管理员不回显登录账号：不公开其账号名，也不随消息下发给客户端。
        "username": "" if admin else user.username,
        "isAdmin": admin,
    }


def _cutoff(now: datetime) -> datetime:
    return now - timedelta(seconds=RETENTION_SECONDS)


def _query(after_id: int | None, cutoff: datetime, newest_first: bool):
    """滚动窗口内的**普通发言**（公告由 `announcement_query` 单独处理）。"""
    stmt = (
        select(ChatMessage, User)
        .join(User, User.id == ChatMessage.user_id)
        .where(ChatMessage.kind == KIND_NORMAL)
        .where(ChatMessage.created_at >= cutoff)
        .order_by(ChatMessage.id.desc() if newest_first else ChatMessage.id)
        .limit(MAX_MESSAGES)
    )
    if after_id is not None:
        stmt = stmt.where(ChatMessage.id > after_id)
    return stmt


def _announcement_query(after_id: int | None, newest_first: bool):
    """管理员公告：不受滚动窗口限制，长期保留。"""
    stmt = (
        select(ChatMessage, User)
        .join(User, User.id == ChatMessage.user_id)
        .where(ChatMessage.kind == KIND_ANNOUNCEMENT)
        .order_by(ChatMessage.id.desc() if newest_first else ChatMessage.id)
    )
    if after_id is not None:
        stmt = stmt.where(ChatMessage.id > after_id)
    return stmt


async def recent_messages(db: AsyncSession) -> list[dict]:
    """窗口内最近的普通发言（按时间正序，供首屏加载）。"""
    rows = (await db.execute(_query(None, _cutoff(utcnow()), newest_first=True))).all()
    return [serialize(row, user) for row, user in reversed(rows)]


async def new_messages(db: AsyncSession, after_id: int) -> list[dict]:
    """比游标更新的普通发言（按时间正序，供 WS 增量推送）。"""
    rows = (await db.execute(_query(after_id, _cutoff(utcnow()), newest_first=False))).all()
    return [serialize(row, user) for row, user in rows]


async def announcements(db: AsyncSession) -> list[dict]:
    """全部管理员公告（按时间倒序，最新在前，供置顶展示）。"""
    rows = (await db.execute(_announcement_query(None, newest_first=True))).all()
    return [serialize(row, user) for row, user in rows]


async def new_announcements(db: AsyncSession, after_id: int) -> list[dict]:
    """比游标更新的公告（按时间正序，供 WS 增量推送）。"""
    rows = (await db.execute(_announcement_query(after_id, newest_first=False))).all()
    return [serialize(row, user) for row, user in rows]


async def post_message(
    db: AsyncSession, user: User, text: str, kind: str = KIND_NORMAL
) -> dict:
    """发言：归一化文本、写入、顺带清理窗口外的过期普通发言（公告长期保留）。"""
    now = utcnow()
    row = ChatMessage(user_id=user.id, kind=kind, text=clean_text(text), created_at=now)
    db.add(row)
    await db.execute(
        delete(ChatMessage)
        .where(ChatMessage.kind == KIND_NORMAL)
        .where(ChatMessage.created_at < _cutoff(now))
    )
    await db.commit()
    return serialize(row, user)


async def issue_ticket(db: AsyncSession, user: User) -> str:
    """签发 WebSocket 一次性票据。"""
    now = time.time()
    await db.execute(delete(ChatTicket).where(ChatTicket.expires_at < now))
    token = secrets.token_urlsafe(32)
    db.add(ChatTicket(token=token, user_id=user.id, expires_at=now + TICKET_TTL_SECONDS))
    await db.commit()
    return token


async def consume_ticket(db: AsyncSession, token: str) -> int | None:
    """核销票据：一次性，过期或不存在返回 None。"""
    row = await db.scalar(select(ChatTicket).where(ChatTicket.token == token).with_for_update())
    if row is None or row.expires_at < time.time():
        return None
    user_id = row.user_id
    await db.delete(row)
    await db.commit()
    return user_id

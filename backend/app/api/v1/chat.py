"""聊天室接口：单一大厅文本聊天（实名 `昵称#账号`）、管理员公告与 WebSocket 推送。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.v1.admin import AdminUser
from app.core.database import SessionLocal
from app.core.deps import CurrentUser, DbSession, guard_rate
from app.models import KIND_ANNOUNCEMENT, KIND_NORMAL, User
from app.models.base import utcnow
from app.schemas.game import ChatSendRequest
from app.services import chat
from app.services.broadcast import MEMBER_CHECK_SECONDS, Producer, hub

router = APIRouter(prefix="/chat", tags=["chat"])

# 聊天室广播通道名：所有连接共享同一个轮询生产者的增量结果。
CHAT_CHANNEL = "chat"


def _chat_producer_factory() -> Producer:
    """创建一个带游标的聊天室广播生产者（每个进程的该通道只创建一次）。"""
    cursor: list[int] = []

    async def producer() -> dict | None:
        async with SessionLocal() as db:
            if not cursor:
                # 首帧：把游标推到当前最新，避免把窗口内历史当成新增重复推送。
                msg_id, ann_id = await chat.cursors(db)
                cursor.extend([msg_id, ann_id])
                return None
            messages, anns, msg_id, ann_id = await chat.broadcast_delta(db, cursor[0], cursor[1])
        cursor[0], cursor[1] = msg_id, ann_id
        if not messages and not anns:
            return None
        return {"type": "update", "messages": messages, "announcements": anns}

    return producer


async def _active(user_id: int) -> bool:
    """低频校验连接所属账号仍有效（封号即断开）。"""
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        return user is not None and not user.banned


@router.get("/messages")
async def messages(db: DbSession, user: CurrentUser) -> dict:
    """大厅最近消息（滚动窗口内）与置顶公告，供首屏加载与 WS 断线回退。"""
    return {
        "messages": await chat.recent_messages(db),
        "announcements": await chat.announcements(db),
        "serverTime": utcnow().isoformat(),
    }


@router.post("/messages")
async def send(payload: ChatSendRequest, db: DbSession, user: CurrentUser) -> dict:
    """大厅发言：滑动窗口限频（20 条 / 60 秒）防刷屏。"""
    await guard_rate(db, "chat_send", str(user.id), 20, 60, "发言过于频繁，请稍后再试")
    return {"message": await chat.post_message(db, user, payload.text, KIND_NORMAL)}


@router.post("/announce")
async def announce(payload: ChatSendRequest, db: DbSession, user: User = AdminUser) -> dict:
    """管理员公告：不受大厅发言限频约束。"""
    return {"message": await chat.post_message(db, user, payload.text, KIND_ANNOUNCEMENT)}


@router.post("/ticket")
async def ticket(db: DbSession, user: CurrentUser) -> dict:
    """签发 WebSocket 一次性票据（WS 无法携带 Authorization 头）。"""
    await guard_rate(db, "chat_ticket", str(user.id), 30, 60, "请求过于频繁，请稍后再试")
    return {"ticket": await chat.issue_ticket(db, user)}


@router.websocket("/ws")
async def stream(ws: WebSocket) -> None:
    token = ws.query_params.get("ticket", "")
    async with SessionLocal() as db:
        user_id = await chat.consume_ticket(db, token)
        if user_id is None:
            await ws.close(code=4401)
            return
        user = await db.get(User, user_id)
        if user is None or user.banned:
            await ws.close(code=4403)
            return

    await ws.accept()
    # 先订阅再回放历史：此后发布的增量要么已在历史中（按 id 去重），要么进队列，不会漏帧。
    queue = await hub.subscribe(CHAT_CHANNEL, _chat_producer_factory, chat.POLL_SECONDS)
    try:
        async with SessionLocal() as db:
            history = await chat.recent_messages(db)
            pinned = await chat.announcements(db)
        await ws.send_json({"type": "history", "messages": history, "announcements": pinned})

        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=MEMBER_CHECK_SECONDS)
            except asyncio.TimeoutError:
                # 低频封号检查（原实现每个轮询周期都查一次）。
                if not await _active(user_id):
                    await ws.close(code=4403)
                    return
                continue
            await ws.send_json(payload)
    except (WebSocketDisconnect, RuntimeError):
        return
    finally:
        await hub.unsubscribe(CHAT_CHANNEL, queue)

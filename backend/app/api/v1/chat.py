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

router = APIRouter(prefix="/chat", tags=["chat"])


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
    try:
        # 首帧回放滚动窗口内的历史与置顶公告，随后按游标增量推送（与 coop 的快照 / 更新同构）。
        async with SessionLocal() as db:
            history = await chat.recent_messages(db)
            pinned = await chat.announcements(db)
        last_id = history[-1]["id"] if history else 0
        last_ann_id = max((a["id"] for a in pinned), default=0)
        await ws.send_json(
            {"type": "history", "messages": history, "announcements": pinned}
        )

        while True:
            async with SessionLocal() as db:
                user = await db.get(User, user_id)
                if user is None or user.banned:
                    await ws.close(code=4403)
                    return
                fresh = await chat.new_messages(db, last_id)
                fresh_ann = await chat.new_announcements(db, last_ann_id)
            if fresh:
                last_id = fresh[-1]["id"]
            if fresh_ann:
                last_ann_id = fresh_ann[-1]["id"]
            if fresh or fresh_ann:
                await ws.send_json(
                    {"type": "update", "messages": fresh, "announcements": fresh_ann}
                )
            await asyncio.sleep(chat.POLL_SECONDS)
    except (WebSocketDisconnect, RuntimeError):
        return

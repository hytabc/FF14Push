"""WS 广播：共享通道向多个订阅者分发同一份产出 + 聊天室增量游标。

不建立真实 WebSocket 连接（httpx 测试客户端不支持的场景），而是直接验证
`services/broadcast` 的分发语义与 `services/chat` 的游标推进——这两处是 C3 改造的核心。
"""

from __future__ import annotations

import asyncio

from app.services import chat
from app.services.broadcast import BroadcastHub

API = "/api/v1"


async def test_hub_fans_out_one_poll_to_all_subscribers() -> None:
    """每个 channel 只跑一个生产者，同一次产出要分发给该通道的全部订阅者。"""
    hub = BroadcastHub()
    counter = {"n": 0}

    def factory():
        async def producer():
            counter["n"] += 1
            return {"n": counter["n"]}

        return producer

    q1 = await hub.subscribe("t", factory, 0.01)
    q2 = await hub.subscribe("t", factory, 0.01)

    # 收集两端收到的序号，直到出现「同一个序号被两个订阅者都拿到」。
    seen: dict[int, int] = {}
    for _ in range(50):
        for queue in (q1, q2):
            try:
                payload = queue.get_nowait()
            except asyncio.QueueEmpty:
                continue
            seen[payload["n"]] = seen.get(payload["n"], 0) + 1
        if any(count >= 2 for count in seen.values()):
            break
        await asyncio.sleep(0.02)

    assert any(count >= 2 for count in seen.values()), "同一次产出应分发给两个订阅者"
    # 生产者是共享的：产出序号数不超过轮询次数，且远少于「连接数 × 轮询次数」。
    assert counter["n"] >= 1

    await hub.unsubscribe("t", q1)
    await hub.unsubscribe("t", q2)
    await hub.shutdown()


async def test_hub_recycles_channel_after_last_subscriber_leaves() -> None:
    """最后一个订阅者离开后通道被回收：重新订阅会得到新的生产者（游标重置）。"""
    hub = BroadcastHub()
    starts = {"n": 0}

    def factory():
        starts["n"] += 1
        value = {"n": 0}

        async def producer():
            value["n"] += 1
            return {"start": starts["n"], "n": value["n"]}

        return producer

    q1 = await hub.subscribe("t", factory, 0.01)
    await asyncio.wait_for(q1.get(), timeout=1)
    await hub.unsubscribe("t", q1)
    assert starts["n"] == 1

    q2 = await hub.subscribe("t", factory, 0.01)
    payload = await asyncio.wait_for(q2.get(), timeout=1)
    assert starts["n"] == 2, "通道回收后应创建新的生产者"
    assert payload["n"] == 1, "新生产者的游标应从零开始"
    await hub.unsubscribe("t", q2)
    await hub.shutdown()


async def test_chat_broadcast_delta_advances_cursors(client, session_factory) -> None:
    """聊天室增量：游标前的历史不算新增，新发言只返回一次。"""
    reg = await client.post(
        f"{API}/auth/register",
        json={"username": "caster", "password": "secret123", "nickname": "caster"},
    )
    token = reg.json()["accessToken"]

    async with session_factory() as db:
        msg_id, ann_id = await chat.cursors(db)

    sent = await client.post(
        f"{API}/chat/messages", json={"text": "hello"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert sent.status_code == 200, sent.text

    async with session_factory() as db:
        messages, anns, next_msg, next_ann = await chat.broadcast_delta(db, msg_id, ann_id)
    assert [m["text"] for m in messages] == ["hello"]
    assert anns == []
    assert next_msg > msg_id
    assert next_ann == ann_id

    # 同一游标再读一次：无新增（不会重复推送）。
    async with session_factory() as db:
        again, anns_again, same_msg, same_ann = await chat.broadcast_delta(db, next_msg, next_ann)
    assert again == [] and anns_again == []
    assert same_msg == next_msg and same_ann == next_ann

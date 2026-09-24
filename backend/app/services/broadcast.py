"""WebSocket 广播：每进程一次轮询 + 内存分发。

原实现是「每个连接各自按游标轮询数据库」，DB 查询量随连接数线性增长
（聊天室约 3 查询 / 连接 / 秒）。这里改为：每个 channel 一个后台任务，按固定间隔
**读一次**数据库，再把结果投递到各订阅者的队列；连接侧只需 drain 队列。

多 worker 仍然安全：每个进程各自轮询数据库（与「各连接按游标轮询」语义等价），
只是把 **O(连接数)** 的查询量降为 **O(进程数)**；分发是幂等的，不引入跨进程状态。

用法（连接侧）：
    queue = await hub.subscribe(name, factory, interval)
    try:
        ...  # 首帧可自行取一次完整快照，随后消费 queue
    finally:
        await hub.unsubscribe(name, queue)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("eorzea.broadcast")

# 单个订阅者的队列上限：满则丢弃（慢连接不拖累其他连接，也不阻塞生产者）。
QUEUE_SIZE = 32

Producer = Callable[[], Awaitable[Any]]
ProducerFactory = Callable[[], Producer]


class _Channel:
    """一个广播通道：共享的生产者任务 + 若干订阅队列。"""

    def __init__(self, name: str, producer: Producer, interval: float) -> None:
        self.name = name
        self.producer = producer
        self.interval = interval
        self.subscribers: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None

    async def run(self) -> None:
        while True:
            try:
                payload = await self.producer()
                if payload is not None:
                    self.publish(payload)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("广播通道 %s 生产失败", self.name)
            await asyncio.sleep(self.interval)

    def publish(self, payload: Any) -> None:
        for queue in list(self.subscribers):
            if queue.full():
                continue
            queue.put_nowait(payload)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    @property
    def has_subscribers(self) -> bool:
        return bool(self.subscribers)


class BroadcastHub:
    """按 channel 名维护共享轮询任务；最后一个订阅者离开后停止并回收该通道。"""

    def __init__(self) -> None:
        self._channels: dict[str, _Channel] = {}
        self._lock = asyncio.Lock()

    async def subscribe(
        self, name: str, factory: ProducerFactory, interval: float
    ) -> asyncio.Queue:
        async with self._lock:
            channel = self._channels.get(name)
            if channel is None:
                # factory 只在该通道首次建立时调用一次：生产者的游标等状态随之创建。
                channel = _Channel(name, factory(), interval)
                self._channels[name] = channel
            queue = channel.subscribe()
            if channel.task is None or channel.task.done():
                channel.task = asyncio.create_task(channel.run())
            return queue

    async def unsubscribe(self, name: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            channel = self._channels.get(name)
            if channel is None:
                return
            channel.unsubscribe(queue)
            if channel.has_subscribers:
                return
            task = channel.task
            self._channels.pop(name, None)
            channel.task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def shutdown(self) -> None:
        """应用关闭时停止所有通道任务。"""
        async with self._lock:
            tasks = [c.task for c in self._channels.values() if c.task is not None]
            self._channels.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


hub = BroadcastHub()

# 低频封号 / 账号有效性检查间隔（秒）：原实现每轮询都查一次，这里降为每 10s 一次。
MEMBER_CHECK_SECONDS = 10.0

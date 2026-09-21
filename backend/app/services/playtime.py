"""累计在线时长。

只由各活动的**服务端**结算窗口累加：战斗用校验后的上报窗口，采集 / 生产 / 钓鱼用
`window_seconds`（自身已封顶），副本用会话时长（再封顶一次）。客户端时间不可信，
且本作不做离线收益，因此离开页面的时间不会计入。
"""

from __future__ import annotations

from typing import Any

# 单次副本上报最多计入的时长（毫秒）：副本会话可能被长时间挂着，避免把挂机算成游玩。
MAX_RAID_PLAY_MS = 30 * 60 * 1000


def add_play_ms(user: Any, ms: int) -> None:
    value = int(ms)
    if value <= 0:
        return
    user.play_ms = int(user.play_ms or 0) + value

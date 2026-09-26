"""死者宫殿：逐节点服务端校验。

照 `raid_balance` 的范式：进入战斗节点时冻结快照（理论击杀时长 × 容差），结算时复算
「服务端时长是否低于下限 / 客户端上报是否超前于服务端时钟」。

说明：与高难副本不同，死者宫殿**入场免费**，因此不把「输出 / 防御门槛」当作拒绝条件
（那会把合法通关误判为失败并可能软锁 run）；门槛只写入快照供运营侧观察。真正的防作弊是
「时长下限 + 只信服务端时钟 + 面板与敌人数值全由服务端下发」。
"""

from __future__ import annotations

from typing import Any

from app.services.combat_model import theoretical_dps
from app.services.stats import HeroStats

# 时长下限的绝对地板：必须低于合法最快（客户端一次出手最快约 0.75s），避免误伤强练度玩家。
MIN_FIGHT_MS = 800
# 理论时长只是期望值，实战有暴击 / 直击 / 技能方差，容差要留足。
DURATION_TOLERANCE = 1.6
# 客户端上报时长允许超出服务端窗口的余量（网络抖动）。
CLOCK_TOLERANCE_MS = 4000


def snapshot(stats: HeroStats, enemy: dict[str, Any]) -> dict[str, Any]:
    kind = str(enemy.get("kind", "normal"))
    dps = max(1.0, theoretical_dps(stats, float(enemy.get("defense", 0.0)), None, kind))
    kill_seconds = float(enemy["hp"]) / dps
    incoming = max(1.0, float(enemy.get("attack", 0.0)) * 0.1) / max(0.1, float(enemy.get("attackInterval", 3.0)))
    survival_seconds = float(stats.max_hp) / incoming
    return {
        "minimumFightMs": max(MIN_FIGHT_MS, int(kill_seconds * 1000 * DURATION_TOLERANCE)),
        "clockToleranceMs": CLOCK_TOLERANCE_MS,
        "outputPassed": kill_seconds <= 30.0,
        "defensePassed": survival_seconds >= 8.0,
    }


def clear_failures(start: dict[str, Any] | None, server_ms: int, fight_ms: int) -> list[str]:
    if not start:
        return ["missing_snapshot"]
    failures: list[str] = []
    if server_ms < int(start.get("minimumFightMs", 0)):
        failures.append("invalid_duration")
    if fight_ms > server_ms + int(start.get("clockToleranceMs", CLOCK_TOLERANCE_MS)):
        failures.append("invalid_duration")
    return sorted(set(failures))

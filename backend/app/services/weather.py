"""天气与艾欧泽亚时间（ET）：服务端时间的纯函数，无后台任务、无持久化。

- 天气：按地区权重表、以 `weather.weatherPeriodSec` 为「时段桶」，用 hash(bucket, regionId)
  确定性选取。同一时刻、同一地区，任何客户端算出的结果都一致。
- 时间：艾欧泽亚时间，1 ET 日 = `weather.eorzea.dayRealSeconds` 现实秒（默认 70 分钟）。
  用于「只在深夜 / 白昼出现的鱼」这类门槛。

前端 `frontend/src/game/weather.ts` 用同一套 32 位整型哈希镜像本模块，故可做天气预报；
服务端结算始终以本模块为准。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.services.game_config import CONFIG

_MASK = 0xFFFFFFFF


def _now(now: datetime | None = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _cfg() -> dict[str, Any]:
    return CONFIG.weather


def weather_period_sec() -> int:
    return int(_cfg()["weatherPeriodSec"])


def weather_type(weather_id: str) -> dict[str, Any] | None:
    return next((t for t in _cfg()["types"] if t["id"] == weather_id), None)


def weather_name(weather_id: str) -> str:
    spec = weather_type(weather_id)
    return spec["name"] if spec else weather_id


def _region_weights(region_id: int) -> dict[str, int]:
    for region in _cfg()["regions"]:
        if int(region["regionId"]) == int(region_id):
            return {k: int(v) for k, v in region["weights"].items()}
    return {}


def hash01(bucket: int, region_id: int) -> float:
    """32 位整型混合器 → [0,1)。与前端 `weather.ts::hash01` 逐位一致。"""
    x = (int(bucket) * 0x9E3779B1) & _MASK
    x = (x ^ ((int(region_id) * 0x85EBCA77) & _MASK)) & _MASK
    x = ((x ^ (x >> 16)) * 0x7FEB352D) & _MASK
    x = ((x ^ (x >> 15)) * 0x846CA68B) & _MASK
    x = (x ^ (x >> 16)) & _MASK
    return x / 0x100000000


def weather_for(region_id: int, now: datetime | None = None) -> str:
    """该地区当前天气 id。无权重表时回落到 clear。"""
    weights = _region_weights(region_id)
    if not weights:
        return "clear"
    period = weather_period_sec()
    bucket = int(_now(now).timestamp()) // period
    total = sum(weights.values())
    roll = hash01(bucket, region_id) * total
    cumulative = 0.0
    last = next(iter(weights))
    for weather_id, weight in weights.items():
        cumulative += weight
        last = weather_id
        if roll < cumulative:
            return weather_id
    return last


def et_seconds(now: datetime | None = None) -> float:
    """当前 ET 时刻在一天内的秒数（0 ≤ s < 86400）。"""
    day = float(_cfg()["eorzea"]["dayRealSeconds"])
    epoch = int(_now(now).timestamp())
    return (epoch % day) / day * 86400.0


def et_hour(now: datetime | None = None) -> int:
    return int(et_seconds(now) // 3600) % 24


def et_clock(now: datetime | None = None) -> str:
    total = et_seconds(now)
    return f"{int(total // 3600) % 24:02d}:{int((total % 3600) // 60):02d}"


def time_of_day(now: datetime | None = None) -> str:
    """拂晓 / 白昼 / 黄昏 / 深夜 之一（窗口跨零点时按环处理）。"""
    hour = et_hour(now)
    windows = _cfg()["timeOfDay"]
    for name, span in windows.items():
        start, end = int(span[0]), int(span[1])
        if start <= end:
            if start <= hour <= end:
                return name
        elif hour >= start or hour <= end:
            return name
    return "day"


def time_of_day_name(name: str) -> str:
    return _cfg().get("timeOfDayNames", {}).get(name, name)


def conditions_for(region_id: int, now: datetime | None = None) -> dict[str, Any]:
    """结算 / 展示用的当前环境条件。"""
    moment = _now(now)
    weather_id = weather_for(region_id, moment)
    tod = time_of_day(moment)
    return {
        "weather": weather_id,
        "weatherName": weather_name(weather_id),
        "weatherHex": (weather_type(weather_id) or {}).get("hex", "#9aa4b2"),
        "etHour": et_hour(moment),
        "etClock": et_clock(moment),
        "timeOfDay": tod,
        "timeOfDayName": time_of_day_name(tod),
    }


def seconds_until_weather_change(now: datetime | None = None) -> int:
    """距离下一次天气时段切换的剩余秒数。"""
    period = weather_period_sec()
    return period - (int(_now(now).timestamp()) % period)


def gate_matches(
    conditions: dict[str, Any],
    weather_ids: Iterable[str] | None,
    time_of_day_ids: Iterable[str] | None,
) -> bool:
    """天气 / 时间门槛判定：未声明即不限制；声明了则必须命中其一。"""
    if weather_ids:
        allowed = list(weather_ids)
        if allowed and conditions.get("weather") not in allowed:
            return False
    if time_of_day_ids:
        allowed = list(time_of_day_ids)
        if allowed and conditions.get("timeOfDay") not in allowed:
            return False
    return True

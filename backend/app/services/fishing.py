"""钓鱼（捕鱼人）：后台自动抛竿，服务端权威结算。

机制：
- 每个钓场有普通鱼（白 / 蓝 / 紫三档）与特殊鱼（鱼王 king / 鱼皇 emperor / 困难鱼 legend）。
- 普通鱼按权重随机；可声明天气 / 时间门槛，未命中门槛时不会出现。
- 特殊鱼统一由 `intuition`（捕鱼人之识）驱动：**每种直觉只绑定一条鱼**，
  钓齐 `requires`（计数型前置，需在当前天气/时段窗口内累计）后开启该鱼的 BUFF，
  **BUFF 期间不刷新、不延长**，到期后必须重新钓齐前置才可再次触发。
- 旧 40 区鱼王 / 鱼皇（`legacy`）沿用同一模型，但其直觉名称与数值保持不变。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivitySession, AutoSellSetting, DohDolProgress, FishRecord, Item, User
from app.services import consumables, dohdol_util, ishgard, titles, weather
from app.services.game_config import CONFIG
from app.services.gathering import cleared_max_region, progress_level
from app.services.playtime import add_play_ms

MAX_CASTS_PER_REPORT = 200

# 多特殊鱼同时可钓时，按稀有度优先判定（困难鱼 > 鱼皇 > 鱼王）。
_SPECIAL_PRIORITY = {"legend": 0, "emperor": 1, "king": 2}


async def _progress(db: AsyncSession, user_id: int) -> DohDolProgress:
    row = (
        await db.execute(
            select(DohDolProgress).where(
                DohDolProgress.user_id == user_id, DohDolProgress.kind == "dol"
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DohDolProgress(user_id=user_id, kind="dol", level=1, exp=0)
        db.add(row)
        await db.flush()
    return row


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def start_fish(db: AsyncSession, user: User, items: Sequence[Item], region_id: int) -> dict[str, Any]:
    if region_id not in CONFIG.fish_region_by_id:
        raise ValueError("该地区没有钓场")
    if region_id > await cleared_max_region(db, user.id) + 1:
        raise ValueError("该地区尚未解锁")
    level = await progress_level(db, user.id, "dol")
    if level < int(CONFIG.fish_region_by_id[region_id]["levelReq"]):
        raise ValueError(
            f"采集等级不足，需要采集等级 {CONFIG.fish_region_by_id[region_id]['levelReq']}"
        )

    await dohdol_util.end_active_sessions(db, user.id)
    await dohdol_util.end_other_battle_sessions(db, user.id)
    now = datetime.now(timezone.utc)
    session = ActivitySession(
        started_at=now, last_report_at=now,
        user_id=user.id, kind="fish", job_id="FSH", region_id=region_id, active=True,
        credit=0.0, session_fish={}, session_insights={}, session_intuition={},
    )
    db.add(session)
    await db.flush()
    speed = (await ishgard.bonus_with_purple(db, user.id, items)).get("gatherSpeedPct", 0.0)
    return {
        "sessionId": session.id,
        "regionId": region_id,
        "conditions": weather.conditions_for(region_id, now),
        "cycle": dohdol_util.cycle_info(dohdol_util.fish_seconds_per_cast(speed), 0.0, now),
    }


# ---------------------------------------------------------------- 会话状态（JSON）
def _load_counts(session: ActivitySession) -> dict[str, int]:
    """本会话鱼获计数。兼容旧格式（id 列表）。"""
    raw = session.session_fish
    if isinstance(raw, dict):
        return {str(k): int(v) for k, v in raw.items()}
    if isinstance(raw, list):
        out: dict[str, int] = {}
        for fish_id in raw:
            out[str(fish_id)] = out.get(str(fish_id), 0) + 1
        return out
    return {}


def _load_insights(session: ActivitySession, now: datetime) -> dict[str, datetime]:
    """仍生效的「捕鱼人之识」（specialId → 到期时间）；顺带丢弃已过期项。"""
    raw = session.session_insights
    out: dict[str, datetime] = {}
    if not isinstance(raw, dict):
        return out
    for special_id, iso in raw.items():
        try:
            expiry = _aware(datetime.fromisoformat(str(iso)))
        except ValueError:
            continue
        if expiry is not None and expiry > now:
            out[str(special_id)] = expiry
    return out


def _load_intuition(session: ActivitySession) -> dict[str, dict[str, int]]:
    raw = session.session_intuition
    out: dict[str, dict[str, int]] = {}
    if not isinstance(raw, dict):
        return out
    for special_id, prog in raw.items():
        if isinstance(prog, dict):
            out[str(special_id)] = {str(k): int(v) for k, v in prog.items()}
    return out


# ---------------------------------------------------------------- 抽取
def _pick_normal(region: dict[str, Any], conditions: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """从满足天气/时间门槛的普通鱼中按权重抽取。全被门槛排除时回落到全部普通鱼。"""
    pool = [
        f for f in region["normal"]
        if weather.gate_matches(conditions, f.get("weather"), f.get("timeOfDay"))
    ]
    if not pool:
        pool = region["normal"]
    total = sum(max(0.0, float(f.get("weight", 1.0))) for f in pool)
    if total <= 0:
        return pool[-1]
    roll = rng.random() * total
    cumulative = 0.0
    for fish in pool:
        cumulative += max(0.0, float(fish.get("weight", 1.0)))
        if roll < cumulative:
            return fish
    return pool[-1]


def _special_candidates(
    region: dict[str, Any],
    conditions: dict[str, Any],
    insights: dict[str, datetime],
    now: datetime,
) -> list[tuple[dict[str, Any], float]]:
    """当前可钓的特殊鱼（门槛命中 + 直觉生效），按稀有度降序。"""
    out: list[tuple[dict[str, Any], float]] = []
    for special in region["specials"]:
        if not weather.gate_matches(conditions, special.get("weather"), special.get("timeOfDay")):
            continue
        intuition = special.get("intuition")
        if intuition is not None:
            expiry = insights.get(special["id"])
            if expiry is None or expiry <= now:
                continue
            chance = float(intuition["chance"])
        else:
            chance = float(special.get("chance", 0.0))
        out.append((special, chance))
    out.sort(key=lambda pair: _SPECIAL_PRIORITY.get(pair[0]["kind"], 9))
    return out


def _resolve_catch(
    region: dict[str, Any],
    conditions: dict[str, Any],
    insights: dict[str, datetime],
    chance_pct: float,
    rng: random.Random,
    now: datetime,
) -> tuple[dict[str, Any], str]:
    """先按稀有度顺序判定特殊鱼（首个命中者胜出），都未命中则抽一条普通鱼。"""
    factor = 1.0 + max(0.0, chance_pct) / 100.0
    for special, chance in _special_candidates(region, conditions, insights, now):
        if rng.random() < chance * factor:
            return special, special["kind"]
    return _pick_normal(region, conditions, rng), "normal"


def _advance_intuition(
    region: dict[str, Any],
    conditions: dict[str, Any],
    caught_id: str,
    count: int,
    insights: dict[str, datetime],
    intuition: dict[str, dict[str, int]],
    insight_pct: float,
    rng: random.Random,
    now: datetime,
) -> None:
    """更新直觉前置进度，并在前置齐备且未激活时开启 BUFF（不刷新）。"""
    for special in region["specials"]:
        spec = special.get("intuition")
        if spec is None:
            continue
        # 不在天气/时间窗口内：既不计前置也不触发（对应「需在特定天气内钓起」）。
        if not weather.gate_matches(conditions, special.get("weather"), special.get("timeOfDay")):
            continue
        special_id = special["id"]
        expiry = insights.get(special_id)
        if expiry is not None and expiry > now:
            continue  # 已激活：绝不刷新，也不重复计数

        requires = {str(r["fishId"]): int(r["count"]) for r in spec["requires"]}
        if caught_id in requires:
            progress = intuition.setdefault(special_id, {})
            progress[caught_id] = progress.get(caught_id, 0) + int(count)
        progress = intuition.get(special_id, {})
        if all(progress.get(fish_id, 0) >= need for fish_id, need in requires.items()):
            low, high = spec["durationSec"]
            duration = rng.uniform(float(low), float(high)) * (1.0 + max(0.0, insight_pct) / 100.0)
            insights[special_id] = now + timedelta(seconds=duration)
            intuition[special_id] = {}  # 触发即消耗前置：到期后须重新钓齐


async def _fish_records_map(db: AsyncSession, user_id: int) -> dict[str, FishRecord]:
    """一次取回该账号的全部鱼获记录（fish_id → 行）。

    上报窗口内可能连续钓起多条鱼，逐次 select 会形成 N+1；循环内直接改内存对象。
    """
    rows = (
        await db.execute(select(FishRecord).where(FishRecord.user_id == user_id))
    ).scalars().all()
    return {str(row.fish_id): row for row in rows}


def _record_fish(
    db: AsyncSession,
    records: dict[str, FishRecord],
    user_id: int,
    fish_id: str,
    region_id: int,
    kind: str,
    size: int,
) -> None:
    row = records.get(str(fish_id))
    if row is None:
        row = FishRecord(
            user_id=user_id, fish_id=fish_id, region_id=region_id, kind=kind, count=1, max_size=size
        )
        db.add(row)
        records[str(fish_id)] = row
        return
    row.count = int(row.count) + 1
    row.max_size = max(int(row.max_size), size)


async def report_fish(
    db: AsyncSession, user: User, items: Sequence[Item], session: ActivitySession
) -> dict[str, Any]:
    region = CONFIG.fish_region_by_id.get(int(session.region_id or 0))
    if region is None:
        raise ValueError("钓场不存在")

    progress = await _progress(db, user.id)
    now = datetime.now(timezone.utc)
    window = dohdol_util.window_seconds(session.last_report_at, now)
    add_play_ms(user, int(window * 1000))

    # 天气/时间在一次上报窗口内视为恒定（窗口上限见 dohdol-levels.json）。
    conditions = weather.conditions_for(region["regionId"], now)

    equip = await ishgard.bonus_with_purple(db, user.id, items)
    potion = await consumables.fish_bonus(db, user.id)
    insight_pct = equip.get("fishInsightPct", 0.0) + potion.get("fishInsightPct", 0.0)
    chance_pct = equip.get("fishChancePct", 0.0) + potion.get("fishChancePct", 0.0)

    cast_seconds = dohdol_util.fish_seconds_per_cast(equip.get("gatherSpeedPct", 0.0))
    total = float(session.credit) + window
    casts = min(int(total // cast_seconds), MAX_CASTS_PER_REPORT)
    session.credit = total - int(total // cast_seconds) * cast_seconds
    session.last_report_at = now
    session.total_actions = int(session.total_actions) + casts

    rng = random.Random()
    counts = _load_counts(session)
    insights = _load_insights(session, now)
    intuition = _load_intuition(session)
    special_by_id = {s["id"]: s for s in region["specials"]}
    records = await _fish_records_map(db, user.id)

    caught: list[dict[str, Any]] = []
    gained: dict[str, int] = {}
    double_catch_pct = equip.get("fishDoubleCatchPct", 0.0)

    # 自动卖鱼：命中档位的鱼不入库，直接按系统回收价结算金币；鱼获记录 / 统计照常写。
    auto_row = (
        await db.execute(select(AutoSellSetting).where(AutoSellSetting.user_id == user.id))
    ).scalar_one_or_none()
    auto_kinds = set(auto_row.fish_kinds or []) if auto_row and auto_row.fish_enabled else set()
    auto_sold: list[dict[str, Any]] = []
    auto_index: dict[str, dict[str, Any]] = {}
    auto_gold = 0

    for _ in range(casts):
        pick, kind = _resolve_catch(region, conditions, insights, chance_pct, rng, now)

        # 「双钩」增加鱼获数量；「脱钩」有概率本次没有收获。
        catch_count = 1
        if double_catch_pct > 0 and rng.random() * 100 < double_catch_pct:
            catch_count = 2
        elif double_catch_pct < 0 and rng.random() * 100 < -double_catch_pct:
            catch_count = 0
        if catch_count == 0:
            continue

        size = rng.randint(int(pick["sizeMin"]), int(pick["sizeMax"]))
        _record_fish(db, records, user.id, pick["id"], int(session.region_id), kind, size)
        counts[pick["id"]] = counts.get(pick["id"], 0) + catch_count
        rarity = pick.get("rarity") if kind == "normal" else None
        for _ in range(catch_count):
            caught.append({
                "id": pick["id"], "name": pick["name"], "kind": kind,
                "rarity": rarity, "size": size, "exp": pick["exp"],
            })

        unit_price = dohdol_util.sell_price(dohdol_util.STACK_MATERIAL, pick["id"])
        if kind in auto_kinds and unit_price > 0:
            auto_gold += unit_price * catch_count
            entry = auto_index.get(pick["id"])
            if entry is None:
                entry = {
                    "itemId": pick["id"], "name": pick["name"], "kind": kind,
                    "count": 0, "unitPrice": unit_price, "total": 0,
                }
                auto_index[pick["id"]] = entry
                auto_sold.append(entry)
            entry["count"] += catch_count
            entry["total"] += unit_price * catch_count
        else:
            gained[pick["id"]] = gained.get(pick["id"], 0) + catch_count

        # 前置进度 / 直觉触发（无论本次钓到的是普通鱼还是特殊鱼，都可能作为他人的前置）。
        _advance_intuition(
            region, conditions, pick["id"], catch_count,
            insights, intuition, insight_pct, rng, now,
        )

    # 批量入库（含材料图鉴解锁）：一次查询 + 内存累加，避免每次抛竿各发一次 select。
    await dohdol_util.stack_add_many(db, user.id, dohdol_util.STACK_MATERIAL, gained)

    # 自动卖鱼金币结算：命中档位的鱼未入库，直接换成金币。
    if auto_gold:
        user.gold = int(user.gold) + auto_gold

    session.session_fish = counts
    session.session_insights = {sid: expiry.isoformat() for sid, expiry in insights.items()}
    session.session_intuition = intuition

    # 经验来源：专用装备（固定加成 + 经验词条）与药水 / 食物的经验加成。
    xp_sources, bonus_pct = dohdol_util.combine_xp_sources(
        dohdol_util.equipped_bonus_sources(items, "gatherXpPct"),
        await consumables.effect_sources(db, user.id, "expGainPct"),
    )
    base_xp = sum(int(c["exp"]) for c in caught)
    xp = round(base_xp * (1.0 + bonus_pct / 100.0))
    level_info = dohdol_util.apply_level_exp(progress, xp)

    new_titles = await titles.evaluate_titles(db, user.id)

    active_insights = [
        {
            "fishId": special_id,
            "name": special_by_id.get(special_id, {}).get("name", special_id),
            "kind": special_by_id.get(special_id, {}).get("kind", "legend"),
            "buffName": (special_by_id.get(special_id, {}).get("intuition") or {}).get(
                "name", CONFIG.fish.get("insightBuffName", "捕鱼人之识")
            ),
            "remainingSec": max(0, int((expiry - now).total_seconds())),
            "expiresAt": expiry.isoformat(),
        }
        for special_id, expiry in sorted(insights.items(), key=lambda kv: kv[1])
        if expiry > now
    ]

    return {
        "caught": caught,
        "gained": [
            {"itemId": m, "name": dohdol_util.material_name(m), "count": c}
            for m, c in sorted(gained.items())
        ],
        "casts": casts,
        "xp": xp,
        "xpBreakdown": dohdol_util.xp_breakdown(base_xp, 1.0, bonus_pct, xp, xp_sources),
        "level": level_info,
        "conditions": conditions,
        "insights": active_insights,
        "autoSold": auto_sold,
        "autoGold": auto_gold,
        "newTitles": new_titles,
        "cycle": dohdol_util.cycle_info(cast_seconds, float(session.credit), now),
    }


async def stop_fish(db: AsyncSession, session: ActivitySession) -> None:
    session.active = False
    session.ended_at = datetime.now(timezone.utc)

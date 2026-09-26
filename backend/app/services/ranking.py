"""排行榜。来源：PRD 排行榜 2.2 / 2.3 / 2.4

- 等级 / 关卡 / 战力 / 金币：每 5 分钟由后台任务刷新到 `rankings` 缓存表。
- 钓鱼种类 / 钓鱼数量：**实时**从 `fish_records` 聚合（数据量小、且刚钓完就该看到），
  不依赖缓存，避免「刚钓完却看不到自己」。
- 生产/采集经验 / 生产/采集属性：同样**实时**聚合（`dohdol_progress` 累计经验 +
  已装备专用装备的展示属性之和），刚制造/采集完即可见。
- 远征榜：**实时**聚合 `coop_records`（按副本取各账号最快通关时长），刚通关即可见。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import and_, delete, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import (
    DohDolProgress,
    FishRecord,
    Hero,
    Item,
    RankingEntry,
    RegionProgress,
    User,
)
from app.models.multiplayer import CoopRecord
from app.services.admin import is_admin
from app.services.locks import release_advisory_lock, try_advisory_lock
from app.services.materia import socket_mods_map
from app.services.stats import compute_stats
from app.services.valuation import hero_power, raise_max_power

# 走缓存刷新（每 5 分钟）的榜单
CACHED_BOARDS = ("level", "stage", "power", "gold", "playtime")
# 实时聚合的钓鱼榜单
FISH_BOARDS = ("fish_species", "fish_count")
# 实时聚合的生产/采集榜（累计经验 + 已装备专用装备属性总值）
DOHDOL_BOARDS = ("doh_exp", "dol_exp", "doh_attr", "dol_attr")
# 实时聚合的远征榜（按副本取各账号最快通关记录）
COOP_BOARDS = ("coop",)
# 对外暴露的全部榜单
BOARDS = CACHED_BOARDS + FISH_BOARDS + DOHDOL_BOARDS + COOP_BOARDS

# 关卡榜：value = 难度 × STAGE_REGION_BASE + 地区（地区上限 40 < base）。
# 这样既保留「value 降序」的既有排序，又让难度成为主序：难度 1-20 关排在难度 0-40 关之上。
STAGE_REGION_BASE = 1000

# 全量刷新时的用户批大小：峰值内存与批大小成正比，而不是与全库规模成正比（小内存服务器关键）。
REFRESH_USER_CHUNK = 500


# ---------------------------------------------------------------- 实时榜底层聚合的短 TTL 缓存
#
# 实时榜（钓鱼 / 生活 / 远征）每次请求都要做一次全表聚合，且「榜单页」与「我的排名」
# 原先是**各算一遍**。这里缓存底层聚合结果：
#   - 同一请求内的两次调用自然合并为一次；
#   - 跨请求在 TTL 内复用（默认 10s，见 settings.ranking_live_cache_seconds）。
# 写入侧（钓鱼 / 采集 / 生产 / 远征通关）调用 `invalidate_live_rankings()` 立即失效，
# 因此「刚钓完看不到自己」不会发生。缓存键数量有界（fish / dohdol / coop:<副本>）。
_LIVE_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def invalidate_live_rankings() -> None:
    """实时榜底层数据变更后调用：清空进程内缓存，下一次读取即为最新。"""
    _LIVE_CACHE.clear()


def _live_cached(key: str) -> list[dict[str, Any]] | None:
    entry = _LIVE_CACHE.get(key)
    if entry is None:
        return None
    stamp, rows = entry
    ttl = float(get_settings().ranking_live_cache_seconds)
    if ttl <= 0 or time.monotonic() - stamp >= ttl:
        return None
    # 返回浅拷贝：调用方会就地排序，不能污染缓存里的顺序。
    return list(rows)


def _live_store(key: str, rows: list[dict[str, Any]]) -> None:
    if float(get_settings().ranking_live_cache_seconds) <= 0:
        return
    _LIVE_CACHE[key] = (time.monotonic(), rows)


async def refresh_all_rankings(db: AsyncSession) -> dict[str, int]:
    """全量重算缓存榜（level / stage / power / gold / playtime）。

    多 worker 场景下由 advisory lock 保证只有一个进程真正执行（见 services/locks.py）；
    未拿到锁时直接返回 0 计数，调用方无需区分。
    """
    if not await try_advisory_lock(db, "eorzea:ranking_refresh"):
        return {board: 0 for board in CACHED_BOARDS}
    try:
        return await _refresh_all_rankings(db)
    finally:
        await release_advisory_lock(db, "eorzea:ranking_refresh")


async def _refresh_all_rankings(db: AsyncSession) -> dict[str, int]:
    """全量重算缓存榜（分批进行，峰值内存有界）。

    小内存服务器上的两条关键约束：

    1. **不把全库装备读进内存**：面板属性只依赖「已装备」的装备——`stats.aggregate_equipment`
       对 `equipped_slot is None` 的装备直接跳过，`stats.hero_items` 也只会保留
       `equipped_hero_id in (None, hero.id)` 的行。因此数据源改为「只取已装备装备」，
       结论与旧实现逐位相同（数量级 = 账号数 × 席位 × 11，而非全库装备）。
    2. **按批处理用户并逐批写入**：全程仍在同一个事务里（调用方 commit），但每批 `flush()`
       释放待写缓冲，峰值内存与 `REFRESH_USER_CHUNK` 成正比而非与用户总数成正比。
    """
    await db.execute(delete(RankingEntry))

    # 通关进度：只取已通关行（旧实现也只使用 cleared 为真的行）。
    progress_rows = (
        await db.execute(select(RegionProgress).where(RegionProgress.cleared.is_(True)))
    ).scalars().all()
    cleared: dict[int, list[RegionProgress]] = {}
    for row in progress_rows:
        cleared.setdefault(row.user_id, []).append(row)

    user_ids = [
        int(uid) for uid in (await db.execute(select(User.id).order_by(User.id))).scalars().all()
    ]

    counts = {board: 0 for board in CACHED_BOARDS}
    for start in range(0, len(user_ids), REFRESH_USER_CHUNK):
        chunk_ids = user_ids[start : start + REFRESH_USER_CHUNK]
        chunk_users = (
            await db.execute(
                select(User).options(selectinload(User.hero)).where(User.id.in_(chunk_ids))
            )
        ).scalars().all()
        # 本批「已装备」装备，按账号分组（不含背包装备；后者对面板无贡献）。
        chunk_items = (
            await db.execute(
                select(Item).where(
                    Item.equipped_slot.is_not(None), Item.user_id.in_(chunk_ids)
                )
            )
        ).scalars().all()
        items_by_user: dict[int, list[Item]] = {}
        for item in chunk_items:
            items_by_user.setdefault(int(item.user_id), []).append(item)

        mods_map = await socket_mods_map(db, chunk_ids)
        rows_to_insert: list[dict[str, Any]] = []
        for user in chunk_users:
            # 管理员与已封禁账号不参与排行榜（管理员另有「不创建英雄」双重保险）
            if is_admin(user) or user.banned:
                continue
            hero = user.hero
            if hero is None:
                continue

            # 与 stats.hero_items 同义：本人账号级装备（equipped_hero_id 为空）+ 该英雄的装备。
            items = [
                item
                for item in items_by_user.get(int(user.id), [])
                if getattr(item, "equipped_hero_id", None) in (None, hero.id)
            ]
            stats = compute_stats(hero, items, mods_map.get(int(user.id)))
            cleared_list = cleared.get(user.id, [])
            # 关卡榜以「难度优先」为主序：取最高难度，再取该难度下已通关的最大地区。
            best = max(cleared_list, key=lambda row: (row.difficulty, row.region_id), default=None)
            stage_value = best.difficulty * STAGE_REGION_BASE + best.region_id if best else 0
            stage_cleared_at = best.cleared_at if best else None
            extra = {"activeTitleId": user.active_title_id}
            # 战力榜按「历史最高战力」排行：当前战力低于曾达到的峰值时仍以峰值排名。
            current_power = hero_power(stats)
            raise_max_power(user, current_power)
            peak_power = int(user.max_power or 0)

            entries = [
                _entry(user, hero, "level", hero.level, hero.exp, extra),
                _entry(
                    user,
                    hero,
                    "stage",
                    stage_value,
                    -int((stage_cleared_at or datetime.now(timezone.utc)).timestamp()),
                    extra,
                ),
                _entry(
                    user,
                    hero,
                    "power",
                    peak_power,
                    0,
                    {"power": current_power, "maxPower": peak_power, **extra},
                ),
                _entry(user, hero, "gold", int(user.gold), 0, extra),
                _entry(user, hero, "playtime", _play_seconds(user), 0, extra),
            ]
            for entry in entries:
                rows_to_insert.append(entry)
                counts[entry["board"]] += 1

        # 逐批写入：一次性 executemany，并在批间 flush 释放缓冲（仍在同一事务内）。
        if rows_to_insert:
            await db.execute(insert(RankingEntry), rows_to_insert)
            await db.flush()

    return counts


# ---------------------------------------------------------------- 钓鱼榜（实时）
async def _fish_stats_by_user(db: AsyncSession) -> dict[int, dict[str, int]]:
    """按账号聚合鱼类统计：种类数、总条数，以及普通 / 鱼王 / 鱼皇 / 困难鱼各自的种类数。"""
    rows = (
        await db.execute(
            select(FishRecord).join(User, User.id == FishRecord.user_id).where(User.banned.is_(False))
        )
    ).scalars().all()
    agg: dict[int, dict[str, int]] = {}
    for row in rows:
        stat = agg.setdefault(
            row.user_id,
            {"species": 0, "count": 0, "normal": 0, "king": 0, "emperor": 0, "legend": 0},
        )
        stat["species"] += 1
        stat["count"] += int(row.count)
        bucket = row.kind if row.kind in ("king", "emperor", "legend") else "normal"
        stat[bucket] += 1
    return agg


def _fish_sort_key(board: str) -> Callable[[dict[str, Any]], tuple[int, int]]:
    if board == "fish_count":
        return lambda row: (row["fishCount"], row["fishSpecies"])
    return lambda row: (row["fishSpecies"], row["fishCount"])


async def _fish_rows_uncached(db: AsyncSession) -> list[dict[str, Any]]:
    agg = await _fish_stats_by_user(db)
    if not agg:
        return []
    ids = list(agg.keys())
    users = (
        await db.execute(select(User).options(selectinload(User.hero)).where(User.id.in_(ids)))
    ).scalars().all()

    out: list[dict[str, Any]] = []
    for user in users:
        if is_admin(user) or user.banned or user.hero is None:
            continue
        stat = agg[user.id]
        out.append(
            {
                "userId": user.id,
                "nickname": user.nickname,
                "username": user.username,
                "level": user.hero.level,
                "activeTitleId": user.active_title_id,
                "playSeconds": _play_seconds(user),
                "fishSpecies": stat["species"],
                "fishCount": stat["count"],
                "fishNormal": stat["normal"],
                "fishKing": stat["king"],
                "fishEmperor": stat["emperor"],
                "fishLegend": stat["legend"],
            }
        )
    return out


async def _fish_rows(db: AsyncSession) -> list[dict[str, Any]]:
    """钓鱼榜聚合（带短 TTL 缓存；两个钓鱼榜共用同一份聚合）。"""
    cached = _live_cached("fish")
    if cached is not None:
        return cached
    rows = await _fish_rows_uncached(db)
    _live_store("fish", rows)
    return list(rows)


def _fish_value(row: dict[str, Any], board: str) -> int:
    return int(row["fishCount"] if board == "fish_count" else row["fishSpecies"])


async def fetch_fish_board(
    db: AsyncSession, board: str, page: int = 1, page_size: int = 100
) -> list[dict[str, Any]]:
    rows = await _fish_rows(db)
    rows.sort(key=_fish_sort_key(board), reverse=True)
    offset = max(0, (page - 1) * page_size)
    return [
        {
            "rank": offset + index + 1,
            "userId": row["userId"],
            "nickname": row["nickname"],
            "username": row["username"],
            "value": _fish_value(row, board),
            "payload": {
                "nickname": row["nickname"],
                "level": row["level"],
                "playSeconds": row["playSeconds"],
                "fishSpecies": row["fishSpecies"],
                "fishCount": row["fishCount"],
                "fishNormal": row["fishNormal"],
                "fishKing": row["fishKing"],
                "fishEmperor": row["fishEmperor"],
                "fishLegend": row["fishLegend"],
                "activeTitleId": row["activeTitleId"],
            },
        }
        for index, row in enumerate(rows[offset : offset + page_size])
    ]


async def fetch_fish_user_rank(
    db: AsyncSession, board: str, user_id: int
) -> dict[str, Any] | None:
    rows = await _fish_rows(db)
    rows.sort(key=_fish_sort_key(board), reverse=True)
    for index, row in enumerate(rows):
        if row["userId"] == user_id:
            return {
                "rank": index + 1,
                "value": _fish_value(row, board),
                "nickname": row["nickname"],
                "username": row["username"],
                "userId": user_id,
            }
    return None


# ---------------------------------------------------------------- 生产/采集榜（实时）
_DEDICATED_CATEGORIES = ("doh_tool", "doh_gear", "dol_tool", "dol_gear")
_DOHDOL_METRIC = {
    "doh_exp": "dohExp",
    "dol_exp": "dolExp",
    "doh_attr": "dohAttr",
    "dol_attr": "dolAttr",
}


def _dohdol_bucket() -> dict[str, float]:
    return {"dohExp": 0, "dolExp": 0, "dohAttr": 0.0, "dolAttr": 0.0, "dohLevel": 1, "dolLevel": 1}


async def _dohdol_stats_by_user(db: AsyncSession) -> dict[int, dict[str, float]]:
    """按账号聚合：生产/采集累计经验与等级，以及已装备专用装备的展示属性之和。"""
    agg: dict[int, dict[str, float]] = {}

    # 累计经验（满级后仍继续累计）+ 生产/采集等级
    rows = (
        await db.execute(
            select(DohDolProgress)
            .join(User, User.id == DohDolProgress.user_id)
            .where(User.banned.is_(False))
        )
    ).scalars().all()
    for row in rows:
        stat = agg.setdefault(row.user_id, _dohdol_bucket())
        if row.kind == "doh":
            stat["dohExp"] = int(row.total_exp or 0)
            stat["dohLevel"] = int(row.level)
        elif row.kind == "dol":
            stat["dolExp"] = int(row.total_exp or 0)
            stat["dolLevel"] = int(row.level)

    # 已装备专用装备：展示属性之和 = Σ base_attrs.value + Σ terms.value（Debuff 为负，按展示值计入）
    items = (
        await db.execute(
            select(Item)
            .join(User, User.id == Item.user_id)
            .where(
                User.banned.is_(False),
                Item.equipped_slot.is_not(None),
                Item.category.in_(_DEDICATED_CATEGORIES),
            )
        )
    ).scalars().all()
    for item in items:
        total = sum(float(entry.get("value", 0.0)) for entry in (item.base_attrs or []))
        total += sum(float(term.get("value", 0.0)) for term in (item.terms or []))
        stat = agg.setdefault(item.user_id, _dohdol_bucket())
        if str(item.category).startswith("doh"):
            stat["dohAttr"] += total
        else:
            stat["dolAttr"] += total
    return agg


async def _dohdol_rows_uncached(db: AsyncSession) -> list[dict[str, Any]]:
    agg = await _dohdol_stats_by_user(db)
    if not agg:
        return []
    ids = list(agg.keys())
    users = (
        await db.execute(select(User).options(selectinload(User.hero)).where(User.id.in_(ids)))
    ).scalars().all()

    out: list[dict[str, Any]] = []
    for user in users:
        if is_admin(user) or user.banned or user.hero is None:
            continue
        stat = agg[user.id]
        out.append(
            {
                "userId": user.id,
                "nickname": user.nickname,
                "username": user.username,
                "level": user.hero.level,
                "activeTitleId": user.active_title_id,
                "playSeconds": _play_seconds(user),
                "dohExp": int(stat["dohExp"]),
                "dolExp": int(stat["dolExp"]),
                "dohAttr": float(stat["dohAttr"]),
                "dolAttr": float(stat["dolAttr"]),
                "dohLevel": int(stat["dohLevel"]),
                "dolLevel": int(stat["dolLevel"]),
            }
        )
    return out


async def _dohdol_rows(db: AsyncSession) -> list[dict[str, Any]]:
    """生活职业榜聚合（带短 TTL 缓存；四个生活榜共用同一份聚合）。"""
    cached = _live_cached("dohdol")
    if cached is not None:
        return cached
    rows = await _dohdol_rows_uncached(db)
    _live_store("dohdol", rows)
    return list(rows)


def _dohdol_sorted(rows: list[dict[str, Any]], board: str) -> list[dict[str, Any]]:
    key = _DOHDOL_METRIC[board]
    ranked = [row for row in rows if float(row[key]) > 0]
    ranked.sort(key=lambda row: (float(row[key]), row["level"]), reverse=True)
    return ranked


def _dohdol_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "nickname": row["nickname"],
        "level": row["level"],
        "playSeconds": row["playSeconds"],
        "activeTitleId": row["activeTitleId"],
        "dohLevel": row["dohLevel"],
        "dolLevel": row["dolLevel"],
        "dohExp": row["dohExp"],
        "dolExp": row["dolExp"],
        "dohAttr": round(row["dohAttr"], 2),
        "dolAttr": round(row["dolAttr"], 2),
    }


async def fetch_dohdol_board(
    db: AsyncSession, board: str, page: int = 1, page_size: int = 100
) -> list[dict[str, Any]]:
    key = _DOHDOL_METRIC[board]
    rows = _dohdol_sorted(await _dohdol_rows(db), board)
    offset = max(0, (page - 1) * page_size)
    return [
        {
            "rank": offset + index + 1,
            "userId": row["userId"],
            "nickname": row["nickname"],
            "username": row["username"],
            "value": round(float(row[key])),
            "payload": _dohdol_payload(row),
        }
        for index, row in enumerate(rows[offset : offset + page_size])
    ]


async def fetch_dohdol_user_rank(
    db: AsyncSession, board: str, user_id: int
) -> dict[str, Any] | None:
    rows = _dohdol_sorted(await _dohdol_rows(db), board)
    for index, row in enumerate(rows):
        if row["userId"] == user_id:
            return {
                "rank": index + 1,
                "value": round(float(row[_DOHDOL_METRIC[board]])),
                "nickname": row["nickname"],
                "username": row["username"],
                "userId": user_id,
            }
    return None


# ---------------------------------------------------------------- 远征榜（实时）
async def _coop_rows_uncached(db: AsyncSession, dungeon_id: str) -> list[dict[str, Any]]:
    """按账号聚合该副本的最快通关记录（刚通关即可见，不依赖缓存刷新）。

    通关时长越小越好，因此这里用升序；同一账号只取其最快的一次，
    并保留该次的阵容（含分角色战斗信息）。
    """
    records = (
        await db.execute(select(CoopRecord).where(CoopRecord.dungeon_id == dungeon_id))
    ).scalars().all()
    if not records:
        return []

    best: dict[int, CoopRecord] = {}
    for row in records:
        current = best.get(row.user_id)
        if current is None or (row.clear_ms, row.created_at) < (current.clear_ms, current.created_at):
            best[row.user_id] = row

    users = (
        await db.execute(
            select(User).options(selectinload(User.hero)).where(User.id.in_(list(best.keys())))
        )
    ).scalars().all()

    out: list[dict[str, Any]] = []
    for user in users:
        if is_admin(user) or user.banned or user.hero is None:
            continue
        row = best[user.id]
        out.append(
            {
                "userId": user.id,
                "nickname": user.nickname,
                "username": user.username,
                "level": user.hero.level,
                "clearMs": int(row.clear_ms),
                "mode": row.mode,
                "hadClone": bool(row.had_clone),
                "dungeonId": row.dungeon_id,
                "createdAt": float(row.created_at),
                "party": row.party or [],
            }
        )
    out.sort(key=lambda row: (row["clearMs"], row["createdAt"]))
    return out


async def _coop_rows(db: AsyncSession, dungeon_id: str) -> list[dict[str, Any]]:
    """远征榜聚合（带短 TTL 缓存；按副本分别缓存）。"""
    key = f"coop:{dungeon_id}"
    cached = _live_cached(key)
    if cached is not None:
        return cached
    rows = await _coop_rows_uncached(db, dungeon_id)
    _live_store(key, rows)
    return list(rows)


def _coop_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "nickname": row["nickname"],
        "level": row["level"],
        "clearMs": row["clearMs"],
        "mode": row["mode"],
        "hadClone": row["hadClone"],
        "dungeonId": row["dungeonId"],
        "createdAt": row["createdAt"],
        "party": row["party"],
    }


async def fetch_coop_board(
    db: AsyncSession, dungeon_id: str, page: int = 1, page_size: int = 100
) -> list[dict[str, Any]]:
    rows = await _coop_rows(db, dungeon_id)
    offset = max(0, (page - 1) * page_size)
    return [
        {
            "rank": offset + index + 1,
            "userId": row["userId"],
            "nickname": row["nickname"],
            "username": row["username"],
            "value": row["clearMs"],
            "payload": _coop_payload(row),
        }
        for index, row in enumerate(rows[offset : offset + page_size])
    ]


async def fetch_coop_user_rank(
    db: AsyncSession, dungeon_id: str, user_id: int
) -> dict[str, Any] | None:
    rows = await _coop_rows(db, dungeon_id)
    for index, row in enumerate(rows):
        if row["userId"] == user_id:
            return {
                "rank": index + 1,
                "value": row["clearMs"],
                "clearMs": row["clearMs"],
                "nickname": row["nickname"],
                "username": row["username"],
                "userId": user_id,
            }
    return None


def _play_seconds(user: User) -> int:
    """累计在线时长（秒）。内部按毫秒累加，展示 / 排名按秒。"""
    return int(user.play_ms or 0) // 1000


def _entry(
    user: User,
    hero: Hero,
    board: str,
    value: int,
    secondary: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造一行待写入 `rankings` 的列字典（供 executemany 批量插入）。"""
    payload = {
        "nickname": user.nickname,
        "level": hero.level,
        "maxRegion": None,
        "jobId": None,
        "fishSpecies": 0,
        "fishCount": 0,
        "playSeconds": _play_seconds(user),
        "activeTitleId": user.active_title_id,
    }
    if extra:
        payload.update(
            {
                "jobId": extra.get("jobId"),
                "fishSpecies": extra.get("fishSpecies", 0),
                "fishCount": extra.get("fishCount", 0),
                "activeTitleId": extra.get("activeTitleId"),
            }
        )
        # 战力榜：value 为历史最高战力，payload 额外带上当前战力（供榜上并列展示）。
        if extra.get("power") is not None:
            payload["power"] = int(extra["power"])
            payload["maxPower"] = int(extra.get("maxPower", extra["power"]))
    return {
        "user_id": user.id,
        "board": board,
        "value": int(value),
        "secondary": int(secondary),
        "nickname": user.nickname,
        "payload": payload,
    }


async def fetch_board(db: AsyncSession, board: str, page: int = 1, page_size: int = 100) -> list[dict[str, Any]]:
    offset = max(0, (page - 1) * page_size)
    rows = (
        await db.execute(
            select(RankingEntry, User.username)
            .join(User, User.id == RankingEntry.user_id)
            .where(RankingEntry.board == board, User.banned.is_(False))
            .order_by(RankingEntry.value.desc(), RankingEntry.secondary.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).all()
    return [
        {
            "rank": offset + index + 1,
            "userId": row.user_id,
            "nickname": row.nickname,
            # 登录账号：与昵称一起展示，便于区分重名玩家（昵称可重复，账号唯一）
            "username": username,
            "value": row.value,
            "payload": row.payload,
        }
        for index, (row, username) in enumerate(rows)
    ]


async def fetch_user_rank(db: AsyncSession, board: str, user_id: int) -> dict[str, Any] | None:
    row = (
        await db.execute(
            select(RankingEntry, User.username)
            .join(User, User.id == RankingEntry.user_id)
            .where(
                RankingEntry.board == board,
                RankingEntry.user_id == user_id,
                User.banned.is_(False),
            )
        )
    ).first()
    if row is None:
        return None
    entry, username = row
    better = (
        await db.execute(
            select(func.count())
            .select_from(RankingEntry)
            .join(User, User.id == RankingEntry.user_id)
            .where(
                RankingEntry.board == board,
                User.banned.is_(False),
                or_(
                    RankingEntry.value > entry.value,
                    and_(RankingEntry.value == entry.value, RankingEntry.secondary > entry.secondary),
                ),
            )
        )
    ).scalar_one()
    return {
        "rank": int(better) + 1,
        "value": entry.value,
        "nickname": entry.nickname,
        "username": username,
        "userId": user_id,
    }

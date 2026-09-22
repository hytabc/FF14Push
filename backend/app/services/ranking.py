"""排行榜。来源：PRD 排行榜 2.2 / 2.3 / 2.4

- 等级 / 关卡 / 战力 / 金币：每 5 分钟由后台任务刷新到 `rankings` 缓存表。
- 钓鱼种类 / 钓鱼数量：**实时**从 `fish_records` 聚合（数据量小、且刚钓完就该看到），
  不依赖缓存，避免「刚钓完却看不到自己」。
- 生产/采集经验 / 生产/采集属性：同样**实时**聚合（`dohdol_progress` 累计经验 +
  已装备专用装备的展示属性之和），刚制造/采集完即可见。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    DohDolProgress,
    FishRecord,
    Hero,
    Item,
    RankingEntry,
    RegionProgress,
    User,
    UserTitle,
)
from app.services.admin import is_admin
from app.services.stats import compute_stats
from app.services.valuation import hero_power

# 走缓存刷新（每 5 分钟）的榜单
CACHED_BOARDS = ("level", "stage", "power", "gold", "playtime")
# 实时聚合的钓鱼榜单
FISH_BOARDS = ("fish_species", "fish_count")
# 实时聚合的生产/采集榜（累计经验 + 已装备专用装备属性总值）
DOHDOL_BOARDS = ("doh_exp", "dol_exp", "doh_attr", "dol_attr")
# 对外暴露的全部榜单
BOARDS = CACHED_BOARDS + FISH_BOARDS + DOHDOL_BOARDS


async def refresh_all_rankings(db: AsyncSession) -> dict[str, int]:
    users = (
        await db.execute(select(User).options(selectinload(User.hero), selectinload(User.items)))
    ).scalars().all()

    progress_rows = (await db.execute(select(RegionProgress))).scalars().all()
    cleared: dict[int, list[RegionProgress]] = {}
    for row in progress_rows:
        if row.cleared:
            cleared.setdefault(row.user_id, []).append(row)

    # 称号（展示在各榜行内；钓鱼榜的统计实时算，不走这里）
    title_map: dict[int, list[str]] = {}
    for row in (await db.execute(select(UserTitle))).scalars().all():
        title_map.setdefault(row.user_id, []).append(row.title_id)

    await db.execute(delete(RankingEntry))

    counts = {board: 0 for board in CACHED_BOARDS}
    for user in users:
        # 管理员与已封禁账号不参与排行榜（管理员另有「不创建英雄」双重保险）
        if is_admin(user) or user.banned:
            continue
        hero = user.hero
        if hero is None:
            continue

        stats = compute_stats(hero, user.items)
        cleared_list = cleared.get(user.id, [])
        max_region = max((r.region_id for r in cleared_list), default=0)
        cleared_at = max((r.cleared_at for r in cleared_list if r.cleared_at), default=None)
        extra = {"titles": title_map.get(user.id, [])}

        entries = [
            _entry(user, hero, "level", hero.level, hero.exp, extra),
            _entry(user, hero, "stage", max_region, -int((cleared_at or datetime.now(timezone.utc)).timestamp()), extra),
            _entry(user, hero, "power", hero_power(stats), 0, {**stats.to_dict(), **extra}),
            _entry(user, hero, "gold", int(user.gold), 0, extra),
            _entry(user, hero, "playtime", _play_seconds(user), 0, extra),
        ]
        for entry in entries:
            db.add(entry)
            counts[entry.board] += 1

    await db.flush()
    return counts


# ---------------------------------------------------------------- 钓鱼榜（实时）
async def _fish_stats_by_user(db: AsyncSession) -> dict[int, dict[str, int]]:
    """按账号聚合鱼类统计：种类数、总条数，以及普通 / 鱼王 / 鱼皇各自的种类数。"""
    rows = (
        await db.execute(
            select(FishRecord).join(User, User.id == FishRecord.user_id).where(User.banned.is_(False))
        )
    ).scalars().all()
    agg: dict[int, dict[str, int]] = {}
    for row in rows:
        stat = agg.setdefault(
            row.user_id, {"species": 0, "count": 0, "normal": 0, "king": 0, "emperor": 0}
        )
        stat["species"] += 1
        stat["count"] += int(row.count)
        bucket = row.kind if row.kind in ("king", "emperor") else "normal"
        stat[bucket] += 1
    return agg


def _fish_sort_key(board: str) -> Callable[[dict[str, Any]], tuple[int, int]]:
    if board == "fish_count":
        return lambda row: (row["fishCount"], row["fishSpecies"])
    return lambda row: (row["fishSpecies"], row["fishCount"])


async def _fish_rows(db: AsyncSession) -> list[dict[str, Any]]:
    agg = await _fish_stats_by_user(db)
    if not agg:
        return []
    ids = list(agg.keys())
    users = (
        await db.execute(select(User).options(selectinload(User.hero)).where(User.id.in_(ids)))
    ).scalars().all()
    title_map: dict[int, list[str]] = {}
    for row in (await db.execute(select(UserTitle).where(UserTitle.user_id.in_(ids)))).scalars().all():
        title_map.setdefault(row.user_id, []).append(row.title_id)

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
                "titles": title_map.get(user.id, []),
                "playSeconds": _play_seconds(user),
                "fishSpecies": stat["species"],
                "fishCount": stat["count"],
                "fishNormal": stat["normal"],
                "fishKing": stat["king"],
                "fishEmperor": stat["emperor"],
            }
        )
    return out


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
                "titles": row["titles"],
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


async def _dohdol_rows(db: AsyncSession) -> list[dict[str, Any]]:
    agg = await _dohdol_stats_by_user(db)
    if not agg:
        return []
    ids = list(agg.keys())
    users = (
        await db.execute(select(User).options(selectinload(User.hero)).where(User.id.in_(ids)))
    ).scalars().all()
    title_map: dict[int, list[str]] = {}
    for row in (await db.execute(select(UserTitle).where(UserTitle.user_id.in_(ids)))).scalars().all():
        title_map.setdefault(row.user_id, []).append(row.title_id)

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
                "titles": title_map.get(user.id, []),
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
        "titles": row["titles"],
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
) -> RankingEntry:
    payload = {
        "nickname": user.nickname,
        "level": hero.level,
        "maxRegion": None,
        "jobId": None,
        "fishSpecies": 0,
        "fishCount": 0,
        "playSeconds": _play_seconds(user),
        "titles": [],
    }
    if extra:
        payload.update(
            {
                "jobId": extra.get("jobId"),
                "fishSpecies": extra.get("fishSpecies", 0),
                "fishCount": extra.get("fishCount", 0),
                "titles": extra.get("titles", []),
            }
        )
    return RankingEntry(
        user_id=user.id,
        board=board,
        value=int(value),
        secondary=int(secondary),
        nickname=user.nickname,
        payload=payload,
    )


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

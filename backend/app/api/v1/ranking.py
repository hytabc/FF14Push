"""排行榜：等级榜 / 关卡榜 / 战力榜 / 金币榜。来源：PRD 排行榜系统"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps import DbSession, OptionalUser
from app.services.ranking import BOARDS, fetch_board, fetch_user_rank, refresh_all_rankings

router = APIRouter(prefix="/ranking", tags=["ranking"])


@router.get("")
async def ranking(
    db: DbSession,
    user: OptionalUser,
    board: str = Query("level", pattern="^(level|stage|power|gold)$"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=100),
) -> dict:
    entries = await fetch_board(db, board, page, pageSize)
    mine = await fetch_user_rank(db, board, user.id) if user else None
    return {
        "board": board,
        "boards": list(BOARDS),
        "page": page,
        "pageSize": pageSize,
        "entries": entries,
        "me": mine,
        "loggedIn": user is not None,
    }


@router.post("/refresh")
async def refresh(db: DbSession, user: OptionalUser) -> dict:
    """手动刷新（服务端本应每 5 分钟自动刷新一次）。"""
    counts = await refresh_all_rankings(db)
    await db.commit()
    return {"ok": True, "counts": counts, "message": "排行榜已刷新"}

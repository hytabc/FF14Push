"""重建伊修加德：全服共享进度的生活玩法接口。

- 专属采集 / 钓鱼 / 生产（复用 ActivitySession，与其它活动互斥）
- 提交产物换积分、出售过期物资
- 独立积分榜（不并入总排行榜）
- 可成长主手装备与紫色附魔
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.core.deps import CurrentItems, CurrentUser, DbSession
from app.models import ActivitySession
from app.schemas.game import (
    ActivityReportRequest,
    ActivityStopRequest,
    IshgardGatherStartRequest,
    IshgardProduceStartRequest,
    IshgardSellRequest,
    IshgardSubmitRequest,
    IshgardToolRequest,
)
from app.services import ishgard

router = APIRouter(prefix="/ishgard", tags=["ishgard"])

_KIND_NAMES = {
    ishgard.KIND_GATHER: "采集",
    ishgard.KIND_FISH: "钓鱼",
    ishgard.KIND_PRODUCE: "生产",
}


async def _session(db: DbSession, user_id: int, session_id: int, kind: str) -> ActivitySession:
    row = (
        await db.execute(
            select(ActivitySession).where(
                ActivitySession.id == session_id,
                ActivitySession.user_id == user_id,
                ActivitySession.kind == kind,
                ActivitySession.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或已结束")
    return row


async def _stop(db: DbSession, user_id: int, session_id: int) -> dict:
    row = (
        await db.execute(
            select(ActivitySession).where(
                ActivitySession.id == session_id, ActivitySession.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    await ishgard.stop_session(db, row)
    await db.commit()
    return {"ok": True}


@router.get("/state")
async def state(db: DbSession, user: CurrentUser) -> dict:
    body = await ishgard.build_state(db, user)
    await db.commit()
    return body


@router.get("/leaderboard")
async def leaderboard(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=100),
) -> dict:
    return {
        "page": page,
        "pageSize": pageSize,
        "entries": await ishgard.board(db, page, pageSize),
        "me": await ishgard.my_rank(db, user.id),
    }


# ------------------------------------------------------------------ 采集
@router.post("/gather/session/start")
async def gather_start(
    payload: IshgardGatherStartRequest, db: DbSession, user: CurrentUser, items: CurrentItems
) -> dict:
    try:
        result = await ishgard.start_gather(db, user, items, payload.jobId)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/gather/session/report")
async def gather_report(
    payload: ActivityReportRequest, db: DbSession, user: CurrentUser, items: CurrentItems
) -> dict:
    session = await _session(db, user.id, payload.sessionId, ishgard.KIND_GATHER)
    try:
        result = await ishgard.report_gather(db, user, items, session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/gather/session/stop")
async def gather_stop(payload: ActivityStopRequest, db: DbSession, user: CurrentUser) -> dict:
    return await _stop(db, user.id, payload.sessionId)


# ------------------------------------------------------------------ 钓鱼
@router.post("/fish/session/start")
async def fish_start(db: DbSession, user: CurrentUser, items: CurrentItems) -> dict:
    try:
        result = await ishgard.start_fish(db, user, items)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/fish/session/report")
async def fish_report(
    payload: ActivityReportRequest, db: DbSession, user: CurrentUser, items: CurrentItems
) -> dict:
    session = await _session(db, user.id, payload.sessionId, ishgard.KIND_FISH)
    try:
        result = await ishgard.report_fish(db, user, items, session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/fish/session/stop")
async def fish_stop(payload: ActivityStopRequest, db: DbSession, user: CurrentUser) -> dict:
    return await _stop(db, user.id, payload.sessionId)


# ------------------------------------------------------------------ 生产
@router.post("/produce/session/start")
async def produce_start(
    payload: IshgardProduceStartRequest, db: DbSession, user: CurrentUser, items: CurrentItems
) -> dict:
    try:
        result = await ishgard.start_produce(
            db, user, items, payload.jobId, payload.recipeId, payload.count
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/produce/session/report")
async def produce_report(
    payload: ActivityReportRequest, db: DbSession, user: CurrentUser, items: CurrentItems
) -> dict:
    session = await _session(db, user.id, payload.sessionId, ishgard.KIND_PRODUCE)
    try:
        result = await ishgard.report_produce(db, user, items, session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/produce/session/stop")
async def produce_stop(payload: ActivityStopRequest, db: DbSession, user: CurrentUser) -> dict:
    return await _stop(db, user.id, payload.sessionId)


# ------------------------------------------------------------------ 提交 / 出售 / 装备
@router.post("/submit")
async def submit(payload: IshgardSubmitRequest, db: DbSession, user: CurrentUser) -> dict:
    try:
        result = await ishgard.submit(db, user, payload.itemId, payload.count)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/sell")
async def sell(payload: IshgardSellRequest, db: DbSession, user: CurrentUser) -> dict:
    try:
        result = await ishgard.sell(db, user, payload.itemId, payload.count)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/tool/claim")
async def tool_claim(payload: IshgardToolRequest, db: DbSession, user: CurrentUser) -> dict:
    try:
        result = await ishgard.claim_tool(db, user, payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/tool/upgrade")
async def tool_upgrade(payload: IshgardToolRequest, db: DbSession, user: CurrentUser) -> dict:
    try:
        result = await ishgard.upgrade_tool(db, user, payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/tool/enchant")
async def tool_enchant(payload: IshgardToolRequest, db: DbSession, user: CurrentUser) -> dict:
    try:
        result = await ishgard.reroll_pink(db, user, payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result

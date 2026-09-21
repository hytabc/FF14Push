"""生产 / 采集 DLC 接口：采集、生产、钓鱼、专用装备、药水与食物。

四活动（战斗 / 采集 / 生产 / 钓鱼）互斥：启动任一会话会自动结束其他会话。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentItems, CurrentUser, DbSession
from app.models import ActivitySession, Item
from app.schemas.game import (
    ActivityReportRequest,
    ActivityStopRequest,
    ConsumableUseRequest,
    DohDolEquipRequest,
    DohDolUnequipRequest,
    FishStartRequest,
    GatherStartRequest,
    ProduceStartRequest,
)
from app.services import consumables, dohdol_util, fishing, gathering, production
from app.services.dohdol_state import build_dohdol_state
from app.services.game_config import CONFIG

router = APIRouter(tags=["dohdol"])

DEDICATED_CATEGORIES = {"doh_tool", "doh_gear", "dol_tool", "dol_gear"}
DEDICATED_SLOTS = {s["id"] for s in CONFIG.dohdol_equipment["slots"]}


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


@router.get("/dohdol/state")
async def dohdol_state(db: DbSession, user: CurrentUser, items: CurrentItems) -> dict:
    return await build_dohdol_state(db, user.id, items)


# ------------------------------------------------------------------ 采集
@router.post("/gather/session/start")
async def gather_start(payload: GatherStartRequest, db: DbSession, user: CurrentUser, items: CurrentItems) -> dict:
    try:
        result = await gathering.start_gather(db, user, items, payload.jobId, payload.regionId)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/gather/session/report")
async def gather_report(payload: ActivityReportRequest, db: DbSession, user: CurrentUser, items: CurrentItems) -> dict:
    session = await _session(db, user.id, payload.sessionId, "gather")
    try:
        result = await gathering.report_gather(db, user, items, session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/gather/session/stop")
async def gather_stop(payload: ActivityStopRequest, db: DbSession, user: CurrentUser) -> dict:
    row = (
        await db.execute(
            select(ActivitySession).where(
                ActivitySession.id == payload.sessionId, ActivitySession.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    await gathering.stop_gather(db, row)
    await db.commit()
    return {"ok": True, "message": "采集已停止"}


# ------------------------------------------------------------------ 生产
@router.post("/produce/session/start")
async def produce_start(payload: ProduceStartRequest, db: DbSession, user: CurrentUser) -> dict:
    try:
        result = await production.start_produce(db, user, payload.jobId, payload.recipeId)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/produce/session/report")
async def produce_report(payload: ActivityReportRequest, db: DbSession, user: CurrentUser, items: CurrentItems) -> dict:
    session = await _session(db, user.id, payload.sessionId, "produce")
    try:
        result = await production.report_produce(db, user, items, session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/produce/session/stop")
async def produce_stop(payload: ActivityStopRequest, db: DbSession, user: CurrentUser) -> dict:
    row = (
        await db.execute(
            select(ActivitySession).where(
                ActivitySession.id == payload.sessionId, ActivitySession.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    await production.stop_produce(db, row)
    await db.commit()
    return {"ok": True, "message": "生产已停止"}


# ------------------------------------------------------------------ 钓鱼
@router.post("/fish/session/start")
async def fish_start(payload: FishStartRequest, db: DbSession, user: CurrentUser) -> dict:
    try:
        result = await fishing.start_fish(db, user, payload.regionId)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/fish/session/report")
async def fish_report(payload: ActivityReportRequest, db: DbSession, user: CurrentUser, items: CurrentItems) -> dict:
    session = await _session(db, user.id, payload.sessionId, "fish")
    try:
        result = await fishing.report_fish(db, user, items, session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post("/fish/session/stop")
async def fish_stop(payload: ActivityStopRequest, db: DbSession, user: CurrentUser) -> dict:
    row = (
        await db.execute(
            select(ActivitySession).where(
                ActivitySession.id == payload.sessionId, ActivitySession.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    await fishing.stop_fish(db, row)
    await db.commit()
    return {"ok": True, "message": "钓鱼已停止"}


# ------------------------------------------------------------------ 消耗品
@router.post("/consumable/use")
async def consumable_use(payload: ConsumableUseRequest, db: DbSession, user: CurrentUser) -> dict:
    try:
        result = await consumables.use_consumable(db, user.id, payload.itemId)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return {**result, "active": await consumables.active_state(db, user.id)}


# ------------------------------------------------------------------ 专用装备
@router.post("/dohdol/equip")
async def dohdol_equip(payload: DohDolEquipRequest, db: DbSession, user: CurrentUser) -> dict:
    if payload.slot not in DEDICATED_SLOTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知的专用装备栏位")
    item = (
        await db.execute(select(Item).where(Item.id == payload.itemId, Item.user_id == user.id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="装备不存在")
    if item.category not in DEDICATED_CATEGORIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该装备不是生产/采集专用装备")
    if item.slot != payload.slot:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="栏位不匹配")

    current = (
        await db.execute(
            select(Item).where(
                Item.user_id == user.id, Item.equipped_slot == payload.slot
            )
        )
    ).scalar_one_or_none()
    if current is not None and current.id != item.id:
        current.equipped_slot = None
    item.equipped_slot = payload.slot
    await db.commit()
    return {"ok": True, "slot": payload.slot, "itemId": item.id}


@router.post("/dohdol/unequip")
async def dohdol_unequip(payload: DohDolUnequipRequest, db: DbSession, user: CurrentUser) -> dict:
    if payload.slot not in DEDICATED_SLOTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知的专用装备栏位")
    current = (
        await db.execute(
            select(Item).where(Item.user_id == user.id, Item.equipped_slot == payload.slot)
        )
    ).scalar_one_or_none()
    if current is not None:
        current.equipped_slot = None
        await db.commit()
    return {"ok": True, "slot": payload.slot}

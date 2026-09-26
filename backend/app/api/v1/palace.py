"""死者宫殿：与账号战力完全隔离的 roguelike 深层迷宫。"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, DbSession
from app.schemas.game import (
    PalaceChooseRequest,
    PalaceEquipRequest,
    PalaceEventChooseRequest,
    PalaceExchangeRequest,
    PalaceGrowthUnlockRequest,
    PalaceNodeClearRequest,
    PalaceNodeEnterRequest,
    PalaceShopBuyRequest,
)
from app.services import palace

router = APIRouter(prefix="/palace", tags=["palace"])


@router.get("/state")
async def palace_state(db: DbSession, user: CurrentUser) -> dict:
    return await palace.state(db, user)


@router.post("/start")
async def palace_start(db: DbSession, user: CurrentUser) -> dict:
    result = await palace.start(db, user)
    await db.commit()
    return result


@router.post("/hero/choose")
async def palace_choose_hero(
    payload: PalaceChooseRequest, db: DbSession, user: CurrentUser
) -> dict:
    result = await palace.choose_hero(db, user, payload.index)
    await db.commit()
    return result


@router.post("/weapon/choose")
async def palace_choose_weapon(
    payload: PalaceChooseRequest, db: DbSession, user: CurrentUser
) -> dict:
    result = await palace.choose_weapon(db, user, payload.index)
    await db.commit()
    return result


@router.post("/node/enter")
async def palace_enter_node(
    payload: PalaceNodeEnterRequest, db: DbSession, user: CurrentUser
) -> dict:
    result = await palace.enter_node(db, user, payload.nodeId)
    await db.commit()
    return result


@router.post("/node/clear")
async def palace_clear_node(
    payload: PalaceNodeClearRequest, db: DbSession, user: CurrentUser
) -> dict:
    result = await palace.clear_node(db, user, payload.nodeId, payload.elapsedMs, payload.result)
    await db.commit()
    return result


@router.post("/reward/claim")
async def palace_claim_reward(
    payload: PalaceChooseRequest, db: DbSession, user: CurrentUser
) -> dict:
    result = await palace.claim_reward(db, user, payload.index)
    await db.commit()
    return result


@router.post("/event/choose")
async def palace_event_choose(
    payload: PalaceEventChooseRequest, db: DbSession, user: CurrentUser
) -> dict:
    result = await palace.event_choose(db, user, payload.nodeId, payload.choiceIndex)
    await db.commit()
    return result


@router.post("/shop/buy")
async def palace_shop_buy(
    payload: PalaceShopBuyRequest, db: DbSession, user: CurrentUser
) -> dict:
    result = await palace.shop_buy(db, user, payload.nodeId, payload.offerIndex)
    await db.commit()
    return result


@router.post("/equip")
async def palace_equip(
    payload: PalaceEquipRequest, db: DbSession, user: CurrentUser
) -> dict:
    result = await palace.equip_item(db, user, payload.index)
    await db.commit()
    return result


@router.post("/abandon")
async def palace_abandon(db: DbSession, user: CurrentUser) -> dict:
    result = await palace.abandon(db, user)
    await db.commit()
    return result


@router.get("/growth")
async def palace_growth(db: DbSession, user: CurrentUser) -> dict:
    profile = await palace.get_profile(db, user.id)
    return palace.growth_view(profile)


@router.post("/growth/unlock")
async def palace_growth_unlock(
    payload: PalaceGrowthUnlockRequest, db: DbSession, user: CurrentUser
) -> dict:
    result = await palace.unlock_growth(db, user, payload.nodeId)
    await db.commit()
    return result


@router.get("/exchange")
async def palace_exchange_view(db: DbSession, user: CurrentUser) -> dict:
    profile = await palace.get_profile(db, user.id)
    return palace.exchange_view(profile)


@router.post("/exchange")
async def palace_exchange(
    payload: PalaceExchangeRequest, db: DbSession, user: CurrentUser
) -> dict:
    result = await palace.exchange(db, user, payload.exchangeId, payload.count)
    await db.commit()
    return result

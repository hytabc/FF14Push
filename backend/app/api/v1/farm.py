"""种田：账号级田地，作物按真实时间生长。"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, DbSession
from app.schemas.game import FarmHarvestRequest, FarmPlantRequest
from app.services import farm

router = APIRouter(prefix="/farm", tags=["farm"])


@router.get("/state")
async def farm_state(db: DbSession, user: CurrentUser) -> dict:
    return await farm.farm_view(db, user)


@router.post("/expand")
async def farm_expand(db: DbSession, user: CurrentUser) -> dict:
    result = await farm.expand(db, user)
    await db.commit()
    return result


@router.post("/plant")
async def farm_plant(payload: FarmPlantRequest, db: DbSession, user: CurrentUser) -> dict:
    result = await farm.plant(db, user, payload.plotIndex, payload.seedId)
    await db.commit()
    return result


@router.post("/harvest")
async def farm_harvest(payload: FarmHarvestRequest, db: DbSession, user: CurrentUser) -> dict:
    result = await farm.harvest(
        db, user, payload.plotIndex, payload.heroId, payload.confirm
    )
    await db.commit()
    return result

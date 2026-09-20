"""玩家设置：自动出售、重播指引。来源：PRD 出售 3.4 / 新手指引 1.2"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models import AutoSellSetting
from app.schemas.game import AutoSellRequest
from app.services.game_config import CONFIG

router = APIRouter(prefix="/settings", tags=["settings"])

VALID_RARITIES = set(CONFIG.rarity_order)


async def _auto_sell(db: DbSession, user_id: int) -> AutoSellSetting:
    row = (
        await db.execute(select(AutoSellSetting).where(AutoSellSetting.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = AutoSellSetting(
            user_id=user_id,
            enabled=False,
            rarities=list(CONFIG.economy["sell"]["autoSellRarities"]),
        )
        db.add(row)
        await db.flush()
    return row


@router.get("/auto-sell")
async def get_auto_sell(db: DbSession, user: CurrentUser) -> dict:
    row = await _auto_sell(db, user.id)
    await db.commit()
    return {"enabled": bool(row.enabled), "rarities": list(row.rarities or [])}


@router.post("/auto-sell")
async def set_auto_sell(payload: AutoSellRequest, db: DbSession, user: CurrentUser) -> dict:
    row = await _auto_sell(db, user.id)
    invalid = [r for r in payload.rarities if r not in VALID_RARITIES]
    if invalid:
        return {"ok": False, "message": f"未知品阶: {invalid}"}
    row.enabled = bool(payload.enabled)
    row.rarities = list(payload.rarities) if payload.rarities else list(CONFIG.economy["sell"]["autoSellRarities"])
    await db.commit()
    return {"enabled": bool(row.enabled), "rarities": list(row.rarities)}

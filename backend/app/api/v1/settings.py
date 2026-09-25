"""玩家设置：自动出售、重播指引。来源：PRD 出售 3.4 / 新手指引 1.2"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models import AutoSellSetting, UserTitle
from app.schemas.game import ActiveTitleRequest, AutoSellFishRequest, AutoSellRequest
from app.services.game_config import CONFIG

router = APIRouter(prefix="/settings", tags=["settings"])

VALID_RARITIES = set(CONFIG.rarity_order)
# 鱼的档位：普通鱼 / 鱼王 / 鱼皇 / 困难鱼（与 fish.json 的 kind 一致）。
VALID_FISH_KINDS = {"normal", "king", "emperor", "legend"}


def _default_fish_kinds() -> list[str]:
    return list(CONFIG.economy["sell"].get("fishAutoSellKinds", ["normal"]))


async def _auto_sell(db: DbSession, user_id: int) -> AutoSellSetting:
    row = (
        await db.execute(select(AutoSellSetting).where(AutoSellSetting.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = AutoSellSetting(
            user_id=user_id,
            enabled=False,
            rarities=list(CONFIG.economy["sell"]["autoSellRarities"]),
            fish_enabled=False,
            fish_kinds=_default_fish_kinds(),
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


@router.get("/auto-sell-fish")
async def get_auto_sell_fish(db: DbSession, user: CurrentUser) -> dict:
    row = await _auto_sell(db, user.id)
    await db.commit()
    return {"enabled": bool(row.fish_enabled), "kinds": list(row.fish_kinds or []) or _default_fish_kinds()}


@router.post("/auto-sell-fish")
async def set_auto_sell_fish(payload: AutoSellFishRequest, db: DbSession, user: CurrentUser) -> dict:
    row = await _auto_sell(db, user.id)
    invalid = [k for k in payload.kinds if k not in VALID_FISH_KINDS]
    if invalid:
        return {"ok": False, "message": f"未知鱼的档位: {invalid}"}
    row.fish_enabled = bool(payload.enabled)
    row.fish_kinds = list(payload.kinds) if payload.kinds else _default_fish_kinds()
    await db.commit()
    return {"enabled": bool(row.fish_enabled), "kinds": list(row.fish_kinds)}


@router.post("/active-title")
async def set_active_title(payload: ActiveTitleRequest, db: DbSession, user: CurrentUser) -> dict:
    """佩戴称号（最多一个）。只能佩戴已拥有的称号，传 None 取消佩戴。"""
    title_id = payload.titleId or None
    if title_id is not None:
        valid = {t["id"] for t in CONFIG.titles["titles"]}
        if title_id not in valid:
            return {"ok": False, "activeTitleId": user.active_title_id, "message": "未知称号"}
        owned = (
            await db.execute(
                select(UserTitle).where(
                    UserTitle.user_id == user.id, UserTitle.title_id == title_id
                )
            )
        ).scalar_one_or_none()
        if owned is None:
            return {"ok": False, "activeTitleId": user.active_title_id, "message": "尚未获得该称号"}
    user.active_title_id = title_id
    await db.commit()
    return {"ok": True, "activeTitleId": user.active_title_id}

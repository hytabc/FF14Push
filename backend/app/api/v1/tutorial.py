"""新手指引：15 步进度、完成奖励、跳过与重播。来源：PRD 新手指引系统"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models import TutorialProgress
from app.schemas.game import TutorialRequest
from app.services.drop_luck import rarity_luck, user_drop_rate
from app.services import consumables
from app.services.game_config import CONFIG
from app.services.grants import grant_generated_items
from app.services.item_factory import generate_item
from app.services.loot import chest_by_id

router = APIRouter(prefix="/tutorial", tags=["tutorial"])

STEPS = CONFIG.tutorial["steps"]
TOTAL_STEPS = len(STEPS)


async def _progress(db: DbSession, user_id: int) -> TutorialProgress:
    row = (
        await db.execute(select(TutorialProgress).where(TutorialProgress.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = TutorialProgress(user_id=user_id, current_step=1)
        db.add(row)
        await db.flush()
    return row


def _payload(row: TutorialProgress) -> dict:
    return {
        "currentStep": row.current_step,
        "totalSteps": TOTAL_STEPS,
        "completed": bool(row.completed),
        "skipped": bool(row.skipped),
        "rewarded": bool(row.rewarded),
        "steps": STEPS,
    }


@router.get("")
async def tutorial(db: DbSession, user: CurrentUser) -> dict:
    row = await _progress(db, user.id)
    await db.commit()
    return _payload(row)


@router.post("/step")
async def set_step(payload: TutorialRequest, db: DbSession, user: CurrentUser) -> dict:
    row = await _progress(db, user.id)
    if payload.step is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少步骤参数")
    if row.completed or row.skipped:
        return _payload(row)
    if payload.step < 1 or payload.step > TOTAL_STEPS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="步骤超出范围")
    if payload.step < row.current_step:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能回退指引步骤")
    row.current_step = payload.step
    await db.commit()
    return _payload(row)


@router.post("/complete")
async def complete(db: DbSession, user: CurrentUser) -> dict:
    """完成全部 15 步：500 金币 + 3 个普通箱。跳过不发放，且奖励仅发一次。来源：PRD 新手指引 1.5"""
    row = await _progress(db, user.id)
    if row.skipped:
        return {**_payload(row), "granted": False, "message": "已跳过指引，不发放奖励"}

    # 重播后再次走完流程：标记完成但不再发奖
    row.current_step = TOTAL_STEPS
    row.completed = True
    if row.rewarded:
        await db.commit()
        return {**_payload(row), "granted": False, "message": "奖励已领取"}

    reward = CONFIG.tutorial["completionReward"]
    user.gold = int(user.gold) + int(reward["gold"])

    luck = rarity_luck(await user_drop_rate(db, user.id)) + await consumables.chest_luck(db, user.id)
    generated = []
    for entry in reward["chests"]:
        chest = chest_by_id(entry["chestId"])
        if chest is None:
            continue
        for _ in range(int(entry["count"])):
            generated.append(
                generate_item(chest["category"], 1, box_tier=chest["tier"], luck=luck)[0]
            )

    grant = await grant_generated_items(db, user, generated, source="tutorial")
    row.rewarded = True
    await db.commit()
    return {
        **_payload(row),
        "granted": True,
        "gold": int(user.gold),
        "goldGained": int(reward["gold"]),
        "items": grant["items"],
    }


@router.post("/skip")
async def skip(db: DbSession, user: CurrentUser) -> dict:
    """跳过指引（不获得奖励）。来源：PRD 新手指引 1.4"""
    row = await _progress(db, user.id)
    row.skipped = True
    await db.commit()
    return {**_payload(row), "message": "已跳过新手指引，可在设置中重新开启"}


@router.post("/restart")
async def restart(db: DbSession, user: CurrentUser) -> dict:
    """从第一步重新播放（已领取的奖励不重置，避免重播刷奖励）。"""
    row = await _progress(db, user.id)
    row.current_step = 1
    row.completed = False
    row.skipped = False
    await db.commit()
    return {**_payload(row), "message": "已从第一步重新开始"}

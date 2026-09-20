"""图鉴：装备 / 怪物 / 词条。来源：PRD 图鉴系统"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models import CodexEquipment, CodexMonster, CodexTerm
from app.services.codex import (
    codex_progress,
    equipment_codex_entries,
    monster_codex_entries,
    term_codex_entries,
)

router = APIRouter(prefix="/codex", tags=["codex"])


@router.get("")
async def codex(
    db: DbSession,
    user: CurrentUser,
    category: str = Query("equipment", pattern="^(equipment|monster|term)$"),
) -> dict:
    progress = await codex_progress(db, user.id)

    if category == "equipment":
        rows = (
            await db.execute(select(CodexEquipment).where(CodexEquipment.user_id == user.id))
        ).scalars().all()
        unlocked = {
            row.base_id: {
                "rarities": list(row.unlocked_rarities or []),
                "totalCount": row.total_count,
                "firstUnlockAt": row.first_unlock_at.isoformat() if row.first_unlock_at else None,
            }
            for row in rows
        }
        entries = []
        for entry in equipment_codex_entries():
            state = unlocked.get(entry["baseId"])
            entries.append(
                {
                    **entry,
                    "unlocked": state is not None,
                    "unlockedRarities": state["rarities"] if state else [],
                    "totalCount": state["totalCount"] if state else 0,
                    "firstUnlockAt": state["firstUnlockAt"] if state else None,
                }
            )
        return {"category": category, "progress": progress, "entries": entries}

    if category == "monster":
        rows = (
            await db.execute(select(CodexMonster).where(CodexMonster.user_id == user.id))
        ).scalars().all()
        unlocked = {
            row.monster_id: {
                "killCount": row.kill_count,
                "firstDefeatAt": row.first_defeat_at.isoformat() if row.first_defeat_at else None,
            }
            for row in rows
        }
        entries = []
        for entry in monster_codex_entries():
            state = unlocked.get(entry["monsterId"])
            entries.append(
                {
                    **entry,
                    "unlocked": state is not None,
                    "killCount": state["killCount"] if state else 0,
                    "firstDefeatAt": state["firstDefeatAt"] if state else None,
                }
            )
        return {"category": category, "progress": progress, "entries": entries}

    rows = (await db.execute(select(CodexTerm).where(CodexTerm.user_id == user.id))).scalars().all()
    unlocked_pairs = {(row.term_id, row.quality) for row in rows}
    first_seen = {(row.term_id, row.quality): row.first_seen_at for row in rows}
    entries = []
    for entry in term_codex_entries():
        qualities = {
            q: {
                "unlocked": (entry["termId"], q) in unlocked_pairs,
                "firstSeenAt": (
                    first_seen[(entry["termId"], q)].isoformat()
                    if (entry["termId"], q) in first_seen and first_seen[(entry["termId"], q)]
                    else None
                ),
            }
            for q in ("common", "rare", "ancient")
        }
        entries.append({**entry, "qualities": qualities})
    return {"category": category, "progress": progress, "entries": entries}

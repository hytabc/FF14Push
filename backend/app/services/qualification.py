"""Recompute access without modifying historical rewards or clears."""
from sqlalchemy import select
from fastapi import HTTPException
from app.models import MechanismTrial, RegionProgress
from app.services.balance import BALANCE, region_gate
from app.services.stats import compute_stats

async def trial_marks(db, user_id):
    rows = (await db.execute(select(MechanismTrial).where(
        MechanismTrial.user_id == user_id, MechanismTrial.passed.is_(True),
        MechanismTrial.version == BALANCE['version']))).scalars().all()
    return {r.scope for r in rows}

async def region_access(db, user_id, hero, items):
    rows = (await db.execute(select(RegionProgress).where(RegionProgress.user_id == user_id))).scalars().all()
    marks = await trial_marks(db,user_id)
    cleared = {r.region_id for r in rows if r.cleared}
    old = {r.region_id for r in rows if r.unlocked}
    stats = compute_stats(hero,items)
    return {int(r): region_gate(int(r),stats,items,cleared,marks,int(r) in old) for r in BALANCE['regions']}

async def require_region(db,user_id,hero,items,region_id):
    missing = (await region_access(db,user_id,hero,items))[region_id]
    if missing: raise HTTPException(403, detail='；'.join(missing))

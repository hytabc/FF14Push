"""玩家自定义的生产 / 采集序列库（≤5 条/账号），带可分享的蓝图ID。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.models import SequenceBlueprint
from app.schemas.game import SequenceOverwriteRequest, SequenceSaveRequest
from app.services.sequences import (
    MAX_NAME_LEN,
    MAX_SEQUENCES_PER_USER,
    generate_share_code,
    normalize_loop_mode,
    sanitize_steps,
    serialize_sequence,
)

router = APIRouter(prefix="/sequences", tags=["sequences"])


async def _user_sequences(db: DbSession, user_id: int) -> list[SequenceBlueprint]:
    return list(
        (
            await db.execute(
                select(SequenceBlueprint)
                .where(SequenceBlueprint.user_id == user_id)
                .order_by(SequenceBlueprint.id)
            )
        ).scalars().all()
    )


async def _owned_sequence(db: DbSession, user_id: int, seq_id: int) -> SequenceBlueprint:
    seq = (
        await db.execute(
            select(SequenceBlueprint).where(
                SequenceBlueprint.id == seq_id, SequenceBlueprint.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if seq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="序列不存在")
    return seq


def _clean_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="序列名称不能为空")
    if len(name) > MAX_NAME_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"序列名称最多 {MAX_NAME_LEN} 字"
        )
    return name


@router.get("")
async def list_sequences(db: DbSession, user: CurrentUser) -> dict:
    sequences = await _user_sequences(db, user.id)
    return {"sequences": [serialize_sequence(s) for s in sequences]}


@router.post("")
async def save_sequence(payload: SequenceSaveRequest, db: DbSession, user: CurrentUser) -> dict:
    """保存当前编辑区；同名则覆盖该序列（保留其蓝图ID）。"""
    name = _clean_name(payload.name)
    steps = sanitize_steps(payload.steps)
    loop_mode = normalize_loop_mode(payload.loopMode)

    existing = (
        await db.execute(
            select(SequenceBlueprint).where(
                SequenceBlueprint.user_id == user.id, SequenceBlueprint.name == name
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.steps = steps
        existing.loop_mode = loop_mode
        existing.loop_total = payload.loopTotal
        await db.flush()
        data = serialize_sequence(existing)
        await db.commit()
        return {"sequence": data}

    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(SequenceBlueprint)
                .where(SequenceBlueprint.user_id == user.id)
            )
        ).scalar_one()
    )
    if total >= MAX_SEQUENCES_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"序列数量已达上限（{MAX_SEQUENCES_PER_USER}）",
        )

    seq = SequenceBlueprint(
        user_id=user.id,
        name=name,
        steps=steps,
        loop_mode=loop_mode,
        loop_total=payload.loopTotal,
        share_code=await generate_share_code(db),
    )
    db.add(seq)
    await db.flush()
    data = serialize_sequence(seq)
    await db.commit()
    return {"sequence": data}


@router.post("/{seq_id}")
async def overwrite_sequence(
    seq_id: int, payload: SequenceOverwriteRequest, db: DbSession, user: CurrentUser
) -> dict:
    """用当前编辑区覆盖指定槽位（蓝图ID不变）。"""
    seq = await _owned_sequence(db, user.id, seq_id)

    if payload.name is not None:
        name = _clean_name(payload.name)
        if name != seq.name:
            dup = (
                await db.execute(
                    select(SequenceBlueprint).where(
                        SequenceBlueprint.user_id == user.id, SequenceBlueprint.name == name
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="序列名称已存在"
                )
            seq.name = name

    seq.steps = sanitize_steps(payload.steps)
    seq.loop_mode = normalize_loop_mode(payload.loopMode)
    seq.loop_total = payload.loopTotal
    await db.flush()
    data = serialize_sequence(seq)
    await db.commit()
    return {"sequence": data}


@router.delete("/{seq_id}")
async def delete_sequence(seq_id: int, db: DbSession, user: CurrentUser) -> dict:
    seq = await _owned_sequence(db, user.id, seq_id)
    await db.delete(seq)
    await db.commit()
    return {"ok": True}


@router.get("/blueprint/{code}")
async def import_blueprint(code: str, db: DbSession, user: CurrentUser) -> dict:
    """凭蓝图ID读取任意玩家的序列（不返回 id / 账号信息）。"""
    normalized = code.strip().upper()
    seq = (
        await db.execute(
            select(SequenceBlueprint).where(SequenceBlueprint.share_code == normalized)
        )
    ).scalar_one_or_none()
    if seq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="蓝图ID不存在")
    return {"sequence": serialize_sequence(seq, include_id=False)}

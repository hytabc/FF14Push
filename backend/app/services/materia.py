"""魔晶石镶嵌：账号级 11 个装备栏位 × 5 孔。

孔位属于账号而不是装备，因此镶嵌结果不随装备更换而变化。服务端权威：镶嵌成功率与取出
全部在服务端结算；镶嵌失败会消耗该魔晶石，取出必定成功并返还。
"""

from __future__ import annotations

import random
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MateriaSocket
from app.services import dohdol_util
from app.services.game_config import CONFIG
from app.services.slots_util import SLOT_BY_ID

MAX_LEVEL = 5


def sockets_per_slot() -> int:
    return int(CONFIG.materia["socketsPerSlot"])


def success_chances() -> list[float]:
    return [float(value) for value in CONFIG.materia["successChance"]]


def merge_from() -> int:
    return int(CONFIG.materia["mergeFrom"])


def materia_def(materia_id: str) -> dict[str, Any] | None:
    return CONFIG.materia_by_id.get(materia_id)


def _materia_view(materia_id: str | None) -> dict[str, Any] | None:
    if not materia_id:
        return None
    spec = materia_def(materia_id)
    if spec is None:
        return None
    return {
        "id": spec["id"],
        "name": spec["name"],
        "type": spec["type"],
        "stat": spec["stat"],
        "statName": spec["statName"],
        "level": int(spec["level"]),
        "value": float(spec["value"]),
        "sell": int(spec["sell"]),
    }


def _sum_mods(rows: Iterable[MateriaSocket]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        spec = materia_def(row.materia_id)
        if spec is None:
            continue
        stat = str(spec["stat"])
        out[stat] = out.get(stat, 0.0) + float(spec["value"])
    return out


async def _rows(db: AsyncSession, user_id: int) -> list[MateriaSocket]:
    return list(
        (await db.execute(select(MateriaSocket).where(MateriaSocket.user_id == user_id)))
        .scalars()
        .all()
    )


async def socket_mods(db: AsyncSession, user_id: int) -> dict[str, float]:
    """已镶嵌魔晶石提供的属性加成（供 compute_stats 注入）。"""
    return _sum_mods(await _rows(db, user_id))


async def socket_mods_map(db: AsyncSession, user_ids: Iterable[int]) -> dict[int, dict[str, float]]:
    """批量版本（排行榜等按多账号计算时使用）。"""
    ids = list(dict.fromkeys(int(uid) for uid in user_ids))
    if not ids:
        return {}
    rows = (
        await db.execute(select(MateriaSocket).where(MateriaSocket.user_id.in_(ids)))
    ).scalars().all()
    grouped: dict[int, list[MateriaSocket]] = {}
    for row in rows:
        grouped.setdefault(int(row.user_id), []).append(row)
    return {uid: _sum_mods(grouped.get(uid, [])) for uid in ids}


async def sockets_view(db: AsyncSession, user_id: int) -> dict[str, Any]:
    """栏目视图：11 栏位 × 5 孔 + 全部 30 种魔晶石库存 + 当前加成合计。"""
    rows = await _rows(db, user_id)
    by_slot: dict[str, dict[int, str]] = {}
    for row in rows:
        by_slot.setdefault(row.slot, {})[int(row.index)] = row.materia_id

    chances = success_chances()
    per_slot = sockets_per_slot()
    slots = []
    for slot in sorted(CONFIG.slots, key=lambda s: s["order"]):
        filled = by_slot.get(slot["id"], {})
        slots.append(
            {
                "id": slot["id"],
                "name": slot["name"],
                "category": slot["category"],
                "order": slot["order"],
                "sockets": [
                    {
                        "index": index,
                        "chance": chances[index],
                        "materia": _materia_view(filled.get(index)),
                    }
                    for index in range(per_slot)
                ],
            }
        )

    counts = await dohdol_util.stack_counts(db, user_id, dohdol_util.STACK_MATERIA)
    stock = []
    for mtype in CONFIG.materia["types"]:
        for level in range(1, MAX_LEVEL + 1):
            materia_id = f"m_{mtype['id']}_{level}"
            view = _materia_view(materia_id)
            if view is None:
                continue
            stock.append({**view, "count": int(counts.get(materia_id, 0))})

    return {
        "slots": slots,
        "socketsPerSlot": per_slot,
        "successChance": chances,
        "mergeFrom": merge_from(),
        "maxLevel": MAX_LEVEL,
        "stock": stock,
        "bonus": {k: round(v, 2) for k, v in _sum_mods(rows).items()},
        "source": {
            "note": "魔晶石仅由挖宝获得；孔位属于账号，换装备 / 换英雄都不改变镶嵌结果。",
        },
    }


def _lowest_empty(filled: dict[int, str], per_slot: int) -> int | None:
    for index in range(per_slot):
        if index not in filled:
            return index
    return None


async def socket_materia(
    db: AsyncSession, user_id: int, slot: str, index: int, materia_id: str
) -> dict[str, Any]:
    if slot not in SLOT_BY_ID:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知栏位")
    if materia_def(materia_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="魔晶石不存在")

    per_slot = sockets_per_slot()
    if not 0 <= index < per_slot:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="孔位不存在")

    rows = await _rows(db, user_id)
    filled = {int(row.index): row.materia_id for row in rows if row.slot == slot}
    if index in filled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该孔位已镶嵌魔晶石")
    expected = _lowest_empty(filled, per_slot)
    if expected is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该栏位孔位已满")
    if index != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"请按顺序镶嵌：当前应镶嵌第 {expected + 1} 孔",
        )

    # 无论成功与否都消耗 1 个魔晶石。
    if not await dohdol_util.stack_consume(
        db, user_id, dohdol_util.STACK_MATERIA, materia_id, 1
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="魔晶石不足")

    chance = success_chances()[index]
    success = random.random() < chance
    if success:
        db.add(MateriaSocket(user_id=user_id, slot=slot, index=index, materia_id=materia_id))
        await db.flush()

    return {
        "success": success,
        "chance": chance,
        "slot": slot,
        "index": index,
        "materia": _materia_view(materia_id),
        "state": await sockets_view(db, user_id),
    }


async def remove_materia(db: AsyncSession, user_id: int, slot: str, index: int) -> dict[str, Any]:
    if slot not in SLOT_BY_ID:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知栏位")
    row = (
        await db.execute(
            select(MateriaSocket).where(
                MateriaSocket.user_id == user_id,
                MateriaSocket.slot == slot,
                MateriaSocket.index == index,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该孔位没有魔晶石")

    materia_id = row.materia_id
    await db.delete(row)
    await db.flush()
    # 取出必定成功并返还。
    await dohdol_util.stack_add(db, user_id, dohdol_util.STACK_MATERIA, materia_id, 1)
    return {
        "removed": _materia_view(materia_id),
        "slot": slot,
        "index": index,
        "state": await sockets_view(db, user_id),
    }


async def merge_materia(db: AsyncSession, user_id: int, materia_id: str) -> dict[str, Any]:
    spec = materia_def(materia_id)
    if spec is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="魔晶石不存在")
    level = int(spec["level"])
    if level >= MAX_LEVEL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已是最高等级魔晶石")

    need = merge_from()
    if not await dohdol_util.stack_consume(
        db, user_id, dohdol_util.STACK_MATERIA, materia_id, need
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"魔晶石不足，需要 {need} 个"
        )

    target_id = f"m_{spec['type']}_{level + 1}"
    await dohdol_util.stack_add(db, user_id, dohdol_util.STACK_MATERIA, target_id, 1)
    return {
        "consumed": materia_id,
        "count": need,
        "produced": _materia_view(target_id),
        "state": await sockets_view(db, user_id),
    }

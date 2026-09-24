"""魔晶石镶嵌。孔位属于账号级 11 个装备栏位，每栏 5 孔，不随装备更换。"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, DbSession
from app.schemas.game import MateriaMergeRequest, MateriaRemoveRequest, MateriaSocketRequest
from app.services import materia

router = APIRouter(prefix="/materia", tags=["materia"])


@router.get("/state")
async def materia_state(db: DbSession, user: CurrentUser) -> dict:
    return await materia.sockets_view(db, user.id)


@router.post("/socket")
async def materia_socket(
    payload: MateriaSocketRequest, db: DbSession, user: CurrentUser
) -> dict:
    result = await materia.socket_materia(
        db, user.id, payload.slot, payload.index, payload.materiaId
    )
    await db.commit()
    return result


@router.post("/remove")
async def materia_remove(
    payload: MateriaRemoveRequest, db: DbSession, user: CurrentUser
) -> dict:
    result = await materia.remove_materia(db, user.id, payload.slot, payload.index)
    await db.commit()
    return result


@router.post("/merge")
async def materia_merge(payload: MateriaMergeRequest, db: DbSession, user: CurrentUser) -> dict:
    result = await materia.merge_materia(db, user.id, payload.materiaId)
    await db.commit()
    return result

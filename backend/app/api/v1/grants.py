"""补偿公示：管理员发放金币的记录，对全服玩家公开（只读，无需登录）。"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.deps import DbSession
from app.models import AdminGrant

router = APIRouter(prefix="/grants", tags=["grants"])


@router.get("")
async def list_grants(
    db: DbSession,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=100),
) -> dict:
    """按发放时间倒序列出补偿记录（晚发放的在前）。

    公开只读：与排行榜同级的信息，不含任何内部字段（不返回操作管理员的账号 / id）。
    """
    total = await db.scalar(select(func.count()).select_from(AdminGrant)) or 0
    rows = (
        (
            await db.execute(
                select(AdminGrant)
                .order_by(AdminGrant.id.desc())
                .offset((page - 1) * pageSize)
                .limit(pageSize)
            )
        )
        .scalars()
        .all()
    )
    return {
        "page": page,
        "pageSize": pageSize,
        "total": int(total),
        "records": [
            {
                "id": row.id,
                "userId": row.user_id,
                "nickname": row.nickname,
                "amount": int(row.amount),
                "note": row.note,
                "createdAt": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }

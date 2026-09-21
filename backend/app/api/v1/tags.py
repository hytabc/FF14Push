"""玩家自定义装备标签：命名 + 调色板颜色，用于给装备打标与背包筛选。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentItems, CurrentUser, DbSession
from app.models import ItemTag
from app.schemas.game import TagCreateRequest, TagUpdateRequest
from app.services.game_config import CONFIG
from app.services.serialization import tag_to_dict

router = APIRouter(prefix="/tags", tags=["tags"])

MAX_TAGS_PER_USER = 30
VALID_COLORS = set(CONFIG.tag_colors["order"])


async def _user_tags(db: DbSession, user_id: int) -> list[ItemTag]:
    return list(
        (
            await db.execute(
                select(ItemTag).where(ItemTag.user_id == user_id).order_by(ItemTag.id)
            )
        ).scalars().all()
    )


async def _owned_tag(db: DbSession, user_id: int, tag_id: int) -> ItemTag:
    tag = (
        await db.execute(select(ItemTag).where(ItemTag.id == tag_id, ItemTag.user_id == user_id))
    ).scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="标签不存在")
    return tag


def _clean_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="标签名称不能为空")
    return name


def _check_color(color: str) -> None:
    if color not in VALID_COLORS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知标签颜色")


@router.get("")
async def list_tags(db: DbSession, user: CurrentUser) -> dict:
    tags = await _user_tags(db, user.id)
    return {"tags": [tag_to_dict(t) for t in tags]}


@router.post("")
async def create_tag(payload: TagCreateRequest, db: DbSession, user: CurrentUser) -> dict:
    name = _clean_name(payload.name)
    _check_color(payload.color)

    tags = await _user_tags(db, user.id)
    if len(tags) >= MAX_TAGS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"标签数量已达上限（{MAX_TAGS_PER_USER}）"
        )
    if any(t.name == name for t in tags):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="标签名称已存在")

    tag = ItemTag(user_id=user.id, name=name, color=payload.color)
    db.add(tag)
    await db.flush()
    data = tag_to_dict(tag)
    await db.commit()
    return {"tag": data}


@router.post("/{tag_id}")
async def update_tag(
    tag_id: int, payload: TagUpdateRequest, db: DbSession, user: CurrentUser
) -> dict:
    tag = await _owned_tag(db, user.id, tag_id)

    if payload.name is not None:
        name = _clean_name(payload.name)
        if name != tag.name:
            dup = (
                await db.execute(
                    select(ItemTag).where(ItemTag.user_id == user.id, ItemTag.name == name)
                )
            ).scalar_one_or_none()
            if dup is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="标签名称已存在"
                )
            tag.name = name
    if payload.color is not None:
        _check_color(payload.color)
        tag.color = payload.color

    await db.flush()
    data = tag_to_dict(tag)
    await db.commit()
    return {"tag": data}


@router.delete("/{tag_id}")
async def delete_tag(tag_id: int, db: DbSession, user: CurrentUser, items: CurrentItems) -> dict:
    tag = await _owned_tag(db, user.id, tag_id)
    await db.delete(tag)
    # 从本人所有装备上移除该标签
    for item in items:
        ids = list(item.tag_ids or [])
        if tag_id in ids:
            item.tag_ids = [i for i in ids if i != tag_id]
    await db.commit()
    return {"ok": True}

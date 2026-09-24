"""玩家间交易板业务：上架托管、整单买断成交（抽手续费）、下架 / 到期退回。

规则要点：
- 上架即把物品从卖家背包 / 库存迁出（装备删除行 + 保存快照；堆叠扣减数量），进入托管。
- 成交：买家扣全款，卖家得 `total - fee`（fee = floor(total × feePct)，金币直接销毁回收）。
- 未售出到期（listingDays 天）自动退回卖家。
- 卖家 / 买家同一 IP 的成交写入审计日志（可疑洗钱行为留痕，不拦截）。
"""

from __future__ import annotations

from datetime import timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, DohDolProgress, Item, MarketListing, User
from app.models.base import utcnow
from app.models.market import (
    LISTING_KIND_EQUIPMENT,
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
    STATUS_SOLD,
)
from app.services import dohdol_util
from app.services.codex import unlock_equipment, unlock_terms
from app.services.game_config import CONFIG
from app.services.progression import highest_hero_level
from app.services.roster import lock_user
from app.services.serialization import item_to_dict
from app.services.valuation import sell_price, sell_price_range


# 生产 / 采集专用装备分类 → 对应的职业等级 kind。
DOHDOL_CATEGORY_KIND = {
    "doh_tool": "doh",
    "doh_gear": "doh",
    "dol_tool": "dol",
    "dol_gear": "dol",
}

# 等级门槛类别 → 玩家可读名称（用于错误提示）。
REQ_KIND_LABEL = {
    "combat": "任意英雄等级",
    "doh": "生产职业等级",
    "dol": "采集职业等级",
}


# ------------------------------------------------------------------ 配置
def _cfg() -> dict[str, Any]:
    return CONFIG.economy["market"]


def fee_pct() -> float:
    return float(_cfg()["feePct"])


def fee_of(price: int) -> int:
    """手续费（金币回收），向下取整。"""
    return max(0, int(int(price) * fee_pct()))


def net_of(price: int) -> int:
    return int(price) - fee_of(price)


def listing_days() -> int:
    return int(_cfg()["listingDays"])


def max_active_listings() -> int:
    return int(_cfg()["maxActiveListings"])


def max_stack_quantity() -> int:
    return int(_cfg()["maxStackQuantityPerListing"])


def min_price() -> int:
    return int(_cfg()["minPrice"])


def max_price() -> int:
    return int(_cfg()["maxPrice"])


def reference_price_of(kind: str, item_key: str) -> int:
    """系统回收价（参考值）：堆叠物取配置单价（装备需实体，另算）。"""
    if kind == LISTING_KIND_EQUIPMENT:
        return 0
    return int(dohdol_util.sell_price(kind, item_key))


def _aware(dt: Any) -> Any:
    """SQLite 会返回 naive datetime，统一成 UTC 再比较。"""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_expired(row: MarketListing) -> bool:
    return _aware(row.expires_at) <= utcnow()


# ------------------------------------------------------------------ 购买等级门槛
def requirement_of(row: MarketListing) -> tuple[str, int] | None:
    """购买该寄售单所需的等级门槛，返回 (kind, level)；素材 / 消耗品无限制返回 None。

    - 战斗职业装备（weapon / armor / accessory）→ kind="combat"：账号内任一英雄达标即可。
    - 生产 / 采集专用装备 → kind="doh" / "dol"：对应职业等级达标。
    - 等级要求 ≤ 1 视为无门槛。
    """
    if row.kind != LISTING_KIND_EQUIPMENT:
        return None
    level = int(row.level_req or 1)
    if level <= 1:
        return None
    return (DOHDOL_CATEGORY_KIND.get(row.category or "", "combat"), level)


async def buyer_levels(db: AsyncSession, user_id: int) -> dict[str, int]:
    """买家可用于购买限制的三类等级：战斗（最高英雄）/ 生产 / 采集。"""
    rows = (
        await db.execute(select(DohDolProgress).where(DohDolProgress.user_id == user_id))
    ).scalars().all()
    by_kind = {row.kind: int(row.level) for row in rows}
    return {
        "combat": await highest_hero_level(db, user_id),
        "doh": by_kind.get("doh", 1),
        "dol": by_kind.get("dol", 1),
    }


def meets_requirement(row: MarketListing, levels: dict[str, int]) -> bool:
    req = requirement_of(row)
    if req is None:
        return True
    kind, level = req
    return levels.get(kind, 1) >= level


def requirement_error(row: MarketListing) -> str:
    req = requirement_of(row)
    assert req is not None
    kind, level = req
    return f"需要{REQ_KIND_LABEL[kind]}达到 {level} 级才能购买"


# ------------------------------------------------------------------ 快照
def snapshot_item(item: Item) -> dict[str, Any]:
    """装备快照：仅取库中原始字段，避免带上展示用的 min/max 区间。"""
    return {
        "baseId": item.base_id,
        "name": item.name,
        "category": item.category,
        "slot": item.slot,
        "rarity": item.rarity,
        "levelReq": item.level_req,
        "highQuality": bool(item.high_quality),
        "baseAttrs": list(item.base_attrs or []),
        "subAttrs": list(item.sub_attrs or []),
        "terms": list(item.terms or []),
        "refineCount": int(item.refine_count or 0),
        "enchantCount": int(item.enchant_count or 0),
        "source": item.source,
        "tagIds": list(item.tag_ids or []),
    }


def snapshot_detail(snapshot: dict[str, Any]) -> dict[str, Any]:
    """快照 → 前端展示用的精简装备信息。"""
    return {
        "baseId": snapshot.get("baseId"),
        "name": snapshot.get("name"),
        "category": snapshot.get("category"),
        "slot": snapshot.get("slot"),
        "rarity": snapshot.get("rarity"),
        "levelReq": snapshot.get("levelReq"),
        "highQuality": bool(snapshot.get("highQuality", False)),
        "baseAttrs": snapshot.get("baseAttrs") or [],
        "subAttrs": snapshot.get("subAttrs") or [],
        "terms": snapshot.get("terms") or [],
    }


async def recreate_item(
    db: AsyncSession, user_id: int, snapshot: dict[str, Any], *, keep_tags: bool
) -> Item:
    """按快照重建装备行（退回卖家 / 交付买家），并解锁买家图鉴。"""
    item = Item(
        user_id=user_id,
        base_id=snapshot["baseId"],
        name=snapshot.get("name") or snapshot["baseId"],
        category=snapshot["category"],
        slot=snapshot["slot"],
        rarity=snapshot["rarity"],
        level_req=int(snapshot.get("levelReq", 1)),
        high_quality=bool(snapshot.get("highQuality", False)),
        base_attrs=list(snapshot.get("baseAttrs") or []),
        sub_attrs=list(snapshot.get("subAttrs") or []),
        terms=list(snapshot.get("terms") or []),
        refine_count=int(snapshot.get("refineCount", 0)),
        enchant_count=int(snapshot.get("enchantCount", 0)),
        source=snapshot.get("source") or "market",
        tag_ids=list(snapshot.get("tagIds") or []) if keep_tags else [],
    )
    db.add(item)
    await db.flush()
    await unlock_terms(db, user_id, item.terms or [])
    await unlock_equipment(db, user_id, item)
    return item


# ------------------------------------------------------------------ 序列化
def listing_to_dict(
    row: MarketListing,
    seller_nickname: str | None = None,
    levels: dict[str, int] | None = None,
    buyer_nickname: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": row.id,
        "kind": row.kind,
        "itemKey": row.item_key,
        "name": row.name,
        "rarity": row.rarity,
        "category": row.category,
        "slot": row.slot,
        "levelReq": row.level_req,
        "quantity": int(row.quantity),
        "unitPrice": int(row.unit_price),
        "totalPrice": int(row.unit_price) * int(row.quantity),
        "referencePrice": int(row.reference_price or 0),
        "status": row.status,
        "sellerId": row.seller_id,
        "sellerNickname": seller_nickname,
        "buyerId": row.buyer_id,
        "buyerNickname": buyer_nickname,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "expiresAt": row.expires_at.isoformat() if row.expires_at else None,
    }
    req = requirement_of(row)
    data["requiredKind"] = req[0] if req else None
    if levels is not None:
        data["levelMet"] = meets_requirement(row, levels)
    if row.kind == LISTING_KIND_EQUIPMENT and row.snapshot:
        data["equipment"] = snapshot_detail(row.snapshot)
    return data


# ------------------------------------------------------------------ 托管迁移
async def _return_escrow(db: AsyncSession, row: MarketListing) -> None:
    """把托管物退回卖家。"""
    if row.kind == LISTING_KIND_EQUIPMENT:
        await recreate_item(db, row.seller_id, row.snapshot or {}, keep_tags=True)
    else:
        await dohdol_util.stack_add(db, row.seller_id, row.kind, row.item_key, int(row.quantity))


async def _deliver_escrow(db: AsyncSession, row: MarketListing, buyer_id: int) -> Item | None:
    """把托管物交付买家；装备返回新行，堆叠返回 None。"""
    if row.kind == LISTING_KIND_EQUIPMENT:
        return await recreate_item(db, buyer_id, row.snapshot or {}, keep_tags=False)
    await dohdol_util.stack_add(db, buyer_id, row.kind, row.item_key, int(row.quantity))
    return None


# ------------------------------------------------------------------ 上架
def _new_listing(**kwargs: Any) -> MarketListing:
    now = utcnow()
    return MarketListing(
        status=STATUS_ACTIVE,
        created_at=now,
        expires_at=now + timedelta(days=listing_days()),
        **kwargs,
    )


async def count_active(db: AsyncSession, user_id: int) -> int:
    from sqlalchemy import func

    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(MarketListing)
                .where(MarketListing.seller_id == user_id, MarketListing.status == STATUS_ACTIVE)
            )
        ).scalar_one()
    )


async def list_equipment(
    db: AsyncSession, user: User, item: Item, unit_price: int, ip: str | None
) -> MarketListing:
    snapshot = snapshot_item(item)
    listing = _new_listing(
        seller_id=user.id,
        kind=LISTING_KIND_EQUIPMENT,
        item_key=item.base_id,
        name=item.name,
        rarity=item.rarity,
        category=item.category,
        slot=item.slot,
        level_req=item.level_req,
        quantity=1,
        unit_price=int(unit_price),
        reference_price=int(sell_price(item)),
        snapshot=snapshot,
        seller_ip=ip,
    )
    db.add(listing)
    await db.delete(item)
    return listing


async def list_stack(
    db: AsyncSession,
    user: User,
    kind: str,
    item_id: str,
    count: int,
    unit_price: int,
    ip: str | None,
) -> MarketListing | None:
    ok = await dohdol_util.stack_consume(db, user.id, kind, item_id, int(count))
    if not ok:
        return None
    listing = _new_listing(
        seller_id=user.id,
        kind=kind,
        item_key=item_id,
        name=dohdol_util.material_name(item_id),
        quantity=int(count),
        unit_price=int(unit_price),
        reference_price=reference_price_of(kind, item_id),
        seller_ip=ip,
    )
    db.add(listing)
    return listing


# ------------------------------------------------------------------ 成交 / 下架
async def buy_listing(
    db: AsyncSession, buyer: User, row: MarketListing, ip: str | None
) -> dict[str, Any]:
    if row.seller_id == buyer.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能购买自己上架的物品")

    seller = await lock_user(db, row.seller_id)
    if seller is None or seller.banned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="卖家当前不可交易")

    if not meets_requirement(row, await buyer_levels(db, buyer.id)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=requirement_error(row))

    total = int(row.unit_price) * int(row.quantity)
    if int(buyer.gold) < total:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="金币不足")

    fee = fee_of(total)
    buyer.gold = int(buyer.gold) - total
    seller.gold = int(seller.gold) + (total - fee)

    item = await _deliver_escrow(db, row, buyer.id)

    row.status = STATUS_SOLD
    row.buyer_id = buyer.id
    row.sold_price = total
    row.fee = fee
    row.buyer_ip = ip
    row.closed_at = utcnow()

    if ip and row.seller_ip and ip == row.seller_ip:
        db.add(
            AuditLog(
                user_id=buyer.id,
                reason="market_same_ip",
                payload={"listingId": row.id, "sellerId": row.seller_id, "price": total},
                rejected=False,
            )
        )

    await db.commit()
    return {
        "gold": int(buyer.gold),
        "total": total,
        "fee": fee,
        "sellerGold": int(seller.gold),
        "item": item_to_dict(item, sell_price_range(item)) if item is not None else None,
    }


async def cancel_listing(db: AsyncSession, seller: User, row: MarketListing) -> None:
    if row.seller_id != seller.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能下架自己的寄售")
    await _return_escrow(db, row)
    row.status = STATUS_CANCELLED
    row.closed_at = utcnow()
    await db.commit()


# ------------------------------------------------------------------ 到期
async def expire_listings(db: AsyncSession, limit: int = 50) -> int:
    """把已到期的挂单退回卖家。批量有界，配合浏览 / 我的寄售接口惰性触发。"""
    now = utcnow()
    rows = (
        await db.execute(
            select(MarketListing)
            .where(MarketListing.status == STATUS_ACTIVE, MarketListing.expires_at < now)
            .order_by(MarketListing.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    if not rows:
        return 0
    for row in rows:
        await _return_escrow(db, row)
        row.status = STATUS_EXPIRED
        row.closed_at = now
    await db.commit()
    return len(rows)

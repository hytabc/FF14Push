"""市场交易板接口：浏览 / 我的寄售 / 上架 / 购买 / 下架；收购单（求购）发布 / 成交 / 取消。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, client_ip, guard_rate
from app.models import Item, MarketBuyOrder, MarketListing, User
from app.models.base import utcnow
from app.models.market import (
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
    STATUS_FILLED,
    STATUS_SOLD,
)
from app.schemas.game import (
    BuyOrderCancelRequest,
    BuyOrderCreateRequest,
    BuyOrderFillRequest,
    MarketBuyRequest,
    MarketCancelRequest,
    MarketListRequest,
)
from app.services import dohdol_util, market

router = APIRouter(prefix="/market", tags=["market"])

_SORTS = {
    "price_asc": (MarketListing.unit_price.asc(), MarketListing.id.asc()),
    "price_desc": (MarketListing.unit_price.desc(), MarketListing.id.asc()),
    "time_desc": (MarketListing.created_at.desc(), MarketListing.id.desc()),
}

_BUY_ORDER_SORTS = {
    "price_asc": (MarketBuyOrder.unit_price.asc(), MarketBuyOrder.id.asc()),
    "price_desc": (MarketBuyOrder.unit_price.desc(), MarketBuyOrder.id.asc()),
    "time_desc": (MarketBuyOrder.created_at.desc(), MarketBuyOrder.id.desc()),
}


def _active_conditions() -> list:
    return [
        MarketListing.status == STATUS_ACTIVE,
        MarketListing.expires_at > utcnow(),
        User.banned.is_(False),
    ]


def _active_buy_order_conditions() -> list:
    return [
        MarketBuyOrder.status == STATUS_ACTIVE,
        MarketBuyOrder.expires_at > utcnow(),
        User.banned.is_(False),
    ]


@router.get("/listings")
async def listings(
    db: DbSession,
    user: CurrentUser,
    kind: str = Query("all"),
    rarity: str | None = Query(None),
    category: str | None = Query(None),
    slot: str | None = Query(None),
    q: str | None = Query(None, max_length=32),
    levelMin: int | None = Query(None, ge=1),
    levelMax: int | None = Query(None, ge=1),
    priceMin: int | None = Query(None, ge=0),
    priceMax: int | None = Query(None, ge=0),
    sort: str = Query("time_desc"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=50),
) -> dict:
    await market.expire_listings(db)

    conditions = _active_conditions() + [MarketListing.seller_id != user.id]
    if kind and kind != "all":
        if kind == "consumable":
            conditions.append(MarketListing.kind.in_(("potion", "food")))
        elif kind in ("material", "fish"):
            # 鱼与采集材料同存 kind="material"：把「鱼获」与「素材」分开过滤。
            conditions.append(MarketListing.kind == "material")
            fish_ids = dohdol_util.fish_item_ids()
            conditions.append(
                MarketListing.item_key.in_(fish_ids)
                if kind == "fish"
                else MarketListing.item_key.notin_(fish_ids)
            )
        else:
            conditions.append(MarketListing.kind == kind)
    if rarity:
        conditions.append(MarketListing.rarity == rarity)
    if category:
        conditions.append(MarketListing.category == category)
    # 部位 / 等级仅装备有值（堆叠物这两列为 NULL，天然被排除）。
    if slot:
        conditions.append(MarketListing.slot == slot)
    if levelMin is not None:
        conditions.append(MarketListing.level_req >= levelMin)
    if levelMax is not None:
        conditions.append(MarketListing.level_req <= levelMax)
    if priceMin is not None:
        conditions.append(MarketListing.unit_price >= priceMin)
    if priceMax is not None:
        conditions.append(MarketListing.unit_price <= priceMax)
    if q:
        conditions.append(MarketListing.name.ilike(f"%{q}%"))

    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(MarketListing)
                .join(User, User.id == MarketListing.seller_id)
                .where(*conditions)
            )
        ).scalar_one()
    )

    order = _SORTS.get(sort, _SORTS["time_desc"])
    rows = (
        await db.execute(
            select(MarketListing, User.nickname)
            .join(User, User.id == MarketListing.seller_id)
            .where(*conditions)
            .order_by(*order)
            .offset((page - 1) * pageSize)
            .limit(pageSize)
        )
    ).all()

    levels = await market.buyer_levels(db, user.id)
    return {
        "listings": [market.listing_to_dict(row, nickname, levels) for row, nickname in rows],
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "feePct": market.fee_pct(),
        "listingDays": market.listing_days(),
        "maxActiveListings": market.max_active_listings(),
    }


@router.get("/mine")
async def mine(db: DbSession, user: CurrentUser) -> dict:
    await market.expire_listings(db)

    active = (
        await db.execute(
            select(MarketListing)
            .where(
                MarketListing.seller_id == user.id,
                MarketListing.status == STATUS_ACTIVE,
                MarketListing.expires_at > utcnow(),
            )
            .order_by(MarketListing.created_at.desc(), MarketListing.id.desc())
        )
    ).scalars().all()

    closed = (
        await db.execute(
            select(MarketListing)
            .where(
                MarketListing.seller_id == user.id,
                MarketListing.status.in_((STATUS_SOLD, STATUS_CANCELLED, STATUS_EXPIRED)),
            )
            .order_by(MarketListing.closed_at.desc(), MarketListing.id.desc())
            .limit(50)
        )
    ).scalars().all()

    # 已售出记录需要展示「被谁买走」，批量取买家昵称。
    buyer_ids = {row.buyer_id for row in closed if row.buyer_id}
    buyer_names: dict[int, str] = {}
    if buyer_ids:
        buyer_names = {
            row.id: row.nickname
            for row in (
                await db.execute(select(User.id, User.nickname).where(User.id.in_(buyer_ids)))
            ).all()
        }

    return {
        "active": [market.listing_to_dict(row, user.nickname) for row in active],
        "closed": [
            market.listing_to_dict(row, user.nickname, buyer_nickname=buyer_names.get(row.buyer_id))
            for row in closed
        ],
        "activeCount": len(active),
        "maxActiveListings": market.max_active_listings(),
        "feePct": market.fee_pct(),
    }


@router.post("/list")
async def create_listings(
    payload: MarketListRequest, request: Request, db: DbSession, user: CurrentUser
) -> dict:
    await guard_rate(db, "market_list", str(user.id), 30, 60, "上架过于频繁，请稍后再试")

    lo, hi = market.min_price(), market.max_price()
    for entry in payload.entries:
        if not (lo <= entry.unitPrice <= hi):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"单价需在 {lo} ~ {hi} 之间",
            )

    active = await market.count_active(db, user.id)
    if active + len(payload.entries) > market.max_active_listings():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"在售寄售单已达上限（{market.max_active_listings()}）",
        )

    ip = client_ip(request)
    created: list[MarketListing] = []
    for entry in payload.entries:
        if entry.type == "equipment":
            if entry.itemId is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少装备 id")
            item = (
                await db.execute(
                    select(Item).where(Item.id == entry.itemId, Item.user_id == user.id)
                )
            ).scalar_one_or_none()
            if item is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="装备不存在")
            if item.equipped_slot:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="已装备的装备需先卸下"
                )
            created.append(await market.list_equipment(db, user, item, entry.unitPrice, ip))
        else:
            if not entry.stackKind or not entry.stackItemId:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="缺少堆叠物品信息"
                )
            expected = dohdol_util.sellable_kind(entry.stackItemId)
            if expected != entry.stackKind:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="物品类型不匹配"
                )
            if entry.count > market.max_stack_quantity():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"单次上架数量不得超过 {market.max_stack_quantity()}",
                )
            row = await market.list_stack(
                db, user, entry.stackKind, entry.stackItemId, entry.count, entry.unitPrice, ip
            )
            if row is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="数量不足")
            created.append(row)

    await db.commit()
    return {
        "gold": int(user.gold),
        "listings": [market.listing_to_dict(row, user.nickname) for row in created],
        "activeCount": await market.count_active(db, user.id),
    }


@router.post("/buy")
async def buy(
    payload: MarketBuyRequest, request: Request, db: DbSession, user: CurrentUser
) -> dict:
    await guard_rate(db, "market_buy", str(user.id), 60, 60, "购买过于频繁，请稍后再试")

    row = (
        await db.execute(
            select(MarketListing).where(MarketListing.id == payload.listingId).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="寄售单不存在")
    if row.status != STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该寄售单已售出或已下架")
    if market.is_expired(row):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该寄售单已过期")

    return await market.buy_listing(db, user, row, client_ip(request))


@router.post("/cancel")
async def cancel(
    payload: MarketCancelRequest, db: DbSession, user: CurrentUser
) -> dict:
    row = (
        await db.execute(
            select(MarketListing).where(MarketListing.id == payload.listingId).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="寄售单不存在")
    if row.status != STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该寄售单已结束")

    await market.cancel_listing(db, user, row)
    return {"gold": int(user.gold), "message": "已下架"}


# ------------------------------------------------------------------ 收购单（求购）
@router.get("/buy-orders")
async def buy_orders(
    db: DbSession,
    user: CurrentUser,
    kind: str = Query("all"),
    sort: str = Query("time_desc"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=50),
) -> dict:
    """浏览他人发布的收购单。"""
    await market.expire_buy_orders(db)

    conditions = _active_buy_order_conditions() + [MarketBuyOrder.buyer_id != user.id]
    if kind and kind != "all":
        if kind == "consumable":
            conditions.append(MarketBuyOrder.kind.in_(("potion", "food")))
        elif kind in ("material", "fish"):
            # 与 /listings 同口径：鱼获与素材分开。
            conditions.append(MarketBuyOrder.kind == "material")
            fish_ids = dohdol_util.fish_item_ids()
            conditions.append(
                MarketBuyOrder.item_key.in_(fish_ids)
                if kind == "fish"
                else MarketBuyOrder.item_key.notin_(fish_ids)
            )
        else:
            conditions.append(MarketBuyOrder.kind == kind)

    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(MarketBuyOrder)
                .join(User, User.id == MarketBuyOrder.buyer_id)
                .where(*conditions)
            )
        ).scalar_one()
    )

    order = _BUY_ORDER_SORTS.get(sort, _BUY_ORDER_SORTS["time_desc"])
    rows = (
        await db.execute(
            select(MarketBuyOrder, User.nickname)
            .join(User, User.id == MarketBuyOrder.buyer_id)
            .where(*conditions)
            .order_by(*order)
            .offset((page - 1) * pageSize)
            .limit(pageSize)
        )
    ).all()

    return {
        "orders": [market.buy_order_to_dict(row, nickname) for row, nickname in rows],
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "feePct": market.fee_pct(),
        "listingDays": market.listing_days(),
        "maxActiveBuyOrders": market.max_active_buy_orders(),
    }


@router.get("/buy-orders/mine")
async def my_buy_orders(db: DbSession, user: CurrentUser) -> dict:
    await market.expire_buy_orders(db)

    active = (
        await db.execute(
            select(MarketBuyOrder)
            .where(
                MarketBuyOrder.buyer_id == user.id,
                MarketBuyOrder.status == STATUS_ACTIVE,
                MarketBuyOrder.expires_at > utcnow(),
            )
            .order_by(MarketBuyOrder.created_at.desc(), MarketBuyOrder.id.desc())
        )
    ).scalars().all()

    closed = (
        await db.execute(
            select(MarketBuyOrder)
            .where(
                MarketBuyOrder.buyer_id == user.id,
                MarketBuyOrder.status.in_((STATUS_FILLED, STATUS_CANCELLED, STATUS_EXPIRED)),
            )
            .order_by(MarketBuyOrder.closed_at.desc(), MarketBuyOrder.id.desc())
            .limit(50)
        )
    ).scalars().all()

    return {
        "active": [market.buy_order_to_dict(row, user.nickname) for row in active],
        "closed": [market.buy_order_to_dict(row, user.nickname) for row in closed],
        "activeCount": len(active),
        "maxActiveBuyOrders": market.max_active_buy_orders(),
        "feePct": market.fee_pct(),
    }


@router.post("/buy-orders")
async def create_buy_order(
    payload: BuyOrderCreateRequest, request: Request, db: DbSession, user: CurrentUser
) -> dict:
    """发布收购单：托管 unitPrice × quantity 金币求购某堆叠物。"""
    await guard_rate(db, "market_buy_order", str(user.id), 30, 60, "发布收购过于频繁，请稍后再试")

    lo, hi = market.min_price(), market.max_price()
    if not (lo <= payload.unitPrice <= hi):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"单价需在 {lo} ~ {hi} 之间"
        )
    if payload.quantity > market.max_stack_quantity():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"单笔求购数量不得超过 {market.max_stack_quantity()}",
        )
    if dohdol_util.sellable_kind(payload.itemId) != payload.kind:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="物品类型不匹配")

    order = await market.create_buy_order(
        db,
        user,
        payload.kind,
        payload.itemId,
        payload.quantity,
        payload.unitPrice,
        client_ip(request),
    )
    await db.commit()
    return {"gold": int(user.gold), "order": market.buy_order_to_dict(order, user.nickname)}


@router.post("/buy-orders/cancel")
async def cancel_buy_order(
    payload: BuyOrderCancelRequest, db: DbSession, user: CurrentUser
) -> dict:
    row = (
        await db.execute(
            select(MarketBuyOrder).where(MarketBuyOrder.id == payload.orderId).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="收购单不存在")
    if row.status != STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该收购单已结束")

    refund = await market.cancel_buy_order(db, user, row)
    return {"gold": int(user.gold), "refund": refund, "message": "已取消收购单"}


@router.post("/buy-orders/fill")
async def fill_buy_order(
    payload: BuyOrderFillRequest, db: DbSession, user: CurrentUser
) -> dict:
    """卖给收购单：按 count 部分 / 全部成交。"""
    await guard_rate(db, "market_fill", str(user.id), 60, 60, "出售过于频繁，请稍后再试")

    row = (
        await db.execute(
            select(MarketBuyOrder).where(MarketBuyOrder.id == payload.orderId).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="收购单不存在")
    if row.status != STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该收购单已结束")
    if market.is_expired(row):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该收购单已过期")

    return await market.fill_buy_order(db, user, row, payload.count)

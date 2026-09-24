"""Account-wide activity exclusion and roster operations."""
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import func, select, update
from app.models import User, Hero, Item, BattleSession, RaidSession, ActivitySession
from app.models.multiplayer import CoopMember, CoopRoom
from app.models.treasure import STATUS_ENDED, TreasureRun
from app.models.world_boss import SESSION_RUNNING, WorldBossSession
from app.services.game_config import CONFIG


def _roster_config() -> dict:
    return CONFIG.heroes.get("roster") or {}


def base_hero_capacity() -> int:
    """名册基准容量（不花金币即可拥有的席位数）。"""
    return int(_roster_config().get("baseCapacity", 8))


def max_hero_capacity() -> int:
    """名册容量上限。"""
    return int(_roster_config().get("maxCapacity", base_hero_capacity()))


def hero_capacity(user) -> int:
    """该账号当前名册容量（钳制在基准与上限之间）。"""
    value = int(getattr(user, "hero_capacity", 0) or 0)
    return max(base_hero_capacity(), min(max_hero_capacity(), value))


def hero_expand_cost(capacity: int) -> int | None:
    """从当前容量再开一席的金币价格；已达上限返回 None。价格线性递增。"""
    if capacity >= max_hero_capacity():
        return None
    first = int(_roster_config().get("firstExpandCost", 0))
    step = int(_roster_config().get("expandCostStep", 0))
    return first + (capacity - base_hero_capacity()) * step


async def expand_hero_roster(db, user) -> dict:
    """花费金币为该账号的名册扩充一席。"""
    capacity = hero_capacity(user)
    cost = hero_expand_cost(capacity)
    if cost is None:
        raise HTTPException(400, f"远征队席位已达上限（{max_hero_capacity()} 席）")
    if int(user.gold) < cost:
        raise HTTPException(400, f"金币不足，需要 {cost}")
    user.gold = int(user.gold) - cost
    user.hero_capacity = capacity + 1
    await db.flush()
    return {
        "gold": int(user.gold),
        "cost": cost,
        "capacity": capacity + 1,
        "maxCapacity": max_hero_capacity(),
        "expandCost": hero_expand_cost(capacity + 1),
    }


async def lock_user(db, user_id):
    return await db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))

async def require_idle_team(db, user_id):
    active = await db.scalar(select(CoopRoom.id).join(CoopMember, CoopMember.room_id == CoopRoom.id).where(
        CoopMember.user_id == user_id, CoopRoom.status == 'running').limit(1))
    if active:
        raise HTTPException(409, '团队战斗进行中，英雄和装备已锁定')
    # 世界BOSS 同样是服务端权威战斗：进行中锁定英雄与装备，与远征互斥。
    boss_active = await db.scalar(select(WorldBossSession.id).where(
        WorldBossSession.user_id == user_id, WorldBossSession.status == SESSION_RUNNING).limit(1))
    if boss_active:
        raise HTTPException(409, '世界BOSS 战斗进行中，英雄和装备已锁定')

async def end_treasure_runs(db, user_id):
    """结束该账号进行中的挖宝副本（已开箱入账的奖励不受影响）。"""
    await db.execute(update(TreasureRun).where(
        TreasureRun.user_id == user_id, TreasureRun.status != STATUS_ENDED
    ).values(status=STATUS_ENDED, ended_reason='superseded'))

async def stop_activities(db, user_id):
    now = datetime.now(timezone.utc)
    for model in (BattleSession, RaidSession, ActivitySession):
        await db.execute(update(model).where(model.user_id == user_id, model.active.is_(True)).values(active=False, ended_at=now))
    # 挖宝：开始其它活动 / 切换英雄 / 解雇时，进行中的副本一并结束。
    await end_treasure_runs(db, user_id)

async def owned_hero(db, user_id, hero_id):
    hero = await db.scalar(select(Hero).where(Hero.user_id == user_id, Hero.id == hero_id))
    if hero is None:
        raise HTTPException(404, '英雄不存在')
    return hero

async def dismiss_hero(db, user, hero_id):
    await require_idle_team(db, user.id)
    hero = await owned_hero(db, user.id, hero_id)
    total = await db.scalar(select(func.count()).select_from(Hero).where(Hero.user_id == user.id))
    if (total or 0) <= 1:
        raise HTTPException(400, '至少保留一名英雄，无法解雇')
    await stop_activities(db, user.id)
    await db.execute(update(Item).where(Item.equipped_hero_id == hero.id).values(equipped_slot=None, equipped_hero_id=None))
    if user.active_hero_id == hero.id:
        user.active_hero_id = await db.scalar(select(Hero.id).where(Hero.user_id == user.id, Hero.id != hero.id).order_by(Hero.id).limit(1))
        await db.flush()
    await db.delete(hero)

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from app.core.deps import CurrentUser, DbSession
from app.models import Hero, Item
from app.services.materia import socket_mods
from app.services.roster import (
    owned_hero,
    stop_activities,
    dismiss_hero,
    expand_hero_roster,
    hero_capacity,
    hero_expand_cost,
    max_hero_capacity,
)
from app.services.stats import compute_stats
from app.services.serialization import hero_to_dict, loadout
from app.api.v1.inventory import equip as inventory_equip, unequip as inventory_unequip
from app.schemas.game import UnequipRequest

router = APIRouter(prefix='/heroes', tags=['heroes'])

class HeroChoice(BaseModel):
    heroId: int

@router.get('')
async def roster(db: DbSession, user: CurrentUser):
    items = (await db.scalars(select(Item).where(Item.user_id == user.id))).all()
    heroes = (await db.scalars(select(Hero).where(Hero.user_id == user.id).order_by(Hero.id))).all()
    sockets = await socket_mods(db, user.id)
    capacity = hero_capacity(user)
    return {'activeHeroId': user.active_hero_id, 'capacity': capacity,
        'maxCapacity': max_hero_capacity(), 'expandCost': hero_expand_cost(capacity),
        'heroes': [
            {**hero_to_dict(h, compute_stats(h, items, sockets)), 'loadout': loadout(items, h.id)} for h in heroes]}

@router.post('/switch')
async def switch(payload: HeroChoice, db: DbSession, user: CurrentUser):
    hero = await owned_hero(db, user.id, payload.heroId)
    await stop_activities(db, user.id)
    user.active_hero_id = hero.id
    await db.commit()
    return {'activeHeroId': hero.id}

@router.post('/expand')
async def expand(db: DbSession, user: CurrentUser):
    """花费金币为远征队（英雄名册）扩充一席。"""
    result = await expand_hero_roster(db, user)
    await db.commit()
    return result

@router.post('/{hero_id}/equip')
async def equip(hero_id: int, payload: dict, db: DbSession, user: CurrentUser):
    hero = await owned_hero(db, user.id, hero_id)
    items = (await db.scalars(select(Item).where(Item.user_id == user.id))).all()
    return await inventory_equip(payload, db, user, hero, items, await socket_mods(db, user.id))

@router.post('/{hero_id}/unequip')
async def unequip(hero_id: int, payload: UnequipRequest, db: DbSession, user: CurrentUser):
    hero = await owned_hero(db, user.id, hero_id)
    items = (await db.scalars(select(Item).where(Item.user_id == user.id))).all()
    return await inventory_unequip(payload, db, user, hero, items, await socket_mods(db, user.id))

@router.delete('/{hero_id}')
async def dismiss(hero_id: int, db: DbSession, user: CurrentUser):
    await dismiss_hero(db, user, hero_id)
    await db.commit()
    return {'ok': True}

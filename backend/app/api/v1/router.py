"""v1 路由汇总。"""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    battle,
    chat,
    chest,
    codex,
    dohdol,
    economy,
    farm,
    friends,
    game,
    grants,
    inventory,
    market,
    materia,
    raid,
    ranking,
    redeem,
    region,
    sequences,
    settings,
    tags,
    tavern,
    treasure,
    tutorial,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(game.router)
api_router.include_router(grants.router)
api_router.include_router(battle.router)
api_router.include_router(inventory.router)
api_router.include_router(friends.router)
api_router.include_router(market.router)
api_router.include_router(chat.router)
api_router.include_router(chest.router)
api_router.include_router(economy.router)
api_router.include_router(region.router)
api_router.include_router(tavern.router)
api_router.include_router(codex.router)
api_router.include_router(ranking.router)
api_router.include_router(tutorial.router)
api_router.include_router(settings.router)
api_router.include_router(tags.router)
api_router.include_router(redeem.router)
api_router.include_router(raid.router)
api_router.include_router(dohdol.router)
api_router.include_router(materia.router)
api_router.include_router(farm.router)
api_router.include_router(treasure.router)
api_router.include_router(sequences.router)
api_router.include_router(admin.router)

from app.api.v1 import heroes, registrations, pvp, coop, worldboss
for module in (heroes, registrations, pvp, coop, worldboss):
    api_router.include_router(module.router)

"""v1 路由汇总。"""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    battle,
    chest,
    codex,
    dohdol,
    economy,
    game,
    inventory,
    raid,
    ranking,
    redeem,
    region,
    settings,
    tags,
    tavern,
    tutorial,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(game.router)
api_router.include_router(battle.router)
api_router.include_router(inventory.router)
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
api_router.include_router(admin.router)

from app.api.v1 import heroes, registrations, pvp, coop
for module in (heroes, registrations, pvp, coop):
    api_router.include_router(module.router)

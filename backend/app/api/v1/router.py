"""v1 路由汇总。"""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    battle,
    chest,
    codex,
    economy,
    game,
    inventory,
    ranking,
    redeem,
    region,
    settings,
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
api_router.include_router(redeem.router)

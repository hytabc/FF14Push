"""英雄经验与升级。来源：PRD 2.11"""

from __future__ import annotations

from typing import Any

from app.services.game_config import CONFIG

LEVEL_CAP = int(CONFIG.heroes["levelCap"])


def exp_to_next(level: int) -> int:
    cfg = CONFIG.heroes["expCurve"]
    return max(1, round(float(cfg["base"]) * float(cfg["growth"]) ** max(0, level - 1)))


def exp_to_next_cached(level: int) -> int:
    return exp_to_next(level)


def apply_exp(hero: Any, amount: int) -> dict[str, int]:
    """结算经验，返回升级信息。"""
    if amount <= 0:
        return {"levelsGained": 0, "exp": hero.exp, "level": hero.level}

    hero.exp += int(amount)
    gained = 0
    while hero.level < LEVEL_CAP:
        need = exp_to_next(hero.level)
        if hero.exp < need:
            break
        hero.exp -= need
        hero.level += 1
        gained += 1
    if hero.level >= LEVEL_CAP:
        hero.exp = 0
    return {"levelsGained": gained, "exp": hero.exp, "level": hero.level}

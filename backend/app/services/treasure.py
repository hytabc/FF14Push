"""挖宝：5 层副本的服务端权威状态机。

- 每层怪物 = 难度(层-1) 的地区 40 关底 BOSS（`regions_util.boss_stats`），玩家侧不套用难度削弱。
- 门的 50/50、宝箱内容与猜大小结果全部由服务端结算；客户端只模拟每层战斗并上报「已击败」。
- 宝箱在开箱时 roll 并**立即入账**，因此选错门 / 阵亡都不会影响已获得的奖励。
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Hero, Item, TreasureRun, User
from app.models.treasure import STATUS_CLEARED, STATUS_ENDED, STATUS_FIGHTING
from app.services import consumables, dohdol_util, titles
from app.services.difficulty import monster_exp_multiplier, monster_gold_multiplier
from app.services.egg_heroes import treasure_gold_bonus
from app.services.game_config import CONFIG
from app.services.playtime import add_play_ms
from app.services.progression import apply_exp, combat_exp
from app.services.regions_util import apply_exp_bonus, boss_stats, roll_gold
from app.services.roster import stop_activities

# 单层在线时长计入上限（服务端窗口，防挂机刷时长）。
MAX_FLOOR_PLAY_MS = 30 * 60 * 1000


def _cfg() -> dict[str, Any]:
    return CONFIG.treasure


def entry_cost() -> int:
    return int(_cfg()["entryCost"])


def floors() -> int:
    return int(_cfg()["floors"])


def doors() -> int:
    return int(_cfg()["doors"])


def correct_chance() -> float:
    return float(_cfg()["correctChance"])


def source_region_id() -> int:
    return int(_cfg()["sourceRegionId"])


def max_guesses() -> int:
    return int(_cfg()["maxGuesses"])


def config_view() -> dict[str, Any]:
    """把挖宝数值原样下发（前端用于展示概率与「?」说明，与结算同源）。"""
    cfg = _cfg()
    return {
        key: cfg[key]
        for key in (
            "entryCost",
            "floors",
            "doors",
            "correctChance",
            "sourceRegionId",
            "goldMultiplier",
            "expMultiplier",
            "finalBonusGold",
            "specialEventChance",
            "cardMin",
            "cardMax",
            "maxGuesses",
            "rewardIncreasePerGuess",
            "tieIsLoss",
            "rewardWeights",
            "rewardsPerFloor",
            "stackQtyPerFloor",
            "potionTierByFloor",
            "materiaLevelByFloor",
        )
    }


def boss_for_floor(floor: int) -> dict[str, Any]:
    """本层怪物：难度(层-1) 的地区 40 关底 BOSS（难度倍率已烘焙进数值，玩家侧不再缩放）。"""
    difficulty = max(0, min(15, int(floor) - 1))
    return boss_stats(source_region_id(), difficulty)


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:  # SQLite 返回 naive datetime
        return moment.replace(tzinfo=timezone.utc)
    return moment


async def active_run(db: AsyncSession, user_id: int) -> TreasureRun | None:
    return (
        await db.execute(
            select(TreasureRun)
            .where(TreasureRun.user_id == user_id, TreasureRun.status != STATUS_ENDED)
            .order_by(TreasureRun.id.desc())
        )
    ).scalars().first()


async def load_run(db: AsyncSession, user_id: int, run_id: int) -> TreasureRun:
    run = (
        await db.execute(
            select(TreasureRun).where(TreasureRun.id == run_id, TreasureRun.user_id == user_id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="挖宝副本不存在")
    return run


def run_view(run: TreasureRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "runId": int(run.id),
        "floor": int(run.floor),
        "status": run.status,
        "multiplier": round(float(run.multiplier or 0.0), 3),
        "card": int(run.card) if run.card is not None else None,
        "guessesUsed": int(run.guesses_used or 0),
        "maxGuesses": max_guesses(),
        "eventActive": bool(run.event_active),
        "chestOpened": bool(run.chest_opened),
        "endedReason": run.ended_reason,
        "boss": boss_for_floor(int(run.floor)) if run.status == STATUS_FIGHTING else None,
    }


async def state(db: AsyncSession, user_id: int) -> dict[str, Any]:
    return {"config": config_view(), "run": run_view(await active_run(db, user_id))}


# ------------------------------------------------------------------ 流程
async def start(db: AsyncSession, user: User, hero: Hero | None) -> dict[str, Any]:
    cost = entry_cost()
    if int(user.gold) < cost:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"金币不足，需要 {cost}"
        )

    # 四活动互斥：进入挖宝即结束其它活动与上一次未完成的挖宝。
    await stop_activities(db, user.id)
    await dohdol_util.end_active_sessions(db, user.id)

    user.gold = int(user.gold) - cost
    now = datetime.now(timezone.utc)
    run = TreasureRun(
        user_id=user.id,
        hero_id=hero.id if hero is not None else None,
        floor=1,
        status=STATUS_FIGHTING,
        multiplier=1.0,
        floor_started_at=now,
    )
    db.add(run)
    await db.flush()
    return {"cost": cost, "gold": int(user.gold), "run": run_view(run)}


async def retry(db: AsyncSession, user: User, run: TreasureRun) -> dict[str, Any]:
    if run.status != STATUS_FIGHTING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="当前层无需重试"
        )
    run.floor_started_at = datetime.now(timezone.utc)
    await db.flush()
    return {"run": run_view(run)}


async def abandon(db: AsyncSession, user: User, run: TreasureRun) -> dict[str, Any]:
    if run.status == STATUS_ENDED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="副本已结束")
    run.status = STATUS_ENDED
    run.ended_reason = "abandoned"
    await db.flush()
    return {"run": run_view(run)}


async def clear_floor(db: AsyncSession, user: User, run: TreasureRun) -> dict[str, Any]:
    """击败本层怪物：校验服务端计时，并判定是否触发猜大小事件。"""
    if run.status != STATUS_FIGHTING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="当前状态无法结算本层"
        )

    started = _as_utc(run.floor_started_at or run.created_at)
    elapsed_ms = int(max(0.0, (datetime.now(timezone.utc) - started).total_seconds() * 1000))
    if elapsed_ms < int(_cfg().get("minFloorFightMs", 0)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="战斗时长异常")

    add_play_ms(user, min(elapsed_ms, MAX_FLOOR_PLAY_MS))
    run.status = STATUS_CLEARED
    run.chest_opened = False
    run.multiplier = 1.0
    run.card = None
    run.guesses_used = 0
    run.event_active = False

    event = None
    if random.random() < float(_cfg()["specialEventChance"]):
        run.card = random.randint(int(_cfg()["cardMin"]), int(_cfg()["cardMax"]))
        run.event_active = True
        event = {
            "card": int(run.card),
            "maxGuesses": max_guesses(),
            "rewardIncreasePerGuess": float(_cfg()["rewardIncreasePerGuess"]),
        }
    await db.flush()
    return {"event": event, "run": run_view(run)}


async def gamble(db: AsyncSession, user: User, run: TreasureRun, guess: str) -> dict[str, Any]:
    if not run.event_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前没有猜大小事件")

    previous = int(run.card or 0)
    card = random.randint(int(_cfg()["cardMin"]), int(_cfg()["cardMax"]))
    run.card = card
    run.guesses_used = int(run.guesses_used or 0) + 1
    tie_is_loss = bool(_cfg()["tieIsLoss"])

    cleared = False
    if card == previous and not tie_is_loss:
        result = "tie"
    else:
        correct = card > previous if guess == "high" else card < previous
        if card == previous:  # tieIsLoss
            correct = False
        if correct:
            result = "win"
            run.multiplier = float(run.multiplier or 0.0) + float(
                _cfg()["rewardIncreasePerGuess"]
            )
        else:
            result = "lose"
            run.multiplier = 0.0  # 猜错：当前层宝箱奖励清零
            cleared = True

    finished = cleared or int(run.guesses_used) >= max_guesses()
    if finished:
        run.event_active = False
    await db.flush()
    return {
        "previousCard": previous,
        "card": card,
        "result": result,
        "multiplier": round(float(run.multiplier or 0.0), 3),
        "guessesUsed": int(run.guesses_used),
        "guessesLeft": max(0, max_guesses() - int(run.guesses_used)),
        "cleared": cleared,
        "finished": finished,
        "run": run_view(run),
    }


async def stop_gamble(db: AsyncSession, user: User, run: TreasureRun) -> dict[str, Any]:
    if not run.event_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前没有猜大小事件")
    run.event_active = False
    await db.flush()
    return {"run": run_view(run)}


# ------------------------------------------------------------------ 宝箱
def _potion_tier(potion_id: str) -> int:
    return int(potion_id[-1]) if potion_id[-1].isdigit() else 1


def _potion_ids_for_tier(tier: int) -> list[str]:
    return [
        item["id"]
        for item in CONFIG.consumables["items"]
        if item["kind"] == "potion" and _potion_tier(item["id"]) == tier
    ]


def _materia_ids_for_floor(floor: int) -> list[str]:
    ranges = _cfg()["materiaLevelByFloor"]
    low, high = ranges[min(len(ranges), max(1, floor)) - 1]
    return [
        f"m_{mtype['id']}_{level}"
        for mtype in CONFIG.materia["types"]
        for level in range(int(low), int(high) + 1)
    ]


def _pick_kind(rng: random.Random) -> str:
    weights = _cfg()["rewardWeights"]
    total = sum(max(0.0, float(value)) for value in weights.values())
    roll = rng.random() * total
    cumulative = 0.0
    picked = next(iter(weights))
    for kind, weight in weights.items():
        cumulative += max(0.0, float(weight))
        if roll < cumulative:
            picked = kind
            break
    return picked


def _entries_for_floor(floor: int) -> int:
    spec = _cfg()["rewardsPerFloor"]
    return max(1, int(spec["base"]) + int(spec["perFloor"]) * (floor - 1))


def _qty_for_floor(floor: int, rng: random.Random) -> int:
    spec = _cfg()["stackQtyPerFloor"]
    base = int(spec["base"]) + int(spec["perFloor"]) * (floor - 1)
    return max(1, base)


async def open_chest(
    db: AsyncSession,
    user: User,
    hero: Hero | None,
    run: TreasureRun,
    term_mods: dict[str, float],
) -> dict[str, Any]:
    if run.status != STATUS_CLEARED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="尚未通关本层")
    if run.event_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先结束猜大小事件")
    if run.chest_opened:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="本层宝箱已开启")

    floor = int(run.floor)
    difficulty = max(0, floor - 1)
    multiplier = float(run.multiplier or 0.0)
    rng = random.Random()
    # 彩蛋被动「金主」：挖宝所有金币奖励 +value（含下底附赠），0.1 = +10%。
    gold_factor = 1.0 + treasure_gold_bonus(hero.egg_id if hero is not None else None)

    gold_base = (
        roll_gold(source_region_id(), "boss", 0.0, rng)
        * monster_gold_multiplier(difficulty)
    )
    gold_bonus = 1.0 + max(0.0, float(term_mods.get("goldGainPct", 0.0))) / 100.0
    gold_unit = gold_base * float(_cfg()["goldMultiplier"]) * gold_bonus
    exp_base = gold_base * float(CONFIG.monsters["xpPerGold"]) * monster_exp_multiplier(difficulty)
    exp_unit = apply_exp_bonus(
        max(1, int(exp_base * float(_cfg()["expMultiplier"]))), term_mods
    )

    rewards: list[dict[str, Any]] = []
    gold_total = 0
    exp_total = 0
    bonus_gold = 0

    if multiplier <= 0:
        # 猜错：当前层宝箱奖励清空（金币 / 经验 / 物品一律不入账）。
        run.chest_opened = True
        completed = floor >= floors()
        if completed:
            bonus_gold = int(_cfg()["finalBonusGold"] * gold_factor)
            user.gold = int(user.gold) + bonus_gold
            rewards.append({"kind": "bonusGold", "amount": bonus_gold})
            run.status = STATUS_ENDED
            run.ended_reason = "completed"
        # 彩蛋称号：下底（通关第 5 层）时极低概率掉落。
        new_titles = (
            await titles.roll_random_titles(db, user.id, "treasure_bottom") if completed else []
        )
        await db.flush()
        return {
            "floor": floor,
            "multiplier": 0.0,
            "rewards": rewards,
            "gold": int(user.gold),
            "goldGained": bonus_gold,
            "expGained": 0,
            "level": None,
            "bonusGold": bonus_gold,
            "completed": completed,
            "cleared": True,
            "newTitles": new_titles,
            "run": run_view(run),
        }

    for _ in range(_entries_for_floor(floor)):
        kind = _pick_kind(rng)
        if kind == "gold":
            amount = int(gold_unit * multiplier * gold_factor)
            gold_total += amount
            rewards.append({"kind": "gold", "amount": amount})
        elif kind == "exp":
            amount = int(exp_unit * multiplier)
            exp_total += amount
            rewards.append({"kind": "exp", "amount": amount})
        elif kind == "potion":
            tier = int(_cfg()["potionTierByFloor"][min(len(_cfg()["potionTierByFloor"]), floor) - 1])
            pool = _potion_ids_for_tier(tier)
            item_id = rng.choice(pool)
            count = _qty_for_floor(floor, rng)
            await dohdol_util.stack_add(db, user.id, dohdol_util.STACK_POTION, item_id, count)
            rewards.append(
                {
                    "kind": "potion",
                    "itemId": item_id,
                    "name": dohdol_util.material_name(item_id),
                    "count": count,
                    "tier": tier,
                }
            )
        elif kind == "materia":
            item_id = rng.choice(_materia_ids_for_floor(floor))
            count = _qty_for_floor(floor, rng)
            await dohdol_util.stack_add(db, user.id, dohdol_util.STACK_MATERIA, item_id, count)
            view = CONFIG.materia_by_id[item_id]
            rewards.append(
                {
                    "kind": "materia",
                    "itemId": item_id,
                    "name": view["name"],
                    "count": count,
                    "level": int(view["level"]),
                    "stat": view["stat"],
                    "statName": view["statName"],
                    "value": float(view["value"]),
                }
            )
        else:  # seed
            seed = rng.choice(CONFIG.farm["seeds"])
            count = _qty_for_floor(floor, rng)
            await dohdol_util.stack_add(db, user.id, dohdol_util.STACK_SEED, seed["id"], count)
            rewards.append(
                {"kind": "seed", "itemId": seed["id"], "name": seed["name"], "count": count}
            )

    # 通关第 5 层：额外赠送金币（「除了宝箱奖励，还附赠」，不受猜大小倍率影响）。
    if floor >= floors():
        bonus_gold = int(_cfg()["finalBonusGold"] * gold_factor)
        if bonus_gold:
            gold_total += bonus_gold
            rewards.append({"kind": "bonusGold", "amount": bonus_gold})

    if gold_total:
        user.gold = int(user.gold) + gold_total

    level_info = None
    exp_gained = 0
    if exp_total > 0 and hero is not None:
        exp_gained = await combat_exp(db, hero, exp_total)
        level_info = apply_exp(hero, exp_gained)

    run.chest_opened = True
    completed = floor >= floors()
    if completed:
        run.status = STATUS_ENDED
        run.ended_reason = "completed"
    # 彩蛋称号：下底（通关第 5 层）时极低概率掉落。
    new_titles = (
        await titles.roll_random_titles(db, user.id, "treasure_bottom") if completed else []
    )
    await db.flush()

    return {
        "floor": floor,
        "multiplier": round(multiplier, 3),
        "rewards": rewards,
        "gold": int(user.gold),
        "goldGained": gold_total,
        "expGained": exp_gained,
        "level": level_info,
        "bonusGold": bonus_gold,
        "completed": completed,
        "newTitles": new_titles,
        "run": run_view(run),
    }


async def choose_door(
    db: AsyncSession, user: User, run: TreasureRun, door: int
) -> dict[str, Any]:
    if run.status != STATUS_CLEARED or not run.chest_opened:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先开启本层宝箱")
    if int(run.floor) >= floors():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已是最后一层")
    if not 0 <= door < doors():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="门不存在")

    correct = random.random() < correct_chance()
    if correct:
        run.floor = int(run.floor) + 1
        run.status = STATUS_FIGHTING
        run.chest_opened = False
        run.multiplier = 1.0
        run.card = None
        run.guesses_used = 0
        run.event_active = False
        run.floor_started_at = datetime.now(timezone.utc)
    else:
        # 选错门：退出副本，但已开箱入账的奖励保留。
        run.status = STATUS_ENDED
        run.ended_reason = "wrong_door"
    await db.flush()
    return {"correct": correct, "door": door, "run": run_view(run)}

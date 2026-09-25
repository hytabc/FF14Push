"""远征通关记录的持久化。

通关瞬间（服务端权威模拟结束后）由 worker 调用 `record_clear`，把
`coop_battles.state` 里的分角色战斗信息与通关时长抽取成可查询的
`coop_records` 行，供「远征榜」按副本展示通关时长与阵容。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.multiplayer import CoopBattle, CoopRecord, CoopRoom


def build_party(state: dict, nicknames: dict[int, str]) -> list[dict]:
    """把战斗状态里的全部席位抽成紧凑的阵容快照（含分角色战斗信息）。"""
    party: list[dict] = []
    for hero in state.get("heroes", []):
        snap = hero["snapshot"]
        owner_id = int(snap.get("ownerId", hero.get("controllerId", 0)))
        party.append(
            {
                "slot": int(hero["slot"]),
                "heroId": int(snap.get("heroId", 0)),
                "ownerId": owner_id,
                "account": nicknames.get(owner_id, ""),
                "name": snap.get("name", ""),
                "jobId": snap.get("jobId", ""),
                "role": snap.get("role", "dps"),
                "level": int(snap.get("level", 1)),
                "clone": bool(hero.get("clone")),
                "damage": round(float(hero.get("damage", 0.0))),
                "healing": round(float(hero.get("healing", 0.0))),
                "damageTaken": round(float(hero.get("damageTaken", 0.0))),
                "deaths": int(hero.get("deaths", 0)),
                "minHpRatio": round(float(hero.get("minHpRatio", 1.0)), 4),
                "dangerMs": int(hero.get("dangerMs", 0)),
            }
        )
    return party


async def record_clear(db: AsyncSession, room: CoopRoom, battle: CoopBattle, now: float) -> None:
    """通关时写入记录；每个真实参战账号一行，重复调用幂等。"""
    if battle is None or battle.status != "cleared":
        return
    state = battle.state
    heroes = state.get("heroes", [])
    if not heroes:
        return

    owner_ids = {int(h["snapshot"].get("ownerId", 0)) for h in heroes}
    owner_ids.discard(0)
    nicknames: dict[int, str] = {}
    if owner_ids:
        rows = (await db.execute(select(User.id, User.nickname).where(User.id.in_(owner_ids)))).all()
        nicknames = {row.id: row.nickname for row in rows}

    party = build_party(state, nicknames)
    clear_ms = int(state.get("elapsedMs", 0))
    had_clone = bool(state.get("hadClone"))

    # 真实参战账号：排除外部克隆席位（与 coop_rewards 的奖励口径一致）
    accounts = {int(h["controllerId"]) for h in heroes if not h.get("registeredClone")}
    for user_id in accounts:
        existing = await db.scalar(
            select(CoopRecord.id).where(
                CoopRecord.battle_id == battle.id, CoopRecord.user_id == user_id
            )
        )
        if existing is not None:
            continue
        db.add(
            CoopRecord(
                battle_id=battle.id,
                room_id=room.id,
                user_id=user_id,
                dungeon_id=room.dungeon_id,
                mode=room.mode,
                had_clone=had_clone,
                clear_ms=clear_ms,
                party=party,
                created_at=now,
            )
        )
    await db.flush()
    # 远征榜是实时聚合：通关记录写入后失效进程内缓存，刚通关即可见。
    from app.services.ranking import invalidate_live_rankings

    invalidate_live_rankings()

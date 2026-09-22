"""开发用（只读）：读取线上玩家数据分布，作为高难副本难度/奖励的标定基准。

连接 `DATABASE_URL`（或仓库根目录 `.env` 里的 `POSTGRES_*`），**只执行 SELECT**，
不会写入 / 修改任何数据。输出：

- 英雄数量与等级分布；
- 每个等级的战力分布（中位数 / 最大值），战力口径与游戏内一致（`hero_power`）；
- 满级（Lv100）英雄的战力与三维，用于确认高难门槛锚点。

运行：`python scripts/raid-player-baseline.py`
（需要能连通数据库；本地 docker 部署可先 `docker compose up -d db`）
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.progression import LEVEL_CAP  # noqa: E402
from app.services.stats import compute_stats  # noqa: E402
from app.services.valuation import hero_power  # noqa: E402


def _load_env_file() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _database_url() -> str:
    _load_env_file()
    url = os.environ.get("DATABASE_URL")
    if not url:
        user = os.environ.get("POSTGRES_USER", "eorzea")
        password = os.environ.get("POSTGRES_PASSWORD", "eorzea")
        host = os.environ.get("POSTGRES_HOST", "localhost")
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB", "eorzea")
        url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")


HERO_SQL = """
    SELECT id, user_id, level, talent, attr_bias, strength, agility, intellect, ancient_attr, egg_id
    FROM heroes
"""
ITEM_SQL = """
    SELECT equipped_hero_id, rarity, base_attrs, sub_attrs, terms, equipped_slot, category, slot,
           level_req, base_id
    FROM items
    WHERE equipped_hero_id IS NOT NULL
"""


def _hex_to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _item(row: Any) -> SimpleNamespace:
    return SimpleNamespace(
        rarity=row["rarity"],
        base_attrs=row["base_attrs"] or [],
        sub_attrs=row["sub_attrs"] or [],
        terms=row["terms"] or [],
        equipped_slot=row["equipped_slot"],
        category=row["category"],
        slot=row["slot"],
        level_req=row["level_req"],
        base_id=row["base_id"],
    )


async def main() -> None:
    import asyncpg

    conn = await asyncpg.connect(_database_url())
    try:
        for type_name in ("json", "jsonb"):
            await conn.set_type_codec(
                type_name, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
            )
        heroes = await conn.fetch(HERO_SQL)
        items = await conn.fetch(ITEM_SQL)
    finally:
        await conn.close()

    equipped: dict[int, list[SimpleNamespace]] = {}
    for row in items:
        equipped.setdefault(int(row["equipped_hero_id"]), []).append(_item(row))

    per_level: dict[int, list[int]] = {}
    full_level: list[tuple[int, int, tuple[int, int, int]]] = []
    for row in heroes:
        level = int(row["level"] or 1)
        hero = SimpleNamespace(
            level=level,
            talent=row["talent"],
            attr_bias=row["attr_bias"],
            strength=_hex_to_int(row["strength"]),
            agility=_hex_to_int(row["agility"]),
            intellect=_hex_to_int(row["intellect"]),
            ancient_attr=row["ancient_attr"],
            egg_id=row["egg_id"],
        )
        try:
            power = int(hero_power(compute_stats(hero, equipped.get(int(row["id"]), []))))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! hero {row['id']} 战力计算失败: {exc}")
            continue
        per_level.setdefault(level, []).append(power)
        if level >= LEVEL_CAP:
            full_level.append(
                (
                    power,
                    hero.strength + hero.agility + hero.intellect,
                    (hero.strength, hero.agility, hero.intellect),
                )
            )

    total_items = sum(len(v) for v in equipped.values())
    print(f"英雄数={len(heroes)} 已装备物品数={total_items}")
    print("等级分布（等级 人数 战力中位数 战力最大值）：")
    for level in sorted(per_level):
        powers = per_level[level]
        print(
            f"  Lv{level:<4d} n={len(powers):<4d} median={int(statistics.median(powers)):<8d} "
            f"max={max(powers):<8d}"
        )
    if full_level:
        print(f"满级 Lv{LEVEL_CAP} 英雄 {len(full_level)} 个（战力 三维和 三维）：")
        for power, total, attrs in sorted(full_level, reverse=True):
            print(f"  战力={power:<8d} 三维和={total:<5d} str/dex/int={attrs[0]}/{attrs[1]}/{attrs[2]}")
    else:
        print(f"没有满级（Lv{LEVEL_CAP}）英雄。")


if __name__ == "__main__":
    asyncio.run(main())

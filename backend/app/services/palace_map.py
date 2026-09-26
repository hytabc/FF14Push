"""死者宫殿：每层路径图（DAG）的生成与合法性校验。

每层 10 步（第 10 步固定为层 BOSS），行内 1–3 个节点，边可 1对1 / 1对多 / 多对1。
生成一次后存入 run 快照，服务端据此校验玩家的每一次选择。
"""

from __future__ import annotations

import random
from typing import Any

from app.services.game_config import CONFIG

# 非战斗节点类型（进入即可结算，不需战斗）。
NON_BATTLE_TYPES = {"event", "shop", "chest", "rest"}
BATTLE_TYPES = {"battle", "elite", "boss"}


def _cfg() -> dict[str, Any]:
    return CONFIG.palace


def steps_per_floor() -> int:
    return int(_cfg()["stepsPerFloor"])


def _weights_for_step(step: int) -> dict[str, float]:
    bands = _cfg()["nodeTypeWeights"]
    chosen = bands[-1]
    for band in bands:
        if step <= int(band["maxStep"]):
            chosen = band
            break
    return {str(k): float(v) for k, v in chosen["weights"].items()}


def _pick_type(step: int, rng: random.Random) -> str:
    weights = _weights_for_step(step)
    roll = rng.random()
    cumulative = 0.0
    picked = next(iter(weights))
    for kind, weight in weights.items():
        cumulative += weight
        if roll < cumulative:
            picked = kind
            break
    return picked


def generate_map(floor: int, rng: random.Random | None = None) -> dict[str, Any]:
    """生成第 floor 层的路径图。"""
    rng = rng or random.Random()
    steps = steps_per_floor()
    rows: list[dict[str, Any]] = []
    for step in range(1, steps + 1):
        if step == steps:
            nodes = [{"id": f"{step}-0", "type": "boss"}]
        else:
            count = rng.choice([1, 2, 3]) if step > 1 else rng.choice([2, 3])
            nodes = [
                {"id": f"{step}-{i}", "type": _pick_type(step, rng)} for i in range(count)
            ]
        rows.append({"step": step, "nodes": nodes})

    edges: list[dict[str, str]] = []
    for i in range(steps - 1):
        cur = [n["id"] for n in rows[i]["nodes"]]
        nxt = [n["id"] for n in rows[i + 1]["nodes"]]
        pairs: set[tuple[str, str]] = set()
        # 先保证每个后继至少有一条入边（覆盖 多对1 / 1对1）
        for k, node_id in enumerate(nxt):
            pairs.add((cur[k % len(cur)], node_id))
        # 再保证每个当前节点至少有一条出边（可能是 1对多）
        for node_id in cur:
            if not any(pair[0] == node_id for pair in pairs):
                pairs.add((node_id, rng.choice(nxt)))
        # 随机加一些分支（1对多）
        for node_id in cur:
            if len(nxt) > 1 and rng.random() < 0.5:
                pairs.add((node_id, rng.choice(nxt)))
        edges.extend({"from": a, "to": b} for a, b in sorted(pairs))

    return {"floor": int(floor), "rows": rows, "edges": edges}


def find_node(game_map: dict[str, Any] | None, node_id: str) -> dict[str, Any] | None:
    if not game_map:
        return None
    for row in game_map.get("rows", []):
        for node in row["nodes"]:
            if node["id"] == node_id:
                return node
    return None


def node_step(game_map: dict[str, Any] | None, node_id: str) -> int | None:
    if not game_map:
        return None
    for row in game_map.get("rows", []):
        for node in row["nodes"]:
            if node["id"] == node_id:
                return int(row["step"])
    return None


def start_ids(game_map: dict[str, Any] | None) -> list[str]:
    if not game_map or not game_map.get("rows"):
        return []
    return [n["id"] for n in game_map["rows"][0]["nodes"]]


def next_ids(game_map: dict[str, Any] | None, node_id: str | None) -> list[str]:
    """node_id 为 None 时返回本层起点节点。"""
    if node_id is None:
        return start_ids(game_map)
    return [e["to"] for e in (game_map or {}).get("edges", []) if e["from"] == node_id]


def is_reachable(game_map: dict[str, Any] | None, node_id: str) -> bool:
    return node_id in {n["id"] for row in (game_map or {}).get("rows", []) for n in row["nodes"]}

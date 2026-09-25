"""世界BOSS 确定性模拟引擎（100ms tick）。

纯 JSON 输入/输出，无墙钟、无 DB。服务端唯一权威：客户端只提交「上阵英雄」，
伤害与英雄存亡全部在这里计算。BOSS 的全局血量不在此 state 内，由 worker 用
`state['damageDealt']` 的增量对全局单行做原子递减。

规则（来源：需求「世界BOSS」）：
- 单个 BOSS；BOSS 普攻按固定间隔对**全部存活英雄**造成伤害。
- BOSS 技能按固定间隔**随机抽取**释放，与普攻计时完全独立。
- 每个英雄独立结算死亡与复活（reviveSeconds）。
- 80~99 级英雄输出/治疗按 levelMultiplier 削弱，满级不变。
"""

from __future__ import annotations

from copy import deepcopy

from app.services.coop_engine import shield_cap_pct

TICK = 100
BASIC_CD_MS = 2000
GCD_MS = 1500

STATUS_RUNNING = "running"


def random_unit(state: dict) -> float:
    state["rng"] = (1664525 * state["rng"] + 1013904223) & 0xFFFFFFFF
    return state["rng"] / 4294967296


def event(state: dict, kind: str, text: str, **data) -> None:
    state["eventSequence"] += 1
    state["events"].append(
        {"seq": state["eventSequence"], "at": state["elapsedMs"], "kind": kind, "text": text, **data}
    )
    state["events"] = state["events"][-200:]


def new_state(config: dict, snapshots: list[dict], seed: int = 20260924) -> dict:
    """用上阵英雄快照构造初始 state。snapshots 为 coop_snapshot 生成的快照（含 levelMultiplier）。"""
    boss_cfg = config["boss"]
    state: dict = {
        "version": config["version"],
        "elapsedMs": 0,
        "status": STATUS_RUNNING,
        "rng": seed,
        "eventSequence": 0,
        "events": [],
        "heroes": [],
        "damageDealt": 0.0,
        "reviveSeconds": int(boss_cfg["reviveSeconds"]),
        # 阶段：由全局剩余血量占比决定（worker 每批推进前写入 bossHpRatio）。
        "bossHpRatio": 1.0,
        "phase": 1,
        "defenseMultiplier": 1.0,
        "skillPotencyMultiplier": 1.0,
        "boss": {
            "nextAttack": int(boss_cfg["attackIntervalSeconds"] * 1000),
            "nextSkill": int(boss_cfg["skillIntervalSeconds"] * 1000),
            "attackBuff": 0.0,
            "attackBuffUntil": 0,
            "damageReduce": 0.0,
            "damageReduceUntil": 0,
            "pendingSkill": None,
            "skillCasts": 0,
            "lastSkill": None,
        },
    }
    for slot, snap in enumerate(snapshots):
        stats = snap["stats"]
        state["heroes"].append(
            {
                "slot": slot,
                "snapshot": deepcopy(snap),
                "levelMultiplier": float(snap.get("levelMultiplier", 1.0)),
                "hp": float(stats["max_hp"]),
                "mp": float(stats["max_mp"]),
                "shield": 0.0,
                "deadUntil": 0,
                "cooldowns": {},
                "lastCastAt": {},
                "nextAttack": 0,
                "gcdUntil": 0,
                "nextHeal": 0,
                "buffs": [],
                "dots": [],
                "slow": [],
                "damage": 0.0,
                "healing": 0.0,
                "damageTaken": 0.0,
                "minHpRatio": 1.0,
                "deaths": 0,
            }
        )
    return state


def resolve_phase(state: dict, config: dict) -> None:
    """按剩余血量占比结算当前阶段：血量越低，BOSS 防御越厚（英雄输出折算）、技能威力越高。

    `bossHpRatio` 由 worker 每批推进前用全局血量写入；阶段切换时记录事件。
    """
    table = config.get("phases") or []
    ratio = float(state.get("bossHpRatio", 1.0))
    if not table:
        return
    phase = max(
        table, key=lambda p: float(p["minHpRatio"]) if float(p["minHpRatio"]) <= ratio else -1.0
    )
    state["defenseMultiplier"] = float(phase["defenseMultiplier"])
    state["skillPotencyMultiplier"] = float(phase["skillPotencyMultiplier"])
    if int(phase["id"]) != int(state.get("phase", 1)):
        state["phase"] = int(phase["id"])
        event(
            state,
            "phase",
            f"BOSS 进入{phase['name']}：防御 ×{phase['defenseMultiplier']}、技能威力 ×{phase['skillPotencyMultiplier']}",
            phase=int(phase["id"]),
        )


def boss_attack_power(state: dict, config: dict) -> float:
    boss = state["boss"]
    base = float(config["boss"]["attack"])
    if boss["attackBuffUntil"] > state["elapsedMs"]:
        base *= 1.0 + float(boss["attackBuff"])
    return base


def boss_damage_taken_factor(state: dict) -> float:
    """英雄输出折算：BOSS 主动减伤 × 当前阶段防御（defenseMultiplier 越高，英雄输出越低）。"""
    factor = 1.0
    boss = state["boss"]
    if boss["damageReduceUntil"] > state["elapsedMs"]:
        factor *= max(0.0, 1.0 - float(boss["damageReduce"]))
    factor /= max(1e-6, float(state.get("defenseMultiplier", 1.0)))
    return factor


def deal_damage(state: dict, hero: dict, amount: float) -> None:
    """英雄对 BOSS 造成伤害（计入本会话累计；BOSS 减伤与阶段防御生效）。"""
    value = max(0.0, float(amount)) * boss_damage_taken_factor(state)
    hero["damage"] += value
    state["damageDealt"] += value


def heal_hero(state: dict, hero: dict, amount: float) -> None:
    if hero["hp"] <= 0:
        return
    value = max(0.0, float(amount)) * hero["levelMultiplier"]
    actual = min(value, hero["snapshot"]["stats"]["max_hp"] - hero["hp"])
    hero["hp"] += actual
    hero["healing"] += actual


def damage_hero(state: dict, hero: dict, amount: float, source: str) -> None:
    if hero["hp"] <= 0:
        return
    reduction = max(
        [b["value"] for b in hero["buffs"] if b["type"] == "damageReduction" and b["until"] > state["elapsedMs"]]
        + [0.0]
    )
    value = max(0.0, float(amount)) * (1.0 - min(0.8, reduction))
    max_hp = hero["snapshot"]["stats"]["max_hp"]
    absorbed = min(hero["shield"], value)
    hero["shield"] -= absorbed
    value -= absorbed
    hero["damageTaken"] += min(hero["hp"], value)
    # 生命值以整数结算：伤害后向下取整，避免残留 (0,1) 区间的小数生命值让英雄
    # 「显示 0 血却仍存活并战斗」。存活即至少 1 点，0 表示阵亡。
    hero["hp"] = float(max(0, int(hero["hp"] - value)))
    hero["minHpRatio"] = min(hero["minHpRatio"], hero["hp"] / max_hp)
    if hero["hp"] <= 0:
        hero["deadUntil"] = state["elapsedMs"] + state["reviveSeconds"] * 1000
        hero["deaths"] += 1
        hero["shield"] = 0.0
        hero["buffs"] = []
        hero["dots"] = []
        hero["slow"] = []
        event(state, "death", f"{hero['snapshot']['name']}倒下了", slot=hero["slot"], source=source)


def slow_factor(hero: dict, now: int) -> float:
    """当前攻速削减系数：1 - 生效中的最大削减（上限 60%）。"""
    active = [s["value"] for s in hero["slow"] if s["until"] > now]
    return 1.0 - min(0.6, max(active) if active else 0.0)


def auto_actions(state: dict, hero: dict) -> None:
    now = state["elapsedMs"]
    snap = hero["snapshot"]
    stats = snap["stats"]
    role = snap.get("role", "dps")
    attack = stats["magic_attack"] if stats.get("main_attr") == "int" else stats["attack"]
    buff = 1.0 + sum(
        b["value"] for b in hero["buffs"] if b["type"] in ("allDamageBuff", "attackBuff") and b["until"] > now
    )
    crit = 1.0 + stats.get("crit_rate_pct", 0.0) / 100.0 * max(0.0, stats.get("crit_damage_pct", 0.0) / 100.0 - 1.0)
    mult = buff * crit * (1.0 + stats.get("det_bonus_pct", 0.0) / 100.0) * hero["levelMultiplier"]
    slow = slow_factor(hero, now)

    if now >= hero["nextAttack"]:
        deal_damage(state, hero, attack * mult * (0.9 + random_unit(state) * 0.2))
        hero["nextAttack"] = now + int(BASIC_CD_MS / max(0.2, (1.0 + stats.get("attack_speed_pct", 0.0) / 100.0) * slow))

    if role == "healer" and now >= hero["nextHeal"]:
        alive = [h for h in state["heroes"] if h["hp"] > 0]
        if alive:
            target = min(alive, key=lambda h: h["hp"] / h["snapshot"]["stats"]["max_hp"])
            heal_hero(state, target, snap.get("healing", 0.0) * mult)
        hero["nextHeal"] = now + 2000

    if now < hero["gcdUntil"]:
        return
    skills = sorted(
        snap.get("skills", []),
        key=lambda s: (
            s.get("priority", 3),
            hero["lastCastAt"].get(s["id"], float("-inf")) if s.get("priority", 3) == 3 else 0.0,
            float(s.get("potency", 0) or 0),
        ),
    )
    skill = next(
        (
            s
            for s in skills
            if hero["cooldowns"].get(s["id"], 0) <= now and s.get("mpCost", 0) <= hero["mp"]
        ),
        None,
    )
    if skill is None:
        return
    hero["mp"] -= skill.get("mpCost", 0)
    hero["gcdUntil"] = now + int(GCD_MS / max(0.2, slow))
    hero["cooldowns"][skill["id"]] = now + int(float(skill.get("cd", 3)) * 1000)
    hero["lastCastAt"][skill["id"]] = now
    if skill.get("potency", 0):
        deal_damage(state, hero, attack * float(skill["potency"]) / 100.0 * snap.get("skillMultiplier", 1.0) * mult * (0.9 + random_unit(state) * 0.2))

    alive = [h for h in state["heroes"] if h["hp"] > 0]
    for effect in skill.get("effects", []):
        typ = effect.get("type")
        value = float(effect.get("value", 0.0))
        duration = int(float(effect.get("duration", 10)) * 1000)
        if typ in ("heal", "fullHeal", "shield"):
            targets = alive if skill.get("teamTarget") == "party" else [hero]
            for ally in targets:
                if typ == "shield":
                    cap = stats["max_hp"] * shield_cap_pct() / 100
                    ally["shield"] = min(cap, ally["shield"] + stats["max_hp"] * value * hero["levelMultiplier"])
                else:
                    heal_hero(state, ally, stats["max_hp"] * (1.0 if typ == "fullHeal" else value))
        elif typ == "healOverTime":
            targets = alive if skill.get("teamTarget") == "party" else [hero]
            for ally in targets:
                ally["buffs"].append(
                    {"type": typ, "value": stats["max_hp"] * value * hero["levelMultiplier"], "until": now + duration}
                )
        elif typ in ("damageReduction", "allDamageBuff", "attackBuff", "critRateBuff"):
            hero["buffs"].append({"type": typ, "value": value, "until": now + duration})


def hit_hero(state: dict, config: dict, hero: dict, potency_pct: float) -> None:
    """按 BOSS 攻击力 × 威力% 对单个英雄结算伤害（防御减伤）。"""
    power = boss_attack_power(state, config) * potency_pct / 100.0
    defense = hero["snapshot"]["stats"].get("phys_def", 0.0)
    damage_hero(state, hero, max(power * 0.1, power - defense * 0.8), "BOSS")


def cast_skill(state: dict, config: dict, skill: dict) -> None:
    boss = state["boss"]
    now = state["elapsedMs"]
    boss["skillCasts"] += 1
    boss["lastSkill"] = skill["id"]
    event(state, "bossSkill", f"BOSS 释放「{skill['name']}」", skillId=skill["id"], effect=skill.get("effect"))

    effect = skill.get("effect")
    if effect == "charge":
        boss["pendingSkill"] = {"skill": skill, "at": now + int(float(skill.get("chargeSeconds", 2)) * 1000)}
        return
    if effect == "enrage":
        boss["attackBuff"] = float(skill.get("attackBuff", 0.0))
        boss["attackBuffUntil"] = now + int(float(skill.get("duration", 10)) * 1000)
        return
    if effect == "shield":
        boss["damageReduce"] = float(skill.get("damageReduce", 0.0))
        boss["damageReduceUntil"] = now + int(float(skill.get("duration", 6)) * 1000)
        return

    alive = [h for h in state["heroes"] if h["hp"] > 0]
    if not alive:
        return
    # 阶段技能威力加成（仅技能，不影响普攻）。
    potency = float(skill.get("potency", 0.0)) * float(state.get("skillPotencyMultiplier", 1.0))
    duration_ms = int(float(skill.get("duration", 6)) * 1000) or 6000
    if effect == "nuke":
        hit_hero(state, config, alive[int(random_unit(state) * len(alive)) % len(alive)], potency)
    elif effect == "aoe":
        for hero in alive:
            hit_hero(state, config, hero, potency)
    elif effect == "dot":
        per_tick = boss_attack_power(state, config) * potency / 100.0 * TICK / duration_ms
        for hero in alive:
            hero["dots"].append({"until": now + duration_ms, "damage": per_tick})
    elif effect == "debuff":
        slow = float(skill.get("attackSpeedDebuff", 0.0))
        for hero in alive:
            hit_hero(state, config, hero, potency)
            hero["slow"].append({"value": slow, "until": now + duration_ms})


def step(state: dict, config: dict) -> None:
    if state["status"] != STATUS_RUNNING:
        return
    state["elapsedMs"] += TICK
    now = state["elapsedMs"]
    boss = state["boss"]
    boss_cfg = config["boss"]
    # 阶段随全局血量变化（P2/P3 防御更厚、技能威力更高）。
    resolve_phase(state, config)

    for hero in state["heroes"]:
        if hero["hp"] <= 0:
            if now >= hero["deadUntil"]:
                hero["hp"] = float(hero["snapshot"]["stats"]["max_hp"])
                hero["shield"] = 0.0
                event(state, "revive", f"{hero['snapshot']['name']}复活", slot=hero["slot"])
            else:
                continue
        stats = hero["snapshot"]["stats"]
        hero["mp"] = min(stats["max_mp"], hero["mp"] + stats.get("mp_regen", 0.0) * 0.1)
        hero["buffs"] = [b for b in hero["buffs"] if b["until"] > now]
        hero["dots"] = [d for d in hero["dots"] if d["until"] > now]
        hero["slow"] = [s for s in hero["slow"] if s["until"] > now]
        heal_hero(state, hero, stats.get("hp_regen", 0.0) * 0.1)
        for dot in hero["dots"]:
            damage_hero(state, hero, dot["damage"], "持续伤害")
        if hero["hp"] > 0:
            auto_actions(state, hero)

    # BOSS 普攻：固定间隔，对全部存活英雄生效，与技能计时独立。
    if now >= boss["nextAttack"]:
        for hero in [h for h in state["heroes"] if h["hp"] > 0]:
            power = boss_attack_power(state, config)
            defense = hero["snapshot"]["stats"].get("phys_def", 0.0)
            damage_hero(state, hero, max(power * 0.1, power - defense * 0.8), boss_cfg["name"])
        boss["nextAttack"] = now + int(float(boss_cfg["attackIntervalSeconds"]) * 1000)

    # BOSS 技能：固定间隔随机抽取，独立于普攻。
    pending = boss["pendingSkill"]
    if pending is not None and now >= pending["at"]:
        boss["pendingSkill"] = None
        cast_skill(state, config, {**pending["skill"], "effect": "aoe"})
    elif now >= boss["nextSkill"]:
        pool = boss_cfg["skillPool"]
        skill = pool[int(random_unit(state) * len(pool)) % len(pool)]
        boss["nextSkill"] = now + int(float(boss_cfg["skillIntervalSeconds"]) * 1000)
        cast_skill(state, config, skill)


def advance(state: dict, config: dict, milliseconds: int) -> dict:
    for _ in range(int(milliseconds) // TICK):
        step(state, config)
        if state["status"] != STATUS_RUNNING:
            break
    return state

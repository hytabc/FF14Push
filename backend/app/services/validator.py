"""战斗上报校验。来源：PRD 排行榜 2.5（服务端校验、防篡改）

策略：
- 击杀数超过理论上限 → 按上限截断，超出容差 2 倍以上则整单拒绝并写审计日志；
- 单只怪物金币超过该地区理论上限 → 截断到上限；
- 掉落物一律由服务端 RNG 产出，客户端只上报「是否发生了掉落」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.combat_model import max_gold_for_kill
from app.services.regions_util import kills_required
from app.services.stats import HeroStats

MAX_ELAPSED_MS = 20_000
MIN_ELAPSED_MS = 300
ALLOWED_TEMPLATES = {"normal", "highAtk", "highDef", "fast", "elite"}


@dataclass
class KillReport:
    monster_id: str
    gold: int
    exp: int
    dropped: bool = False


@dataclass
class ValidationResult:
    accepted: bool
    issues: list[str] = field(default_factory=list)
    kills: list[KillReport] = field(default_factory=list)
    total_gold: int = 0
    total_exp: int = 0
    drop_count: int = 0
    consumed_credit: float = 0.0
    reject_reason: str | None = None


def validate_report(
    stats: HeroStats,
    region_id: int,
    elapsed_ms: int,
    kills: list[dict[str, Any]],
    allowance: float,
    tolerance: float = 1.10,
) -> ValidationResult:
    """allowance 为本次上报可用的击杀额度（含跨上报累积的余额）。"""
    issues: list[str] = []

    if elapsed_ms < MIN_ELAPSED_MS or elapsed_ms > MAX_ELAPSED_MS:
        return ValidationResult(
            accepted=False,
            issues=[f"elapsedMs 超出允许区间: {elapsed_ms}"],
            reject_reason="invalid_elapsed",
        )

    allowed = max(0.0, allowance)

    for kill in kills:
        template_id = str(kill.get("monsterId", "normal"))
        if template_id not in ALLOWED_TEMPLATES:
            return ValidationResult(
                accepted=False,
                issues=[f"未知怪物模板: {template_id}"],
                reject_reason="unknown_monster",
            )

    if len(kills) > allowed * 2:
        return ValidationResult(
            accepted=False,
            issues=[f"击杀数 {len(kills)} 远超上限 {allowed:.2f}"],
            reject_reason="kill_rate_exceeded",
        )

    accepted_count = min(len(kills), int(allowed))
    accepted_kills: list[KillReport] = []
    for kill in kills[:accepted_count]:
        template_id = str(kill.get("monsterId", "normal"))
        kind = "elite" if template_id == "elite" else "normal"
        cap = max_gold_for_kill(region_id, kind, stats)
        gold = int(kill.get("gold", 0))
        if gold < 0:
            gold = 0
            issues.append("金币为负，已归零")
        if gold > cap:
            issues.append(f"金币 {gold} 超过上限 {cap:.0f}，已截断")
            gold = int(cap)
        exp = int(kill.get("exp", 0))
        max_exp = int(cap * 2) + 10
        if exp > max_exp:
            issues.append(f"经验 {exp} 超过上限 {max_exp}，已截断")
            exp = max_exp
        accepted_kills.append(
            KillReport(
                monster_id=template_id,
                gold=max(0, gold),
                exp=max(0, exp),
                dropped=bool(kill.get("dropped", False)),
            )
        )

    return ValidationResult(
        accepted=True,
        issues=issues,
        kills=accepted_kills,
        total_gold=sum(k.gold for k in accepted_kills),
        total_exp=sum(k.exp for k in accepted_kills),
        drop_count=sum(1 for k in accepted_kills if k.dropped),
        consumed_credit=float(accepted_count),
    )


def validate_boss_claim(stats: HeroStats, region_id: int, kill_count: int) -> bool:
    """BOSS 出现前置条件：小怪击杀计数达到地区要求。"""
    return kill_count >= kills_required(region_id)



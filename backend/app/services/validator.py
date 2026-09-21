"""战斗上报校验。来源：PRD 排行榜 2.5（服务端校验、防篡改）

策略：
- 击杀数超过理论上限 → 按上限截断，超出容差 2 倍（另加 1 只粒度容差）以上则整单拒绝并写审计日志；
- 单只怪物金币超过该地区理论上限 → 截断到上限；
- 装备不再由怪物掉落（仅抽箱获取），客户端上报的 dropped 一律忽略。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.combat_model import max_gold_for_kill
from app.services.game_config import CONFIG
from app.services.regions_util import kills_required
from app.services.stats import HeroStats

# 单次上报最多结算的真实窗口（毫秒）：页面切到后台时客户端会按墙钟补算这段时间，
# 服务端同步放宽窗口，合法上报才不会被截断。关闭页面后不再上报，窗口再大也换不来
# 离线收益；同时这个上限也限制了单次系统时钟跳变最多能换取的额度（防作弊）。
MAX_ELAPSED_MS = int(float(CONFIG.combat["catchUpSeconds"]) * 1000)
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
    doubled_kills: int = 0
    reject_reason: str | None = None


def validate_report(
    stats: HeroStats,
    region_id: int,
    elapsed_ms: int,
    kills: list[dict[str, Any]],
    allowance: float,
    tolerance: float = 1.10,
    double_charges: int = 0,
) -> ValidationResult:
    """allowance 为本次上报可用的击杀额度（含跨上报累积的余额）。

    double_charges 为彩蛋技能「拔豆芽」剩余的奖励翻倍怪物数：前 min(double_charges, N)
    只被接受击杀的金币/经验上限放宽为 2 倍，并计入 `doubled_kills` 供调用方扣减。
    """
    issues: list[str] = []
    double_charges = max(0, int(double_charges))

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

    # 击杀数是整数：窗口内额度可能不足 1（例如低等级地区短窗口），
    # 需要给 1 只的粒度容差；额度大时仍以 2 倍为界，防作弊强度不变。
    if len(kills) > allowed * 2 + 1:
        return ValidationResult(
            accepted=False,
            issues=[f"击杀数 {len(kills)} 远超上限 {allowed:.2f}"],
            reject_reason="kill_rate_exceeded",
        )

    accepted_count = min(len(kills), int(allowed))
    accepted_kills: list[KillReport] = []
    doubled_kills = 0
    for index, kill in enumerate(kills[:accepted_count]):
        template_id = str(kill.get("monsterId", "normal"))
        kind = "elite" if template_id == "elite" else "normal"
        cap = max_gold_for_kill(region_id, kind, stats)
        if index < double_charges:
            # 彩蛋「拔豆芽」：该只怪物经验/金币翻倍，放宽上限
            cap *= 2
            doubled_kills += 1
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
                # 装备不再由怪物掉落（仅抽箱获取），不采信客户端上报的 dropped
                dropped=False,
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
        doubled_kills=doubled_kills,
    )


def validate_boss_claim(stats: HeroStats, region_id: int, kill_count: int) -> bool:
    """BOSS 出现前置条件：小怪击杀计数达到地区要求。"""
    return kill_count >= kills_required(region_id)



"""请求 / 响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=64)
    nickname: str | None = Field(default=None, max_length=32)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    accessToken: str
    tokenType: str = "bearer"


class SkillCast(BaseModel):
    skillId: str
    count: int = 0


class KillEvent(BaseModel):
    monsterId: str
    gold: int
    exp: int
    # 已忽略：装备仅通过抽箱获取，服务端不再采信该字段（保留以兼容旧客户端）
    dropped: bool = False


class BattleStartRequest(BaseModel):
    regionId: int


class BattleReportRequest(BaseModel):
    sessionId: int
    regionId: int
    elapsedMs: int
    kills: list[KillEvent] = Field(default_factory=list)
    skillCasts: list[SkillCast] = Field(default_factory=list)
    killCount: int = 0
    bossKilled: bool = False
    died: bool = False
    bossFightMs: int | None = None


class BattleStopRequest(BaseModel):
    sessionId: int


class EquipRequest(BaseModel):
    itemId: int
    slot: str


class UnequipRequest(BaseModel):
    slot: str


class SellRequest(BaseModel):
    itemIds: list[int]


class ChestOpenRequest(BaseModel):
    chestId: str
    count: int = 1


class CraftRequest(BaseModel):
    category: str
    auto: bool = True


class RefineRequest(BaseModel):
    itemId: int


class EnchantRequest(BaseModel):
    itemId: int
    autoUntilRare: bool = False
    maxAttempts: int = 200


class RegionEnterRequest(BaseModel):
    regionId: int


class TavernRefreshRequest(BaseModel):
    useGold: bool = True


class TavernRecruitRequest(BaseModel):
    confirm: bool = True


class TutorialRequest(BaseModel):
    step: int | None = None


class AutoSellRequest(BaseModel):
    enabled: bool
    rarities: list[str] = Field(default_factory=list)


class ApiMessage(BaseModel):
    ok: bool = True
    message: str = "ok"
    data: dict[str, Any] | None = None

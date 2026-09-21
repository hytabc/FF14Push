"""请求 / 响应模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=64)
    nickname: str | None = Field(default=None, max_length=32)


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str = Field(min_length=6, max_length=64)
    confirmPassword: str


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
    # 仅作参考：上报窗口一律以服务端时钟计算（客户端时间可被篡改，采信即等于允许加速）
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
    # 抽箱等级档位：箱子内容按该等级生成；需玩家等级达到该档位。省略时按玩家当前等级。
    level: int | None = None


class TagCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=16)
    color: str = Field(min_length=1, max_length=16)


class TagUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=16)
    color: str | None = Field(default=None, min_length=1, max_length=16)


class SetItemTagsRequest(BaseModel):
    itemId: int
    tagIds: list[int] = Field(default_factory=list)


class CraftRequest(BaseModel):
    category: str
    auto: bool = True


class RefineRequest(BaseModel):
    itemId: int
    # random=彻底随机（现价，全部重新洗牌）；basedOnCurrent=基于当前（更贵，每条在当前值附近小幅浮动，可升可降）
    mode: Literal["random", "basedOnCurrent"] = "random"


class EnchantRequest(BaseModel):
    itemId: int
    autoUntilRare: bool = False
    maxAttempts: int = 200
    mode: Literal["random", "basedOnCurrent"] = "random"


class RegionEnterRequest(BaseModel):
    regionId: int


class TavernRefreshRequest(BaseModel):
    useGold: bool = True


class TavernRecruitRequest(BaseModel):
    confirm: bool = True


class TavernTenPullRecruitRequest(BaseModel):
    index: int
    confirm: bool = True


class TutorialRequest(BaseModel):
    step: int | None = None


class AutoSellRequest(BaseModel):
    enabled: bool
    rarities: list[str] = Field(default_factory=list)


class RaidStartRequest(BaseModel):
    raidId: str


class RaidReportRequest(BaseModel):
    mechanismFailures: list[str] = Field(default_factory=list, max_length=32)
    sessionId: int
    raidId: str
    elapsedMs: int = 0
    cleared: bool = False
    died: bool = False
    fightMs: int | None = Field(default=None, ge=0)


class RaidStopRequest(BaseModel):
    sessionId: int


class RaidChestClaimRequest(BaseModel):
    # 自选的装备种类（底材 slot，如 mainHand / head / ring）
    slot: str = Field(min_length=1, max_length=24)


class RedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class AdminResetPasswordRequest(BaseModel):
    userId: int
    newPassword: str = Field(min_length=6, max_length=64)


class AdminBanRequest(BaseModel):
    userId: int
    banned: bool = True


class ApiMessage(BaseModel):
    ok: bool = True
    message: str = "ok"
    data: dict[str, Any] | None = None

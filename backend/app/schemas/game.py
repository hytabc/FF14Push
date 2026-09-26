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


class ChangeNicknameRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=32)


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


class AutoEquipRequest(BaseModel):
    """一键最强：是否把已被其他英雄装备的装备也纳入候选。"""

    includeEquipped: bool = False


class ChestOpenRequest(BaseModel):
    chestId: str
    count: int = 1
    # 抽箱等级档位：箱子内容按该等级生成；需玩家等级达到该档位。省略时按玩家当前等级。
    level: int | None = None


class ChestUnlockRequest(BaseModel):
    # 要一次性金币解锁的连抽档位（如 50 / 100）。
    count: int


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
    # 连续重造次数：一次请求结算多次（金币不足时提前停止）
    times: int = Field(default=1, ge=1, le=50)
    # 使用「重新打造卡」（仅生产/采集专用装备）：强制 basedOnCurrent，每件每次消耗 1 张、不扣金币
    useCard: bool = False


class EnchantRequest(BaseModel):
    itemId: int
    autoUntilRare: bool = False
    maxAttempts: int = 200
    mode: Literal["random", "basedOnCurrent"] = "random"
    # 连续附魔次数：一次请求结算多次（金币不足时提前停止）
    times: int = Field(default=1, ge=1, le=50)
    # 使用「重新打造卡」（仅生产/采集专用装备）：强制 basedOnCurrent，每件每次消耗 1 张、不扣金币
    useCard: bool = False


class RegionEnterRequest(BaseModel):
    regionId: int


class DifficultyRequest(BaseModel):
    """切换地区战斗难度（0 = 当前各地区数值，仅限已解锁范围）。"""

    level: int = Field(ge=0)


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


class AutoSellFishRequest(BaseModel):
    """自动卖鱼：按鱼的档位（normal / king / emperor / legend）选择要自动出售的鱼。"""

    enabled: bool
    kinds: list[str] = Field(default_factory=list)


class ActiveTitleRequest(BaseModel):
    """佩戴称号（设置页最多一个）；None 表示不佩戴。"""

    titleId: str | None = Field(default=None, max_length=48)


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


class AdminGrantGoldRequest(BaseModel):
    userId: int
    amount: int = Field(gt=0)
    reason: str = Field(default="", max_length=200)


class ApiMessage(BaseModel):
    ok: bool = True
    message: str = "ok"
    data: dict[str, Any] | None = None


# --------------------------------------------------------------- 生产 / 采集 DLC
class GatherStartRequest(BaseModel):
    jobId: str = Field(min_length=2, max_length=8)
    regionId: int


class ProduceStartRequest(BaseModel):
    jobId: str = Field(min_length=2, max_length=8)
    recipeId: str = Field(min_length=1, max_length=48)
    # 制造件数：None = 制作全部（按当前材料上限）；>=1 = 制作 X 个（不足时按材料上限结算）
    count: int | None = Field(default=None, ge=1, le=100000)


class FishStartRequest(BaseModel):
    regionId: int


class ActivityReportRequest(BaseModel):
    sessionId: int


class ActivityStopRequest(BaseModel):
    sessionId: int


class ConsumableUseRequest(BaseModel):
    itemId: str = Field(min_length=1, max_length=48)


class DohDolEquipRequest(BaseModel):
    itemId: int
    slot: str = Field(min_length=1, max_length=24)


class DohDolUnequipRequest(BaseModel):
    slot: str = Field(min_length=1, max_length=24)


class SellStackRequest(BaseModel):
    """出售堆叠物品（采集材料 / 半成品 / 鱼 / 药水 / 食物）。"""

    kind: str = Field(min_length=1, max_length=16)
    itemId: str = Field(min_length=1, max_length=48)
    count: int = Field(default=1, ge=1)


# --------------------------------------------------------------- 重建伊修加德
class IshgardGatherStartRequest(BaseModel):
    jobId: str = Field(min_length=2, max_length=8)


class IshgardProduceStartRequest(BaseModel):
    jobId: str = Field(min_length=2, max_length=8)
    recipeId: str = Field(min_length=1, max_length=48)
    count: int | None = Field(default=None, ge=1, le=100000)


class IshgardSubmitRequest(BaseModel):
    """提交当前阶段的重建产物换取积分。"""

    itemId: str = Field(min_length=1, max_length=48)
    count: int = Field(default=1, ge=1)


class IshgardToolRequest(BaseModel):
    """可成长主手装备操作（kind: doh 生产 / dol 采集）。"""

    kind: Literal["doh", "dol"]


class IshgardSellRequest(BaseModel):
    """出售重建专属物资（材料 / 鱼 / 产物）。"""

    itemId: str = Field(min_length=1, max_length=48)
    count: int = Field(default=1, ge=1)


# --------------------------------------------------------------- 市场交易板
# 可上架 / 可求购的堆叠物种类（与 dohdol_util.STACK_* 对齐）。
StackKind = Literal["material", "potion", "food", "materia", "seed"]


class MarketListEntry(BaseModel):
    """上架条目：装备（type=equipment，itemId 为装备行 id）或堆叠物（type=stack）。"""

    type: Literal["equipment", "stack"]
    itemId: int | None = None
    stackKind: StackKind | None = None
    stackItemId: str | None = Field(default=None, max_length=48)
    count: int = Field(default=1, ge=1)
    unitPrice: int = Field(ge=1)


class MarketListRequest(BaseModel):
    entries: list[MarketListEntry] = Field(min_length=1, max_length=50)


class MarketBuyRequest(BaseModel):
    listingId: int


class MarketCancelRequest(BaseModel):
    listingId: int


class BuyOrderCreateRequest(BaseModel):
    """发布收购单：托管 unitPrice × quantity 金币求购某堆叠物。"""

    kind: StackKind
    itemId: str = Field(min_length=1, max_length=48)
    quantity: int = Field(ge=1)
    unitPrice: int = Field(ge=1)


class BuyOrderCancelRequest(BaseModel):
    orderId: int


class BuyOrderFillRequest(BaseModel):
    """卖给收购单：按 count 部分/全部成交。"""

    orderId: int
    count: int = Field(ge=1)


# --------------------------------------------------------------- 好友系统
class FriendByCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=12)


class FriendTargetRequest(BaseModel):
    userId: int


class FriendTransferRequest(BaseModel):
    userId: int
    amount: int = Field(ge=1)


# --------------------------------------------------------------- 聊天室
class ChatSendRequest(BaseModel):
    """大厅发言 / 管理员公告：仅文本，长度上限与 `services/chat.MAX_TEXT_LEN` 一致。"""

    text: str = Field(min_length=1, max_length=200)


# --------------------------------------------------------------- 魔晶石镶嵌
class MateriaSocketRequest(BaseModel):
    """在账号级栏位的指定孔位镶嵌魔晶石（孔位须按顺序填充）。"""

    slot: str = Field(min_length=1, max_length=16)
    index: int = Field(ge=0, le=15)
    materiaId: str = Field(min_length=1, max_length=32)


class MateriaRemoveRequest(BaseModel):
    """取出孔位中的魔晶石（必定成功并返还）。"""

    slot: str = Field(min_length=1, max_length=16)
    index: int = Field(ge=0, le=15)


class MateriaMergeRequest(BaseModel):
    """合成：mergeFrom 个同级同种魔晶石 → 1 个高一级。"""

    materiaId: str = Field(min_length=1, max_length=32)


# --------------------------------------------------------------- 种田
class FarmPlantRequest(BaseModel):
    plotIndex: int = Field(ge=0, le=15)
    seedId: str = Field(min_length=1, max_length=32)


class FarmHarvestRequest(BaseModel):
    plotIndex: int = Field(ge=0, le=15)
    # 经验种子：选择获得 +1 级的英雄；金币种子忽略该字段。
    heroId: int | None = None
    # 目标英雄满级时的二次确认（前端弹窗后传 true）。
    confirm: bool = False


# --------------------------------------------------------------- 挖宝
class TreasureFloorClearRequest(BaseModel):
    runId: int
    # 仅作参考：服务端以自己的时钟校验最短战斗时长。
    elapsedMs: int = 0


class TreasureGambleRequest(BaseModel):
    runId: int
    guess: Literal["high", "low"]


class TreasureGambleStopRequest(BaseModel):
    runId: int


class TreasureChestOpenRequest(BaseModel):
    runId: int


class TreasureDoorRequest(BaseModel):
    runId: int
    door: int = Field(ge=0, le=7)


class TreasureRunRequest(BaseModel):
    runId: int


# --------------------------------------------------------------- 生产 / 采集序列库
class SequenceSaveRequest(BaseModel):
    """保存当前编辑区为自定义序列；同名时覆盖已有序列。"""

    name: str = Field(min_length=1, max_length=24)
    steps: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    loopMode: Literal["once", "count", "infinite"] = "once"
    loopTotal: int = Field(default=3, ge=1, le=10000)


class SequenceOverwriteRequest(BaseModel):
    """用当前编辑区覆盖指定序列槽位；可选改名。"""

    steps: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    loopMode: Literal["once", "count", "infinite"] = "once"
    loopTotal: int = Field(default=3, ge=1, le=10000)
    name: str | None = Field(default=None, min_length=1, max_length=24)


# --------------------------------------------------------------- 死者宫殿
class PalaceChooseRequest(BaseModel):
    """开局三选一（英雄 / 奖励）。"""

    index: int = Field(ge=0, le=63)


class PalaceNodeEnterRequest(BaseModel):
    nodeId: str = Field(min_length=1, max_length=16)


class PalaceNodeClearRequest(BaseModel):
    nodeId: str = Field(min_length=1, max_length=16)
    elapsedMs: int = Field(default=0, ge=0)
    result: Literal["win", "lose"] = "win"


class PalaceEventChooseRequest(BaseModel):
    nodeId: str = Field(min_length=1, max_length=16)
    choiceIndex: int = Field(ge=0, le=15)


class PalaceShopBuyRequest(BaseModel):
    nodeId: str = Field(min_length=1, max_length=16)
    offerIndex: int = Field(ge=0, le=15)


class PalaceEquipRequest(BaseModel):
    index: int = Field(ge=0, le=1023)


class PalaceGrowthUnlockRequest(BaseModel):
    nodeId: str = Field(min_length=1, max_length=64)


class PalaceExchangeRequest(BaseModel):
    exchangeId: str = Field(min_length=1, max_length=64)
    count: int = Field(default=1, ge=1, le=999)


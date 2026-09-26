# 死者宫殿（Palace of the Dead）Roguelike 玩法设计文档（PRD）

> 状态：**待确认** —— 确认本文档后再进入编码。
> 关联需求：新增玩法「死者宫殿」：与账号战力完全隔离的 roguelike 深层迷宫（选英雄 / 选武器 / 路径选择 / 节点战斗 / 局外成长树 / 代币兑换 / 通行称号）。
> 关联既有系统：酒馆招募（随机英雄）、抽箱（随机武器与装备生成）、地区战斗模拟器、高难副本（服务端逐节点权威校验）、挖宝（多层副本状态机）、称号、堆叠背包、活动互斥、导航 / 音效 / 移动端安全区。

---

## 1. 背景与设计目标

### 1.1 背景

FF14 的「死者宫殿」是一套**从 1 级起步、在随机迷宫中靠拾取与运气推进**的深层迷宫玩法，与主线的等级 / 装备养成几乎解耦。本项目已有完善的**账号级**养成（装备 / 秘药 / 魔晶石 / 名册），因此本玩法必须保证「**自成一套平行数值**」，不能被账号战力碾压，也不能污染账号数值。

### 1.2 设计目标

1. **完全隔离**：不读账号装备 / 英雄 / 秘药 / 食物 / 魔晶石 / 周目难度；副本内英雄 1 级起步、仅副本内成长，装备、金币、BUFF 全部存于本次运行（run）快照。
2. **可玩闭环**：进入 → 三选一英雄 → 三选一武器 → 路径选择 → 战斗 / 事件 / 商店 → 三选一奖励 → 层 BOSS → 成长点 / 代币 → 下一层。
3. **长期养成**：局外成长树（**>200 节点 / >20 类别 / 全树消耗 >400 点**）、代币兑换（烈火纹章 / 玻璃南瓜）、通行称号（死灵术士）。
4. **可调可标定**：全部数值集中在共享 JSON，配套无头蒙特卡洛标定脚本与回归断言，锁死「零成长 ≤5 层、满成长可秒杀前几层」。
5. **多端可用**：独立的战斗 UI / 装备 UI / 路径 UI，窄屏与桌面均不溢出，贴边元素避让安全区。

### 1.3 非目标（明确不做）

- 不参与排行榜，不影响账号战力 / 等级 / 金币 / 装备。
- 不提供离线收益：关闭页面即停止本地模拟（run 进度保留在服务端）。
- 不与账号背包互通（唯一的出口是「兑换」页把奖励发放到账号背包）。

---

## 2. 隔离边界（必须保留）

| 外部系统 | 与死者宫殿的关系 |
| --- | --- |
| 账号英雄 / 名册 | **不参与**。副本内英雄由副本随机生成，副本内 1 级起步，仅副本内升级 |
| 账号装备 / 武器 | **不参与**。副本内武器 / 装备由副本内生成，存于 run 快照，不落 `items` 表 |
| 秘药 / 食物 / 魔晶石 / 名册加成 | **不生效**（副本不调用 `consumables.*` / `materia.socket_mods`） |
| 地区 battle_difficulty 周目 | **不生效**（副本不走难度乘数） |
| 战力门槛 `balance.soft_penalty` | **不生效**（副本用自身数值，不做账号战力门槛） |
| 活动互斥 | **参与**：与地区战斗 / 采集 / 生产 / 钓鱼 / 挖宝 / 远征 / 世界BOSS 互斥 |
| 输出到账号 | 局外成长点、代币（纹章 / 南瓜）、称号、兑换奖励（种子 / 魔晶石 / 卡 / 秘药）进账号背包 |

---

## 3. 玩法总览

### 3.1 核心循环

```
进入副本 ──▶ 随机 3 英雄 3选1 ──▶ 随机 3 武器 3选1 ──▶ 进入第 1 层路径图
   ▲                                                        │
   │                        ┌───────────────────────────────┘
   │                        ▼
   │   ┌─────────────── 第 F 层（F = 1..10）路径图（DAG） ───────────────┐
   │   │  选择节点 → 进入 → 战斗 / 事件 / 商店 / 宝箱 / 休息 → 结算        │
   │   │  每层至多 10 步，第 10 步固定为本层 BOSS                         │
   │   │  战斗胜利 → 奖励 3选1（装备 / BUFF / 两者）                       │
   │   │  击败层 BOSS → 成长点（按层）+ 代币（1-5 烈火纹章 / 6-10 玻璃南瓜）│
   │   └──────────────────────────────────────────────────────────────┘
   │                        │
   │                        ▼ 第 10 层 BOSS 击败 → 本次 run 通关
   └────────────  局外：成长树加点 / 兑换页 / 称号（死灵术士 = 通关 10 次）
```

### 3.2 参与条件与生命周期

- 登录即可参与；进入副本会**结束其它进行中的活动会话**（沿用既有互斥）。
- 中途切页 / 断线：run 保留在服务端，重新进入续接**未完成节点**。
- 开始其它战斗类活动：按互斥规则结束本次 run（**已入账奖励保留**）。
- 本次 run 通关（击败第 10 层层 BOSS）或主动放弃（`POST /palace/abandon`）后结束。

---

## 4. 开局：选英雄与选武器

### 4.1 选英雄（照酒馆）

- 服务端用 `services/recruiting.generate_candidate()` 生成 **3 个候选**（资质 talent / 三维 / 职业 job / 技能），落库 run 快照。
- 前端展示 3 张英雄卡，玩家选择其一（`POST /palace/hero/choose {index}`）。
- 副本内英雄初始 **1 级**，受局外成长「初始等级」加成（`start_level`）。
- 资质（talent）权重受局外成长「高品质英雄概率」（`hero_talent`）调节。

### 4.2 选武器（照抽箱，只出武器）

- 服务端用 `item_factory.generate_item(category="weapon", level=起手档, box_tier=..., luck=...)` 生成 **3 件武器**，用 `serialization.item_to_dict` 返回展示结构。
- 玩家选择其一（`POST /palace/weapon/choose {index}`），进入副本装备栏 `mainHand`。
- 起手档次受局外成长「起手武器等级」（`equip_level`）与「高品质装备概率」（`equip_quality`）调节。

---

## 5. 路径图与节点

### 5.1 路径图生成（服务端权威）

- 每层生成一张 **DAG**：行 = 步（step），列 = 同行节点；行内 1–3 个节点，边可为 **1对1 / 1对多 / 多对1**。
- **第 10 步固定为单节点（层 BOSS）**，所有第 9 步节点收敛到它。
- 起点为第 1 步的节点（1–3 个），玩家从中选择。
- 生成后用 `map_json` 存入 run 快照；节点数据结构：

```jsonc
{
  "seed": 123456789,
  "rows": [
    { "step": 1, "nodes": [ { "id": "1-0", "type": "battle" }, { "id": "1-1", "type": "event" } ] },
    { "step": 2, "nodes": [ { "id": "2-0", "type": "battle" } ] },
    ...
    { "step": 10, "nodes": [ { "id": "10-0", "type": "boss" } ] }
  ],
  "edges": [ { "from": "1-0", "to": "2-0" }, { "from": "1-0", "to": "2-1" }, { "from": "1-1", "to": "2-0" } ]
}
```

### 5.2 节点类型与权重（配置驱动，按层段区分）

| 类型 | 说明 | 首版权重（第 1-4 / 5-7 / 8-9 步） |
| --- | --- | --- |
| `battle` | 普通战斗 | 50 / 45 / 40 |
| `elite` | 精英战斗（更强、奖励更好） | 10 / 15 / 20 |
| `event` | 事件 | 22 / 20 / 18 |
| `shop` | 商店（副本金币消费） | 6 / 8 / 8 |
| `chest` | 宝箱（直接给装备 / 金币） | 8 / 8 / 8 |
| `rest` | 休息（回复 / 少量奖励） | 4 / 4 / 6 |
| `boss` | 层 BOSS（第 10 步固定） | — |

> 权重之和必须为 1；由 `test_shared_data.py` 断言。玩家在事件 / 商店 / 休息节点不需要战斗。

### 5.3 节点进入与结算

- `POST /palace/node/enter {nodeId}`：校验 nodeId 是**当前可选后继**之一；返回节点上下文（战斗节点返回敌人统计快照；事件节点返回事件内容与选项；商店返回商品；宝箱返回内容）。
- 战斗节点：前端用 `BattleSimulator({raid:{bosses:[enemy], enrage:null}})` 本地模拟，结束后 `POST /palace/node/clear {nodeId, elapsedMs, result}` 上报。
- 服务端按 §11 校验通过后返回奖励选项与成长（经验 / 升级）。

---

## 6. 战斗与奖励

### 6.1 战斗模型

- **单英雄 vs 单敌人**（`BattleSimulator` 的 `raid` 模式，`enrage` 为 null；精英 / 层 BOSS 可带多个技能）。
- 战斗内英雄面板**完全由副本数据计算**（见 §7），不叠加任何账号加成。
- 敌人数值来自 §8 的副本怪物曲线，按**层数**与节点类型（普通 / 精英 / BOSS）取值。

### 6.2 战斗奖励（三选一）

- 战斗胜利后服务端生成 **3 个奖励选项**，玩家 `POST /palace/reward/claim {index}` 选择其一。
- 选项种类由权重决定：`equip`（副本装备）/ `buff`（副本 BUFF）/ `both`（装备 + BUFF 同一条目）。
- 首版权重：`{ "equip": 0.45, "buff": 0.35, "both": 0.20 }`，由配置驱动。
- 精英与层 BOSS 额外提高 `equip` 品质 / 数量（配置 `eliteBonus` / `bossBonus`）。

### 6.3 副本内装备

- 副本装备 = `item_factory.generate_item(...)` 生成的装备字典（`baseId/name/category/slot/rarity/levelReq/highQuality/baseAttrs/subAttrs/terms`），存 run JSON，**不落 `items` 表**。
- 栏位复用 `slots_util` 规则（主手 / 副手 / 头 / 身 / 手 / 腿 / 脚 / 饰品等），单 hero 穿戴。
- 可在装备 UI 中穿戴 / 替换（旧件留在副本背包）。

### 6.4 副本内 BUFF

- BUFF = 持久作用于本次 run 的增益，存 run JSON `buffs[]`，形如 `{ "id", "name", "stat", "value", "desc" }`。
- 生效方式：在 `dataclasses.replace` 派生的副本面板上按 `stat` 乘算 / 加算（见 §7）。

### 6.5 副本内经验与升级

- 战斗结算发放副本经验，复用 `progression.exp_to_next` 曲线；副本等级上限配置 `levelCap`（首版 50）。
- 升级提升副本英雄三维 / 面板（复用 `heroes.json` 的属性公式，但只作用于 run）。

---

## 7. 副本面板计算（与账号隔离）

- 复用 `services/stats.compute_stats` / `HeroStats`：由 run 快照构造 **transient hero / items 对象**（只提供 `compute_stats` 读取的字段），得到基础副本面板。
- 再叠加**局外成长**（数值类节点）与**副本 BUFF**：用 `dataclasses.replace` 派生新面板（参考 `services/difficulty.scale_player_stats`），**不落账号库**。
- 前后端必须使用同一 `HeroStats`：前端 `BattleSimulator` 直接吃 `/palace/node/enter` 返回的面板，服务端理论模型用同一面板做校验，保证逐节点校验不误判。

---

## 8. 数值曲线（起始值，待 §13 标定）

### 8.1 副本怪物曲线

每层一组基准值（普通怪），精英 / BOSS 用倍率：

```jsonc
"monsters": {
  "floors": [
    { "floor": 1,  "hp": 200,     "attack": 20,    "defense": 8,     "xp": 55,     "gold": 30 },
    { "floor": 2,  "hp": 620,     "attack": 48,    "defense": 24,    "xp": 140,    "gold": 70 },
    { "floor": 3,  "hp": 1900,    "attack": 112,   "defense": 60,    "xp": 340,    "gold": 150 },
    { "floor": 4,  "hp": 5800,    "attack": 260,   "defense": 150,   "xp": 820,    "gold": 320 },
    { "floor": 5,  "hp": 18000,   "attack": 620,   "defense": 400,   "xp": 2200,   "gold": 700 },
    { "floor": 6,  "hp": 52000,   "attack": 1500,  "defense": 1050,  "xp": 6000,   "gold": 1500 },
    { "floor": 7,  "hp": 150000,  "attack": 3400,  "defense": 2600,  "xp": 16000,  "gold": 3200 },
    { "floor": 8,  "hp": 420000,  "attack": 7600,  "defense": 6000,  "xp": 44000,  "gold": 7000 },
    { "floor": 9,  "hp": 1150000, "attack": 16500, "defense": 13500, "xp": 120000, "gold": 15000 },
    { "floor": 10, "hp": 3100000, "attack": 35000, "defense": 30000, "xp": 330000, "gold": 32000 }
  ],
  "elite": { "hp": 2.2, "attack": 1.3, "defense": 1.5, "xp": 2.0, "gold": 2.0 },
  "boss":  { "hp": 6.5, "attack": 1.6, "defense": 1.7, "xp": 6.0, "gold": 6.0 }
}
```

- 曲线按「零成长上限第 5 层、满成长可秒杀第 1–3 层」标定（见 §18 实测结果与 `scripts/palace-balance.py`）。

### 8.2 层 BOSS 奖励

```jsonc
"bossReward": {
  "growthPoints": [2, 2, 3, 3, 4, 4, 5, 5, 6, 10],   // 按层 1..10
  "flameCrest":    [1, 1, 1, 2, 2, 0, 0, 0, 0, 0],     // 第 1-5 层
  "glassPumpkin":  [0, 0, 0, 0, 0, 1, 1, 2, 2, 3],     // 第 6-10 层
  "clearBonusGrowthPoints": 10                          // 击败第 10 层层 BOSS 额外
}
```

- 全树消耗 >400 点：一次完整通关约得 `ΣgrowthPoints + clearBonus = 44 + 10 = 54`，约 8–10 次满通可点满（长线养成）。
- 击败第 10 层层 BOSS 时 `PalaceProfile.floor10_clears += 1`。

---

## 9. 事件系统（>30 类）

配置 `shared/data/palace-events.json`；每个事件：

```jsonc
{
  "id": "ev_forge_upgrade",
  "name": "幽灵铁匠",
  "type": "equip_level_up",
  "weight": 8,
  "floorRange": [1, 10],
  "desc": "幽灵铁匠愿意为你强化一件装备。",
  "choices": [
    { "label": "强化武器等级", "effects": [ { "kind": "equip_level_up", "target": "weapon", "value": 1 } ] },
    { "label": "离开", "effects": [] }
  ]
}
```

- **效果（effect.kind）**至少覆盖：`equip_rarity_up`（品质升级）、`equip_level_up`（等级升级）、`hero_attr_up`（英雄属性提升，力量 / 敏捷 / 智力）、`skill_effect_up`（技能效果提高）、`grant_equip`（给装备）、`grant_buff`（给 BUFF）、`grant_gold`（副本金币）、`lose_hp`（扣血）、`curse`（减益）、`heal`（回复）、`grant_revive`（复活次数）、`dup_reward`（宝箱双倍）、`gain_growth`（直接给成长点，稀有）。
- **首版事件 ≥32 条**，由 `scripts/gen-palace-data.py` 从「事件模板 × 数值档」生成，关键事件（品质升级 / 等级升级 / 属性提升 / 技能提升）手工精调。
- 多选项事件由服务端权威结算；`lose_hp` 不会直接把玩家打死（下限保留 1 点血）。

---

## 10. 局外成长树（>200 节点 / >20 类别 / 消耗 >400 点）

配置 `shared/data/palace-growth.json`：

```jsonc
{
  "categories": [
    {
      "id": "hero_talent",
      "name": "高品质英雄",
      "desc": "提高进入副本时出现高品质英雄的概率。",
      "nodes": [
        { "id": "hero_talent_1", "tier": 1, "name": "英雄资质 I", "cost": 1, "requires": null,
          "effect": { "stat": "heroTalentWeight", "value": 0.05 } },
        { "id": "hero_talent_2", "tier": 2, "name": "英雄资质 II", "cost": 1, "requires": "hero_talent_1",
          "effect": { "stat": "heroTalentWeight", "value": 0.05 } }
      ]
    }
  ]
}
```

- **类别（首版 ≥22）**：`hero_talent`（高品质英雄概率）、`hero_attack`、`hero_defense`、`hero_hp`、`hero_str`、`hero_dex`、`hero_int`、`start_level`（初始等级）、`start_gold`（初始金币）、`crit`、`dh`（直击）、`attack_speed`、`healing`、`equip_quality`（高品质装备概率）、`equip_level`（起手武器等级）、`drop_count`（掉落数量）、`drop_quality`（掉落品质）、`gold_gain`（副本金币获取）、`event_luck`（事件好运）、`shop_discount`（商店折扣）、`start_buff`（起始 BUFF）、`revive_count`（复活次数）、`boss_growth`（层 BOSS 额外成长点）、`growth_gain`（成长点获取加成）。
- **节点**：每类别 10 级（tier 1..10），首版 24 类别 × 10 级 = **240 节点**；`requires` 形成链式依赖（同类别上一个是前置）。
- **消耗**：单节点 `cost` 随 tier 递增（首版 `[1,1,1,2,2,2,3,3,3,4]`，单类别合计 22），全树合计 **528 > 400**。
- **存储**：账号级 `PalaceProfile.growth_points`（余额）+ `unlocked`（已解锁节点 id 列表）。
- **生效**：概率类（`heroTalentWeight` / `equipQuality` / `eventLuck` / `shopDiscount`）影响生成与结算；数值类（`heroAttack` / `heroHp` / …）经 `dataclasses.replace` 作用于副本面板。
- **加点点数不足时**按钮显式标注（如「成长点不足（需 5，当前 3）」）。

---

## 11. 反作弊与服务端权威

1. **服务端权威**：路径合法性、节点结算、奖励、成长点、代币、兑换、称号全部服务端结算。
2. **逐节点快照校验**（照 `services/raid_balance.py`）：
   - 进入战斗节点时冻结快照：`minimumFightMs = 理论时长 × durationTolerance`、`outputPassed` / `defensePassed` 门槛、`node_started_at`。
   - 结算时 `clear_failures`：`server_elapsed_ms < minimumFightMs`、`fight_ms > server_elapsed_ms + clockToleranceMs`、输出 / 防御不达标 → 拒绝（`invalid_duration` / `output` / `defense`）。
   - **窗口只认服务端时钟**，忽略客户端 `elapsedMs` 的实际跨度。
3. **`minimumFightMs` 必须低于合法最快**（客户端一次出手最快约 0.75s），否则合法通关被误报「战斗时长异常」（参照 `treasure.minFloorFightMs` 的教训）；前端对「时长异常」等待重试。
4. **不信任客户端数值**：只接受「节点 id / 战斗时长 / 结果布尔」；面板、敌人数值、奖励全由服务端给出。
5. **并发与幂等**：run / profile 更新用行锁；`reward/claim`、`growth/unlock`、`exchange` 幂等（重复请求返回既有结果或拒绝）。

---

## 12. 接口清单

新增 `backend/app/api/v1/palace.py`，前缀 `/api/v1/palace`：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/palace/state` | 入口态：profile（成长点 / 代币 / 通关次数）+ 进行中 run（若可续，返回断点）+ 配置驱动的展示数据 |
| POST | `/palace/start` | 进入副本（结束其它活动；无进行中 run 则新建），返回 3 个英雄候选 |
| POST | `/palace/hero/choose` | 选定英雄（`index`），返回 3 个武器候选 |
| POST | `/palace/weapon/choose` | 选定武器（`index`）→ 生成第 1 层路径图 |
| POST | `/palace/node/enter` | 进入合法后继节点（`nodeId`），返回节点上下文 |
| POST | `/palace/node/clear` | 上报战斗结果（`nodeId` / `elapsedMs` / `result`），校验后返回奖励选项与升级信息 |
| POST | `/palace/reward/claim` | 领取奖励三选一（`index`） |
| POST | `/palace/event/choose` | 事件选项结算（`nodeId` / `choiceIndex`） |
| POST | `/palace/shop/buy` | 商店购买（`nodeId` / `offerIndex`） |
| POST | `/palace/chest/claim` | 宝箱 / 休息结算 |
| GET | `/palace/growth` | 成长树 + 已解锁 + 成长点余额 |
| POST | `/palace/growth/unlock` | 解锁成长节点（`nodeId`） |
| GET | `/palace/exchange` | 兑换目录 + 代币余额 |
| POST | `/palace/exchange` | 兑换（`exchangeId` / `count`），发放到账号背包 |
| POST | `/palace/abandon` | 放弃本次 run（已入账奖励保留） |

- 请求 / 响应 Pydantic 模型加入 `backend/app/schemas/game.py`。

---

## 13. 奖励兑换

配置 `palace.exchange[]`：

| id | 奖励 | 消耗（首版） |
| --- | --- | --- |
| `ex_seed_gold` | 金币种子 `seed_gold` | 2 烈火纹章 |
| `ex_seed_exp` | 经验种子 `seed_exp` | 3 烈火纹章 |
| `ex_materia_l5` | 随机 5 级魔晶石 `m_*_5` | 3 玻璃南瓜 |
| `ex_recraft_card` | 重新打造卡 `recraft_card` | 1 玻璃南瓜 |
| `ex_potion3` | 随机 3 级秘药 | 4 烈火纹章 |
| `ex_food3` | 随机 3 级料理 | 4 烈火纹章 |

- 兑现走 `dohdol_util.stack_add`（种子 / 卡 / 魔晶石 / 秘药）与 `grant_generated_items`（装备类）。
- 服务端行锁 + 余额校验；`count ≥ 1`。

---

## 14. 称号：死灵术士

- `titles.json` 新增：

```jsonc
{ "id": "palace_necro", "name": "死灵术士", "desc": "通关死者宫殿第 10 层 10 次。",
  "condition": { "type": "palace_clear", "count": 10 } }
```

- `services/titles.py` 新增 `evaluate_palace_titles(db, user_id)`（比对 `PalaceProfile.floor10_clears ≥ count`），在层 BOSS 结算处调用；`matches()` 对新 type 返回 `False`（与 `coop_clear` / `random_drop` 同待遇），正常出现在设置页与称号图鉴。

---

## 15. 数据模型与迁移

新增迁移（Alembic，**只建表 / 只加行，永不清理**）：

### 15.1 `palace_profiles`（账号级）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `user_id` | int unique | 账号 |
| `growth_points` | int | 成长点余额 |
| `total_growth_earned` | int | 累计获得成长点（审计 / 展示） |
| `flame_crest` | int | 烈火纹章 |
| `glass_pumpkin` | int | 玻璃南瓜 |
| `floor10_clears` | int | 通关第 10 层次数（称号判定） |
| `unlocked` | JSON | 已解锁成长节点 id 列表 |
| `created_at` / `updated_at` | float | 时间 |

### 15.2 `palace_runs`（每账号至多一份进行中）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `user_id` | int unique | 账号 |
| `status` | str | `choosing_hero` / `choosing_weapon` / `running` / `ended` |
| `floor` | int | 当前层 1–10 |
| `step` | int | 当前步 1–10 |
| `hero` | JSON | 副本英雄快照（level/exp/talent/三维/job/attrs） |
| `hero_candidates` | JSON | 待选英雄候选（3） |
| `weapon_candidates` | JSON | 待选武器候选（3） |
| `map` | JSON | 当前层路径图 |
| `current_node` | str? | 当前所在节点 id |
| `items` | JSON | 副本装备列表 |
| `buffs` | JSON | 副本 BUFF 列表 |
| `run_gold` | int | 副本金币 |
| `pending_reward` | JSON? | 待领奖励三选一 |
| `pending_node` | JSON? | 待结算事件 / 商店 / 宝箱上下文 |
| `revive_left` | int | 剩余复活次数 |
| `snapshot` | JSON? | 当前战斗节点的校验快照 |
| `node_started_at` | float? | 当前节点开始时间（服务端时钟） |
| `updated_at` / `created_at` | float | 时间 |

---

## 16. 共享配置清单

| 文件 | 内容 |
| --- | --- |
| `shared/data/palace.json` | 入口 / 层数 / 步数、节点权重、怪物曲线、战斗奖励权重、副本金币、层 BOSS 奖励、兑换表、等级上限、复活次数 |
| `shared/data/palace-growth.json` | 成长树（≥22 类别 × 10 级 ≥220 节点） |
| `shared/data/palace-events.json` | 事件库（≥32 条） |

- 由 `scripts/gen-palace-data.py` 生成（关键类别手工精调区）。
- 双端加载：`shared/schema/loader.py`（snake_case）⟷ `shared/schema/index.ts`（camelCase）。
- `backend/tests/test_shared_data.py` 新增结构断言（层数 / 步数、权重和为 1、成长树规模与消耗、事件数量、兑换引用存在、怪物数值递增）。

---

## 17. 前端设计（二级页面）

### 17.1 路由与导航

- 路由：`/palace` → `views/PalaceView.vue`。
- 导航：加入「战斗」分组（须与路由一一对应，`navigation.spec.ts` 会断言）。

### 17.2 页面结构（状态机分区 + 页内 Tab）

1. **入口 / 概览**：规则（折叠进 `?` / `<details>`）、我的成长点 / 代币 / 通关次数、开始 / 继续按钮。
2. **选英雄 / 选武器**：三选一卡片（英雄卡轻组件 + `ItemCard` 装备卡）。
3. **路径图**：DAG 可视化（步为行、节点为列、连线示意）；可选节点高亮；移动端横向滚动。
4. **战斗**：独立战斗面板——单英雄（头像 / 血条 / 蓝条 / 技能条 / 绝技槽）+ 敌人；飘字复用 `BattleFloatLayer`、血条复用 `HealthBar`；日志区固定高滚动。
5. **事件 / 商店 / 宝箱 / 休息**：事件卡 + 选项按钮；商店网格；宝箱三选一。
6. **结算 / 奖励**：奖励三选一（`ItemCard` / BUFF 卡）。
7. **装备**：副本内背包与穿戴（复用 `ItemPickerModal` 交互套路 + `slots_util` 栏位）。
8. **局外成长树**：类别分组 + 节点网格 + 加点（点数不足显式标注）。
9. **奖励兑换**：代币余额 + 商品网格 + 数量选择。

- 移动端：`--app-safe-*` 避让、`lg:grid-cols-2` 双栏、固定高日志、`gallery-cell` 批量卡片、浮层 `Teleport to="body"`。
- 音效：新增 `palace.*` 前缀 cue（进入 / 选英雄 / 选武器 / 节点进入 / 战斗 / 升级 / 事件 / 商店 / 层 BOSS / 通关 / 加点 / 兑换），补 `CUES` 与 `audio.spec.ts` 的 `required` 清单。
- store：`stores/palace.ts` 照 `stores/treasure.ts`（rAF 步进 + `simBudgetMs` 补算 + 时长异常重试 + 后台静默）。

---

## 18. 数值标定与防挂机

### 18.1 标定目标

1. **零成长**：无论运气多好，最多到达**第 5 层**（第 6 层小怪数值超纲）。
2. **满成长**：可**秒杀第 1–3 层**小怪；即使运气差也不至于卡死在第 1–2 层（前几层给足缓冲）。
3. 单次完整通关的点数 / 代币产出与成长树消耗匹配（长线养成）。

### 18.2 标定方法

- `scripts/palace-balance.py` + `backend/app/services/palace_sim.py`：用真实战斗公式（`combat_model.theoretical_dps` + `palace_stats.compute_run_stats`）跑**蒙特卡洛**——对「零成长 / 半成长 / 满成长」三种配置，模拟「随机英雄 × 随机装备 × 每战按 3 选 1 概率获取装备与祝福 × 随机敌人」，记录到达层数分布。
- 回归：`backend/tests/test_palace.py` 断言关键边界（零成长 ≤5 层、满成长可秒杀第 1–3 层且最低到达 ≥6 层、成长显著提升到达层数）。

### 18.3 实测结果（seed 0–39，节点近似 7 战 + 层主）

| 配置 | 平均到达 | 分布 |
| --- | --- | --- |
| 零成长 | ~4.1 层 | 3 层起，**上限 5 层** |
| 半成长 | ~8.3 层 | 7–9 层 |
| 满成长 | ~8.5 层 | 8–10 层 |

单只小怪理论击杀秒数（满成长 / 零成长）：第 1 层 `0.00s / 2.31s`、第 2 层 `0.01s / 0.60s`、第 3 层 `0.02s / 1.92s`、第 8 层 `5.48s / 303.7s`。

- 零成长「运气极好」也只能到第 5 层，符合需求。
- 满成长可**秒杀前 3 层**小怪，且运气差时最低也到第 8 层（不卡死前几关），并能到达第 10 层——「死灵术士」称号可通过。
- 模拟刻意**保守**（固定 7 战/层、每战按概率给奖励、不计事件的极端增益），真实极限会更远。
- 所有数值写在配置中，可随时调整（符合「数值优先改共享 JSON」）。

---

## 19. 验收标准

1. 闭环可用：选英雄 → 选武器 → 路径推进 → 战斗 / 事件 / 商店 → 奖励 → 层 BOSS → 下一层 → 10 层通关。
2. 隔离正确：带任何账号装备 / 秘药进入，副本面板与战斗结果不受影响。
3. 路径：1对1 / 1对多 / 多对1 均可走；第 10 步必为层 BOSS；非法后继节点被拒。
4. 成长树：≥22 类别 / ≥200 节点 / 全树消耗 >400 点；加点与生效正确、幂等。
5. 兑换：纹章 / 南瓜正确扣减与发放；重新打造卡 = 1 南瓜、3 级料理 = 4 纹章（按配置）。
6. 称号：`floor10_clears ≥ 10` 幂等补发「死灵术士」。
7. 标定：零成长到达 ≤5 层；满成长前几层速通；运气差也不卡死前几关。
8. 再进入：中途退出后重新进入可续接未完成节点。
9. 多端：窄屏 / 桌面均可完整操作，无溢出，贴边 UI 避让安全区。

---

## 20. 待定 / 可调项

1. 每层步数与节点数（当前 10 步），是否把事件 / 商店计入步数以减轻单 run 长度。
2. 单 run 战斗次数较多（最多约 100 节点），是否增加「自动战斗 / 快进」。
3. 成长树各类别节点数与点数曲线（脚本可调）。
4. 兑换商品清单与消耗数量。
5. 副本内装备的词条 / 品阶池是否与账号装备完全一致。
6. 副本等级上限与经验曲线。

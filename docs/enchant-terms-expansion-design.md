# 附魔词条扩展设计（战斗 12 类 + 生产/采集）

> 本文为「附魔/词条」扩充的设计稿（PRD）。战斗词条池见 `shared/data/terms.json`，
> 生产/采集词条池见 `shared/data/dohdol-equipment.json`（由 `scripts/gen-dohdol-data.py` 生成），
> 机制参数见 `shared/data/combat.json`，评分权重见 `shared/data/economy.json`。
> 落地实现必须与本文数值一致；两端公式同源：前端 `frontend/src/game/core/{battle,combat}.ts`，
> 后端 `backend/app/services/{stats,combat_model,damage}.py`。

## 1. 总则

1. **实现方式沿用现有 proc 模式**：新增效果以「新的 `stat` 键 + `combat.json` 参数块」表达。
   词条只承载「触发概率/强度值」（`range` 随机），效果量（持续时间、倍率、阈值、层数上限）统一放在
   `combat.json:equipEffects`，避免数值散落。
2. **`trigger` 字段仅用于展示**（`常驻 / 触发 / 持续`），实际行为由 `stat` 键约定决定。
3. **`category` 字段**：每个词条新增必填 `category`；`terms.json` 与 `dohdol-equipment.json` 增加
   `categories` 名表（`id → 中文名`），词条图鉴按类筛选/分组。
4. **风险代价词条**：新增可选字段 `cost: { stat, ratio }`。落库词条对象携带
   `cost: { stat, value, name }`，其中 `value = round(主值 × ratio)`。代价通过 `aggregate_equipment`
   累加进 `term_mods[cost.stat]`，与主效果一同生效；UI 以「负向配对」展示。
5. **DPS 一致性红线**：任何**提升 DPS** 的新机制必须镜像进后端
   `combat_model.theoretical_dps / proc_dps_bonus`，否则合法上报会被击杀额度校验拒绝。
   仅影响生存/资源的机制**不建模**（与 `wither`/`blind`/恢复类同待遇），并在代码注释说明。
6. Debuff 恒为 `common`（`economy.json:debuffQualityEnabled=false` 不变）；扩池不改变 Debuff 出现频率，
   只增加多样性、避免某栏位候选耗尽。

## 2. 战斗类别（`category`）

| id | 名称 | 说明 |
|---|---|---|
| attribute | 常住属性 | 常驻面板属性增减 |
| onAttack | 攻击触发 | 命中/释放时概率触发 |
| abnormal | 异常 | 对目标施加减益状态 |
| onHitTaken | 受击 | 自身受到伤害时触发 |
| defense | 防御 | 减伤 / 格挡 / 护盾强化 |
| conditional | 条件 | 满足条件（血量/魔力/目标/时间）时生效 |
| growth | 动态成长 | 战斗内可叠加成长 |
| convert | 资源转换 | 生命/魔力/击杀资源互换 |
| synergy | 联动 | 属性之间相互转化/加成 |
| risk | 风险代价 | 有明确副作用的强力增益（`cost`） |
| special | 特殊机制 | 复活 / 处决 / 免死等 |
| charge | 累计触发 | 累计量达阈值后触发 |

## 3. 战斗新增 Buff（`shared/data/terms.json:terms`）

数值区间沿用现有词条量级（对照 `strBoost` 2–15、`burnOnHit` 5–20 等）。

| category | id | name | stat | range | slots | desc |
|---|---|---|---|---|---|---|
| attribute | magicPower | 魔力增幅 | magicAttackPct | [2,15] | 全 | 魔法攻击力 +{v}% |
| attribute | ironWall | 铁壁 | physDefPct | [3,18] | 防具/饰 | 物理防御 +{v}% |
| attribute | aegisWard | 魔防屏障 | magicDefPct | [3,18] | 防具/饰 | 魔法防御 +{v}% |
| attribute | manaPool | 魔力上限 | maxMpPct | [3,20] | 全 | 最大魔力 +{v}% |
| attribute | healPower | 治愈之力 | healPowerPct | [3,15] | 头/身/饰 | 治疗效果 +{v}% |
| onAttack | bleedOnHit | 裂伤 | bleedProcPct | [5,20] | 主手/手/饰 | 命中 {v}% 概率使目标流血，8 秒每秒受到攻击力 25% 的伤害 |
| onAttack | defBreakOnHit | 破防 | defBreakProcPct | [5,20] | 主手/手/饰 | 命中 {v}% 概率使目标防御 -25%，持续 8 秒 |
| onAttack | combo | 连击 | doubleAttackPct | [3,12] | 主手/手/饰 | {v}% 概率追加一次普攻 |
| abnormal | slowOnHit | 缓速 | slowProcPct | [5,20] | 主手/手/饰 | 命中 {v}% 概率使目标攻击速度 -20%，持续 8 秒 |
| abnormal | stunOnHit | 眩晕 | stunProcPct | [3,12] | 主手/手 | 命中 {v}% 概率眩晕目标 2 秒 |
| onHitTaken | reflectOnHit | 反震 | reflectProcPct | [5,20] | 身/腿/脚/饰 | 受击 {v}% 概率反弹本次伤害的 30% |
| onHitTaken | vengeanceOnHit | 复仇 | vengeanceProcPct | [5,20] | 身/饰 | 受击 {v}% 概率获得攻击 +15%，持续 6 秒 |
| onHitTaken | aegisOnHit | 庇护 | aegisProcPct | [5,20] | 身/饰 | 受击 {v}% 概率获得最大生命 8% 的护盾 |
| onHitTaken | resolveOnHit | 坚毅 | resolveProcPct | [3,12] | 头/饰 | 受击 {v}% 概率恢复 6% 最大魔力 |
| defense | guard | 守护 | guardPct | [3,15] | 全 | 受到伤害 -{v}% |
| defense | block | 格挡 | blockProcPct | [5,20] | 盾/身/手 | {v}% 概率格挡，本次伤害减半 |
| defense | shieldBoost | 护盾强化 | shieldBoostPct | [5,25] | 盾/头/身 | 护盾获得量 +{v}% |
| conditional | lastStand | 背水 | lowHpAttackPct | [5,25] | 全 | 生命低于 50% 时攻击 +{v}% |
| conditional | openingRush | 先手 | openingDamagePct | [5,25] | 主手/饰 | 战斗开始 10 秒内伤害 +{v}% |
| conditional | bossHunter | 讨伐 | bossDamagePct | [5,25] | 主手/饰 | 对精英与 BOSS 伤害 +{v}% |
| conditional | desperateMp | 枯竭 | lowMpRegenPct | [5,20] | 头/饰 | 魔力低于 30% 时魔力恢复 +{v}% |
| growth | battleSpirit | 战意 | killStackAttackPct | [1,4] | 主手/身 | 每击杀 +{v}% 攻击，最多 10 层 |
| growth | sharpness | 锐意 | hitStackSpeedPct | [0.5,2] | 手/饰 | 每次命中 +{v}% 攻击速度，最多 10 层 |
| growth | chanting | 咏唱 | skillStackDamagePct | [1,3] | 主手/头 | 每次释放技能 +{v}% 技能伤害，最多 8 层 |
| convert | hpToMp | 转魔 | hpToMpPct | [3,10] | 头/饰 | 魔力 < 50% 时每秒将最大生命 {v}% 转为魔力，恢复到 80% 停止 |
| convert | mpSurge | 魔力灌注 | mpSurgeDamagePct | [5,20] | 主手/饰 | 技能伤害额外提升 当前魔力% × {v}% |
| convert | killRestoreMp | 汲魔 | killRestoreMpPct | [3,10] | 饰 | 击杀恢复 {v}% 最大魔力 |
| synergy | vitToAttack | 体魄 | vitToAttackPct | [5,20] | 身/饰 | 体力值的 {v}% 转化为攻击 |
| synergy | critToDet | 断罪 | critToDetPct | [5,20] | 头/饰 | 暴击值的 {v}% 转化为信念 |
| synergy | dhConvert | 直击转化 | dhConvertPct | [5,15] | 耳/镯 | 暴击率的 {v}% 转化为直击率（既有词条，归入本类） |
| risk | berserk | 狂战 | berserkPct | [5,20] | 主手/身 | cost: damageTakenPct × 0.5；攻击 +{v}%，受到伤害 +{c}% |
| risk | glassCannon | 玻璃大炮 | glassCannonPct | [5,20] | 主手/身 | cost: maxHpPct × 0.5；全伤害 +{v}%，最大生命 {c}% |
| risk | reckless | 孤注 | recklessPct | [5,20] | 主手/手 | cost: damageTakenPct × 0.4；技能伤害 +{v}%，受到伤害 +{c}% |
| special | deathResist | 死亡抵抗 | reviveChancePct | [5,15] | 全 | 死亡时 {v}% 概率复活并回复 30% 生命（既有死属性，本次实现） |
| special | execute | 处决 | executePct | [5,20] | 主手/饰 | 目标生命低于 30% 时伤害 +{v}% |
| special | cheatDeath | 不死 | cheatDeathPct | [3,10] | 身/饰 | 受致命伤害时 {v}% 概率免死并保留 1 点生命（每场 1 次） |
| charge | chargeBlast | 蓄势 | chargeBlastPct | [5,20] | 主手/手 | 累计造成目标 100% 最大生命伤害后触发范围爆发（攻击力 {v}%） |
| charge | chargeShield | 受创蓄力 | chargeShieldPct | [5,20] | 身/饰 | 累计受到 30% 最大生命伤害后获得护盾（最大生命 {v}%） |
| charge | chargeHeal | 咏唱蓄能 | chargeHealPct | [5,20] | 头/饰 | 累计释放 10 次技能后恢复最大生命 {v}% |

> 表中 `{c}` 表示 `cost` 折算值（= `round(v × ratio)`）；实现时 `desc` 用 `{v}` 与 `{c}` 两个占位符。

## 4. 战斗新增 Debuff（`shared/data/terms.json:terms`）

| id | name | stat | range | desc |
|---|---|---|---|---|
| magicWeak | 魔力枯竭 | magicAttackPct | [-15,-3] | 魔法攻击力 {v}% |
| armorBreak | 破甲 | physDefPct | [-18,-3] | 物理防御 {v}% |
| magicBreak | 魔防崩坏 | magicDefPct | [-18,-3] | 魔法防御 {v}% |
| manaDrought | 魔力上限削减 | maxMpPct | [-20,-3] | 最大魔力 {v}% |
| healSuppress | 治愈抑制 | healPowerPct | [-15,-3] | 治疗效果 {v}% |
| shieldCrack | 破盾 | shieldBoostPct | [-25,-5] | 护盾获得量 {v}% |
| frailty | 重创 | damageTakenPct | [4,15] | 受到伤害 +{v}% |
| weakPoint | 暴击破绽 | critDamagePct | [-12,-3] | 暴击伤害 {v}% |
| cdDelayed | 迟滞 | cdReducePct | [-8,-2] | 技能冷却 {v}%（负值即延长） |
| expDrain | 惰怠 | expGainPct | [-18,-3] | 经验获取 {v}% |
| miserly | 吝啬 | goldGainPct | [-15,-3] | 击杀金币 {v}% |
| bloodless | 失血 | lifestealPct | [-5,-1] | 吸血 {v}% |
| dulled | 钝锋 | skillDamagePct | [-10,-2] | 技能伤害 {v}% |

**平衡目标**：战斗池最终约 80 Buff / 25 Debuff（Debuff 占比约 24%）。现有 45 条（33/12）→ 目标
78 Buff / 25 Debuff。因 `debuffChance` 逐条判定，扩池不改变 Debuff 频率。

## 5. 机制参数（`combat.json:equipEffects`）

```jsonc
{
  "proc": {
    "bleed":     { "potencyPct": 25, "durationSec": 8, "tickSec": 1 },
    "defBreak":  { "defenseDownPct": 25, "durationSec": 8 },
    "slow":      { "attackSpeedDownPct": 20, "durationSec": 8 },
    "stun":      { "durationSec": 2 },
    "reflect":   { "damagePct": 30 },
    "vengeance": { "attackBuffPct": 15, "durationSec": 6 },
    "aegis":     { "maxHpShieldPct": 0.08, "durationSec": 6 },
    "resolve":   { "maxMpRestorePct": 0.06 }
  },
  "conditional": {
    "lowHp":   { "hpThresholdPct": 50 },
    "opening": { "windowSec": 10 },
    "boss":    { "kinds": ["elite", "boss"] },
    "lowMp":   { "mpThresholdPct": 30 }
  },
  "growth": {
    "killStackAttackPct":  { "maxStacks": 10 },
    "hitStackSpeedPct":    { "maxStacks": 10 },
    "skillStackDamagePct": { "maxStacks": 8 }
  },
  "convert": { "hpToMp": { "intervalSec": 1 }, "mpSurge": { "basePctOfMp": 1.0 }, "killRestoreMp": {} },
  "charge": {
    "chargeBlast":  { "hpThresholdPct": 100, "potencyPct": 200 },
    "chargeShield": { "hpThresholdPct": 30 },
    "chargeHeal":   { "castThreshold": 10 }
  },
  "special": {
    "execute":    { "hpThresholdPct": 30 },
    "cheatDeath": { "durationSec": 0 },
    "revive":     { "reviveHpPct": 0.30 }
  }
}
```

### 公式

- **面板折算**（`stats.compute_stats`）：`magicAttack ×= 1 + magicAttackPct/100`；
  `physDef ×= 1 + physDefPct/100`；`magicDef ×= 1 + magicDefPct/100`；`maxMp ×= 1 + maxMpPct/100`；
  `healMultiplier ×= 1 + healPowerPct/100`；`tenacity += guardPct`；护盾获得量 `×(1 + shieldBoostPct/100)`；
  `vitToAttackPct`：`attack += 体力值 × vitToAttackPct/100`；`critToDetPct`：`detValue += critValue × critToDetPct/100`。
- **命中/受击 proc**：`Math.random()*100 < 概率值` → 生效（参数取 `equipEffects.proc`）。
- **条件**：`lowHp` → `heroHp/maxHp < 阈值`；`opening` → `battleElapsedSec < windowSec`；
  `boss` → 当前目标 `kind ∈ kinds`；`lowMp` → `heroMp/maxMp < 阈值`。
- **成长**：命中/击杀/施法时 `层数 = min(层数+1, maxStacks)`，加成为 `层数 × 值`。
- **累计**：累计量达阈值触发一次 → 归零（或按需保留）。
- **风险**：`cost` 值 = `round(主值 × ratio)`，累加进 `term_mods[cost.stat]`（可为 `damageTakenPct`/`maxHpPct`）。

### 后端镜像清单

| 机制 | 是否镜像后端 DPS 模型 | 理由 |
|---|---|---|
| bleed / defBreak / doubleAttack / execute / bossHunter / openingDamage / lowHpAttack | **是** | 直接提高 DPS，需放宽击杀额度 |
| growth（战意/锐意/咏唱） | **是** | 战斗内 DPS 增长 |
| mpSurge / killRestoreMp / hpToMp | 否 | 仅资源，不提高期望 DPS 上限 |
| reflect / vengeance / aegis / resolve / block / guard / shieldBoost | 否 | 仅生存 |
| slow / stun / defBreak（敌方减益的生存部分） | 部分 | defBreak 降低目标防御 → 计入 DPS；slow/stun 仅生存 |
| charge*（爆发） | **是** | chargeBlast 触发伤害计入 DPS |
| cheatDeath / reviveChance | 否 | 仅生存 |
| vitToAttack / critToDet / magicAttackPct 等面板 | 自动 | 面板由 `stats.py` 计算，`theoretical_dps` 直接读取 |

## 6. 生产/采集新增词条（`dohdol-equipment.json`）

`bonusNames` 新增键：`craftMaterialSavePct`、`craftExtraOutputPct`、`craftQualityJumpPct`、
`gatherExtraActionPct`、`gatherRareChancePct`、`gatherDoublePct`、`fishDoubleCatchPct`。

| id | name | type | stat | range | desc |
|---|---|---|---|---|---|
| dohFrugal | 节俭 | buff | craftMaterialSavePct | [5,20] | 制造 {v}% 概率不消耗材料 |
| dohProlific | 多产 | buff | craftExtraOutputPct | [3,12] | 制造 {v}% 概率额外产出 1 件 |
| dohMasterpiece | 杰作 | buff | craftQualityJumpPct | [2,8] | 制造品质跃升概率 +{v}% |
| dolExtraAction | 勤采 | buff | gatherExtraActionPct | [3,12] | 采集 {v}% 概率额外采集一次 |
| dolRareFind | 珍稀 | buff | gatherRareChancePct | [3,10] | 采集 {v}% 概率获得稀有材料 |
| dolDoubleHaul | 满载 | buff | gatherDoublePct | [3,12] | 采集 {v}% 概率产量翻倍 |
| dolDoubleCatch | 双钩 | buff | fishDoubleCatchPct | [3,12] | 钓鱼 {v}% 概率双倍鱼获 |
| dohWasteful | 浪费 | debuff | craftMaterialSavePct | [-20,-5] | 制造额外消耗材料概率 |
| dohBarren | 减产 | debuff | craftExtraOutputPct | [-12,-3] | 额外产出概率 {v}% |
| dohFlawed | 瑕疵 | debuff | craftQualityJumpPct | [-8,-2] | 品质跃升概率 {v}% |
| dolIdle | 怠惰 | debuff | gatherExtraActionPct | [-12,-3] | 额外采集概率 {v}% |
| dolBarren | 空手 | debuff | gatherRareChancePct | [-10,-3] | 稀有材料概率 {v}% |
| dolBadCatch | 脱钩 | debuff | fishDoubleCatchPct | [-12,-3] | 双倍鱼获概率 {v}% |

生产分类名表：`doh 生产` / `dol 采集` / `craftOutput 制造产出` / `gatherOutput 采集产出` / `fish 钓鱼`。

**结算接入点**：`production.report_produce`（材料节省/额外产出/品质跃升）、
`gathering.report_gather`（额外采集/稀有材料/产量翻倍）、`fishing.report_fish`（双倍鱼获）。
`dohdol_util.equipped_bonus` 已按 stat 键汇总，无需改动。

## 7. 评分（战力）

`economy.json:power.weights` 为新 stat 补充权重（未登记即 0），保证「战力 ↔ 真实价值」单调。
risk 类按 upside 折价（同时含 `cost` 的负权重项）。

## 8. 验收

- `backend/tests/test_shared_data.py`：所有词条含合法 `category`；`power.weights` 覆盖新增关键 stat。
- `backend/tests/test_engine.py`：`category` 落库、`cost` 折算、成长层数上限、条件/受击 proc、
  `reviveChance`/`cheatDeath`、`charge` 触发；`TestDebuffHasNoQuality` 与太古保底不回归。
- `backend/tests/test_dohdol.py`：生产新词条有效性与结算；`test_rarity_luck_sources_are_consistent` 仍通过。
- 前端 `*.spec.ts`：新机制用例；`core.spec.ts` 击杀手感不回归。
- 游戏内：图鉴按类筛选可见、附魔能抽出新词条、战斗日志出现新 proc、生产/采集结算体现新加成。

# 项目上下文：艾欧泽亚放置录

本文件供后续新聊天快速了解项目。更新日期：2026-09-25。功能状态以当前代码、共享配置和测试为准；修改架构、启动方式或核心规则时同步更新本文。

## 项目概况

- 仓库名 `FF14Push`，产品名「艾欧泽亚放置录 / Eorzea Idle Chronicle」。这是 FF14 同人放置类网页游戏，并非消息推送工具，与官方无关。
- 核心循环：英雄自动战斗 → 获得金币和经验 → 抽箱获取装备 → 穿戴、合成、重造、附魔 → 推进地区和副本。
- 已包含 40 个地区、21 个战斗职业、装备养成、酒馆招募、图鉴、排行榜、管理功能，以及生产/采集/钓鱼系统。
- 联机 DLC 已有实现：最多 8 名独立英雄（**名册容量可用金币扩充到 20 席**，基准 8 席、线性递增、见 `shared/data/heroes.json:roster` 与 `services/roster.py`，接口 `POST /heroes/expand`）、异步 PvP、个人/离线/在线合作、12 个团队副本；前端入口为「名册」「远征」「竞技场」。不要将设计文档中的全部内容直接当成待开发任务。
- 远征通关记录与「远征榜」已实现：`coop_worker` 在通关瞬间把时长与全席位分角色战斗信息写入 `coop_records`（每个真实参战账号一行）；排行榜页「远征榜」按副本实时聚合（不走 5 分钟缓存），展示最快通关时长与阵容。
- 好友系统已实现：账号有唯一「好友码」（`users.friend_code`，注册 / 迁移生成），凭码申请 + 对方同意后成为好友；好友列表展示在线状态（`users.last_seen_at` + 前端心跳，45s 内视为在线）。好友间可金币转账，手续费 `economy.json:transfer.feePct`（默认 10%）从转账额扣除后销毁，另有单笔上下限与每日累计上限（见 `services/friends.py`）。
- 聊天室已实现：单一公开大厅，登录后可看可发，实名展示 `昵称#登录账号`（同排行榜；**管理员只显示「管理员」+ 徽章，`services/chat.serialize` 不回显也不下发其登录账号**）。仅文本（单条 ≤200 字），**不保留聊天记录**——服务端只保留最近 10 分钟消息（`services/chat.py:RETENTION_SECONDS`），窗口外历史永不返回、发言时清理过期行；发言限频 20 条/60 秒（`guard_rate`）。实时推送为 WebSocket `/api/v1/chat/ws`（短时效一次性 ticket 鉴权，`services/chat.issue_ticket/consume_ticket`），广播沿用 `api/v1/coop.py` 的「各连接按游标轮询 DB」模式，天然多 worker 安全。管理员可在聊天室发公告（`POST /chat/announce`，高亮、不受发言限频）。**公告是「不保留记录」的例外**：长期保留、置顶于聊天室顶部，不参与滚动窗口的读取与清理（`services/chat.announcements/new_announcements`，按 id 倒序最新在前）。表：`chat_messages`、`chat_tickets`（迁移 `o1a2b3c4d5e7`）。
- 世界BOSS 已实现：全服共享血量的 BOSS「黄金巴哈姆特」（初始 **20 亿**血量、第一阶段攻击力 20000）。**采用「讨伐周期」制**：`worldboss.json:periodSeconds`（默认 5h）是唯一结算单位——周期内 BOSS 被击杀只进入 `respawnSeconds`（60s）短休整、到点满血重生且 **cycle 不变**、可反复讨伐（`kills` 计数）；周期到时（`period_ends_at`）无论存亡都满血、**cycle+1**、结束上一周期全部会话（`services/world_boss.roll_world_boss`），**击杀与结算解耦**，弱玩家只要在周期内参与就一定有奖励。所有在线玩家各自上阵最多 8 名英雄同时削弱同一血量；**战斗运算下放客户端**：前端 `game/core/worldboss.ts` 复刻 `services/worldboss_engine.py`（100ms tick，BOSS 普攻对全体存活英雄、技能按固定间隔随机独立释放，英雄各自独立死亡/复活）在本地模拟并按窗口把伤害增量上报 `POST /worldboss/report`；服务端只做**上限夹取**（`services/worldboss_model.py`：理论上界 × 窗口 × 容差，窗口只认服务端时钟，`reportSeq` 幂等）与**共享部分结算**（全局血量原子递减、贡献累计、周期换轮、奖励），`worldboss_worker` 仅推进全局时间（周期换轮 / 短休整复活），**不再扫描玩家会话**。**阶段（P1→P2→P3）**按全服剩余血量占比自动进入（`worldboss.json:phases`：≤60% 进 P2、≤30% 进 P3）：血量越低 **BOSS 防御越厚**（英雄输出按 `1/defenseMultiplier` 折算）、**技能威力越高**（`skillPotencyMultiplier`，不影响普攻）；阶段由客户端按 WS / 上报响应回传的全局血量占比写入 `state.bossHpRatio`。场地要求英雄 80 级以上，80–99 级输出/治疗被线性削弱（满级解除）。按**周期**结算：奖励 = **击杀奖励 + 档位 + 名次加成**——**击杀奖励**（`reward.killReward`）按本周期全服击杀次数给**所有达标玩家同额**发放（件数 = `min(击杀次数 × perKill, maxItems)`，换轮时把结束周期的击杀数写入 `world_boss_cycles`，只新增行、永不清理）；**档位**（`reward.tiers`，按周期累计伤害取最高达标档）+ **名次加成**（`reward.rankBonus`，仅前 10 名）已下调；入榜门槛累计伤害 ≥ 500 万。**「本周期进度」与排行榜同源**：`/worldboss/report` 的 `myDamage` 返回**周期累计贡献**（不是本场会话累计）。榜单行可点击展开查看该玩家本周期各英雄的伤害与占比（贡献按 `heroId` 累加增量，跨多次上阵不重复计数）。**世界BOSS 血量、周期与总伤害榜不随版本更新重置**（贡献/奖励行永久保留）。「绝境龙神」固定红色（神话）品质、100 级，仅世界BOSS 掉落（不可抽奖/打造/合成），可重造/附魔但成本 ×`economy.json:exclusiveCostMultiplier`（远高于其他装备）。数据表 `world_bosses` / `world_boss_sessions` / `world_boss_contributions` / `world_boss_rewards` / `world_boss_tickets` / `world_boss_cycles`（迁移 `p2b4d6f8a0c2`；周期列 `period_ends_at` / `kills` 见 `t6f8a0b2c4d6`，客户端上报游标 `last_report_at` / `last_report_seq` 见 `y2f4a6b8c0d2`，每周期击杀快照 `world_boss_cycles` 见 `c1d2e3f4a5b6`；设计见 `docs/world-boss-cycle-redesign.md` 与 `docs/multiplayer-load-bandwidth-design.md`），配置见 `shared/data/worldboss.json`、`shared/data/exclusive-equipment.json`。
- 地区战斗**难度等级（周目制）** 已实现：账号级 `users.battle_difficulty`（当前，0–15）与 `battle_difficulty_max`（已解锁上限），地区进度按 `region_progress.difficulty` 隔离——进入新难度后 40 个地区重新锁定，**每次**击败当前难度第 40 区关底 BOSS 即解锁下一难度（`api/v1/battle.py::_settle_boss`；刻意不要求首通，否则功能上线前已通关的旧存档永远无法解锁）；切换难度用 `POST /battle/difficulty`，仅限已解锁范围且会结束进行中会话、落回该难度「已通关最高地区 +1」。数值：怪物按**加法**放大（生命/防御/经验 `1+N`、攻击 `1+0.5N`、金币 `1+0.5N`），玩家攻击/防御按**乘法**缩小（`0.85^N` / `0.9^N`）；配置在 `shared/data/combat.json:difficulty`，前后端镜像 `services/difficulty.py` ⟷ `game/core/difficulty.ts`。难度 0 与历史数值逐位相同；玩家缩放只在战斗结算处施加，**不进入 `compute_stats` / 战力门槛**（否则高难度会自我锁门）；击杀额度、金币/经验上限与 BOSS 奖励都要带难度（`combat_model.py` / `validator.py`），否则合法上报会被拒或截断。难度只作用于地区战斗，不影响高难副本 / 远征 / 世界BOSS；**挖宝只借难度放大怪物数值与经验，挖宝金币不吃难度金币加成**（`services/treasure.py`，否则会击穿 `test_shared_data.py:test_treasure_is_not_a_gold_printer` 的防刷边界）。排行榜「关卡榜」（`services/ranking.py`）也把难度纳入主序：`value = 难度 × 1000 + 已通关最高地区`（难度 1 第 20 关排在难度 0 第 40 关之上），前端 `RankingView.vue` 按同基数解码展示。
- **挖宝 / 魔晶石 / 种田** 三个系统已实现，配置集中在 `shared/data/treasure.json`、`materia.json`、`farm.json`，后端服务 `services/treasure.py`、`materia.py`、`farm.py`，接口 `api/v1/treasure.py`、`materia.py`、`farm.py`，页面 `TreasureView.vue`、`MateriaView.vue`、`FarmView.vue`。要点：**挖宝**花 100 万进 5 层副本，每层怪物 = 难度(层-1) 的地区 40 关底 BOSS（难度只放大怪物与经验、不削弱玩家，且**挖宝金币不吃难度加成**），门 50/50、**宝箱在开箱时 roll 并立即入账**（选错门 / 阵亡都不影响已入账奖励）、阵亡可原地重试、每层 5% 猜大小、通关第 5 层额外 1000 万（**开箱转盘**：`components/TreasureWheel.vue` 把开箱做成圆盘转盘，扇区几何在 `game/core/wheel.ts` —— 每件奖励一个扇区、干扰项补足到至少 8 个扇区、逐件停在对应扇区，并尊重 `prefers-reduced-motion`；奖励仍由服务端结算，动画纯展示）；**魔晶石**孔位属**账号级 11 栏位 × 5 孔**（不随装备更换），第 1 孔 100%→第 5 孔 5%、失败消耗、取出返还，6 种 × 5 级（FF14 国译名）、5 合 1，加成经 `stats.compute_stats(socket_mods=...)` 注入；**种田**账号级田地 2→12 片、作物按**真实时间**生长（**离线也生长**，是「不做离线收益」的显式例外）、金币种子 1000 万 / 经验种子 +1 级（满级需二次确认）。三者共新增迁移 `r4d6f8a0c2e4`（`materia_sockets` / `farm_plots` / `treasure_runs` + `users.farm_unlocked`）。挖宝属战斗类活动，`services/roster.end_treasure_runs` 已接入互斥（开始其它活动 / 切换 / 解雇英雄都会结束进行中的副本）。
- 界面及项目文档主要使用中文，新增内容保持已有命名和文案风格。
- **顶部导航分组**：`frontend/src/navigation.ts` 以「分组（一级）→ 小节（三级小标题）→ 页面（二级）」定义菜单（战斗 / 养成 / 生活 / 社交 / 其它），桌面端渲染为页头分组下拉、窄屏渲染为侧边抽屉（均在 `frontend/src/App.vue`）。**新增页面必须同时挂进该文件**——`frontend/src/navigation.spec.ts` 会断言菜单路径与 `router/index.ts` 的登录后路由一一对应（不重不漏）。
- 玩家间**交易板**已实现（表 `market_listings` / `market_buy_orders`，服务 `services/market.py`，接口 `api/v1/market.py`，页面 `MarketView.vue`，配置 `shared/data/economy.json:market`）。**寄售**：上架即托管（装备删行 + 快照，堆叠扣库存），整单买断成交，成交价抽 `feePct` 手续费（金币直接销毁），未售出 `listingDays` 天到期退回；可交易的堆叠物种类由 `dohdol_util.sellable_kind` 决定（material / potion / food / **materia** / **seed**），前端 `MarketView.vue` 的子页签与 `StackKind` 联合类型需与之同步。**鱼获与采集材料同存 `kind="material"`**：市场用 `dohdol_util.fish_item_ids()` 把 `kind=fish`（仅鱼获，`/market/listings` 与 `/market/buy-orders` 的独立页签）与 `kind=material`（**排除**鱼获）分开过滤，两侧口径一致，改过滤时需同步。**收购单（求购）**：仅支持堆叠物，发布时按 `unit_price × quantity` **全额托管金币**，卖家手动按剩余数量**部分成交**（卖家得 `amount - fee`），未成交部分在下架 / 到期时退还；**刻意不做自动撮合、不记录逐笔成交历史**（只记 `filled` 总量），单账号进行中收购单上限 `maxActiveBuyOrders`。两侧托管/成交都在写端点内完成，对手方用 `lock_user` 加锁（加锁顺序：当前用户 → 单据行 → 对手方）。**参考价**（`MarketListing.reference_price`，展示为「参考价」，与系统回收价 `sell_price` 解耦）改为**按真实获取来源折算**：装备 = 抽箱期望成本（品类×品阶×抽箱等级档位，含保底，与 16 合 1 合成取最省）× 属性/词条实时系数；堆叠物 = 来源成本折算（魔晶石/种子按挖宝入场成本分摊、药水/食物按配方材料成本、材料按档位价值），且不低于系统回收价。基准表由 `scripts/derive-market-reference.py` 生成到 `shared/data/market-reference.json`（`CONFIG.market_reference`），实时系数在 `shared/data/economy.json:market.reference`，计算见 `services/reference.py`；改动 `chests/rarities/crafting/treasure/materia/recipes` 后须重跑该脚本。

- **钓鱼 2.0** 已实现（迁移 `v8b0d2f4a6c8`：`users.active_title_id` + `activity_sessions.session_insights/session_intuition`，旧单值 `insight_expires_at` 已删除）：普通鱼分**白 / 蓝 / 紫**三档并可带**天气 / 时间门槛**；每钓场的特殊鱼（旧鱼王 / 鱼皇 + 新增 `kind:"legend"` 困难鱼，如镜中蝶、七彩天主）统一由 **`intuition`（捕鱼人之识）** 驱动——**每种直觉只绑定一条鱼**，需在该鱼的天气 / 时段窗口内钓齐**计数型前置**（`requires: [{fishId,count}]`）才开启，**BUFF 期间不刷新 / 不延长**，到期后须重新钓齐才能再次触发。天气与艾欧泽亚时间（ET）是**服务端时间的纯函数**：`backend/app/services/weather.py` ⟷ `frontend/src/game/weather.ts` 用同一 32 位整型哈希（`hash01`）逐位一致，前端据此做**天气预报**；改算法必须同步两端（`test_dohdol.py::TestWeather::test_hash_matches_frontend_snapshot` 锁住快照）。数据：`shared/data/fish.json`（结构 `normal[]` + `specials[]`，旧 `king/emperor` 已迁入 `specials[]` 并标 `legacy:true`，**id 与数值不变**）+ `shared/data/weather.json`；由 `scripts/gen-fish-data.py` 从冻结的 `scripts/fish-base.json` 重建（改内容改脚本并重跑，不要手改 `fish.json`）。称号由 `services/titles.py` **数据驱动**判定（`titles.json` 的 `condition.type`：`all_king/all_emperor`（仅 legacy）/`all_legend`/`all_special`/`count_kind`/`count_rarity`/`specific_fish`/`species_count`/`fish_count`/`region_group_king`），每人可在设置页**佩戴一个**（`POST /settings/active-title`，`users.active_title_id`），佩戴中的称号在排行榜 / 玩家资料突出展示；旧称号只统计 legacy 鱼王 / 鱼皇，**新增困难鱼不影响其达成条件**。`fish_records.kind` 现可为 `normal|king|emperor|legend`，`services/ranking.py` 的钓鱼榜与 `services/dohdol_state.py` 的 `fishStats` 已同步 legend 桶。提高特殊鱼概率的加成（专用装备词条「渔王的直觉」与药食的 `fishChancePct`、`fishInsightPct`）在 `fishing._resolve_catch` / `_advance_intuition` 中对所有特殊鱼统一乘同一系数，**鱼王 / 鱼皇 / 困难鱼一视同仁**，展示名统一为「特殊鱼概率」（`dohdol-equipment.json:bonusNames`、`consumables.json:effectNames`），不要按 `kind` 过滤。另有 **10 个彩蛋称号**（挖宝下底 ×5 / 采集 ×5，`condition.type == "random_drop"`，**极低概率**）：**非确定性**，由 `titles.roll_random_titles(db, user_id, event, rolls)` 在 `services/treasure.open_chest`（通关第 5 层 = 下底）与 `services/gathering.report_gather`（按本次采集动作数 `rolls`）处抽取，逐称号独立判定（合并概率 `1−(1−p)^rolls`）、已拥有则跳过；**`evaluate_titles` 不处理 `random_drop`**（`matches()` 对其返回 False），故彩蛋不会被确定性条件误发。这两个响应各带 `newTitles`，前端 `dohdol`/`treasure` store 弹「达成彩蛋称号」提示（`titles.json` 中 `egg: true` 在设置页 / 钓鱼页标「彩蛋」）。

- **全场景音效**已实现：音效由**浏览器实时合成**（Web Audio API），谱面是纯数据、**不打包任何音频素材、不引入第三方音频库**。引擎在 `frontend/src/game/audio.ts`（单例 `sound`，导出 `SoundCue` 联合类型 + `CUES` 谱面 + 纯函数 `gate()` 节流闸门），设置由 `frontend/src/stores/sound.ts` 持有并注入（localStorage 前缀 `eorzea.sound.*`：`enabled` / `master` / `battle` / `ui` / `ambient`，对应设置页音效区块）。战斗语义事件由 `BattleSimulator` 的可选构造参数 `onSound?: (cue: SoundCue) => void` 上报（未注入即静默，核心模拟器不依赖音频），`stores/game.ts`、`stores/treasure.ts` 传入 `sound.play`；世界BOSS 音效来自 WebSocket 增量事件（按 `seq` 去重）。事件点：战斗（`battle.hit/crit/skill/signature/heal/hurt/kill/clear/death/revive/boss.*`）、挖宝转盘与选门、抽箱滚轮、重造 / 附魔（涨跌不同音）、魔晶石、采集 / 生产 / 钓鱼 / 序列 / 种田、掉落气泡（按品阶）、弹窗开关。**关键事件必响、高频事件按最小间隔节流**（单音效 `throttleMs` + 全局 100ms 窗口并发上限），避免 DoT / proc 高峰爆音。AudioContext 在首个用户手势解锁（`App.vue`），页面切到后台（`document.hidden`）时静默。新增音效必须同时补 `CUES` 谱面（`Record<SoundCue, CueSpec>` 会强制穷尽），并同步 `frontend/src/game/audio.spec.ts` 的「关键音效齐备」清单。

## 协作约定

- **对话语言**：与用户的所有交流（回复、计划、说明、提问）一律使用中文。
- **更新日志（面向玩家的公告，必须执行，勿遗漏）**：根目录 `CHANGELOG.md` 是「所有版本更新内容」的单一事实来源，也是前端顶栏版本号与「更新公告」弹窗的数据源（前端经 `frontend/src/version.ts` 读取，`App.vue` / `components/VersionAnnouncementModal.vue` 展示）。**该文件内容会原样展示给玩家**。
  - 只写**玩家可感知**的内容（新玩法、数值与平衡调整、界面与体验变化、问题修复等），用玩家能看懂的语言，尽量一句话表述清晰。
  - **禁止**写入任何实现细节或内部信息：文件名 / 路径 / 类名 / 函数名 / 常量 / 数据库迁移 / 依赖 / 脚本 / 测试 / 重构 / 文档 / 部署等。
  - 每次**玩家可感知**的变动都要在**最新版本**条目下追加一条概要；纯内部技术变动不要写入本文件。
  - 发布新版本时，在最上方新增一条 `## Vx.y.z — YYYY-MM-DD` 条目，并同步 `package.json`、`frontend/package.json`、`backend/pyproject.toml`、`backend/app/main.py` 的版本号；前端顶栏版本号与公告弹窗会随之自动更新（公告按 localStorage 已读版本判定，用户下次进入即看到）。
  - 维护者可能手动补充更新简报，保留其内容，不要覆盖或重排。

## 阅读顺序与事实来源

1. 本文件：架构、关键约束、开发入口。
2. `README.md`：玩法说明、运行部署、核心设计、与 PRD 的差异和已知限制。
3. `docs/multiplayer-dlc-design.md`：联机 DLC 的设计、接口及验收背景。
4. `docs/multiplayer-load-bandwidth-design.md`：多人运算下放（世界BOSS 客户端模拟 + 防作弊边界）与传输压缩。
5. `docs/server-resource-optimization-design.md`：2C/2G 服务器的 CPU / 内存优化（连接池分档、排行榜刷新、实时榜缓存、WS 共享生产者、数据保留清理），含实施偏差与理由。
6. `prd.md`：原始需求。现有实现有明确调整，不要仅按原始 PRD 恢复旧规则。
7. 相关代码、`shared/data/*.json` 和测试：确认实际行为。

README 早期目录概览中的页面数、测试数、Compose 服务数可能落后于代码；不要沿用这些数字判断项目现状。

## 技术栈与目录导航

前端使用 Vue 3、TypeScript、Vite 6、Pinia、Vue Router、Tailwind CSS 4、Axios；根目录通过 npm workspace 管理 `frontend`。后端使用 Python 3.11+、FastAPI、Pydantic 2、SQLAlchemy 2 异步会话和 Alembic。本地默认 SQLite，部署使用 PostgreSQL 16。另有 Capacitor 8 的 **Android 外壳**（`android/`，纯 WebView 直接加载线上地址），与游戏逻辑无关，见下方「Android 客户端」。

| 路径 | 职责 |
| --- | --- |
| `capacitor.config.ts` | Android / iOS 外壳配置（`server.url` 指向的线上地址、状态栏样式）；换地址改这里，或临时用 `EORZEA_APP_URL` 覆盖 |
| `android/` | Capacitor 生成的 Android 工程；发布签名 `keystore/` 与 `keystore.properties` 为本机私有、不入库 |
| `ios/` | Capacitor 生成的 iOS 工程（Xcode 工程 + SPM）；签名材料 `signing.properties` / `*.mobileprovision` / `*.p12` 为本机私有、不入库 |
| `harmony/` | HarmonyOS 外壳（**不是 Capacitor**，手写 ArkTS + ArkUI `Web` 组件，Stage 模型，API 26）；签名材料 `*.p12` / `*.cer` / `*.p7b` 与 `.hvigor/` 不入库 |
| `assets/` | App 图标源图（`scripts/gen-app-icon.mjs` 产出、`@capacitor/assets` 的输入）；`npm run app:icons` 据此重新展开到 `android/app/src/main/res/`、`ios/App/App/Assets.xcassets/` 与 `harmony/**/resources/base/media/` |
| `scripts/build-apk.sh` | 构建 Android 安装包；自动探测 JDK / Android SDK 并校验 JDK 是否可用于 Android 构建 |
| `scripts/build-ios.sh` | 构建 iOS 安装包（`xcodebuild archive` → 导出 `.ipa`）；自检 Xcode / 团队 ID，导出方式由 `IOS_EXPORT_METHOD` 决定 |
| `scripts/build-hap.sh` | 构建 HarmonyOS 安装包（`hvigorw assembleHap`）；自检 DevEco / SDK / Java，并把版本号同步进 `harmony/AppScope/app.json5` |
| `scripts/build-mobile.sh` | 三端编排（`npm run app:all`）：预检 → 构建 → 汇总。**只做编排与缺项提示**，缺硬前置（Xcode / Apple 签名 / DevEco / Java）就跳过该端并打印补充步骤，缺软前置（发布密钥 / 鸿蒙签名）照常构建但标 ⚠；权威校验仍在上面三个单端脚本里。注意 macOS 自带 bash 3.2，脚本内**不能用 `declare -A`** |
| `scripts/gen-app-icon.mjs` | App 图标 / 启动图生成器（1024² 图标、2732² 启动图，「母水晶」主题） |
| `scripts/gen-harmony-icons.mjs` | 由 `assets/` 生成鸿蒙图标（`app_icon` / `icon` / `startIcon`，216²） |
| `frontend/src/views/` | 游戏页面；`RosterView.vue`、`CoopView.vue`、`ArenaView.vue` 为联机相关入口；`GameTestView.vue` 为「游戏测试」页，用 iframe 内嵌独立单文件小游戏 |
| `frontend/public/games/` | 独立单文件小游戏静态资源（`ff14-test-game.html`），由 Vite 直接托管，与主游戏进度无关 |
| `frontend/src/components/` | 物品卡、弹窗、指引等公共 UI |
| `frontend/src/stores/` | 认证、游戏状态、生活职业、物品操作等 Pinia 状态 |
| `frontend/src/api/` | API 调用、JWT 注入、错误及封号响应处理 |
| `frontend/src/router/index.ts` | 页面路由 |
| `frontend/src/game/core/` | 本地战斗模拟、战斗公式、地区推进、采集等逻辑 |
| `frontend/src/game/multiplayer.ts` | 联机客户端辅助逻辑 |
| `shared/data/*.json` | 前后端共享的玩法与数值配置，单一事实来源 |
| `shared/schema/index.ts`、`shared/schema/loader.py` | 双端类型、加载和底材展开；结构变更需同步检查 |
| `backend/app/main.py` | FastAPI 入口、生命周期、管理员初始化及排行榜定时刷新 |
| `backend/app/api/v1/` | API 路由；统一由 `router.py` 汇总，默认前缀 `/api/v1` |
| `backend/app/core/` | 环境配置、数据库、认证、安全和依赖注入 |
| `backend/app/models/`、`backend/app/schemas/` | ORM 模型与请求/响应模型 |
| `backend/app/services/` | 数值、战斗校验、掉落、装备、生活职业、联机业务与数据保留清理（`retention.py`） |
| `backend/app/coop_worker.py` | 独立进程推进团队战斗、处理指令、租约及断线状态 |
| `backend/alembic/versions/` | 数据库结构与数据迁移 |
| `backend/tests/`、`frontend/src/**/*.spec.ts` | pytest 与 Vitest 测试 |
| `scripts/` | 本地启动、图标生成、数值推导和合作战斗标定工具 |
| `CHANGELOG.md` | 根目录更新日志，版本更新内容的单一事实来源；前端 `src/version.ts` 解析为顶栏版本号与更新公告内容 |

## 必须保留的设计边界

- **服务端是资产与进度的权威。** 普通战斗由客户端模拟并批量上报，服务端校验收益、击杀额度、解锁及推进；不要信任客户端金币、击杀数或时间。
- 击杀额度使用服务端记录的真实间隔，客户端 `elapsedMs` 仅供参考。调整模拟器时同时检查 `backend/app/services/validator.py` 和相关战斗模型，避免合法上报被拒或出现超额收益。
- **时长下限的容差要留足**：挖宝 `shared/data/treasure.json:minFloorFightMs` 与高难 `shared/data/balance.json:raids.*.durationTolerance`（经 `raid_balance.minimumFightMs`）是「防脚本秒通」的服务端计时下限，但客户端一次出手最快约 0.75s，实战还有暴击 / 直击 / 技能方差，强练度玩家会远快于理论时长。下限必须低于合法最快通关，否则会把合法通关误报为「战斗时长异常 / 战斗时长校验」；挖宝客户端对此时长校验会自动等待重试，高难则直接判负，改这两个值时务必同步回归 `test_treasure.py::test_fast_floor_clear_is_accepted` 与 `test_api.py::TestRaid::test_hard_raid_fast_clear_is_accepted`。
- 普通挂机不提供离线收益。联机「离线合作/克隆体」是独立机制，不等于为普通挂机新增离线回补；团队战斗由 worker 推进，worker 中断也不补算离线时间。
- 装备归属账号，英雄穿戴状态与账号背包需要保持一致；切换、解雇及多英雄操作应检查 `roster.py`、相关模型与事务逻辑，避免装备或资产重复。
- 好友金币转账同为服务端权威：`services/friends.py` 按 id 升序双行锁两方账号，校验好友关系 / 余额 / 单笔上下限 / 每日累计额度后再结算，手续费按 `floor(amount × feePct)` 销毁（净额不为 0 增长来源），流水写入 `coin_transfers`。
- **反多开（防小号刷金币）**：账号关联判定 = 设备指纹 **或** IP。设备指纹由前端 `frontend/src/utils/device.ts` 从浏览器信号派生（同一台机器的不同浏览器 / 无痕得到同一标识），随每个请求以请求头 `X-Device-Id` 发送；IP 取 `users.reg_ip` / `users.last_ip` 与 `user_devices.first_ip` / `last_ip`，比较前过滤 `unknown` / 回环 / `testclient` 等哨兵值（见 `services/devices.py`）。数据表 `user_devices`（迁移 `u7a9c1e3b5d7`，并发动线字段见 `w9c1e3f5a7b9`）。
  - **可强制（不依赖指纹不可伪造）的两条**：
    - **同一账号单端登录**：登录时 `users.session_epoch += 1`，令牌内携带 `ep`；`core/deps.get_current_user` 比对不一致即 401 `{code:"session_replaced"}`（`POST /auth/logout` 亦推进纪元，使全端失效）。老令牌无 `ep` 视为 0，升级不踢存量会话。开关 `antiAlt.singleSessionPerAccount`。
    - **同一设备并发在线上限**：`user_devices.last_seen_at` / `online_since` 记录心跳；心跳按**连续在线起始时间先到先得**重算，超出 `antiAlt.maxOnlineAccountsPerDevice`（默认 1）的账号被写入 `users.multi_online_blocked_at`，其**非 GET 请求**（含 `/auth/` 除外）返回 409 `{code:"device_limit"}`；心跳本身是 GET 始终放行，其他账号离线后自动恢复。口径由 `antiAlt.onlineLimitScope`（`device` / `device_or_ip`）决定，默认仅指纹（NAT 下用 IP 会误伤）。
  - **纵深防御（本质可绕过：换设备 / 清 Cookie / VPN）**：注册处同一设备最多 `antiAlt.maxAccountsPerDevice`（默认 2 = 1 大号 + 1 小号）个账号；设备标识取「`X-Device-Id` 请求头 ∪ 服务端签名的 httpOnly 设备 Cookie」的**并集**，因此清 localStorage 换新指纹仍被旧 Cookie 关联到同一设备；另有同一真实 IP 的注册上限 `antiAlt.maxAccountsPerIp`（<= 0 关闭）。登录 / 心跳只登记，不在注册上限上硬拦（避免锁死存量多开账号）。
  - **关联账号（同设备 / 同 IP）**之间的好友转账按 pair 双向 24h 累计受 `antiAlt.transferDailyLimit` 限制，交易板寄售成交受单笔 + pair 24h 累计（`antiAlt.marketDailyLimit`）限制，收购单成交只受单笔上限（`MarketBuyOrder` 不记录卖家、无逐笔成交归属）。
  - 管理端排查入口：`GET /admin/online`（`services/admin_monitor.py`，**只读**）返回当前在线账号（`users.last_seen_at` 在 `devices.ONLINE_WINDOW_SECONDS` = 45s 内）及其最近 / 注册 IP、设备指纹，并按「同设备 / 同 IP」做**连通分量分组**（只保留含在线账号的组，组内附共享的设备 / IP），供管理员识别多开；不写库、不改变任何拦截 / 额度逻辑。前端入口在「管理」页的「在线玩家」标签（**手动刷新**，不轮询）。
  - 改判定或额度时同步回归 `tests/test_anti_alt.py`、`tests/test_session_limits.py`、`tests/test_admin_monitor.py` 与 `services/devices.py`。

- **补偿公示（对全服公开的数据）**：管理员用 `POST /admin/grant-gold`（`api/v1/admin.py`）为指定玩家发放金币补偿，单次上限 `services/admin.GRANT_MAX_AMOUNT`（20 亿）、只增不减、禁用给管理员账号发放，改写前用 `lock_user` 加行锁。每次发放写一行 `AdminGrant`（表 `admin_grant_records`，迁移 `z3a5c7e9b1d3`）。该表**与 `audit_logs` 分开、且不被 retention 清理**——因为 `GET /grants`（`api/v1/grants.py`，公开只读、无需登录）把它作为「补偿公示」展示给全服玩家（前端 `GrantView.vue` + 导航「补偿公示」）。公示**包含事由**（管理员填写，即对玩家公开）但**不返回操作管理员的账号 / id**；新增公示字段前先确认不会泄露内部信息，且发放入口要提示「事由将对全服公开」。
- **并发降载（大量用户长时间挂机时的负载约束）**：
  - **WS 广播是「每进程一次轮询 + 内存分发」**（`services/broadcast.py`）：聊天室 / 远征房间不再「每个连接各查一次库」，改由每 channel 一个生产者读一次后投递给订阅队列；每个进程各自轮询，因此仍多 worker 安全。**不要退回「每连接轮询 DB」**。世界BOSS 的伤害榜走进程内短 TTL 缓存（`world_boss.cached_contribution_rows`，仅 WS 经 `leaderboard_view(use_cache=True)` 使用）；HTTP 接口与测试必须走不带缓存的读取，否则刚写入的贡献会被缓存挡住（`test_world_boss.py` 有断言）。
  - **挂机热路径禁止 N+1**：采集 / 生产 / 钓鱼 / 战斗上报一律用批量接口（`dohdol_util.stack_add_many` / `stack_consume_many`、`codex.unlock_monsters` / `unlock_materials`），不要退回「按件 / 按怪逐条 select」。
  - **`/game/state` 不重复查询**：`api/v1/game.py` 不要声明 `CurrentItems`（`build_game_state` 需要**全部**装备，依赖注入加载的用不上）；已算好的 `socket_mods` / `cleared_region_count` 要透传给 `region_access` / `chest_rarity_luck`。
  - 排行榜刷新：批量 `executemany` 写入 + `services/locks.try_advisory_lock` 互斥；生产改由独立 `ranking-worker` 进程执行（`RANKING_IN_API=false`）。
  - 传输压缩（`core/compression.py`）：响应优先 **brotli**（`BROTLI_ENABLED`，客户端支持 `br` 时）、不支持则由 `GZipMiddleware`（`GZIP_ENABLED`）兜底——**注册顺序必须是先 Brotli 再 GZip**（后注册的在外层，Starlette GZip 见到已有 `Content-Encoding` 会跳过，否则永远走 gzip）；请求体支持客户端 gzip 压缩（`REQUEST_DECOMPRESS_ENABLED`，解压上限 `REQUEST_MAX_DECOMPRESSED_BYTES` 防 gzip bomb，超限 413）；WebSocket 用 uvicorn `--ws-per-message-deflate true`（**必须带值**——它是 click 的 `type=bool` 选项，写成裸 flag 会把后一个参数当成它的值导致启动失败；已在 `docker-entrypoint.sh` 固定）。nginx 必须保留 `gzip_proxied any`（默认 `off` 会让 `/api/` 反代响应**完全不压缩**），且 `chat/ws`、`worldboss/ws` 需要与 `coop/ws` 一样带 Upgrade 头的独立 `location`（同时透传 `Sec-WebSocket-Extensions` 以使 permessage-deflate 生效）。
  - 大响应省流量：`/game/state`（`Cache-Control: no-cache` + `Vary: Authorization`）与 `/game/config`（`public, max-age=3600`）都带 **ETag**，内容未变时回 304 无 body（`core/http_cache.conditional_json`）。序列化口径与 `JSONResponse` 一致，勿改用其它 dumps 参数。
  - **小内存服务器（2C/2G）的降载约定**（设计见 `docs/server-resource-optimization-design.md`）：
    - 连接池**按进程角色分档**：`DB_POOL_PROFILE=api`（默认，`DB_POOL_SIZE=5`/`DB_MAX_OVERFLOW=5`）与 `worker`（固定 2/0）。compose 给三个 worker 服务用 `entrypoint: ["env","DB_POOL_PROFILE=worker",...]` 注入。**改池大小必须核算 `进程数 × (pool+overflow) < db 的 max_connections(40)`**。
    - 缓存榜刷新**必须在独立 `ranking-worker`**（`RANKING_IN_API=false` 已是代码默认）；间隔由 `RANKING_REFRESH_SECONDS` 控制。刷新实现是**分批 + 只加载已装备装备**（`ranking.py:_refresh_all_rankings`）——面板只依赖已装备装备（`stats.aggregate_equipment` 跳过未装备），**不要退回 `selectinload(User.items)` 全量加载**（曾可吃 GB 级内存）。
    - 实时榜（钓鱼 / 生活 / 远征）的底层聚合走进程内短 TTL 缓存（`ranking.py:_LIVE_CACHE`，`RANKING_LIVE_CACHE_SECONDS`）——同一请求内的「榜单页 + 我的排名」只聚合一次。**新增会改变这些榜数据的写入点时，必须调用 `ranking.invalidate_live_rankings()`**（现有：钓鱼/采集/生产上报、专用装备穿脱、远征通关）。
    - `/game/config` 的响应体在进程内只构造一次（`api/v1/game.py:_CONFIG_RESPONSE`）；`/game/state` 的 ETag 仍需每次编码（内容随玩家变化）。
    - 世界BOSS 的 WebSocket 已改为 **`broadcast.hub` 共享生产者**（每进程 0.5s 轮询一次），**不要再退回「每连接各查一次库」**；`me` 由各连接用 `build_leaderboard` 就地拼装。
    - 数据保留清理在 `services/retention.py`，由 `ranking-worker` 周期执行（`RETENTION_*`）。它**只清「终态 + 超期」**的行；`world_boss_contributions`/`rewards`、`coop_records`、`coin_transfers`、**`user_devices`（反多开判定依据）**永不清理。`coop_rooms`/`coop_battles` 因被 `coop_records` 以无 CASCADE 外键引用而**不能清**；`chat_messages` 公告是长期保留的例外。`security_events` 的全局清扫也在这里做（`ratelimit.hit` 内的按 key 清理是热路径，**不要改成全局扫描**）。
    - `api/v1/admin.py:/online` 的分组**必须**保留组内的离线小号（管理员要靠它识别多开），**不要**改成 `WHERE last_seen_at >= cutoff` 预筛；`users.last_seen_at` 也**不要**加索引（每次心跳都 UPDATE 且无 SQL 读它）。详见 `services/admin_monitor.py:online_overview` 的说明。
  - 前端：`stores/game.ts:loadState` 是单飞 + 合并（突发动作不再各发一次全量请求），`stores/dohdol.ts` 在后台标签页降频上报；改这两处前先看 `stores/dohdol.spec.ts` 的时序断言（测试环境为 Node，没有 `document`，需用 `isPageHidden()` 之类的守卫）。
  - **采集 / 生产序列的断点续传**：序列队列与「运行断点」按账号持久化在浏览器本地（键 `eorzea.sequence.<userId>`，读写与结构校验见 `frontend/src/utils/sequenceStorage.ts`），整页刷新 / 版本更新重载后由 `stores/dohdol.ts:restore` 恢复——保存 ≤15 分钟且处于运行中才自动续传，否则只恢复队列、不自动运行；**应用内切换页面仍保持「停止运行、保留队列」**（`GatherView`/`ProduceView` 的 `onUnmounted → stopSequence` 语义不变）。制作步续传以「剩余件数」重启会话，汇总时用 `seqProducedBase` 偏移换算累计值；恢复后必须 `seedStepIds` 抬升 id 计数器，否则新增步骤会与恢复的 `step-N` id 撞车。服务端不保存运行队列 / 断点，续传复用现有 start/report/stop 会话接口。
- **采集 / 生产自定义序列库（≤5，蓝图ID 分享）**：玩家可把当前编辑区保存为命名序列（表 `sequence_blueprints`，服务端账号级，同名保存即覆盖、每账号最多 5 条），每条带唯一「蓝图ID」（`share_code`，8 位易读字符）。接口 `backend/app/api/v1/sequences.py`（`GET/POST /sequences`、`POST/DELETE /sequences/{id}`、`GET /sequences/blueprint/{code}` 供任意登录玩家导入；步骤入库前经 `services/sequences.sanitize_steps` 结构校验、≤50 步）。前端 `stores/sequences.ts` + `components/SequenceLibraryModal.vue`（入口在共用的 `SequencePanel.vue`）；「读取 / 导入」走 `stores/dohdol.ts:loadSequence` 替换编辑区（重分配 step id、按当前等级 / 解锁重解析采集点），不占用槽位、也不写本地断点。
- 怪物、精英不直接掉落装备；主要通过抽箱获取，另有 BOSS 宝箱奖励。
- **抽箱档位按「名册最高英雄等级」**：`POST /chest/open` 的等级档位解锁以 `services/progression.highest_hero_level`（角色库内最高英雄，**非当前上场英雄**）判定，前端 `ChestView.vue` 用 `game.state.heroes` 的等级最大值同源展示（`rosterLevel`），不要退回 `hero.level`。
- **地区 BOSS 出场需服务端确认**：客户端只有拿到服务端确认的击杀数（`battle.ts:bossUnlocked`，由 `applyServerKillCount` 置位）才进入 BOSS 阶段——`_settle_boss` 按服务端权威计数放行，若客户端提前进场会因计数滞后被静默丢弃（含金币/经验/宝箱）。放行判定不得改用客户端上报的 `killCount`（可伪造 → BOSS 金币刷子）。
- **世界BOSS 是「客户端模拟 + 服务端上限夹取」**（与地区战斗同构，非远征式服务端权威）：前端 `game/core/worldboss.ts` 与后端 `services/worldboss_engine.py` **必须逐位一致**（同种子同配置同结果，`frontend/src/game/core/worldbossEngine.spec.ts` 有跨语言黄金快照），改任一侧必须同步另一侧并刷新该快照。服务端侧**不可放宽**的边界：窗口只认服务端时钟（`session.last_report_at`，忽略客户端 `elapsedMs`）、伤害上限 = 理论模型（`services/worldboss_model.py`）× 窗口 × `WORLDBOSS_REPORT_TOLERANCE`、超标 2 倍整单拒绝并写 `AuditLog`、`reportSeq` 幂等、全局血量原子递减与贡献 / 奖励全部服务端。上调容差前先测满练度合法上报不被误拒（`tests/test_world_boss.py` 的 report 用例）。
- **金币收益明细**：小怪 / BOSS / 副本的金币由服务端返回 `goldCalculation`（`progression.gold_calculation`，与 `exp_calculation` 同构），前端 `utils/battleLog.goldLog` 写入战斗日志（与 `experienceLog` 对称）；`battle.ts` 不再输出逐杀金币行。
- 普攻（`ADVENTURER_SKILL`，零耗蓝兜底）威力由 `combat.json:basicAttackPotency` 指定（当前 50%，低于技能威力），前后端同源：前端 `combat.ts`、后端 `combat_model.BASIC_ATTACK_POTENCY`。改这个值会同时改变整体 DPS，进而影响怪物按「命中次数」的标定与 `core.spec.ts` 的击杀手感测试。
- 地区关底 BOSS 有单次命中伤害上限 `bosses.json:maxHitDamagePct`（当前 20% 最大生命），在 `battle.ts:capBossHit` 结算，用于防止开局爆发 / 暴击大招秒杀 BOSS；仅地区 BOSS 生效（高难与联机不走此上限），且客户端做上限比服务端理论模型更保守，不影响上报校验。
- **技能轮转（避免反复刷同一个技能）**：技能选择为「优先级 → 同优先级内按规则排序 → 取第一个可用」。`jobs.json` 每个职业 10 个技能（原 7 + 短 CD 轮转技 / DOT / 职能特色技），同优先级内规则为：(1) 普通技能层级（优先级 3，填充技）按**最近最少使用**（`lastCastAt`）轮转——攻速 / 冷却缩减会把填充技 CD 压到 GCD 以下使其常驻，不轮转就会一直用同一个技能；(2) 增益 / 高伤层级按**威力从低到高**，沿用原有「先用得起、再放大招」的蓝耗节奏（参考快照 `multiplayer.json:references` 的技能顺序即按威力升序标定，改这条排序会让远征参考队数值漂移）。此规则在**四处同源**：`frontend/src/game/core/battle.ts:pickSkill`、`frontend/src/game/core/worldboss.ts:autoActions`、`backend/app/services/worldboss_engine.py:auto_actions`、`backend/app/services/coop_engine.py:auto_actions`、`backend/app/services/pvp_engine.py:duel`，改一处必须同步其余；纯确定性状态，不消耗随机数（否则会打乱世界BOSS 跨语言黄金快照的随机流）。当前选择不是按蓝耗优先，故**不要**改成「大招优先」，否则会把蓝打空退化为只能普攻。
- **绝技（招牌技能）**：每个战斗职业一个，配置在 `shared/data/jobs.json` 的 `job.signature`（不计入 `skills[]`，`maxSkills` 为 10）。机制为独立充能槽（`battle.ts:signatureCharge`）：战斗中按 `chargeSeconds` 匀速充能、每次击杀额外 `chargePerKill`，满槽自动释放；**不占 GCD、不耗魔力**，故不与普通技能抢出手。伤害型绝技（`potency>0`）对整体 DPS 的贡献必须同时镜像到后端 `combat_model.signature_potency_per_sec`（按纯时间充能取有效冷却，客户端击杀加速带来的偏差由 2x 校验容差覆盖），否则合法上报会被击杀额度拒绝；buff/生存型绝技无需建模。新增效果类型 `undying`（锁血不死，`battle.ts:heroDies`）不与装备词条 `cheatDeath` 冲突（各自独立计时 / 标记）。
- **职业定位攻防效率**：`shared/data/jobs.json:roles` 为每个定位（tank / healer / melee / physicalRanged / magicalRanged）配置 `attackEfficiency` / `defenseEfficiency`（近战DPS 为基准 1.0），`services/stats.py:role_efficiency` 在 `compute_stats` 里对面板 `attack` / `magicAttack` 与 `physDef` / `magicDef` 整体乘算；因为前后端与校验模型（`combat_model`）共用同一份 `HeroStats`，效率会同时作用于实战、面板与战力。英雄面板对应属性的「如何计算」由 `frontend/src/game/explanations.ts` 展示（读 `breakdown.roleEfficiency`）。初始英雄起始武器取**基准职业**（龙骑士 `w_lance_0`），避免唯一的新手英雄被定位效率削弱开荒——改 `heroes.json:initialHero.starterWeapon` 时须同步 `test_api.py` / `test_multiplayer.py` 里按配置推导的起始职业断言。
- **主属性与英雄型（`heroes.json:attrGainRate` + `combat.json:biasBonus`）**：装备三维（力量/敏捷/智力）**全部 100% 生效**（`attrGainRate` 三项均 1.0，已取消「非主属性 50%」）。英雄型改为**纯增益表** `combat.json:biasBonus`（取代原 `primaryLink`）：力量→`crit`、敏捷→`dh` + `attackSpeedPct`、智力→`det`、均衡→三属性小幅 + `coreAttrPct`（按百分比乘到 str/dex/int 三维总量，vit 不变）；`job_match` 把均衡型视为与任意职业匹配（享受 +15% 主属性装备收益）。纯面板级改动经 `HeroStats` 自动被客户端战斗与后端 `combat_model` 同步；前端 `explanations.ts` 的「如何计算」读 `breakdown.biasBonus`，改数值须两端同源。
- **装备职能限制**：英雄职能由其**已装备的主手武器**决定（`base.job_id` → 职业 → 职能）。防具/饰品按职能词缀绑定职能——词缀在 `shared/data/base-items.json:variants[].role` 声明，`shared/schema/loader.py:BaseItem.role` ⟷ `shared/schema/index.ts:BaseItem.role` 双端暴露，后端统一用 `services/slots_util.py:role_of_base` 取（武器按职业、其余按词缀；基础型与世界BOSS 专属防具「强攻/守护」无职能 → 不限制）。`api/v1/inventory.py::equip`：非武器栏位须与当前武器职能一致，否则 400；**换武器时自动卸下**不符职能的防具/饰品并在响应里返回 `unequipped`（`unequip` 永远允许，避免换武器把装备卡死）。前端 `utils/itemFilters.ts:roleOfBaseId` 与 `EquipmentView` / `ItemPickerModal` 用同一口径把不符候选置灰标记「职能不符」——改判定须两边同步。
- **治疗续航与回蓝收敛**：治疗技能固定耗蓝过低时，膨胀的蓝条与基础回蓝会永久覆盖其消耗，形成「无限回蓝 → 无限回血 → 永不死亡」。故：(1) 治疗职业（role=healer）的**治疗 / 护盾**技能在 `mpCost` 之外另按「最大魔力 × `heroes.json:mp.healSkillCostMaxMpPct`」收费，前端 `combat.ts:skillMpCost` ⟷ `battle.ts:rawMpCost` 同源，技能面板展示实际耗蓝（`HeroView` / `MainView`）；(2) 治疗技能数值下调、CD 延长（`jobs.json`，由 `core.spec.ts` 与 `test_shared_data.py` 守卫）；(3) 按最大魔力比例回蓝的**词条范围**收敛（灵息 / 坚毅 / 枯竭 / 转魔 / 汲魔，见 `terms.json`）且 `combat.json:proc.mpRegenBuff` 减半。新增任何按比例回蓝的来源时必须一并评估这组约束，避免重新打开无限自愈。
- 数值优先修改共享 JSON，避免前后端各自硬编码。`combat.json`、`monsters.json`、`balance.json`、`multiplayer.json` 分别承载相关战斗、怪物、战力与联机配置。
- 魔晶石加成是**账号级**面板加成，必须通过 `stats.compute_stats(hero, items, socket_mods)` 注入：新增任何「计算英雄面板 / 战力 / 门槛」的调用点都要一并传入 `await materia.socket_mods(db, user_id)`（或 `CurrentSockets` 依赖版，见 `core/deps.py`），否则面板、战力榜与地区/副本门槛会与实战不一致。挖宝的怪物数值、宝箱内容与猜大小，以及种田的成熟判定，**全部只认服务端时钟与随机数**；客户端的 `elapsedMs` 仅作参考。
- **附魔词条扩展（战斗 12 类 + 生产/采集）**：战斗词条按 `terms.json:categories` 分为 12 类（常住属性 / 攻击触发 / 异常 / 受击 / 防御 / 条件 / 动态成长 / 资源转换 / 联动 / 风险代价 / 特殊机制 / 累计触发）+「收益获取」。新增机制的数值 / 阈值集中在 `combat.json:equipEffects`（`proc`/`conditional`/`growth`/`convert`/`charge`/`special`），前端 `battle.ts` 结算；**任何提升期望 DPS 的新机制必须同步镜像到 `combat_model.py`**（否则合法上报会被击杀额度拒绝），仅影响生存 / 资源的机制不建模（与凋零 / 失明同待遇）。**攻击触发（onAttack proc）只由「直接伤害技能命中」触发**——普通攻击与持续伤害（DOT）结算都不触发，后端期望按「技能出手率」`proc_rate`（不含普攻 / 连击）估算，前端 `combat.ts:procDpsBonus` 同源。**DOT 与 HOT（持续治疗 / 生机 / 灵息）统一每 `combat.json:effectTickSeconds`（当前 3）秒结算一次、`duration` 内总量不变**（单次量 = 每秒量 × 窗口时长，到期补尾窗），四套战斗引擎（`battle.ts` / `worldboss.ts` / `worldboss_engine.py` / `coop_engine.py`）同源读取；被动 `hpRegen` / `mpRegen` / 转魔仍按 1s。风险代价类词条用 `cost: {stat, ratio}` 声明副作用，落库 `value = round(主值 × ratio)` 并由 `stats.aggregate_equipment` 累加进 `term_mods`；`desc` 使用 `{v}` / `{c}` 占位符。词条 `category` 为必填，词条图鉴支持按类别筛选。词条可声明 `maxItemLevel`（可出现的**最高**装备等级）：经验类词条（战斗 `expGain` / `expDrain`、生产采集 `dohInspiration` / `dolKeenSense`）设为 `99`，满级（100 级）装备不再出现（`item_factory.roll_terms` / `roll_dedicated_terms` 按装备等级过滤，「基于当前」重造 / 附魔也会剔除）。生产 / 采集扩展词条由 `scripts/gen-dohdol-data.py` 生成（改词条要改脚本并重跑）。设计见 `docs/enchant-terms-expansion-design.md`。
- 抽箱品阶概率与生产品阶概率共用一套「幸运来源」归一化（`services/luck_sources.py`）：`p = Σ weight × min(值 / ref, 1)`，权重合计 = 1，各 `ref` 为该来源的真实最大值（含太古词条），因此只有全部来源满才达到上限。来源主体在 `chests.json:rarityLuck` 与 `recipes.json:equipment.rarityScaling`，远征 / 高难的难度权重在 `multiplayer.json:difficultyWeights` 与 `raids.json:difficultyWeights`（仅计首通）。新增来源时同步更新前端文案与 `tests/test_shared_data.py` 中「ref = 配置推导值」的断言。
- 战力不等同于装备出售估值。普通副本允许低战力挑战，高难与地区解锁有服务端资格条件；已移除机制试炼，不应重新依赖它。
- 战力配置有校验与安全默认值：修改 `balance.json` 时检查 `services/balance.py` 和 `balance_defaults.py`；不兼容规则需考虑版本和既有挑战快照。
- 联机 API 与 worker 共享数据库状态。修改时保留锁顺序、租约、指令处理及奖励幂等语义；SQLite 测试不能替代 PostgreSQL 并发验证。
- **前端性能不变量（改战斗循环 / 大列表时务必保留）：**
  - `BattleSimulator.floating` 与 `log` 的**数组引用只在真正增删时变化**（飘字见 `tickFloating`：只在有条目过期时才 `filter` 重建，未过期的帧只递减 `remaining`）。这是为了不让按帧驱动的循环每帧把订阅方标记为脏 —— 若改回「每帧重建数组」，战斗页会从 ~10Hz 退回 ~60Hz 整页重渲染（`stores/game.ts` 的 `floating`/`battleLog` 直接返回该数组）。`core.spec.ts` 有断言守住这一点。
  - 副本 / 挖宝的 BOSS 面板（`game.raidBosses`、`treasure.bosses`）**只依赖 100ms 的 `uiTick`，不依赖每帧的 `logVersion`**：`bossEntries()` 每次求值都新建数组与对象，挂在每帧上会让整页 60fps 重渲染。
  - 高频更新的 UI 片段（如伤害飘字层 `components/BattleFloatLayer.vue`）要**自己从 store 读状态**，不要由页面组件读取后再传 prop —— 否则页面会跟着高频更新一起重渲染。
  - 批量卡片列表（抽箱结果、图鉴、选择弹窗）统一用 CSS `gallery-cell`（`content-visibility: auto`）跳过屏外元素的布局/绘制，并配合**分批挂载**（`ChestView` 的 `rampMount`）或**渐进渲染**（`composables/useVisibleLimit.ts` 的「显示更多」）避免单帧创建上百个节点。抽箱揭晓弹窗用 `Modal` 的 `:blur="false"`（`card-flat`）避免大量动画子元素反复触发 `backdrop-filter` 重算。
  - 卡片内的弹层（`InfoTip` / `TermBadges`）一律 `Teleport to="body"`：`content-visibility` 会引入 `contain: paint`，若弹层留在卡内会被错误定位（给卡片加 `gallery-cell` 前先确认这一点）。

- **移动端外壳（Capacitor：Android / iOS）**：只做「把网页装进 App」，不改动任何游戏逻辑，但下面几条是踩过坑的约束。
  - **是 WebView 直接加载线上地址（`capacitor.config.ts:server.url`），不是把 `frontend/dist` 打包进去当站点。** 因此 WebView 的源就是 nginx 的源：登录 Cookie、httpOnly 设备 Cookie、WebSocket、localStorage 与浏览器完全一致，服务端发版也不需要重新发包。**不要**改成「打包前端产物 + 把 `VITE_API_BASE` 指向绝对地址」——那会引入跨域、设备 Cookie 失效（`X-Device-Id` 之外的关联判定会掉）以及 WebSocket 源校验等一串问题。
  - **构建需要完整的 JDK 21–24（必须带 `jlink`）**。Android Studio / IDEA / PyCharm 自带的 JBR 都不行：JBR 25 会让 Gradle 8.14.3 自带的 Groovy 3 报 `Unsupported class file major version 69`；JBR 本身是精简运行时、没有 `jlink`，AGP 的 `JdkImageTransform`（转换 `core-for-system-modules.jar`）会失败。`scripts/build-apk.sh` 已按「版本合适且带 jlink」挑选，报错信息也指向 `brew install openjdk@21`。用 Android Studio 直接构建要把 *Settings → Build Tools → Gradle → Gradle JDK* 指到同一份 JDK。
  - **`android/build.gradle` 里的阿里云镜像必须保留**。`capacitor-android` / `capacitor-cordova-android-plugins` 两个子工程自带 `buildscript` 块，只声明了 `google()` + `mavenCentral()`；国内直连 `repo.maven.apache.org` 会 403，而 Gradle 遇到非 404 响应是直接判失败、不会继续尝试下一个仓库。根工程的 `allprojects` 只覆盖「工程依赖」，覆盖不到子工程的 buildscript 类路径，所以那里额外用了 `gradle.beforeProject` 注入镜像 —— 删掉任何一处都会让构建在依赖解析阶段挂掉。
  - **`versionCode` / `versionName` 由根 `package.json` 推导**（`major*10000 + minor*100 + patch`），不要在 `android/app/build.gradle` 里手写，避免发布时多处版本号漂移。
  - **全面屏（edge-to-edge）避让只有一个数据源：`--app-safe-*`**（定义在 `frontend/src/style.css`，值为 `var(--safe-area-inset-*, env(..., 0px))`）。优先级不能颠倒：**Android 必须用 Capacitor 注入的 `--safe-area-inset-*`** —— Android WebView < 140 有 Chromium 已知 bug，`env(safe-area-inset-*)` 取不到真值（见 `@capacitor/core/system-bars.md`），只靠 `env()` 会让内容钻到状态栏 / 手势条下面。`capacitor.config.ts` 的 `SystemBars.insetsHandling: 'css'` 就是打开这个注入；iOS 与桌面没有注入变量，自动回退 `env()`（WebKit 正常，桌面恒 0）。
  - **Android 还需在原生侧开 edge-to-edge**：`android/.../MainActivity.java` 的 `onCreate` 里调 `EdgeToEdge.enable(this, SystemBarStyle.dark(...), SystemBarStyle.dark(...))`（Capacitor 8 不会替你调，9 才会）。改这里必须**重打 APK**；只改前端则只需部署（外壳是 `server.url` 加载线上站点）。
  - **JS 侧统一走 `frontend/src/utils/safeArea.ts`**：`readSafeArea()`（先读注入变量、再退 `env` 探针）、`clampToViewport()`（把 fixed 浮层收进安全区）、`installSafeAreaSync()`（`App.vue` 挂载时安装，含 `MutationObserver` —— 原生注入是**异步**的，必须监听 `<html>` 的 inline style）。改安全区逻辑只改这一个文件。
  - **新增贴边 UI 必须避让，不要硬编码 `bottom-4` / `top-3`**：现有已适配的是页头（`[data-app-header]` 顶部内边距）、页脚（`[data-app-footer]`）、移动抽屉、`ToastStack`（顶部）、`LootBubbles`（右下）、`Modal`（四边）、`BuffDock`（拖拽夹取）、`InfoTip` / `TermBadges` / `SearchSelect`（浮层夹取）。
  - **图标只能改 `scripts/gen-app-icon.mjs` 后重跑 `npm run app:icons`**（它写 `assets/`，再由 `@capacitor/assets` 展开到 `android/app/src/main/res/`）；直接改 `res/` 里的 PNG 会在下次展开时被覆盖。生成器用「到多边形的有符号距离」做解析式抗锯齿，辉光函数**内部不加亮**（`glowPolygon` 内部距离恒为 0，用 `max(sd,0)` 会得到满强度叠加、把水晶切面冲淡）；金色光环描边在 1024 网格下不能低于约 20，否则缩到 mdpi(48px) 会被抹掉。
  - 发布签名 `android/keystore/` 与 `android/keystore.properties` 是本机私有的，**不要提交**；密钥库是 PKCS12，`keyPassword` 必须与 `storePassword` 相同（Android 会忽略单独的 keypass）。缺失时构建回退 debug 签名。
  - **iOS 工程由 `npx cap add ios` 生成，打包走 `scripts/build-ios.sh`**（`npm run app:ios`）。与 Android 最大的不同是 **iOS 必须有 Apple 签名**：脚本先自检 `xcode-select -p` 是否指向真正的 Xcode（只有 Command Line Tools 时直接报错退出），团队 ID 取 `IOS_TEAM_ID` 或 `ios/signing.properties` 的 `teamId=`，导出方式取 `IOS_EXPORT_METHOD`（`development` / `ad-hoc` / `app-store-connect` / `enterprise`，默认 development）。`ExportOptions.plist` 在构建时生成到 `build/`，**不要把团队 ID 提交进仓库**。
  - **iOS 的版本号与 Android 同源、由脚本注入**：`MARKETING_VERSION` = 根 `package.json` 的版本号，`CURRENT_PROJECT_VERSION` = `major*10000 + minor*100 + patch`；`scripts/build-ios.sh` 通过 `xcodebuild MARKETING_VERSION=... CURRENT_PROJECT_VERSION=...` 传入。**不要在 Xcode 里手改这两个值**，否则会与 Android 端漂移。iOS 走 Swift Package Manager（无 CocoaPods），依赖由 `cap sync ios` 写进 `ios/App/CapApp-SPM/Package.swift`。
  - **图标 / 启动图两端一起展开**：`npm run app:icons` 会 `capacitor-assets generate --android --ios`，iOS 侧写到 `ios/App/App/Assets.xcassets/`。只改了 `assets/` 却没重跑时，iOS 会继续用 Capacitor 默认图标。
  - **`server.url` 壳应用在 App Store 可能被判「最低功能性」**：功能上可用（与 Android 同一套机制），但上架审核有风险，需自行评估；内部分发（ad-hoc / 企业）不受此影响。
  - **HarmonyOS 外壳不是 Capacitor，是手写的 ArkTS 工程（`harmony/`）**：Capacitor 无鸿蒙支持，故用 ArkUI 的 `Web` 组件整屏加载同一线上地址。地址写在 `harmony/entry/src/main/ets/pages/Index.ets` 的 `APP_URL`，与 `capacitor.config.ts:server.url` **同源**——改线上地址要同时改这两处。Stage 模型 + API 26；`entry/src/main/module.json5` 只申请 `ohos.permission.INTERNET`（与 `GET_NETWORK_INFO`），不含其它权限。
  - **鸿蒙构建走 DevEco 自带工具链**（`scripts/build-hap.sh`）：默认用 `/Applications/DevEco-Studio.app/Contents` 下的 `tools/hvigor/bin/hvigorw` + `sdk`，可用 `DEVECO_HOME` / `DEVECO_SDK_HOME` 覆盖。**PackageHap 阶段必须有 Java**（打包/签名工具是 Java 程序）——macOS 上若没装系统 JDK，`/usr/bin/java` 只是会报 `Unable to locate a Java Runtime` 的壳，脚本会自动挑 DevEco 自带的 JBR。`build-profile.json5` 里 API 26+ 的 `compatibleSdkVersion` / `targetSdkVersion` 必须是**纯版本字符串 `"26.0.0"`**（API 10–25 才是 `'5.0.0(12)'` 那种带括号形式，写错会直接报 00306042）；`modelVersion` 必须是 `6.0.0`，且 `hvigor/hvigor-config.json5` 与根 `oh-package.json5` 两处要一致。
  - **鸿蒙版本号同样由 `build-hap.sh` 从根 `package.json` 同步**（写 `harmony/AppScope/app.json5` 的 `versionName` / `versionCode`，规则同 Android 的 `major*10000+minor*100+patch`），不要在 DevEco 里手改。
  - **鸿蒙签名材料不入库**（`*.p12` / `*.cer` / `*.p7b`、`.hvigor/`、`oh_modules/`、`local.properties`）：在 DevEco 里「自动签名」（需华为开发者账号）或手填 `build-profile.json5` 的 `signingConfigs`；未签名时 hvigor 仍产出 `entry-default-unsigned.hap`（可编译、**装不上设备**），脚本会把这个区别打印出来。
  - **鸿蒙的全面屏避让靠系统默认布局**：`Index.ets` 刻意不调 `expandSafeArea`，内容天然让开状态栏与底部手势条（小横条）；网页内另有 `--app-safe-*` 那一套（此时 insets 为 0）。两套叠加即可，不要给 Web 组件再加 `expandSafeArea`。
  - **HarmonyOS NEXT（API 12+）不再兼容 Android APK**：纯血鸿蒙设备只能装 HAP，HarmonyOS 4.x 及以下继续用 APK。`server.url` 壳应用在华为应用市场与 Apple 一样存在「最低功能性」审核风险。

## 本地开发

以下命令默认从仓库根目录执行：

```bash
./scripts/dev.sh             # 启动 API、合作战斗 worker 和 Vite
./scripts/dev.sh backend     # 仅启动 API 与合作战斗 worker
./scripts/dev.sh frontend    # 仅启动 Vite
./scripts/dev.sh test        # 后端 pytest、前端 Vitest、TypeScript 类型检查
```

脚本首次运行会从 `.env.local.example` 生成 `.env.local`、创建 `backend/.venv` 并安装依赖。默认游戏入口 `http://localhost:5173`，API 文档 `http://127.0.0.1:8000/docs`，健康检查 `/health`。实际端口以环境配置为准。

- 本地配置：根目录 `.env.local`；部署模板：根目录 `.env.example`。后端直接运行时通过 Pydantic 读取工作目录下的 `.env`，不会自动读取根目录 `.env.local`；一键脚本负责加载并传入。
- 默认本地数据库为 `backend/dev.db`，日志为 `.dev-logs/backend.log`、`frontend.log`、`coop-worker.log`。
- 前端通过 `VITE_API_BASE` 选择 API 地址，一键脚本自动注入；生产构建为 `/api/v1`，由 nginx 反代。
- Python/npm/Docker 默认使用国内镜像，覆盖方法见环境模板和 README。
- `./scripts/dev.sh --reset` 会删除本地 SQLite 数据，不作为常规启动或修复步骤。

Android 客户端与上面互不影响，单独用 npm 脚本构建（约束见「必须保留的设计边界 · Android 客户端」）：

```bash
npm run app:icons            # 生成 App 图标 / 启动图，并展开到 android/app/src/main/res/
npm run app:apk              # 构建前端产物 → cap sync → Gradle 出已签名 APK
npm run app:open             # 用 Android Studio 打开 android/ 工程
```

`npm run app:apk` 会自行挑选可用的 JDK 并补写 `android/local.properties`，产物在 `android/app/build/outputs/apk/release/app-release.apk`。

## 测试与验证

依赖已安装时，可按改动范围直接执行：

```bash
# 在仓库根目录运行
npm test
npm run typecheck
npm run build

# 后端测试在 backend 目录运行
cd backend
.venv/bin/python -m pytest tests/ -q
```

- 前端 `npm run build` 包含 `vue-tsc --noEmit` 和 Vite 构建；Vitest 默认使用 Node 环境。
- 后端常规接口测试使用内存 SQLite。重点测试包括 `test_shared_data.py`、`test_engine.py`、`test_api.py`、`test_balance.py`、`test_dohdol.py` 以及 `test_multiplayer*.py`。
- `test_multiplayer_postgres.py` 为可选真实 PostgreSQL 迁移/并发测试；未配置 `DLC_TEST_DATABASE_URL` 时跳过。它会重建目标数据库的 `public` schema，只能使用专门可销毁的测试数据库，并要求 `DLC_TEST_ALLOW_RESET=yes`。
- 修改共享公式时检查双端结果；修改接口时同步检查前端调用与类型；修改持久化结构时补充迁移并验证旧数据兼容性。
- 按实际执行情况说明验证结果，不把历史文档中的测试数量或通过状态作为本次验证证据。

## 数据库升级与部署

- 当前 `docker-compose.yml` 有六个服务：`db`、`backend`、`coop-worker`、`worldboss-worker`、`ranking-worker`、`frontend`（另有 `db-backup`）。worker 使用后端镜像但独立运行：缺少 `coop-worker` 时团队战斗不会推进；缺少 `worldboss-worker` 时世界BOSS 的**全局时间**不再推进（周期换轮 / 短休整复活变慢，玩家伤害因客户端上报仍会正常结算——它已不承载会话推进）；缺少 `ranking-worker` 时缓存榜（等级 / 关卡 / 战力 / 金币 / 游玩时间）不再刷新、**数据保留清理也不再执行**（`services/retention.py` 挂在该进程循环里）。`scripts/dev.sh` 会一并启动两个战斗 worker；本地开发默认仍由 API 进程刷新排行榜（`RANKING_IN_API=true`），且 `.env.local.example` 里 `RETENTION_ENABLED=false`（本地不跑清理）。
- 后端容器默认 `UVICORN_WORKERS=1`（2C/2G 服务器上内存优先；单进程 asyncio 足够处理 I/O 型挂机请求，且省一份配置与连接池。压测确认 CPU 是瓶颈时可调到 2）。多进程时排行榜刷新由 advisory lock 保证只执行一次。数据库连接池由 `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` 控制（仅 PostgreSQL 生效），并按 `DB_POOL_PROFILE` 分档，见「必须保留的设计边界 · 并发降载」。
- PostgreSQL 容器已显式调参（`docker-compose.yml` 的 `db.command`：`shared_buffers=192MB` / `effective_cache_size=768MB` / `work_mem=4MB` / `maintenance_work_mem=64MB` / `max_connections=40` + `shm_size: 128m`）。`max_connections=40` 必须 ≥ 各进程连接池上限之和；`work_mem` 是「每排序节点」内存，并发会乘算，**不要调大**。
- 各服务已设 `mem_limit`（backend 384m / coop 256m / worldboss 192m / ranking 384m / db 640m / frontend 64m / db-backup 128m），避免单点峰值 OOM 拖垮整机；调资源时同步核对 `docs/server-resource-optimization-design.md` 的 2 GB 预算表。
- PostgreSQL 使用 Alembic：在正确数据库环境下，从 `backend` 执行 `.venv/bin/alembic upgrade head`。生产容器入口会先执行迁移，再启动 API；`AUTO_CREATE_TABLES=false`。
- `AUTO_CREATE_TABLES=true` 只能确保表存在，不能替代已有表的结构迁移。
- 对于联机 DLC 之前由 `create_all` 建立的本地 SQLite，已有专用 `backend/app/migrate_local.py`：停止 API/worker，在 `backend` 目录、正确 `DATABASE_URL` 下运行 `.venv/bin/python -m app.migrate_local`。它会创建 `.before-dlc` 备份；不要把该脚本当成所有未来升级的通用迁移器。
- 部署使用 `docker compose up -d --build`，完整配置和备份操作见 README。数据库持久化目录默认为 `data/postgres`。
- 不将实际 `.env`、`.env.local`、数据库、备份、日志或密钥写入代码和文档；说明配置时使用模板和占位值。

## 后续任务的工作方式

先检查工作区现有改动，按任务定位对应页面、store、API、服务与共享配置，再实施修改。保留已有用户改动和数据库数据；避免为修复问题直接重置数据。功能、接口、数值或运行方式发生变化时同步维护相关文档；本文只记录长期有效的项目上下文，不记录未经验证的完成状态。

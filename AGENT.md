# 项目上下文：艾欧泽亚放置录

本文件供后续新聊天快速了解项目。更新日期：2026-09-23。功能状态以当前代码、共享配置和测试为准；修改架构、启动方式或核心规则时同步更新本文。

## 项目概况

- 仓库名 `FF14Push`，产品名「艾欧泽亚放置录 / Eorzea Idle Chronicle」。这是 FF14 同人放置类网页游戏，并非消息推送工具，与官方无关。
- 核心循环：英雄自动战斗 → 获得金币和经验 → 抽箱获取装备 → 穿戴、合成、重造、附魔 → 推进地区和副本。
- 已包含 40 个地区、21 个战斗职业、装备养成、酒馆招募、图鉴、排行榜、管理功能，以及生产/采集/钓鱼系统。
- 联机 DLC 已有实现：最多 8 名独立英雄、异步 PvP、个人/离线/在线合作、12 个团队副本；前端入口为「名册」「远征」「竞技场」。不要将设计文档中的全部内容直接当成待开发任务。
- 远征通关记录与「远征榜」已实现：`coop_worker` 在通关瞬间把时长与全席位分角色战斗信息写入 `coop_records`（每个真实参战账号一行）；排行榜页「远征榜」按副本实时聚合（不走 5 分钟缓存），展示最快通关时长与阵容。
- 好友系统已实现：账号有唯一「好友码」（`users.friend_code`，注册 / 迁移生成），凭码申请 + 对方同意后成为好友；好友列表展示在线状态（`users.last_seen_at` + 前端心跳，45s 内视为在线）。好友间可金币转账，手续费 `economy.json:transfer.feePct`（默认 10%）从转账额扣除后销毁，另有单笔上下限与每日累计上限（见 `services/friends.py`）。
- 聊天室已实现：单一公开大厅，登录后可看可发，实名展示 `昵称#登录账号`（同排行榜；**管理员只显示「管理员」+ 徽章，`services/chat.serialize` 不回显也不下发其登录账号**）。仅文本（单条 ≤200 字），**不保留聊天记录**——服务端只保留最近 10 分钟消息（`services/chat.py:RETENTION_SECONDS`），窗口外历史永不返回、发言时清理过期行；发言限频 20 条/60 秒（`guard_rate`）。实时推送为 WebSocket `/api/v1/chat/ws`（短时效一次性 ticket 鉴权，`services/chat.issue_ticket/consume_ticket`），广播沿用 `api/v1/coop.py` 的「各连接按游标轮询 DB」模式，天然多 worker 安全。管理员可在聊天室发公告（`POST /chat/announce`，高亮、不受发言限频）。**公告是「不保留记录」的例外**：长期保留、置顶于聊天室顶部，不参与滚动窗口的读取与清理（`services/chat.announcements/new_announcements`，按 id 倒序最新在前）。表：`chat_messages`、`chat_tickets`（迁移 `o1a2b3c4d5e7`）。
- 世界BOSS 已实现：全服共享血量的 BOSS「黄金巴哈姆特」（初始 **20 亿**血量、第一阶段攻击力 20000）。**采用「讨伐周期」制**：`worldboss.json:periodSeconds`（默认 5h）是唯一结算单位——周期内 BOSS 被击杀只进入 `respawnSeconds`（60s）短休整、到点满血重生且 **cycle 不变**、可反复讨伐（`kills` 计数）；周期到时（`period_ends_at`）无论存亡都满血、**cycle+1**、结束上一周期全部会话（`services/world_boss.roll_world_boss`），**击杀与结算解耦**，弱玩家只要在周期内参与就一定有奖励。所有在线玩家各自上阵最多 8 名英雄同时削弱同一血量；由独立进程 `worldboss_worker` 服务端权威推进（`services/worldboss_engine.py`，100ms tick，BOSS 普攻对全体存活英雄、技能按固定间隔随机独立释放，英雄各自独立死亡/复活），前端只渲染 WebSocket 快照。**阶段（P1→P2→P3）**按全服剩余血量占比自动进入（`worldboss.json:phases`：≤60% 进 P2、≤30% 进 P3）：血量越低 **BOSS 防御越厚**（英雄输出按 `1/defenseMultiplier` 折算）、**技能威力越高**（`skillPotencyMultiplier`，不影响普攻）；阶段由 worker 每批推进前把全局血量占比写入 `state.bossHpRatio`。场地要求英雄 80 级以上，80–99 级输出/治疗被线性削弱（满级解除）。按**周期**结算：奖励 = **档位 + 名次加成**（`reward.tiers` 按周期累计伤害取最高达标档 + `reward.rankBonus` 仅前 10 名；入榜门槛累计伤害 ≥ 500 万）——第 1 名打满顶档 = 10+10 = 20 件，达标弱玩家保底 1 件（旧「名次独占」曲线已废弃）。**榜单行可点击展开**查看该玩家本周期各英雄的伤害与占比（贡献按 `heroId` 累加增量，跨多次上阵不重复计数）。**世界BOSS 血量、周期与总伤害榜不随版本更新重置**（贡献/奖励行永久保留）。「绝境龙神」固定红色（神话）品质、100 级，仅世界BOSS 掉落（不可抽奖/打造/合成），可重造/附魔但成本 ×`economy.json:exclusiveCostMultiplier`（远高于其他装备）。数据表 `world_bosses` / `world_boss_sessions` / `world_boss_contributions` / `world_boss_rewards` / `world_boss_tickets`（迁移 `p2b4d6f8a0c2`；周期列 `period_ends_at` / `kills` 见 `t6f8a0b2c4d6`，设计见 `docs/world-boss-cycle-redesign.md`），配置见 `shared/data/worldboss.json`、`shared/data/exclusive-equipment.json`。
- 地区战斗**难度等级（周目制）** 已实现：账号级 `users.battle_difficulty`（当前，0–15）与 `battle_difficulty_max`（已解锁上限），地区进度按 `region_progress.difficulty` 隔离——进入新难度后 40 个地区重新锁定，**每次**击败当前难度第 40 区关底 BOSS 即解锁下一难度（`api/v1/battle.py::_settle_boss`；刻意不要求首通，否则功能上线前已通关的旧存档永远无法解锁）；切换难度用 `POST /battle/difficulty`，仅限已解锁范围且会结束进行中会话、落回该难度「已通关最高地区 +1」。数值：怪物按**加法**放大（生命/防御/经验 `1+N`、攻击 `1+0.5N`、金币 `1+0.1N`），玩家攻击/防御按**乘法**缩小（`0.85^N` / `0.9^N`）；配置在 `shared/data/combat.json:difficulty`，前后端镜像 `services/difficulty.py` ⟷ `game/core/difficulty.ts`。难度 0 与历史数值逐位相同；玩家缩放只在战斗结算处施加，**不进入 `compute_stats` / 战力门槛**（否则高难度会自我锁门）；击杀额度、金币/经验上限与 BOSS 奖励都要带难度（`combat_model.py` / `validator.py`），否则合法上报会被拒或截断。难度只作用于地区战斗，不影响高难副本 / 远征 / 世界BOSS。排行榜「关卡榜」（`services/ranking.py`）也把难度纳入主序：`value = 难度 × 1000 + 已通关最高地区`（难度 1 第 20 关排在难度 0 第 40 关之上），前端 `RankingView.vue` 按同基数解码展示。
- **挖宝 / 魔晶石 / 种田** 三个系统已实现，配置集中在 `shared/data/treasure.json`、`materia.json`、`farm.json`，后端服务 `services/treasure.py`、`materia.py`、`farm.py`，接口 `api/v1/treasure.py`、`materia.py`、`farm.py`，页面 `TreasureView.vue`、`MateriaView.vue`、`FarmView.vue`。要点：**挖宝**花 100 万进 5 层副本，每层怪物 = 难度(层-1) 的地区 40 关底 BOSS（难度只放大怪物、不削弱玩家），门 50/50、**宝箱在开箱时 roll 并立即入账**（选错门 / 阵亡都不影响已入账奖励）、阵亡可原地重试、每层 5% 猜大小、通关第 5 层额外 1000 万（**开箱转盘**：`components/TreasureWheel.vue` 把开箱做成圆盘转盘，扇区几何在 `game/core/wheel.ts` —— 每件奖励一个扇区、干扰项补足到至少 8 个扇区、逐件停在对应扇区，并尊重 `prefers-reduced-motion`；奖励仍由服务端结算，动画纯展示）；**魔晶石**孔位属**账号级 11 栏位 × 5 孔**（不随装备更换），第 1 孔 100%→第 5 孔 5%、失败消耗、取出返还，6 种 × 5 级（FF14 国译名）、5 合 1，加成经 `stats.compute_stats(socket_mods=...)` 注入；**种田**账号级田地 2→10 片、作物按**真实时间**生长（**离线也生长**，是「不做离线收益」的显式例外）、金币种子 1000 万 / 经验种子 +1 级（满级需二次确认）。三者共新增迁移 `r4d6f8a0c2e4`（`materia_sockets` / `farm_plots` / `treasure_runs` + `users.farm_unlocked`）。挖宝属战斗类活动，`services/roster.end_treasure_runs` 已接入互斥（开始其它活动 / 切换 / 解雇英雄都会结束进行中的副本）。
- 界面及项目文档主要使用中文，新增内容保持已有命名和文案风格。
- 玩家间**交易板**已实现（表 `market_listings` / `market_buy_orders`，服务 `services/market.py`，接口 `api/v1/market.py`，页面 `MarketView.vue`，配置 `shared/data/economy.json:market`）。**寄售**：上架即托管（装备删行 + 快照，堆叠扣库存），整单买断成交，成交价抽 `feePct` 手续费（金币直接销毁），未售出 `listingDays` 天到期退回；可交易的堆叠物种类由 `dohdol_util.sellable_kind` 决定（material / potion / food / **materia** / **seed**），前端 `MarketView.vue` 的子页签与 `StackKind` 联合类型需与之同步。**收购单（求购）**：仅支持堆叠物，发布时按 `unit_price × quantity` **全额托管金币**，卖家手动按剩余数量**部分成交**（卖家得 `amount - fee`），未成交部分在下架 / 到期时退还；**刻意不做自动撮合、不记录逐笔成交历史**（只记 `filled` 总量），单账号进行中收购单上限 `maxActiveBuyOrders`。两侧托管/成交都在写端点内完成，对手方用 `lock_user` 加锁（加锁顺序：当前用户 → 单据行 → 对手方）。

- **钓鱼 2.0** 已实现（迁移 `v8b0d2f4a6c8`：`users.active_title_id` + `activity_sessions.session_insights/session_intuition`，旧单值 `insight_expires_at` 已删除）：普通鱼分**白 / 蓝 / 紫**三档并可带**天气 / 时间门槛**；每钓场的特殊鱼（旧鱼王 / 鱼皇 + 新增 `kind:"legend"` 困难鱼，如镜中蝶、七彩天主）统一由 **`intuition`（捕鱼人之识）** 驱动——**每种直觉只绑定一条鱼**，需在该鱼的天气 / 时段窗口内钓齐**计数型前置**（`requires: [{fishId,count}]`）才开启，**BUFF 期间不刷新 / 不延长**，到期后须重新钓齐才能再次触发。天气与艾欧泽亚时间（ET）是**服务端时间的纯函数**：`backend/app/services/weather.py` ⟷ `frontend/src/game/weather.ts` 用同一 32 位整型哈希（`hash01`）逐位一致，前端据此做**天气预报**；改算法必须同步两端（`test_dohdol.py::TestWeather::test_hash_matches_frontend_snapshot` 锁住快照）。数据：`shared/data/fish.json`（结构 `normal[]` + `specials[]`，旧 `king/emperor` 已迁入 `specials[]` 并标 `legacy:true`，**id 与数值不变**）+ `shared/data/weather.json`；由 `scripts/gen-fish-data.py` 从冻结的 `scripts/fish-base.json` 重建（改内容改脚本并重跑，不要手改 `fish.json`）。称号由 `services/titles.py` **数据驱动**判定（`titles.json` 的 `condition.type`：`all_king/all_emperor`（仅 legacy）/`all_legend`/`all_special`/`count_kind`/`count_rarity`/`specific_fish`/`species_count`/`fish_count`/`region_group_king`），每人可在设置页**佩戴一个**（`POST /settings/active-title`，`users.active_title_id`），佩戴中的称号在排行榜 / 玩家资料突出展示；旧称号只统计 legacy 鱼王 / 鱼皇，**新增困难鱼不影响其达成条件**。`fish_records.kind` 现可为 `normal|king|emperor|legend`，`services/ranking.py` 的钓鱼榜与 `services/dohdol_state.py` 的 `fishStats` 已同步 legend 桶。另有 **10 个彩蛋称号**（挖宝下底 ×5 / 采集 ×5，`condition.type == "random_drop"`，**极低概率**）：**非确定性**，由 `titles.roll_random_titles(db, user_id, event, rolls)` 在 `services/treasure.open_chest`（通关第 5 层 = 下底）与 `services/gathering.report_gather`（按本次采集动作数 `rolls`）处抽取，逐称号独立判定（合并概率 `1−(1−p)^rolls`）、已拥有则跳过；**`evaluate_titles` 不处理 `random_drop`**（`matches()` 对其返回 False），故彩蛋不会被确定性条件误发。这两个响应各带 `newTitles`，前端 `dohdol`/`treasure` store 弹「达成彩蛋称号」提示（`titles.json` 中 `egg: true` 在设置页 / 钓鱼页标「彩蛋」）。

- **全场景音效**已实现：音效由**浏览器实时合成**（Web Audio API），谱面是纯数据、**不打包任何音频素材、不引入第三方音频库**。引擎在 `frontend/src/game/audio.ts`（单例 `sound`，导出 `SoundCue` 联合类型 + `CUES` 谱面 + 纯函数 `gate()` 节流闸门），设置由 `frontend/src/stores/sound.ts` 持有并注入（localStorage 前缀 `eorzea.sound.*`：`enabled` / `master` / `battle` / `ui` / `ambient`，对应设置页音效区块）。战斗语义事件由 `BattleSimulator` 的可选构造参数 `onSound?: (cue: SoundCue) => void` 上报（未注入即静默，核心模拟器不依赖音频），`stores/game.ts`、`stores/treasure.ts` 传入 `sound.play`；世界BOSS 音效来自 WebSocket 增量事件（按 `seq` 去重）。事件点：战斗（`battle.hit/crit/skill/signature/heal/hurt/kill/clear/death/revive/boss.*`）、挖宝转盘与选门、抽箱滚轮、重造 / 附魔（涨跌不同音）、魔晶石、采集 / 生产 / 钓鱼 / 序列 / 种田、掉落气泡（按品阶）、弹窗开关。**关键事件必响、高频事件按最小间隔节流**（单音效 `throttleMs` + 全局 100ms 窗口并发上限），避免 DoT / proc 高峰爆音。AudioContext 在首个用户手势解锁（`App.vue`），页面切到后台（`document.hidden`）时静默。新增音效必须同时补 `CUES` 谱面（`Record<SoundCue, CueSpec>` 会强制穷尽），并同步 `frontend/src/game/audio.spec.ts` 的「关键音效齐备」清单。

## 阅读顺序与事实来源

1. 本文件：架构、关键约束、开发入口。
2. `README.md`：玩法说明、运行部署、核心设计、与 PRD 的差异和已知限制。
3. `docs/multiplayer-dlc-design.md`：联机 DLC 的设计、接口及验收背景。
4. `prd.md`：原始需求。现有实现有明确调整，不要仅按原始 PRD 恢复旧规则。
5. 相关代码、`shared/data/*.json` 和测试：确认实际行为。

README 早期目录概览中的页面数、测试数、Compose 服务数可能落后于代码；不要沿用这些数字判断项目现状。

## 技术栈与目录导航

前端使用 Vue 3、TypeScript、Vite 6、Pinia、Vue Router、Tailwind CSS 4、Axios；根目录通过 npm workspace 管理 `frontend`。后端使用 Python 3.11+、FastAPI、Pydantic 2、SQLAlchemy 2 异步会话和 Alembic。本地默认 SQLite，部署使用 PostgreSQL 16。

| 路径 | 职责 |
| --- | --- |
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
| `backend/app/services/` | 数值、战斗校验、掉落、装备、生活职业和联机业务 |
| `backend/app/coop_worker.py` | 独立进程推进团队战斗、处理指令、租约及断线状态 |
| `backend/alembic/versions/` | 数据库结构与数据迁移 |
| `backend/tests/`、`frontend/src/**/*.spec.ts` | pytest 与 Vitest 测试 |
| `scripts/` | 本地启动、图标生成、数值推导和合作战斗标定工具 |

## 必须保留的设计边界

- **服务端是资产与进度的权威。** 普通战斗由客户端模拟并批量上报，服务端校验收益、击杀额度、解锁及推进；不要信任客户端金币、击杀数或时间。
- 击杀额度使用服务端记录的真实间隔，客户端 `elapsedMs` 仅供参考。调整模拟器时同时检查 `backend/app/services/validator.py` 和相关战斗模型，避免合法上报被拒或出现超额收益。
- **时长下限的容差要留足**：挖宝 `shared/data/treasure.json:minFloorFightMs` 与高难 `shared/data/balance.json:raids.*.durationTolerance`（经 `raid_balance.minimumFightMs`）是「防脚本秒通」的服务端计时下限，但客户端一次出手最快约 0.75s，实战还有暴击 / 直击 / 技能方差，强练度玩家会远快于理论时长。下限必须低于合法最快通关，否则会把合法通关误报为「战斗时长异常 / 战斗时长校验」；挖宝客户端对此时长校验会自动等待重试，高难则直接判负，改这两个值时务必同步回归 `test_treasure.py::test_fast_floor_clear_is_accepted` 与 `test_api.py::TestRaid::test_hard_raid_fast_clear_is_accepted`。
- 普通挂机不提供离线收益。联机「离线合作/克隆体」是独立机制，不等于为普通挂机新增离线回补；团队战斗由 worker 推进，worker 中断也不补算离线时间。
- 装备归属账号，英雄穿戴状态与账号背包需要保持一致；切换、解雇及多英雄操作应检查 `roster.py`、相关模型与事务逻辑，避免装备或资产重复。
- 好友金币转账同为服务端权威：`services/friends.py` 按 id 升序双行锁两方账号，校验好友关系 / 余额 / 单笔上下限 / 每日累计额度后再结算，手续费按 `floor(amount × feePct)` 销毁（净额不为 0 增长来源），流水写入 `coin_transfers`。
- **反多开（防小号刷金币）**：账号关联判定 = 设备指纹 **或** IP。设备指纹由前端 `frontend/src/utils/device.ts` 从浏览器信号派生（同一台机器的不同浏览器 / 无痕得到同一标识），随每个请求以请求头 `X-Device-Id` 发送；IP 取 `users.reg_ip` / `users.last_ip` 与 `user_devices.first_ip` / `last_ip`，比较前过滤 `unknown` / 回环 / `testclient` 等哨兵值（见 `services/devices.py`）。**同一设备最多注册 `economy.json:antiAlt.maxAccountsPerDevice`（默认 2 = 1 大号 + 1 小号）个账号，仅在注册处按设备硬拦**；登录 / 心跳只登记设备与最近 IP、不拦截（避免锁死存量多开账号），未携带 `X-Device-Id` 时不启用该上限。**关联账号（同设备 / 同 IP）**之间的好友转账按 pair 双向 24h 累计受 `antiAlt.transferDailyLimit` 限制，交易板寄售成交受单笔 + pair 24h 累计（`antiAlt.marketDailyLimit`）限制，收购单成交只受单笔上限（`MarketBuyOrder` 不记录卖家、无逐笔成交归属）。数据表 `user_devices`（迁移 `u7a9c1e3b5d7`）。改判定或额度时同步回归 `tests/test_anti_alt.py` 与 `services/devices.py`。
- 怪物、精英不直接掉落装备；主要通过抽箱获取，另有 BOSS 宝箱奖励。
- 普攻（`ADVENTURER_SKILL`，零耗蓝兜底）威力由 `combat.json:basicAttackPotency` 指定（当前 50%，低于技能威力），前后端同源：前端 `combat.ts`、后端 `combat_model.BASIC_ATTACK_POTENCY`。改这个值会同时改变整体 DPS，进而影响怪物按「命中次数」的标定与 `core.spec.ts` 的击杀手感测试。
- 地区关底 BOSS 有单次命中伤害上限 `bosses.json:maxHitDamagePct`（当前 20% 最大生命），在 `battle.ts:capBossHit` 结算，用于防止开局爆发 / 暴击大招秒杀 BOSS；仅地区 BOSS 生效（高难与联机不走此上限），且客户端做上限比服务端理论模型更保守，不影响上报校验。
- **绝技（招牌技能）**：每个战斗职业一个，配置在 `shared/data/jobs.json` 的 `job.signature`（不计入 `skills[]`，`maxSkills` 仍为 7）。机制为独立充能槽（`battle.ts:signatureCharge`）：战斗中按 `chargeSeconds` 匀速充能、每次击杀额外 `chargePerKill`，满槽自动释放；**不占 GCD、不耗魔力**，故不与普通技能抢出手。伤害型绝技（`potency>0`）对整体 DPS 的贡献必须同时镜像到后端 `combat_model.signature_potency_per_sec`（按纯时间充能取有效冷却，客户端击杀加速带来的偏差由 2x 校验容差覆盖），否则合法上报会被击杀额度拒绝；buff/生存型绝技无需建模。新增效果类型 `undying`（锁血不死，`battle.ts:heroDies`）不与装备词条 `cheatDeath` 冲突（各自独立计时 / 标记）。
- 数值优先修改共享 JSON，避免前后端各自硬编码。`combat.json`、`monsters.json`、`balance.json`、`multiplayer.json` 分别承载相关战斗、怪物、战力与联机配置。
- 魔晶石加成是**账号级**面板加成，必须通过 `stats.compute_stats(hero, items, socket_mods)` 注入：新增任何「计算英雄面板 / 战力 / 门槛」的调用点都要一并传入 `await materia.socket_mods(db, user_id)`（或 `CurrentSockets` 依赖版，见 `core/deps.py`），否则面板、战力榜与地区/副本门槛会与实战不一致。挖宝的怪物数值、宝箱内容与猜大小，以及种田的成熟判定，**全部只认服务端时钟与随机数**；客户端的 `elapsedMs` 仅作参考。
- **附魔词条扩展（战斗 12 类 + 生产/采集）**：战斗词条按 `terms.json:categories` 分为 12 类（常住属性 / 攻击触发 / 异常 / 受击 / 防御 / 条件 / 动态成长 / 资源转换 / 联动 / 风险代价 / 特殊机制 / 累计触发）+「收益获取」。新增机制的数值 / 阈值集中在 `combat.json:equipEffects`（`proc`/`conditional`/`growth`/`convert`/`charge`/`special`），前端 `battle.ts` 结算；**任何提升期望 DPS 的新机制必须同步镜像到 `combat_model.py`**（否则合法上报会被击杀额度拒绝），仅影响生存 / 资源的机制不建模（与凋零 / 失明同待遇）。风险代价类词条用 `cost: {stat, ratio}` 声明副作用，落库 `value = round(主值 × ratio)` 并由 `stats.aggregate_equipment` 累加进 `term_mods`；`desc` 使用 `{v}` / `{c}` 占位符。词条 `category` 为必填，词条图鉴支持按类别筛选。生产 / 采集扩展词条由 `scripts/gen-dohdol-data.py` 生成（改词条要改脚本并重跑）。设计见 `docs/enchant-terms-expansion-design.md`。
- 抽箱品阶概率与生产品阶概率共用一套「幸运来源」归一化（`services/luck_sources.py`）：`p = Σ weight × min(值 / ref, 1)`，权重合计 = 1，各 `ref` 为该来源的真实最大值（含太古词条），因此只有全部来源满才达到上限。来源主体在 `chests.json:rarityLuck` 与 `recipes.json:equipment.rarityScaling`，远征 / 高难的难度权重在 `multiplayer.json:difficultyWeights` 与 `raids.json:difficultyWeights`（仅计首通）。新增来源时同步更新前端文案与 `tests/test_shared_data.py` 中「ref = 配置推导值」的断言。
- 战力不等同于装备出售估值。普通副本允许低战力挑战，高难与地区解锁有服务端资格条件；已移除机制试炼，不应重新依赖它。
- 战力配置有校验与安全默认值：修改 `balance.json` 时检查 `services/balance.py` 和 `balance_defaults.py`；不兼容规则需考虑版本和既有挑战快照。
- 联机 API 与 worker 共享数据库状态。修改时保留锁顺序、租约、指令处理及奖励幂等语义；SQLite 测试不能替代 PostgreSQL 并发验证。

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

- 当前 `docker-compose.yml` 有五个服务：`db`、`backend`、`coop-worker`、`worldboss-worker`、`frontend`。worker 使用后端镜像但独立运行：缺少 `coop-worker` 时团队战斗不会推进，缺少 `worldboss-worker` 时世界BOSS 不会推进（血量不下降）。`scripts/dev.sh` 会一并启动两个 worker。
- PostgreSQL 使用 Alembic：在正确数据库环境下，从 `backend` 执行 `.venv/bin/alembic upgrade head`。生产容器入口会先执行迁移，再启动 API；`AUTO_CREATE_TABLES=false`。
- `AUTO_CREATE_TABLES=true` 只能确保表存在，不能替代已有表的结构迁移。
- 对于联机 DLC 之前由 `create_all` 建立的本地 SQLite，已有专用 `backend/app/migrate_local.py`：停止 API/worker，在 `backend` 目录、正确 `DATABASE_URL` 下运行 `.venv/bin/python -m app.migrate_local`。它会创建 `.before-dlc` 备份；不要把该脚本当成所有未来升级的通用迁移器。
- 部署使用 `docker compose up -d --build`，完整配置和备份操作见 README。数据库持久化目录默认为 `data/postgres`。
- 不将实际 `.env`、`.env.local`、数据库、备份、日志或密钥写入代码和文档；说明配置时使用模板和占位值。

## 后续任务的工作方式

先检查工作区现有改动，按任务定位对应页面、store、API、服务与共享配置，再实施修改。保留已有用户改动和数据库数据；避免为修复问题直接重置数据。功能、接口、数值或运行方式发生变化时同步维护相关文档；本文只记录长期有效的项目上下文，不记录未经验证的完成状态。

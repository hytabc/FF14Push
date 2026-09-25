# 服务器 CPU / 内存优化设计

版本：1。项目：Vue 3 / FastAPI / PostgreSQL。本文是实现与验收契约。

背景：目标服务器为 **2 核 / 2 GB**，CPU 与内存都偏紧。前端/带宽侧已在
`docs/multiplayer-load-bandwidth-design.md` 处理（响应 brotli、请求 gzip、WS permessage-deflate、
世界BOSS 运算下放）。本文只解决**服务端自身的 CPU 与内存**：部署与数据库配置调优、应用层重复计算与
峰值内存、只增不减表的清理与保留策略。

> **实施状态：阶段 A、B（B1–B6）、C 已实现并回归通过。**
> 验证：后端 `pytest tests/ -q` **742 passed / 1 skipped**；前端 `npm test` 303 passed、`npm run typecheck` 通过。
> 关键等价性测试：`tests/test_ranking_refresh.py`（只加载已装备装备 + 分批 ⇒ 与全量口径逐位相等）、
> `tests/test_ranking_live_cache.py`（实时榜缓存合并/失效/关闭）、`tests/test_world_boss_ws.py`（共享生产者）、
> `tests/test_retention.py`（只清终态超期、榜单真相与反多开依据不动）、`tests/test_http_cache.py`（config 只构造一次）。
>
> **与原方案的实施偏差（均已按风险重估，理由见 §8.1）**
> 1. **B7（`/admin/online` 加 SQL 过滤）改为「保留原语义 + 说明」**，并且**故意不给 `users.last_seen_at` 加索引**。
> 2. **阶段 C 不清理 `coop_rooms`/`coop_battles` 及其子表**（与 `coop_records` 的外键冲突）。
> 3. **阶段 C 不清理 `chat_messages` 的公告**（AGENT.md 明确其为长期保留的例外）。
> 4. `services/ratelimit.py` 的按 key 清理**保持不变**（热路径必须走索引）；沉寂 key 的全局清扫改由保留任务承担。
> 5. `auto_create_tables` 代码默认值由 `true` 改为 **`false`**（生产 foot-gun）。

---

## 1. 目标与非目标

### 1.1 目标

1. 把**常驻内存**压到 2 GB 机器的安全范围（目标合计 ≈1.35 GB，见 §1.3），并给每个容器加内存上限避免单点 OOM 拖垮整机。
2. 消除**周期性 CPU 尖峰**与**每请求的重复计算**（排行榜全量刷新、`compute_stats` 重复调用、实时榜算两遍）。
3. 消除**单次可吃掉 GB 级内存**的路径（排行榜刷新全库装备入内存）。
4. 给**只增不减**的表加保留策略，遏制长期膨胀与 VACUUM/索引压力。

### 1.2 非目标

- 不改任何**玩法数值**与结算口径（本方案应是「结果逐位不变」的重构）。
- 不清除任何**榜单真相**数据（`world_boss_contributions` / `world_boss_rewards` / `coop_records` / `coin_transfers`）。
- 不引入新的中间件（Redis / Celery 等）；继续用现有进程模型。
- 不改前端页面契约（`/game/state` 的全量形状保持）。

### 1.3 2 GB 内存预算（目标态）

| 组件 | 目标常驻 | 说明 |
|---|---|---|
| OS + dockerd + nginx | ~250 MB | nginx 静态站约 20 MB |
| PostgreSQL | ~450 MB | `shared_buffers` 192 MB + 其他 |
| backend（uvicorn **1** worker） | ~200 MB | 完成阶段 B 后 |
| coop-worker | ~120 MB | 模拟循环 + state |
| worldboss-worker | ~80 MB | 已退化为全局时间推进 |
| ranking-worker | ~200 MB | 完成 B2 后（原可达 GB 级） |
| db-backup | ~30 MB（瞬时） | `pg_dump` 流式，内存低、磁盘高 |
| **合计** | **≈1.35 GB** | 留 ~650 MB 给峰值与页缓存 |

---

## 2. 现状与热点定位

> 所有条目均已按代码核实（含 file:line）。

### 2.1 CPU

| 热点 | 位置 | 量级 |
|---|---|---|
| 排行榜全量刷新 | `services/ranking.py:66 _refresh_all_rankings` | `selectinload(User.items)` 载入**全库装备** + 逐用户 `compute_stats` → O(用户×装备)；`delete(RankingEntry)` 全表删 + 5U 行批量重插；每 300s 一次 |
| 同上默认跑在 API 进程内 | `core/config.py:77 ranking_in_api=True`（compose `:97` 才置 false） | 纯 CPU 同步任务**阻塞事件循环** |
| `/game/state` | `services/state.py:61 build_game_state` | ~25 次逐条查询；`compute_stats` **重复调用**（`state.py:71` + 经 `region_access`→`qualification.py:27` + `state.py:165` 名册每英雄各一次）；序列化全部背包 |
| `/battle/session/report` | `api/v1/battle.py:138` | `compute_stats` 2–3 次（`battle.py:163`、`require_region`、`_settle_boss:352`）；`services/stats.py` **无任何缓存** |
| 实时榜（钓鱼/生活/远征） | `services/ranking.py:126/250/385` + `api/v1/ranking.py:58-68` | 每次请求**全表聚合两遍**（`entries` 与 `me` 各一次）并全量排序，无缓存 |
| worldboss WS | `api/v1/worldboss.py:404-439` | **每连接**每 0.5s 2 次查询 → O(连接数)。chat/coop 已是共享生产者，只剩它 |
| `/game/config` | `api/v1/game.py:27` | 每次请求**重建**含 935 底材 + 全配置的大 dict，再编码 + sha1 |
| ETag 的 304 路径 | `core/http_cache.py:43` | 仍先编码整个 body + sha1；省带宽不省 CPU |

### 2.2 内存

| 热点 | 位置 | 量级 |
|---|---|---|
| 排行榜刷新**全库装备入内存** | `ranking.py:68` | U×I：U=2k/I=100 ≈ 120–160 MB；U=10k/I=200 ≈ **1.2–1.6 GB** ← 唯一能单次吃 GB 的点 |
| `/game/state` 单请求峰值 | `state.py:65,165,171` + `http_cache.py` + 压缩缓冲 | 老账号（~3000 件）≈ **8–13 MB**，并发线性叠加 |
| 实时榜全表载入 | `ranking.py:128/250/385` | 随**总玩家基数**增长（非单账号） |
| `_ROWS_CACHE` | `services/world_boss.py:382` | 存**当前周期全部参战者**（每行含最多 8 条分英雄明细） |
| `/admin/online` | `services/admin_monitor.py:73-96` | **全表 `User` + 全表 `UserDevice`** + 并查集 |
| `CONFIG` 每进程一份 | `services/game_config.py:38` + `shared/schema/loader.py:203` | ≈10 MB/进程；`BaseItem`（`loader.py:22`）**未加 `slots=True`** |
| 连接池超卖 | `core/database.py:31` 单例 engine，所有进程同一套配置 | 5 进程 ×(10+20) = **150** > PG 默认 `max_connections=100` |

### 2.3 部署 / 数据库

- `docker-compose.yml` **全文无** `mem_limit` / `deploy.resources` / `shm_size`。
- `db` 服务**零调优**（`postgres:16-alpine` 默认：`shared_buffers=128MB`、`effective_cache_size=4GB`（会误导 planner）、`work_mem=4MB`、`max_connections=100`）。
- `UVICORN_WORKERS` 默认 2；**每个 API worker 都会跑一遍** `ensure_admin_user`（含 bcrypt ~100ms）+ `ensure_world_boss` + **冗余的 `_worldboss_loop`**（`main.py:95`，与专用 `worldboss-worker` 重复）。
- `db-backup` 每 6h `pg_dump` 全量 → 落地 `dump.sql` 再 `tar -czf`（磁盘峰值 ≈2×，且可能与排行榜刷新撞车）。
- `AUTO_CREATE_TABLES` 代码默认 `True`（`config.py:43`，生产 foot-gun；compose 已显式置 false）。
- 索引：覆盖面良好；唯一缺口 `users.last_seen_at`（`models/account.py:30` **无索引**）。当前在线判定在 Python 侧做，所以**现在加索引不会提速**——除非改成 SQL 过滤（见 B7）。

### 2.4 只增不减的表

`security_events`（`services/ratelimit.py:39-43` **只删当前 scope+key**，沉寂 key 的行永久残留）、
`audit_logs`、`user_devices`、`battle_sessions` / `activity_sessions` / `raid_sessions` / `treasure_runs`（只翻 `active`）、
`coop_rooms` / `coop_battles` / `coop_members` / `coop_commands` / `coop_seats`（终态不删）、`pvp_battles`、
`market_listings`(closed)、`chat_messages`(公告)。

**不可清（榜单真相 / 对账依据）**：`world_boss_contributions`、`world_boss_rewards`、`coop_records`、`coin_transfers`、`rankings`（自清理）。

### 2.5 已优化过、勿重复怀疑

- chat / coop 的 WS 广播已是「每进程/每房间一次读库 + 内存分发」（`services/broadcast.py`）。
- 世界BOSS 榜有进程内 TTL 缓存（`world_boss.py:382`，写入即 `invalidate`）。
- 挂机热路径（采集/生产/钓鱼/战斗上报）已用批量接口，**未发现遗漏的逐件 select**。
- 市场列表/我的挂单/管理端用户搜索**均有** `limit` 分页（`api/v1/market.py:97`、`admin.py`）。
- 逐玩家世界BOSS 会话推进已下放客户端（见 `docs/multiplayer-load-bandwidth-design.md`）。

---

## 3. 阶段 A：部署与数据库配置调优（零代码风险，先做）

### A1 uvicorn 与进程模型

- `UVICORN_WORKERS=1`（2 GB 下内存优先）。代价：单个阻塞型 CPU 请求会占住唯一的 API 进程——由 B1 保证排行榜刷新不在 API 内、B8 抑制并发峰值来兜底。压测后若确认 CPU 才是瓶颈，可回 2（内存已因 B2/B4 释放）。
- `--no-access-log`（可通过环境变量开关）：高并发挂机时每请求一行日志本身就是 CPU/IO 开销。

### A2 连接池按进程角色分档

`core/database.py` 目前是**单例 engine + 所有进程同一套配置**。改为按 `DB_POOL_PROFILE` 分档：

| 进程 | `DB_POOL_SIZE` | `DB_MAX_OVERFLOW` | 最大连接 |
|---|---|---|---|
| `api`（backend） | 5 | 5 | 10 |
| `worker`（coop / worldboss / ranking） | 2 | 0 | 2 |

- 合计最大 ≈ 10 + 2 + 2 + 2 = **16**，远低于调小后的 `max_connections=40`。
- `pool_timeout` 30 → **15**：小机器上宁可快速失败也不要长时间堆积等待。
- `pool_recycle=1800` 保持（防中间设备断连）。

### A3 compose 资源护栏

- 各服务加 `mem_limit`：`backend 384m` / `coop-worker 256m` / `worldboss-worker 192m` / `ranking-worker 384m` / `db 640m` / `frontend 64m` / `db-backup 128m`；`restart: unless-stopped` 已有。
- 可选加 `cpus`（如 `db: "1.0"`、`ranking-worker: "0.5"`）避免单服务吃满 2 核。
- `db` 加 `shm_size: 128m`（Postgres 并行查询 / 大排序用 `/dev/shm`，容器默认 64 MB）。

### A4 PostgreSQL 参数

给 `db` 服务加 `command:`：

```
postgres -c shared_buffers=192MB -c effective_cache_size=768MB
         -c work_mem=4MB -c maintenance_work_mem=64MB -c max_connections=40
```

- `work_mem` **保守取 4MB**：它是**每排序/每哈希节点**的内存，并发下会乘算，小机器不宜调大。
- `max_connections=40` 与 A2 的总连接上限对齐（留余量给 `pg_dump`、迁移、手工连接）。

### A5 备份与启动

- `BACKUP_INTERVAL_HOURS` 6 → **12**；`db-backup` 的 `mktemp` 目录改到挂载卷下（当前写容器可写层，占镜像层空间）；避免与排行榜刷新同刻（B1 之后刷新在 ranking-worker，可在脚本里错峰）。
- 启动：`ensure_admin_user` / `ensure_world_boss` 在**每个 uvicorn worker** 都会跑。单 worker 后只跑一次，保持现状即可；若回到 2 worker，文档记录「可加单进程守卫」为后续项。

---

## 4. 阶段 B：应用层 CPU / 峰值内存

> 每项都要求**结果逐位不变**，并加等价性测试（见 §7）。

### B1 排行榜刷新与冗余轮询移出 API 进程

- `core/config.py` 的 `ranking_in_api` 默认 **`True` → `False`**（compose 已是 false，改默认值防止本地/漏配时把 GB 级峰值带进 API 进程）。
- 新增 `worldboss_loop_in_api`（默认 **`False`**）：`main.py:95` 的 `_worldboss_loop` 只在没有专用 `worldboss-worker` 的部署里开启。默认关闭后可去掉每个 API worker 的 30s 冗余轮询。
- 刷新间隔 300s → **600s**（可配 `RANKING_REFRESH_SECONDS`）；等级/战力/金币/关卡/游玩时间本就是「缓存榜」，10 分钟对玩家感知几乎无损，但尖峰频率减半。

### B2 排行榜刷新只加载「已装备」装备（关键）

现状 `ranking.py:68` 用 `selectinload(User.items)` 把**全库装备（含背包）**读进内存，再对每个用户调 `compute_stats(hero, user.items, mods)`。

**已核实的等价性依据**：`services/stats.py:193` 的 `_compute` 先经 `hero_items()` 过滤，而 `services/stats.py:111`
的 `aggregate_equipment` 对 `equipped_slot is None` 的装备**直接 `continue`** —— 背包里的装备对面板属性**没有任何贡献**。
因此把数据源换成「只取每账号已装备的装备」是逐位等价的。

改法：
- 一次性 `select(Item).where(Item.equipped_slot.is_not(None))`（或按 `user_id` 分批），在内存里按 `equipped_hero_id` 分组；
- 用户遍历改用 `.yield_per(...)` / 按 id 分页，避免一次性把全部 `User` 也读进来；
- `RankingEntry` 的 `delete + insert` 保持（已是 `executemany`），可改为分榜写入降低单次事务体积。

收益：载入行数从「全库装备」降到「已装备装备（≤ 席位×11/账号）」，**一至两个数量级**；GB 级峰值消失。

### B3 实时榜：合并聚合 + 短 TTL 缓存

现状 `api/v1/ranking.py:58-68` 对 fish / dohdol / coop 榜分别调 `fetch_*_board` 与 `fetch_*_user_rank`，
**同一份全表聚合算两遍**。

改法：
- 让 `fetch_*_board` 一次返回 `(entries, me)`（`services/ranking.py:126/250/385` 的 `_*_rows` 结果复用）；
- 加进程内短 TTL 缓存（fish 10s / dohdol 10s / coop 10s），模式沿用 `world_boss._ROWS_CACHE`
  （`world_boss.py:382` 的 `dict[key] = (monotonic, rows)` + `invalidate_*()`）；在钓鱼上报、生产/采集上报、
  远征通关写入处调用 invalidate，避免「刚钓完看不到自己」。

### B4 `compute_stats` 请求内复用

`services/stats.py` 目前每次 `compute_stats` 都重跑 `aggregate_equipment`（O(装备)）且无缓存。

- `/game/state`：`state.py:71` 已算一次 breakdown；把**同一份 `HeroStats`** 透传给 `region_access`（`services/qualification.py:27`）与 `chest_rarity_luck`（`services/drop_luck.py:67`），去掉 2 次重复计算。
- `/battle/session/report`：`battle.py:163` 的 stats 透传给 `require_region` 与 `_settle_boss:352`，把 2–3 次降为 1 次。
- 做法：给相关函数增加**可选参数** `stats: HeroStats | None = None`（`None` 时才自行计算），调用点传入已算好的对象；这样既零行为变化，又不动公共路径的现有签名语义。

### B5 worldboss WS 改共享生产者

`api/v1/worldboss.py:404-439` 是三个 WS 里唯一仍「每连接各查一次库」的（2 查询 / 0.5s / 连接）。
改为 `services/broadcast.hub` 的共享生产者（channel = `worldboss`）：生产者每 0.5s 读一次
`WorldBoss` + 当前周期榜单（走已有的 `cached_contribution_rows`），投递到各订阅队列；连接侧只 drain。
每玩家的会话状态已由客户端本地模拟（`docs/multiplayer-load-bandwidth-design.md`），WS 只需推**全局**状态。

### B6 `/game/config` 结果进程内缓存

`api/v1/game.py:27` 每次请求都重新拼一个含 935 底材 + 全部配置的大 dict，再 `jsonable_encoder` + `dumps` + `sha1`。
配置是**进程生命周期内不变**的静态数据 → 首次请求时构造一次 `(body_bytes, etag)` 并缓存，之后直接返回。
`/game/state` 的 ETag 仍需每次编码（内容随玩家变化），保持现状并在文档中标注这一取舍。

### B7 `/admin/online`（实施时改为「保留语义 + 说明」）

原计划：先用 `WHERE users.last_seen_at >= :cutoff` 缩到在线候选 + 补 `users.last_seen_at` 索引。

**实际未这样做，原因（重要，勿改）**：该接口的分组结果 = 「**含至少一个在线账号的全局连通分量**」，
组内**同时包含与之关联的离线小号**——这正是管理员排查多开时要看的（`services/admin_monitor.py:157-160`
只跳过 `online_count == 0` 的组，保留组内的离线账号）。若先按在线时间预筛，这些离线账号会被丢掉，
反多开排查能力被破坏，且与 `services/devices.py` 的判定口径不一致（用户明确要求**保留禁止多开的限制**）。

另外：`users.last_seen_at` **故意不加索引**——它在每次前端心跳都会被 UPDATE，而当前没有任何 SQL 按它过滤
（在线判定在 Python 侧），加索引只会给写路径添成本。

本次仅在 `services/admin_monitor.py:71-82` 写明「为什么全表、以及不要这样优化」，
并给出正确方向：以在线账号为种子做设备/IP 的**有界扩张**（需保证传递闭包与现有并查集结果一致）。
该接口为管理员手动触发、不在热路径，延迟处理的代价可接受。

### B8（可选）`/game/state` 并发保护

加每账号 in-flight 去重或全局信号量，抑制「同一账号多标签页 / 突发刷新」造成的峰值叠加。
前端已有 `loadState` 单飞+合并，这里是服务端兜底。**本次未实现**（可选）。

### B9（可选，低优先）常驻内存微调

- `shared/schema/loader.py:22` 的 `BaseItem` 加 `slots=True`（frozen dataclass，安全）。
- `GameConfig.raw`（`loader.py:370`）长期持有全部 37 个已解析 JSON；梳理实际被 `CONFIG.raw[...]` 读取的键后裁剪（`api/v1/game.py:35` 等有引用，需逐个核对）。

---

## 5. 阶段 C：数据库清理与保留策略

### C1 修 `security_events` 的「假有界」

`services/ratelimit.py:39-43` 的 `DELETE` 条件带 `scope + key`，**只清当前 key**；被弃用的 IP 等 key 的行永久残留。
改为在保留任务里按 `occurred_at` **全局**删除超期行（保留期 = 各 scope 最大窗口的若干倍，如 **2 天**）。

### C2 新增 `services/retention.py`（挂在 `ranking-worker` 循环）——已实现

按配置周期（默认每 1 小时）执行，全部为「终态 + 超期」条件删除：

| 表 | 条件 | 默认保留 | 状态 |
|---|---|---|---|
| `security_events` | `occurred_at` 超期（**全局**，不限 scope+key） | 2 天 | ✅ 已实现 |
| `battle_sessions` | `active = false` 且 `last_report_at` 超期 | 7 天 | ✅ 已实现 |
| `activity_sessions` | `active = false` 且 `last_report_at` 超期 | 7 天 | ✅ 已实现 |
| `raid_sessions` | `active = false` 且 `started_at` 超期 | 7 天 | ✅ 已实现 |
| `treasure_runs` | `ended_reason IS NOT NULL` 且 `created_at` 超期 | 7 天 | ✅ 已实现 |
| `pvp_battles` | `created_at` 超期 | 30 天 | ✅ 已实现 |
| `audit_logs` | `created_at` 超期 | 30 天 | ✅ 已实现 |
| `coop_rooms` + 子表 | `status IN ('cleared','failed','closed')` 且超期 | 7 天 | ❌ **不做**（见下） |
| `chat_messages` 公告 | 超数量上限 | 最多 200 条 | ❌ **不做**（见下） |

**为什么不做 coop 清理**：`coop_records.battle_id` / `room_id` 以**无 `ondelete` 的外键**引用
`coop_battles` / `coop_rooms`（`models/multiplayer.py:98-99`），而 `coop_records` 是远征榜实时聚合的**真相、不可清理**。
删除房间会因外键约束失败，或迫使删掉榜单记录。要清理必须先设计归档/保留方案（例如给记录去除硬外键），属于后续项。

**为什么不做公告清理**：AGENT.md 明确公告是「不保留记录」的**例外**（长期保留、置顶），清掉会改变既有承诺。

**明确不清理**：`world_boss_contributions`、`world_boss_rewards`、`coop_records`、`coin_transfers`、`rankings`。
`user_devices` **不清理**——它承载反多开「同一设备多账号」判定（见 `services/devices.py`），
按用户要求「保留禁止多开的限制」，本次明确排除在保留策略之外并加了测试断言。

**关于 C1 的实现位置**：`services/ratelimit.py` 的 `DELETE` 仍只删当前 `scope + key`
——它在**每个限流请求**的热路径上，必须走 `(scope,key)` 索引；改成全局扫描会把成本压到热路径。
沉寂 key 的全表清扫改由保留任务承担（`retention_ratelimit_days=2`，大于所有限流窗口，其中最长是按天的注册限流 = 1 天）。

### C3 VACUUM

清理后按需对高 churn 小表执行 `VACUUM (ANALYZE)`（低频，可配开关），避免死元组与索引膨胀。

---

## 6. 配置项与开关清单

| 配置 | 默认 | 位置 | 说明 | 状态 |
|---|---|---|---|---|
| `uvicorn_workers` | `1` | compose / `.env.example` | 由 2 降为 1 | ✅ |
| `DB_POOL_PROFILE` | `api` | `config.py`；compose 给三个 worker 服务传 `worker` | 连接池分档 | ✅ |
| `db_pool_size` / `db_max_overflow` / `db_pool_timeout` | `5` / `5` / `15` | `config.py` | worker 档为 `2`/`0` | ✅ |
| `ranking_in_api` | **`false`**（原 `true`） | `config.py` | 刷新移出 API 进程 | ✅ |
| `worldboss_loop_in_api` | **`false`** | `config.py` | 专用 worker 已承担，去掉 API 内冗余轮询 | ✅ |
| `ranking_refresh_seconds` | `600` | `config.py` | 原硬编码 300 | ✅ |
| `ranking_live_cache_seconds`（实时榜 TTL） | `10.0` | `config.py` | B3；`<= 0` 关闭缓存 | ✅ |
| `retention_enabled` | `true` | `config.py` | C2 总开关 | ✅ |
| `retention_interval_seconds` | `3600` | `config.py` | C2 周期 | ✅ |
| `retention_sessions_days` / `retention_coop_days` / `retention_pvp_days` / `retention_audit_days` / `retention_ratelimit_days` | `7` / `7` / `30` / `30` / `2` | `config.py` | 保留期（`coop` 项当前未使用，见 §5） | ✅ |
| `retention_vacuum` | `true` | `config.py` | 清理后 `VACUUM (ANALYZE)`（仅 PG） | ✅ |
| `auto_create_tables` | **`false`**（原 `true`） | `config.py` | 生产 foot-gun；本地由 `.env.local` 置 true | ✅ |
| `uvicorn_access_log` | `false`（`UVICORN_ACCESS_LOG=1` 打开） | compose / entrypoint | A1 | ✅ |
| `config_response_cache_enabled` | — | — | **未做开关**：`/game/config` 缓存常开（配置进程内不变，无副作用） | 偏差 |

同步更新 `.env.example`、`.env.local.example`、`docker-compose.yml`。

**注**：`DB_POOL_PROFILE` 的 `worker` 分档通过 compose 的
`entrypoint: ["env", "DB_POOL_PROFILE=worker", "python", "-m", ...]` 实现（避免 YAML 合并键的兼容性问题）。

---

## 7. 验收与压测

- **后端回归**：`cd backend && .venv/bin/python -m pytest tests/ -q`，重点 `test_api.py`、`test_balance.py`、`test_shared_data.py`、`test_multiplayer*.py`、`test_world_boss.py`、`test_admin_monitor.py`。
- **等价性断言（本方案的硬性要求）**：
  - B2：同一账号在「全量装备」与「只加载已装备」两种数据源下，`compute_stats` / `hero_power` / 榜单值**完全相等**（新增测试）。
  - B4：透传 stats 与自行计算的路径结果**完全相等**。
  - B3：缓存命中与未命中返回**同一份数据**（含 `me`）。
- **前端**：`npm test`、`npm run typecheck`、`npm run build`（B3 若动 `/ranking` 响应形状需同步检查）。
- **资源实测**（目标机或等价环境）：
  - `docker stats` 记录各服务 RSS，改造前后对比；
  - 生成 N 个账号 × 若干装备的数据，跑一次刷新，对比**峰值 RSS 与耗时**（B2 的主要收益证据）；
  - 并发打 `/game/state`，对比峰值 RSS；
  - `SELECT count(*) FROM pg_stat_activity` 确认 < `max_connections`；
  - `SHOW shared_buffers / effective_cache_size / max_connections` 确认 A4 生效。
- **清理任务**：单测覆盖「超期删 / 未超期留 / **不可清表不被删**」三类断言。

### 7.1 本次实际执行结果

| 项 | 结果 |
|---|---|
| 后端 `pytest tests/ -q` | **742 passed / 1 skipped**（1 skipped 为需真实 PostgreSQL 的 `test_multiplayer_postgres.py`） |
| 前端 `npm test` / `npm run typecheck` | **303 passed** / 通过 |
| B2 等价性 | `tests/test_ranking_refresh.py`：只加载已装备装备的结果 == 全量口径；批大小 1 与 500 结果一致 |
| B3 缓存 | `tests/test_ranking_live_cache.py`：同一请求两次调用只聚合一次；TTL 内复用；失效后重算；TTL=0 时完全绕过 |
| B4 复用 | 由既有 `test_api.py` / `test_balance.py` / `test_world_boss.py` 全量回归覆盖（面板 / 榜单 / BOSS 结算数值不变） |
| B5 共享生产者 | `tests/test_world_boss_ws.py`：首次快照、无变化不推送、血量变化推送、榜单按周期带行、`me` 就地拼装与 `leaderboard_view` 一致 |
| B6 config 缓存 | `tests/test_http_cache.py`：三次请求只构造一次响应，ETag/304 仍正确 |
| C 保留清理 | `tests/test_retention.py`：终态超期删、进行中与近期留、**世界BOSS 贡献与 user_devices 不动**、开关可关 |
| compose 语法 | 本机无 docker，改用 YAML 解析校验：各服务 `mem_limit` / `shm_size` / worker `entrypoint` 均符合预期 |
| Alembic | `alembic upgrade head` 在临时 SQLite 上从头跑到 head 无误（本次未新增迁移） |

**未能在本机验证**（需目标机）：`docker stats` 前后 RSS 对比、`SHOW shared_buffers` 生效确认、
PostgreSQL 下 `VACUUM` 与真实并发连接数。这些是部署后的一次性核对项。

---

## 8. 风险与回滚

### 8.1 实施偏差与理由（对应文首「实施偏差」清单）

1. **B7 保留全表语义、不加索引**：该接口输出「含在线账号的连通分量」，组内**必须**包含关联的离线小号，
   否则破坏反多开排查（用户明确要求保留禁止多开的限制）。且 `last_seen_at` 高频写、无读索引需求。
2. **阶段 C 不清 coop**：`coop_records` 以无 `ondelete` 外键引用 `coop_battles`/`coop_rooms`，
   删除会失败或破坏远征榜真相。
3. **阶段 C 不清公告**：AGENT.md 明确公告为长期保留的例外。
4. **`ratelimit.py` 保持按 key 清理**：热路径不能做全局扫描；全局清扫交给保留任务，
   保留期（2 天）严格大于所有限流窗口（最长 1 天），因此**不会放宽任何限流**。
5. **`auto_create_tables` 默认改 false**：避免漏配时用 `create_all` 掩盖结构漂移。

### 8.2 风险表

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 连接池调小后高并发排队 | `pool_timeout=15` 快速失败 + 压测确认 | 调回原值（纯配置） |
| Postgres 参数不当（`work_mem` 过大 OOM） | 保守取 4MB + 按 `docker stats` 校准 | 移除 `command` 用默认 |
| B2 / B4 改变结算结果 | 逐位等价性测试（§7.1） | 还原为全量加载 / 多次计算 |
| 实时榜 TTL 导致「刚钓完看不到」 | TTL 10s + 写入侧 invalidate（钓鱼/采集/生产上报、专用装备穿脱、远征通关） | `RANKING_LIVE_CACHE_SECONDS=0` 关闭缓存 |
| 进程级缓存在多进程间不一致 | 缓存只存「可重算的聚合」，TTL ≤ 10s，各进程独立 | 同上关闭 |
| 清理任务误删榜单真相 | 保留期配置 + 显式「不可清」白名单 + 测试断言 | 关闭 `retention_enabled` |
| 反多开判定被削弱 | `user_devices` 明确排除在保留策略外，并有测试断言 | — |
| 单 API worker 被单请求阻塞 | B1（刷新移出）+ B6（config 不重建） | `UVICORN_WORKERS=2` |

各阶段**独立可开关**：阶段 A 纯配置；阶段 B 每项有独立开关（实时榜缓存 TTL / 刷新间隔 / WS 共享生产者）；阶段 C 有总开关与保留期。

---

## 9. 实施顺序（实际执行）

1. **阶段 A**（纯配置）
2. **B1 + B2**（消除 GB 级峰值与 API 进程尖峰）
3. **B3 + B4**（每请求重复计算）
4. **B6 + B5**（config 重建、WS 每连接轮询）
5. **阶段 C**（清理与保留）
6. **B7 降级为文档化**；**B8 / B9 未做**（可选项）

每阶段独立提交、独立验收，不一次性推翻。

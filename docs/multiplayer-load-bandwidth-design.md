# 多人对战运算下放与网络压缩设计

版本：1。项目：Vue 3 / FastAPI / PostgreSQL。本文是实现与验收契约。

背景：多人游玩时后端运算负载与带宽压力偏大。目标是（1）把适合的运算下放到客户端并保住防作弊边界，（2）压缩网络传输并精简大响应。

> **实施状态：四个阶段均已实现并回归通过。**
> - 阶段 1：`coop_worker` / `worldboss_worker` 去掉每 tick `deepcopy`，改 `flag_modified` 原地标脏。
> - 阶段 2：`backend/app/core/compression.py`（响应 brotli + 请求体 gzip 解压）、前端 `fflate` 按 1KB 阈值压缩请求体、uvicorn `--ws-per-message-deflate`（实测 101 响应含 `permessage-deflate`）。
> - 阶段 3：`backend/app/core/http_cache.py`（`/game/state` 与 `/game/config` 的 ETag / 304）。
> - 阶段 4：世界BOSS 运算下放（前端 `game/core/worldboss.ts` 复刻引擎、`POST /worldboss/report` 上报、`backend/app/services/worldboss_model.py` 夹取上限、迁移 `y2f4a6b8c0d2`）；跨语言确定性由 `frontend/src/game/core/worldbossEngine.spec.ts` 的 Python 黄金快照锁定。
> - 验证：后端 `pytest tests/ -q` 727 passed / 1 skipped；前端 `npm test` 303 passed、`npm run typecheck`、`npm run build` 均通过。

---

## 1. 目标与非目标

### 1.1 目标

1. 降低多人（远征 / 世界BOSS）持续运行的 **CPU 负载**：先消除 worker 热循环中的明显浪费，再把世界BOSS 的单玩家模拟下放客户端。
2. 降低 **带宽压力**：补齐请求体压缩、响应 brotli、WebSocket 压缩，并精简最大的一批响应。
3. 全程不放松信任边界：**服务端始终是资产与进度的权威**，客户端可算、但结果必须可校验。

### 1.2 非目标

- 不迁移 **远征（coop）** 的战斗运算：8 人共享同一份战斗状态，下放需玩家间共识/仲裁，单人作弊即可破坏整局，风险不可接受。远征只做 worker 优化与传输压缩。
- 不为普通挂机新增离线收益；下放后关闭页面同样停止（与现有一致）。
- 不重写排行榜、奖励、周期结算等服务端权威逻辑。

### 1.3 兼容与边界变更（需确认）

- **世界BOSS 的信任模型发生变更**：由「worker 服务端唯一权威模拟」改为「客户端模拟 + 服务端理论上限校验」，与地区战斗同构。这是显式决策，需同步改写 `AGENT.md:14` 与「必须保留的设计边界」章节，并在 `docs/world-boss-cycle-redesign.md` 标注。
- 其余系统边界不变：抽箱 / 掉落 / 门 / 猜大小的 RNG 仍全部服务端；金币、经验、贡献、奖励仍全部服务端结算。

---

## 2. 现状与瓶颈定位

| 事项 | 实际情况 | 位置 |
|---|---|---|
| 后端框架 | FastAPI（Python 3.11+ / Pydantic 2 / SQLAlchemy 2 async），非 Node | `backend/app/main.py` |
| 响应压缩 | **已有 gzip**（阈值 1024B） | `main.py:94` `GZipMiddleware`；`frontend/nginx.conf:19` `gzip_proxied any` |
| 请求压缩 | **没有**，请求体始终明文 | — |
| 地区战斗 | **已客户端运算**：`BattleSimulator` + 服务端理论上限夹取 | `frontend/src/game/core/battle.ts` ⟷ `backend/app/services/combat_model.py` |
| 干扰项 | 现有 `GZipMiddleware` 注释已说明「先 GZip 再加 CORS，使 CORS 最外层」 | `main.py:92` |

**持续吃 CPU 的两处（热点）**

1. 远征：`backend/app/coop_worker.py:tick_rooms`，每 100ms 处理至多 32 个房间；**每个房间每 tick 前 `deepcopy(battle.state)`**，随后整棵树被修改并回写。
2. 世界BOSS：`backend/app/worldboss_worker.py:tick_worldboss`，每 100ms 处理至多 `MAX_SESSIONS_PER_TICK = 32` 个会话；同样**每 tick `deepcopy(session.state)`**。

`sa.JSON`（`JsonType = sa.JSON().with_variant(JSONB, "postgresql")`，见 `backend/app/models/base.py:12`）**没有变更追踪**（未使用 `MutableDict`）。这正是 `deepcopy` 存在的原因：必须让 JSON 列被重新赋值才能标脏。代价是每 tick 深拷贝一整棵嵌套状态树（8 英雄 × 技能/冷却/buff/dot/事件）。

副作用：`limit(32)` / `MAX_SESSIONS_PER_TICK=32` 是隐性的**并发天花板**——在线房间/会话超过 32 后，推进只是变慢（时间被压缩进后续 tick），而不是报错，因此负载随规模持续上升而吞吐被卡住。

**带宽大头**

- WebSocket 快照：`api/v1/coop.py` 与 `api/v1/worldboss.py` 每 0.5s 推一份**全量** state JSON；WS **未启用** `permessage-deflate`。
- HTTP：`/game/state`（全量游戏状态，最大 JSON）、`/game/config`（全量静态配置）虽已 gzip，但每次动作都重新拉取。

---

## 3. 阶段 1：worker 去 `deepcopy`（零信任变更）

### 3.1 改动

`backend/app/coop_worker.py` 与 `backend/app/worldboss_worker.py`：

- 删除每 tick 的 `deepcopy(row.state)`，改为**原地修改 + 标脏**：

  ```python
  from sqlalchemy.orm.attributes import flag_modified

  state = battle.state          # 不再 deepcopy
  # ... 原有对 state 的原地修改 ...
  flag_modified(battle, "state")  # 显式标脏，等价于原来的「复制 + 重新赋值」
  ```

- 事务回滚时 `async with session_factory() as db` 作用域结束、会话对象即被丢弃，**不存在跨请求共享引用**，原地修改与复制语义等价。
- 无需复制不可变子树：`hero['snapshot']` 在战斗中本就不变，去掉深拷贝后自然不再复制。

### 3.2 附带优化（可选，按测量结果决定）

- `coop_worker` 每房间每 tick 都查成员表与封号用户表；可合并为一次批量查询。
- 去 `deepcopy` 后上调 `limit(32)` / `MAX_SESSIONS_PER_TICK`，提高单 worker 吞吐。

### 3.3 风险与回归

- 风险低：不改变任何对外语义与数值。
- 回归：`backend/tests/test_multiplayer*.py`、`test_world_boss.py`；有 PG 环境再跑 `test_multiplayer_postgres.py`（需 `DLC_TEST_DATABASE_URL` + `DLC_TEST_ALLOW_RESET=yes`）。
- 压测：多房间/多会话下对比 tick 耗时与吞吐。

---

## 4. 阶段 2：增量压缩（零协议变更）

### 4.1 响应 brotli

- 新增 `backend/app/core/compression.py`：`BrotliMiddleware`（纯 ASGI，参考 `Starlette.GZipMiddleware` 的 responder 结构），仅当 `Accept-Encoding` 含 `br`、响应无既有 `Content-Encoding`、`Content-Type` 可压缩且体积 ≥ 阈值时压缩，设 `Content-Encoding: br`。
- **中间件顺序（关键）**：brotli 必须在 **gzip 内层**，由 gzip 作无 `br` 时的兜底。`app.add_middleware` 后注册的在外层，因此注册顺序为：

  ```python
  app.add_middleware(BrotliMiddleware, ...)   # 先注册 → 内层
  app.add_middleware(GZipMiddleware, ...)     # 后注册 → 外层（br 已存在时自动跳过）
  app.add_middleware(CORSMiddleware, ...)     # 最外层，错误响应也带 CORS 头
  ```

  响应方向：`app → brotli(命中则设 br) → gzip(见 Content-Encoding 即跳过) → CORS`。
- 新依赖：`brotli`（或 `brotlicffi`）加入 `backend/pyproject.toml`。
- 新配置：`brotli_enabled` / `brotli_min_size` / `brotli_quality`，命名对齐现有 `gzip_*`。

nginx 侧：官方 `nginx:1.27-alpine` 不带 brotli 动态模块，**不强行加**。后端已对 `/api/` 反代响应按浏览器 `Accept-Encoding` 直接协商 brotli；nginx 继续用 gzip 兜底。静态资源若需 brotli，可选「构建期预压缩 + nginx `gzip_static`」，作为独立可选增强，不在本阶段范围。

### 4.2 请求体 gzip

- 新增 `RequestDecompressMiddleware`（纯 ASGI）：`Content-Encoding: gzip` 时读取 body → 解压 → 重写 `receive` 返回解压后 body，并同步调整 `content-length`。
  - **防 gzip bomb**：解压限定输出上限 `request_max_decompressed_bytes`（默认与 nginx `client_max_body_size 4m` 同量级），超限直接 413。
- 前端 `frontend/src/api/client.ts`：请求体序列化后**仅在 > 1KB 时**才 `fflate.gzipSync` 压缩并设 `Content-Encoding: gzip`；`GET` / 无 body / `FormData` / 流式 body 一律跳过。新增依赖 `fflate`（轻量、零依赖）。
- 阈值理由：小 body 压缩后体积反而变大，得不偿失。

### 4.3 WebSocket `permessage-deflate`

- uvicorn 的 `websockets` 实现支持按消息压缩；在 `backend/docker-entrypoint.sh` 的 uvicorn 启动参数中**显式开启**。
  **注意**：它是 click 的**带值选项**（`type=bool`），必须写成 `--ws-per-message-deflate true`；
  写成裸 flag（`--ws-per-message-deflate --proxy-headers`）会把后一个参数当作它的值，
  启动直接失败（`Invalid value for '--ws-per-message-deflate'`）。
- 需**实测** nginx 是否透传 `Sec-WebSocket-Extensions`（`frontend/nginx.conf` 三个 WS `location` 已带 Upgrade 头）；若不透传，用浏览器 devtools 的 WS 帧确认并补对应 proxy 头。
- 收益：coop/worldboss 的重复 JSON 快照压缩比通常 5–10×，是**多人带宽最直接的收益点**。

### 4.4 阈值策略

`gzip_min_size` 保持 1024（小响应压缩净收益为负），在文档与配置注释中说明。

---

## 5. 阶段 3：精简大响应

### 5.1 `/game/state`：ETag + 304

- 服务端（`backend/app/api/v1/game.py`）对构建出的状态做内容哈希，设置 `ETag` 与 `Cache-Control: no-cache`（可缓存但每次必须回源校验），并加 `Vary: Authorization`（个性化响应，避免缓存串号）。
- 请求带 `If-None-Match` 且内容未变 → 返回 `304`（无 body）。
- 浏览器会**透明处理** 304 并复用缓存 body，axios 侧无需改动；`loadState` 的「单飞 + 合并」策略不变，仍是一次请求。

### 5.2 `/game/config`：强缓存

- 全量静态共享配置，对所有用户一致、仅随版本变化：设置 `ETag` + `Cache-Control: public, max-age=3600`（+ `Vary` 视情况），命中 304 即零 body。

### 5.3 WS 增量快照（可选，后置）

- 世界BOSS 的 `_ws_session()` 已按 `eventSequence` 增量过滤事件，但每次仍推全量 `session_public`。若 4.3 的 deflate 后仍不足，再改为真正增量 patch；**在压缩收益评估之后再决定**，避免过度设计。

---

## 6. 阶段 4：世界BOSS 客户端模拟下放

### 6.1 为什么是世界BOSS

每个 `WorldBossSession` **本就是单玩家独立**（自有英雄快照、自有 RNG、自有 state），只有**全局血量与贡献**共享。因此可以像地区战斗一样：客户端算自己的输出，服务端只校验上限并结算共享部分。远征不具备该性质（8 人共享一份 state），故不下放。

### 6.2 客户端引擎

- 新增 `frontend/src/game/core/worldboss.ts`：移植 `backend/app/services/worldboss_engine.py` 的确定性 100ms 模拟（英雄普攻/技能/治疗/DOT/独立死亡复活、BOSS 普攻全体 + 技能按间隔随机、P1/P2/P3 阶段），数值全部读 `shared/data/worldboss.json`（**与后端同源**）。
- 由 `frontend/src/views/WorldBossView.vue` 的本地循环驱动（复用地区战斗的 rAF + 墙钟预算模式），本地渲染战斗表现。
- 本地 RNG 自由取样即可：BOSS 技能只影响**英雄存亡**，而存亡**不进收益模型**（与地区战斗一致）。

### 6.3 新接口契约

`POST /api/v1/worldboss/report`

```jsonc
{
  "reportSeq": 12,                                   // 单调递增，幂等去重
  "damage": 123456,                                  // 本次窗口总伤害增量
  "perHero": [{ "heroId": 1001, "damage": 65432 }],  // 分英雄增量，Σ == damage
  "elapsedMs": 1500                                  // 仅供参考，服务端不采信
}
```

返回：`{ hp, maxHp, phase, damageAccepted, myDamage, rejected? }`。

### 6.4 服务端校验（防作弊，逐条）

1. **窗口只认服务端时钟**：`window = clamp(now - session.last_report_at, MIN, MAX)`，忽略客户端 `elapsedMs`（复刻 `battle.py:181` 的做法，防止加速/改系统时间放大额度）。
2. **幂等**：`reportSeq ≤ session.last_report_seq` 视为重放，直接返回当前状态，不重复扣血/加贡献。
3. **上限**：`cap = Σ combat_model.theoretical_dps(英雄快照, mob_kind="boss") × (window/1000) × tolerance × levelMultiplier × (1/当前阶段 defenseMultiplier)`。
   - 阶段 `defenseMultiplier` 由**服务端**依据全局血量占比计算并施加，不采信客户端上报的阶段。
   - `tolerance` 取**偏宽松**（起步 1.15），遵循「不误伤满练度玩家，只保留客户端不可伪造的界（真实服务端时间）」。
   - 模型假设「全员全程存活」，给出上界；合法玩家实际低于该界。
4. **完整性**：`damage == ΣperHero` 且 `≤ cap`；超出 `cap × rejectFactor` 整单拒绝并写 `AuditLog`（沿用 `services/validator.py` 模式），轻微超出则按 `cap` 截断、`perHero` 等比例缩放。
5. **共享部分全部服务端**：全局血量原子递减（现有 `case(...)` 更新）、贡献累加（`services/world_boss.add_contribution`）、周期换轮、入榜门槛（累计 ≥ 500 万）、奖励结算，全部保持服务端，逻辑不迁移。
6. **限频兜底**：`/worldboss/report` 接入 `guard_rate`（当前 `/battle/session/report` 与 `/worldboss/*` 无频率限制，靠额度模型限速；新增本接口后补一道频率下限）。

### 6.5 worker 与数据

- `backend/app/worldboss_worker.py`：**退役逐会话推进**，仅保留全局换轮/短休整复活（廉价），或整体退役并由 `main.py` 的 `_worldboss_loop`（30s 兜底）承担。保留 `worldboss_engine.py` 作为服务端参考实现与测试基线。
- `WorldBossSession` 新增 `last_report_at: float`、`last_report_seq: int`（新增 Alembic 迁移），用于窗口与幂等。
- WS：改为只推**全局**（血量/阶段/周期/榜单），不再推每玩家会话状态（本地已有）。

### 6.6 镜像一致性（关键验证）

引擎在前后端各有一份，必须防漂移：

- 共用 `shared/data/worldboss.json` 作为唯一数值来源。
- 新增**跨语言确定性测试**：同种子 + 同配置下，Python 引擎与 TS 引擎跑固定 tick 数，输出逐位一致（冻结黄金快照），模式参照 `test_dohdol.py::TestWeather::test_hash_matches_frontend_snapshot`。

---

## 7. 配置项清单

| 配置 | 默认 | 位置 | 说明 |
|---|---|---|---|
| `brotli_enabled` | `true` | `backend/app/core/config.py` | 响应 brotli 开关 |
| `brotli_min_size` | `1024` | 同上 | 低于此体积不压缩 |
| `brotli_quality` | `4` | 同上 | 压缩级别（速度/体积权衡） |
| `request_decompress_enabled` | `true` | 同上 | 请求体 gzip 解压开关 |
| `request_max_decompressed_bytes` | `8388608` | 同上 | 解压上限（防 gzip bomb） |
| `worldboss_report_tolerance` | `1.15` | 同上 | 世界BOSS 伤害上限容差 |
| `worldboss_report_min_ms` / `max_ms` | 对齐 `MIN/MAX_ELAPSED_MS` | 同上 | 上报窗口钳制 |

同步更新根目录 `.env.example` 与 `docker-compose.yml` 的 `backend-environment`。

---

## 8. 验收清单

- **后端**：`cd backend && .venv/bin/python -m pytest tests/ -q`，重点 `test_multiplayer*.py`、`test_world_boss.py`、`test_gzip.py`（扩展 br）、`test_api.py`；有 PG 时跑 `test_multiplayer_postgres.py`。
- **前端**：`npm test`、`npm run typecheck`、`npm run build`。
- **压缩实测**（浏览器 devtools / Network）：
  - `/game/state` 响应头出现 `Content-Encoding: br`；不支持 br 的客户端回退 gzip。
  - 大 POST 带 `Content-Encoding: gzip`，服务端正确解压并处理。
  - coop/worldboss WS 帧被压缩（`Sec-WebSocket-Extensions` 协商成功）。
  - 超大压缩体（bomb）被 413 拒绝。
- **世界BOSS**：构造超量上报应被截断/拒绝并写审计；正常满练度上报不被误拒；重放 `reportSeq` 不重复扣血；全局血量/阶段/贡献/奖励与改造前一致。
- **镜像一致性**：跨语言确定性测试通过（同种子同配置逐位一致）。
- **压测**：阶段 1 前后对比 worker tick 耗时与吞吐；阶段 4 后 worldboss-worker 不再承载会话推进。

---

## 9. 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 去 `deepcopy` 后 JSON 列漏标脏 | 原地改 + `flag_modified`，测试覆盖回写 | 恢复 deepcopy（改动集中两个 worker） |
| brotli 中间件顺序错误导致双压缩 | 注册顺序固定为 brotli→gzip→CORS；加响应头断言测试 | 关闭 `brotli_enabled` |
| 请求体解压引入 DoS | 解压上限 + 413 | 关闭 `request_decompress_enabled` |
| 误伤满练度玩家（世界BOSS 上限过紧） | 容差偏宽松、模型取全员存活上界、超标只截断不轻易拒绝 | 上调 `worldboss_report_tolerance` |
| 前后端引擎漂移 | 共享配置 + 跨语言确定性测试 | 回退阶段 4，恢复 worker 推进 |
| 客户端作弊者持续打满上限 | 上限即「理论上限」，与地区战斗同级暴露；限频 + 审计 | 调低容差或加严频率 |

各阶段**独立可开关**：阶段 1 无开关（纯优化，可回退）；阶段 2 有 `brotli_enabled` / `request_decompress_enabled`；阶段 4 通过「是否启用客户端模拟 + 是否恢复 worker 推进」开关回退。

---

## 10. 实施顺序

1. **阶段 1** worker 去 `deepcopy`（零风险，先测量收益）
2. **阶段 2** 增量压缩（brotli 响应 → 请求 gzip → WS deflate）
3. **阶段 3** 大响应精简（ETag/304、config 强缓存）
4. **阶段 4** 世界BOSS 客户端模拟（最大改动，含迁移与边界文档同步）

每阶段独立提交、独立验收，不一次性推翻。

# 项目上下文：艾欧泽亚放置录

本文件供后续新聊天快速了解项目。更新日期：2026-09-22。功能状态以当前代码、共享配置和测试为准；修改架构、启动方式或核心规则时同步更新本文。

## 项目概况

- 仓库名 `FF14Push`，产品名「艾欧泽亚放置录 / Eorzea Idle Chronicle」。这是 FF14 同人放置类网页游戏，并非消息推送工具，与官方无关。
- 核心循环：英雄自动战斗 → 获得金币和经验 → 抽箱获取装备 → 穿戴、合成、重造、附魔 → 推进地区和副本。
- 已包含 40 个地区、21 个战斗职业、装备养成、酒馆招募、图鉴、排行榜、管理功能，以及生产/采集/钓鱼系统。
- 联机 DLC 已有实现：最多 8 名独立英雄、异步 PvP、个人/离线/在线合作、12 个团队副本；前端入口为「名册」「远征」「竞技场」。不要将设计文档中的全部内容直接当成待开发任务。
- 远征通关记录与「远征榜」已实现：`coop_worker` 在通关瞬间把时长与全席位分角色战斗信息写入 `coop_records`（每个真实参战账号一行）；排行榜页「远征榜」按副本实时聚合（不走 5 分钟缓存），展示最快通关时长与阵容。
- 好友系统已实现：账号有唯一「好友码」（`users.friend_code`，注册 / 迁移生成），凭码申请 + 对方同意后成为好友；好友列表展示在线状态（`users.last_seen_at` + 前端心跳，45s 内视为在线）。好友间可金币转账，手续费 `economy.json:transfer.feePct`（默认 10%）从转账额扣除后销毁，另有单笔上下限与每日累计上限（见 `services/friends.py`）。
- 界面及项目文档主要使用中文，新增内容保持已有命名和文案风格。

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
- 普通挂机不提供离线收益。联机「离线合作/克隆体」是独立机制，不等于为普通挂机新增离线回补；团队战斗由 worker 推进，worker 中断也不补算离线时间。
- 装备归属账号，英雄穿戴状态与账号背包需要保持一致；切换、解雇及多英雄操作应检查 `roster.py`、相关模型与事务逻辑，避免装备或资产重复。
- 好友金币转账同为服务端权威：`services/friends.py` 按 id 升序双行锁两方账号，校验好友关系 / 余额 / 单笔上下限 / 每日累计额度后再结算，手续费按 `floor(amount × feePct)` 销毁（净额不为 0 增长来源），流水写入 `coin_transfers`。
- 怪物、精英不直接掉落装备；主要通过抽箱获取，另有 BOSS 宝箱奖励。
- 数值优先修改共享 JSON，避免前后端各自硬编码。`combat.json`、`monsters.json`、`balance.json`、`multiplayer.json` 分别承载相关战斗、怪物、战力与联机配置。
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

- 当前 `docker-compose.yml` 有四个服务：`db`、`backend`、`coop-worker`、`frontend`。worker 使用后端镜像但独立运行，缺少它时团队战斗不会正常推进。
- PostgreSQL 使用 Alembic：在正确数据库环境下，从 `backend` 执行 `.venv/bin/alembic upgrade head`。生产容器入口会先执行迁移，再启动 API；`AUTO_CREATE_TABLES=false`。
- `AUTO_CREATE_TABLES=true` 只能确保表存在，不能替代已有表的结构迁移。
- 对于联机 DLC 之前由 `create_all` 建立的本地 SQLite，已有专用 `backend/app/migrate_local.py`：停止 API/worker，在 `backend` 目录、正确 `DATABASE_URL` 下运行 `.venv/bin/python -m app.migrate_local`。它会创建 `.before-dlc` 备份；不要把该脚本当成所有未来升级的通用迁移器。
- 部署使用 `docker compose up -d --build`，完整配置和备份操作见 README。数据库持久化目录默认为 `data/postgres`。
- 不将实际 `.env`、`.env.local`、数据库、备份、日志或密钥写入代码和文档；说明配置时使用模板和占位值。

## 后续任务的工作方式

先检查工作区现有改动，按任务定位对应页面、store、API、服务与共享配置，再实施修改。保留已有用户改动和数据库数据；避免为修复问题直接重置数据。功能、接口、数值或运行方式发生变化时同步维护相关文档；本文只记录长期有效的项目上下文，不记录未经验证的完成状态。

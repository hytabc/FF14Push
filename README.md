# 艾欧泽亚放置录（Eorzea Idle Chronicle）

挂机/放置类网页游戏。英雄在后台自动打怪，用掉落金币开箱抽取装备，装备带随机属性与 Buff/Debuff，
通过穿戴、合成、重造、附魔不断变强，逐关推进 40 个地区关卡。

需求来源：本仓库根目录的 [`prd.md`](./prd.md)（全量实现）。
实施计划：`~/.commandcode/plans/ff14-idle-chronicle-plan.md`。

> 本项目为同人练习项目，与《最终幻想 XIV》官方无关。

---

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3 + Vite 6 + TypeScript + Pinia + Vue Router + Tailwind CSS 4 |
| 后端 | Python 3.11+ / FastAPI + SQLAlchemy 2.0 (async) + Alembic |
| 数据库 | 本地开发 SQLite；服务器部署 PostgreSQL 16 |
| 部署 | 本地一键脚本 `scripts/dev.sh`；服务器 `docker compose`（nginx + API + PG） |
| 共享层 | `shared/` 单一事实来源：配置 JSON + 双端加载器 |

---

## 目录结构

```
FF14Push/
├── prd.md                      需求文档
├── docker-compose.yml          服务器部署编排（db + backend + frontend）
├── .env.example                部署环境变量模板
├── .env.local.example          本地开发环境变量模板
├── .npmrc                      npm 国内镜像源（npmmirror）
├── scripts/dev.sh              ★ 本地一键启动脚本（无需 Docker）
├── shared/                     ★ 前后端共享配置层（唯一事实来源）
│   ├── data/*.json           品阶/栏位/职业/底材/词条/怪物/BOSS/地区/副本/箱子/合成/经济/资质/指引
│   └── schema/
│       ├── index.ts          TS 类型 + 底材展开 + 命名导出
│       └── loader.py         Python 加载器（与 index.ts 同源）
├── backend/                  FastAPI 服务
│   ├── Dockerfile              后端镜像
│   ├── docker-entrypoint.sh    等库 → 迁移 → 启动
│   ├── alembic/                数据库迁移
│   ├── app/
│   │   ├── api/v1/             路由：auth / game / battle / inventory / chest /
│   │   │                       economy / region / tavern / codex / ranking / tutorial / settings
│   │   ├── core/               配置、DB、JWT、依赖
│   │   ├── models/             ORM 模型
│   │   ├── services/           数值引擎、掉落、战斗模型、校验、图鉴、排行…
│   │   └── main.py             应用入口（建表开关 + 排行榜定时刷新）
│   └── tests/                  94 项 pytest（共享数据一致性 / 数值引擎 / 接口集成）
└── frontend/                   Vue3 前端
    ├── Dockerfile              前端镜像（构建 → nginx）
    ├── nginx.conf              静态站点 + /api 反向代理
    └── src/
        ├── api/                axios 封装
        ├── stores/             Pinia：auth / game / toast / itemActions
        ├── game/core/          战斗模拟、伤害、怪物属性、类型定义
        ├── components/         通用组件（物品卡、弹窗、指引、日志）
        └── views/              13 个页面
```

---

## 国内网络环境（依赖源）

默认全部走国内镜像，开箱即用于国内服务器：

| 用途 | 默认源 | 覆盖变量 |
| --- | --- | --- |
| Docker 基础镜像 | `docker.m.daocloud.io/library/` | `DOCKER_IMAGE_MIRROR`（`.env`） |
| pip（后端依赖） | `pypi.tuna.tsinghua.edu.cn` | `PIP_INDEX_URL`（`.env` / `.env.local`） |
| npm（前端依赖） | `registry.npmmirror.com` | `NPM_REGISTRY`（`.env` / `.env.local`）或根目录 `.npmrc` |
| Debian apt（镜像内装 curl） | `mirrors.tuna.tsinghua.edu.cn` | `APT_MIRROR`（`.env`） |

- **Docker 部署**：`docker compose up -d --build` 会用上述源拉基础镜像并安装依赖。
  把对应变量在 `.env` 中设为**空值**即回退官方源——例如服务器已在
  `/etc/docker/daemon.json` 配好 `registry-mirrors` 时，留 `DOCKER_IMAGE_MIRROR=` 空着即可，
  镜像名会回到 `postgres:16-alpine` 这种官方写法。
- **本地开发**：`./scripts/dev.sh` 安装依赖时默认走清华 pip 与 npmmirror；
  直接 `npm install` 则由仓库根目录的 `.npmrc` 生效。
- 绕过 compose 直接 `docker build` 时，用 `--build-arg` 传同名参数
  （`PYTHON_IMAGE` / `NODE_IMAGE` / `NGINX_IMAGE` / `PIP_INDEX_URL` / `NPM_REGISTRY` / `APT_MIRROR`）。

---

## 本地开发（无 Docker）

```bash
./scripts/dev.sh
```

首次运行会自动：生成 `.env.local` → 创建 Python 虚拟环境 → 安装前后端依赖 →
用 **SQLite** 启动后端（自动建表）→ 启动 Vite 前端，并打印访问地址。
按 `Ctrl-C` 一次性停掉全部服务（含 uvicorn 的 reload 子进程）。

```
游戏入口    http://localhost:5173
接口文档    http://127.0.0.1:8000/docs
```

其他用法：

```bash
./scripts/dev.sh --reset     # 先清空本地 SQLite 数据库再启动
./scripts/dev.sh backend     # 只启动后端
./scripts/dev.sh frontend    # 只启动前端
./scripts/dev.sh test        # 后端 pytest + 前端 vitest + 类型检查
./scripts/dev.sh help        # 帮助
```

### 端口配置

端口、数据库、密钥全部来自仓库根目录的 `.env.local`（模板见 `.env.local.example`）：

```ini
BACKEND_PORT=8000
FRONTEND_PORT=5173
DATABASE_URL=sqlite+aiosqlite:///./dev.db
JWT_SECRET=dev-only-secret-change-me-0123456789abcdef
```

改完直接重跑脚本即可。脚本会自动把 `CORS_ORIGINS` 同步成前端实际地址，
并把 `VITE_API_BASE` 注入给 Vite，因此换端口不需要改任何代码。

> 本机若已装 PostgreSQL，把 `DATABASE_URL` 改成
> `postgresql+asyncpg://用户:密码@localhost:5432/库名`，并在 `backend` 目录执行
> `.venv/bin/alembic upgrade head` 即可，脚本其余流程不变。

日志写在 `.dev-logs/backend.log` 与 `.dev-logs/frontend.log`。

---

## 服务器部署（Docker Compose）

```bash
cp .env.example .env          # 修改端口、数据库密码、JWT 密钥
docker compose up -d --build
docker compose logs -f backend
```

访问 `http://<服务器地址>:${FRONTEND_PORT}`（默认 8080）。

编排包含三个服务：

| 服务 | 说明 | 端口 |
| --- | --- | --- |
| `frontend` | nginx 托管前端静态资源，并把 `/api` 反代到后端（同源，无需 CORS） | `${FRONTEND_PORT}` → 80 |
| `backend` | FastAPI，入口脚本会等数据库就绪 → `alembic upgrade head` → 启动 uvicorn | `127.0.0.1:${BACKEND_PORT}` → 8000 |
| `db` | PostgreSQL 16，数据持久化在 `${POSTGRES_DATA_DIR}`（默认 `./data/postgres`，bind mount 到本机） | `127.0.0.1:${POSTGRES_PORT}` → 5432 |

### 端口与变量（`.env`）

```ini
# 对外端口
FRONTEND_PORT=8080     # 唯一需要公网开放的端口
BACKEND_PORT=8000      # 默认只绑定 127.0.0.1
POSTGRES_PORT=5432     # 默认只绑定 127.0.0.1

# 数据库
POSTGRES_USER=eorzea
POSTGRES_PASSWORD=请务必修改
POSTGRES_DB=eorzea

# 数据库文件在本机的存放目录（bind mount）
POSTGRES_DATA_DIR=./data/postgres

# 应用
JWT_SECRET=请替换为随机值（openssl rand -hex 32）
CORS_ORIGINS=http://localhost:8080

# 兑换码（留空关闭该功能；每个账号对同一码只能兑换一次）
REDEEM_CODE=
REDEEM_GOLD=0

# 管理员（留空 ADMIN_PASSWORD 即不启用；管理员不参与排行榜）
ADMIN_USERNAME=admin
ADMIN_PASSWORD=
```

`db` 与 `backend` 默认只监听 `127.0.0.1`，不对外暴露。
若要让后端 API 直接对外（例如前后端分离部署），把 `docker-compose.yml` 中
backend 的 `127.0.0.1:` 前缀去掉，并把 `CORS_ORIGINS` 设为前端实际域名。

前端镜像构建时通过 `VITE_API_BASE=/api/v1` 走同源请求；
若改为独立域名部署，用
`docker compose build --build-arg VITE_API_BASE=https://api.example.com/api/v1 frontend` 重新构建。

### 常用运维命令

```bash
docker compose ps                                    # 服务状态
docker compose logs -f backend                       # 后端日志
docker compose exec backend alembic upgrade head     # 手动迁移
docker compose exec db psql -U eorzea -d eorzea      # 进数据库
docker compose down                                  # 停止（保留数据）
docker compose up -d --build                         # 更新实例（数据保留）
```

### 数据目录与备份

数据库文件通过 bind mount 落在本机目录 `${POSTGRES_DATA_DIR}`（默认仓库内 `./data/postgres`），
不在容器里，因此**重新构建 / 重建容器不会丢数据**：

- 备份：直接复制该目录即可，例如 `tar czf pgdata-$(date +%F).tar.gz -C data postgres`；
- 恢复：`docker compose down` 后用备份替换 `./data/postgres` 再 `docker compose up -d`；
- 迁移服务器：把该目录一起拷到新机器上的相同相对路径即可；
- 换路径：改 `.env` 里的 `POSTGRES_DATA_DIR` 后 `docker compose up -d`（建议先把旧目录内容搬过去）。

> 注意：该目录已在 `.gitignore` 中排除，不要提交到仓库。
> Linux 上若 `db` 容器启动报数据目录权限错误，执行 `sudo chown -R 999:999 ./data/postgres` 后重启。

---

## 手动启动（不使用脚本）

```bash
# 后端
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
cp .env.example .env
.venv/bin/alembic upgrade head          # 或设 AUTO_CREATE_TABLES=true 自动建表
.venv/bin/uvicorn app.main:app --reload --port 8000

# 前端
cd frontend && npm install && npm run dev
```

前端通过 `VITE_API_BASE`（默认 `http://localhost:8000/api/v1`）访问后端。

---

## 核心设计

### 权威边界

- 客户端逐帧模拟战斗并渲染（伤害浮动、技能 CD、日志），技能 CD 以 0.1s 节拍刷新展示。
- 有事件时才批量上报：`{regionId, elapsedMs, kills[], skillCasts[], bossKilled, died}`，
  `elapsedMs` 为距上次成功上报的真实间隔。
- **服务端是唯一权威**：金币/经验上限校验、图鉴解锁、进度推进全部在服务端完成。
  **装备只能通过抽箱获取**（BOSS 宝箱奖励除外），怪物与精英不掉落装备。
  客户端上报的击杀数与金币会被截断或拒绝（写 `audit_logs`）。
- 击杀额度按「理论击杀速率 × 时间」累积，时间窗口取「服务端真实间隔」与「客户端上报值」的较大者，
  跨上报保留余额，短上报与空闲窗口不会误杀合法击杀。

### 不做离线收益

按需求确认，离开页面即暂停战斗，服务端不存在离线回补逻辑。

### 装备归属账号

装备挂在账号而非英雄上：解雇/替换英雄时装备自动卸下并保留在背包（PRD 招募 2.4）。

### 数值锚定

PRD 中怪物与英雄的成长曲线若直接采用会导致数值发散（BOSS 战长达数分钟）。
本项目改为**以「期望英雄」曲线为锚**推导怪物属性。期望英雄 = 等级匹配地区 + 已装备等级对应底材武器 + 5 技能职业：

```
monsterHp = refAttack(level) × refGearAttackMultiplier × (refPotencyPerSecond / 100) × refDamageMultiplier × targetKillSeconds
```

系数全部集中在 `shared/data/monsters.json:reference`，改一处前后端同时生效。实测节奏：

| 场景 | 单怪 | BOSS |
| --- | --- | --- |
| 起始英雄（Lv1 + 铁制长剑）打地区 1 | 6.3s | 25s |
| 期望英雄（等级匹配稀有武器） | 2.5-3.4s | 18-25s |
| 神话毕业装 | 1.6-2.2s | — |
| 裸英雄（无武器） | 10-14s | 75-112s |

小怪阶段总时长约 30-90 秒（8-36 只）；英雄装备不足时会被击杀，从而触发「阵亡重置」机制。

> 早期版本只按「裸普攻」标定参考曲线，玩家只要转职 + 穿装，DPS 就是锚定的 4-8 倍，导致秒杀一切（0.7 秒/只）。现改为按期望英雄锚定。

### 等级压制

英雄等级低于地区 `levelMin` 时按落后级数施加软惩罚（`shared/data/regions.json:levelPenalty`），
保证玩家只能战胜对应等级的怪物：

| 落后级数 | 命中 | 输出 | 受伤 | 单怪耗时 |
| --- | --- | --- | --- | --- |
| 0 | −0% | −0% | +0% | 3.1s |
| 10 | −35% | −50% | +50% | 10.8s |
| 15 | −52% | −75% | +75% | 37.9s |
| 20 | −70% | −85% | +100% | 112.7s |

惩罚同时接入客户端模拟与服务端击杀额度校验（`combat_model.max_kills_in_seconds`），
越级既打不动、也上报不了等级匹配才有的击杀速率。

---

## 已实现系统

| 系统 | 说明 |
| --- | --- |
| 装备品阶 | 6 品阶（白/绿/蓝/紫/橙/红），倍率、词条数量、Debuff 概率、箱内概率 |
| 装备栏位 | 11 格（主手 + 5 防具 + 项链/耳环/手镯/戒指 I/戒指 II），初始全部解锁 |
| 装备属性 | 底材固定属性 × 品阶倍率 × ±20% 浮动；副属性 1-3 条；0-4 个 Buff/Debuff |
| 三属性系统 | 暴击（二次收益）/ 直击（固定 125%）/ 信念（恒定乘算），含等级缩放分段 |
| 主属性 | 力量 / 敏捷 / 智力，非主属性收益 50%，职业匹配加成 |
| 战斗 | 自动释放技能、GCD 1.5s、MP 消耗与回复、技能优先级 |
| 职业 | 21 个战斗职业，每职业 5 个技能（含 60-120s 大招） |
| 地区关卡 | 40 个地区、6 个篇章；小怪计数 → BOSS → 解锁下一地区；阵亡重置 |
| 等级压制 | 英雄等级低于地区下限时按落后级数扣命中/扣输出/增受伤，越级几乎必败（前后端同源） |
| 抽箱 | 6 种箱子、单抽/十连、品阶概率、10/50/200 抽保底 |
| 合成 | 16 件同品阶同类 → 高 1 阶，含一键合成与预览 |
| 出售 | 底价 × 品阶系数 × 属性系数（饱和封顶）× 词条价值 × ±10%，支持批量与自动出售 |
| 重造 | 重掷基础属性与副属性，保留品阶/类型/词条；**消耗随重造次数递增**（不封顶，防无限重造） |
| 附魔 | 重掷全部词条，稀有 1.0% / 太古 0.1%，支持自动追梦；**副属性与 Buff/Debuff 都有品质**，太古以 🌟 标记 |
| 副本 | 6 个副本「高难副本」页，分两档且**都按等级开放**：**普通高难**（`极·*`，Lv20/40/60/80）；**高难度高难**（`绝·*`，均满级 Lv100）。门槛 = 穿满 + **全部神话** + 每件**太古词条**（极* 2、绝* 2-3）+ **requiredPower 战力高线**（10k/25k/45k/80k/120k，Lv100 需 12w）。无小怪、属性按英雄等级锚定后放大、BOSS 自带抗性；**BOSS 还会按玩家战力相对本等级的参考值缩放**（超模装备不再碾压）。双 BOSS 可切换目标，一方阵亡后另一方狂暴（逼同步击杀）。首通重奖、重刷少量金币 |
| 副本压力 | BOSS 的攻击力与倍率经**真实模拟器（BattleSimulator）标定**：达标装（达到该等级 `requiredPower` 的装备）通关后约剩 40%-60% 生命；战力不达标的玩家在入口被高线拦下 |
| 副本技能 | 「高难副本」页每个 BOSS 都带**共享技能池（13 个技能）**：客户端为每个 BOSS 维护**一个共享 CD（6s）**，到点后**随机抽一个**释放（高威力伤害 / 持续伤害 / 增伤 / 减伤 / 减速），不再各技能独立 CD。地区战斗不受影响 |
| 英雄招募 | 酒馆刷新与金币招募，资质 6 阶，三维按偏向分配 |
| 图鉴 | 装备（按底材 × 品阶）、怪物、词条（普通/稀有/太古三档） |
| 排行榜 | 等级榜 / 关卡榜（必做）+ 战力榜 / 金币榜，每 5 分钟服务端刷新；昵称后以 0.6 透明度显示 `#登录账号`（如 `ABCD#zhangsan`）便于区分重名（昵称可重复，账号唯一） |
| 新手指引 | 15 步强制引导，可跳过（无奖励）与设置内重播（奖励只发一次） |
| 兑换码 | 码与奖励金币由 `REDEEM_CODE` / `REDEEM_GOLD` 配置，每个账号对同一码只能兑换一次 |
| 账号 | 账号密码注册登录 + JWT |
| 管理员 | 账号名与密码由 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 配置（启动时创建/同步，改密重启生效）；**不参与排行榜**；登录后可在「管理」页搜索用户并重置其密码（协助玩家找回密码） |

---

## 装备像素图标

180 件装备底材各有 1 张 16×16 像素 PNG（`frontend/src/assets/icons/<baseId>.png`），
由 `scripts/gen-icons.mjs` 生成。不手写 180 份网格，而是组合
**30 个部位底形 × 6 个档位装饰戳 × 6 套材质调色板**：

```bash
npm run gen:icons
```

- 主体配色 = 材质档位色（铁制 → 星辉）；同档位不同部位靠底形区分，同部位不同档位靠装饰戳 + 材质色区分。
- **6 个品阶色不烘焙进图片**，由 `ItemIcon.vue` 用 CSS 描边/光晕施加，所以 180 张图就能覆盖全部底材与品阶组合。
- 单张约 130 字节、180 张合计约 24 KB，低于 Vite 默认 `assetsInlineLimit`，构建时全部内联为 data URI ⇒ **渲染装备时零图片请求**。图鉴页 180 条用 `variant="lite"`（单侧光晕）进一步压低滤镜开销。
- 想改某件装备的造型，只改 `gen-icons.mjs` 里的 `SHAPES` / `ORNAMENTS` / `TIER_PALETTES` 字符画再重跑即可。
- 生成器与 `shared/schema` 的 `expandBaseItems()` 是两份 id 规则实现，由 `frontend/src/utils/icons.spec.ts` 一致性测试锁住。

---

## 与 PRD 的差异说明

| 项 | 说明 |
| --- | --- |
| 装备栏位 | PRD 文字写「10 格」但列举为 11 格，按确认实现为 **11 格**（含双戒指） |
| 栏位解锁 | PRD 2.10.3 的「栏位解锁消耗」取消，初始 **全部解锁** |
| 离线收益 | PRD 2.7.4 作废，**不做离线结算** |
| 装备获取 | PRD 2.7.2 的「怪物概率掉落装备」取消，装备**仅通过抽箱获取**（BOSS 宝箱奖励保留） |
| BOSS 属性倍率 | PRD 4.2 写 HP 为小怪 50-80 倍，与 8.5「BOSS 战 10-30 秒」矛盾；改取可玩倍率 |
| 暴击率来源 | 三属性系统已合并「暴击率/暴击伤害」，敏捷不再提供暴击率 |
| 技能完整表 | PRD 仅给出 5 个职业示例，其余 16 个职业按同格式补全，数值为占位待平衡 |
| 怪物数值 | 改为锚定式推导，见上文「数值锚定」 |
| 起始武器 | PRD 2.5.1 写「初始英雄为冒险者、仅普攻」；因怪物强度按期望英雄锚定，裸英雄会卡死在新手阶段（地区 1 单怪 13.8s，存活期内打不满 8 杀），故开局自动装备一把**铁制长剑**（骑士），见 `heroes.json:initialHero.starterWeapon` |
| 等级压制 | PRD 地区 7.3 只写了「效率极低」；本项目落为可量化的命中/输出/受伤三项软惩罚，见上文「等级压制」 |
| 出售价格 | PRD 出售 3.2 的「×(1 + 属性评分/100)」随等级线性无上限增长，而箱子价格是固定值 → 高等级「买箱卖装备」稳赚。改为**饱和封顶**的属性系数（1 → 1+`attrBonusMax`），并重定品阶系数，使各箱期望卖价仅约为箱价的 20%-60%，只有抽到高品阶（约 5% 概率）才有赚头。见 `shared/data/economy.json:sell`、`rarities.json:sellCoef` |
| 招募资质系数 | PRD 招募 2.3 的资质系数为 1/2/5/15/50/200，神话资质在英雄 30 级时需 86 万金币，实际不可达；改为 **1/2/3/6/12/30**（`baseRecruitCost` 仍为 1000），神话资质 30 级降到 12 万。见 `shared/data/talents.json:talents.*.recruitCoef` |
| 重造 / 附魔消耗 | PRD 重造 4.2 / 附魔 5.2 最高档为 60 万 / 300 万金币，远超实际收入；下调为**最高 3 万 / 5 万**，品阶递增且附魔始终比重造贵。见 `shared/data/rarities.json` 的 `refineCost` / `enchantCost` |
| 重造递增 | PRD 未定义；本项目新增「每次重造在基准价上叠加 25%（不封顶）」，防止同一件装备无限重造刷属性。见 `shared/data/economy.json:refine.costGrowthPerRefine` |
| 高难副本 | PRD 无此系统，为新增内容。副本无小怪、只有 BOSS；属性以**英雄等级**锚定（与地区一致），倍率与抗性见 `shared/data/raids.json`。门槛 = 等级 + 全神话 + 太古/件 + **requiredPower 战力高线**（Lv100 = 12w，见「副本」行）。**两档都按 `requiredLevel` 开放**。奖励首通重奖、重刷仅少量金币，避免成为金币放大器 |
| 副属性品质 | PRD 只给 Buff/Debuff 定义了稀有/太古（附魔 5.3）；本项目把同一套品质规则延伸到**副属性**：普通在区间内随机，稀有取上限，太古取上限 ×1.25（如暴击 100-400 → 太古 500），以 🌟 标记 |
| 经验词条 | PRD 的金币 Buff（地区 5.3）只有金币类；本项目新增「经验获取效率」`expGainPct`（3%-18%，项链/耳环/手镯），由**服务端结算时**乘算，客户端只上报基础经验，避免客户端篡改经验 |
| 副本攻击标定 | 副本 BOSS 的 `hpMultiplier` / `attackMultiplier` 与双 BOSS 狂暴减伤不靠手算：用真实客户端模拟器（`BattleSimulator`）扫描，「达标装通关后剩余生命 ≈ 40%-60%」定档，技能池（6s 共享 CD）计入承伤。见 `shared/data/raids.json`；回归保护见 `tests/test_engine.py:TestRaidPressure` |
| 副本门槛高线 | PRD 无副本系统。本项目 `requiredPower` **不按「刚好够门槛的装备」推算，而是按当前玩家数据人工设定**：Lv80 需 8w、Lv100 需 12w，确保「达到该等级」不等于「能通关」。门槛装/满配装战力参考见 `scripts/derive-raid-power.py` |
| 副本 BOSS 技能 | PRD 只给关底 BOSS 定义了 1 个特殊技能。本项目给「高难副本」页**每个 BOSS** 配 13 个共享技能，并改为**单一共享 CD + 随机抽取**（原为每技能独立 CD），显著提高副本压力；地区战斗仍不触发 BOSS 技能。见 `shared/data/raids.json:bossSkillPool`、`frontend/src/game/core/battle.ts` |
| 越级惩罚 | PRD 地区 7.3 只说「效率极低」；本项目把软惩罚做成接近硬约束：每落后 1 级 **命中 −4% / 输出 −8% / 受伤 +25% / 防御 −12%**（上限 80 / 95 / +1200% / −100%）。落后 **10+ 级几乎必败、20+ 级即使满配也几乎必败**。关键修正：受伤加成改为**减防之后乘算**，并让**防御随落后级数衰减**——否则高防御会把惩罚完全吃掉（实测落后 10 级仍能磨过去）。见 `shared/data/regions.json:levelPenalty` |
| 蓝量经济 | PRD 7.2 只写「智力影响上限与回复」。原公式下 Lv100 英雄有约 **1.1 万蓝、32/s 回复**，而一轮技能合计仅约 500 蓝 → 蓝永远用不完。改为 `maxMp ≈ 40 + 智力×0.7 + 等级成长`（Lv100 约 **600**）、`mpRegen ≈ 0.5 + 智力×0.008`（约 **3.6/s**）：**满蓝约等于一整轮技能消耗，持续施放约 30-60s 见底**，之后回落到零耗蓝普攻；黑魔的「冰封回蓝 / 核爆耗蓝」随之成立。见 `shared/data/heroes.json:attributes` |
| 治疗数值 | PRD 五.4 要求「治疗自愈能力高出 DPS 职业 50-80%」，但原治疗量（治疗 15%、医济 25%+3%×5s、天赐祝福满血、护盾 20%）配合 15s CD 可持续续命。统一**数值砍半 + CD 延长**：治疗 8%/20s、医济 12%+1.5%×5s/40s、天赐祝福由满血改为 50%/180s、护盾 10-12%/40s。见 `shared/data/jobs.json` |
| 职业技能属性 | 力量/敏捷职业的部分技能被写成「魔法伤害」，而它们的 `magicAttack` 只有物理攻击的一半左右 → 实测副本 DPS 差 **5 倍**（骑士 30s vs 龙骑 6s）。改为**所有非智力职业的技能一律物理伤害**，并把威力/秒收敛到离群职业（黑魔 90→69、龙骑 76→72）。见 `shared/data/jobs.json` |
| 管理员账号 | PRD 无此系统。账号名与密码来自环境变量（不落配置、不进镜像），启动时创建/同步；不创建英雄故天然不上榜，`refresh_all_rankings` 另做显式跳过；改密接口用**用户 ID** 定位目标（不暴露账号列表给普通用户），并禁止管理员改自己的密码 |
| 副本战力缩放 | 副本 BOSS 原本只按英雄**等级**锚定，而战力主要来自**装备品阶**（与等级无关），导致门槛一满足就能碾压（实测 Lv49 满装打 raid_1 仅 0.4s）。现改为 `BOSS血量 ×(玩家DPS ÷ 本等级参考DPS)^0.8`、攻击 ×同比例 `^0.4`；参考 DPS = 等级锚定 DPS × 各难度系数，即「刚好够门槛的装备」的输出。比值下限为 1，所以只有超模装备才会触发（达标装实测单场约 45-70s）。见 `shared/data/raids.json:balance` |

---

## 已知限制

- 第三方登录未实现（PRD 标注「开发阶段确定」）。
- 排行榜防作弊仅做速率与区间校验，未做离线行为分析与人工审核后台。
- 图鉴完成度奖励（称号/头像框/徽章）目前只展示进度，未实现奖励发放。
- 数值平衡为初版，虽有回归测试保护节奏区间，仍建议按 PRD 做一轮平衡性测试。
- 容器编排为单机 Compose，未包含 HTTPS 证书与多实例横向扩展。

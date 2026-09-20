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
| 数据库 | PostgreSQL 16（开发环境也可用 SQLite） |
| 共享层 | `shared/` 单一事实来源：配置 JSON + 双端加载器 |

---

## 目录结构

```
FF14Push/
├── prd.md                    需求文档
├── docker-compose.yml        PostgreSQL 容器
├── shared/                   ★ 前后端共享配置层（唯一事实来源）
│   ├── data/*.json           品阶/栏位/职业/底材/词条/怪物/BOSS/地区/箱子/合成/经济/资质/指引
│   └── schema/
│       ├── index.ts          TS 类型 + 底材展开 + 命名导出
│       └── loader.py         Python 加载器（与 index.ts 同源）
├── backend/                  FastAPI 服务
│   ├── alembic/              数据库迁移
│   ├── app/
│   │   ├── api/v1/           路由：auth / game / battle / inventory / chest /
│   │   │                     economy / region / tavern / codex / ranking / tutorial / settings
│   │   ├── core/             配置、DB、JWT、依赖
│   │   ├── models/           ORM 模型
│   │   ├── services/         数值引擎、掉落、战斗模型、校验、图鉴、排行…
│   │   └── main.py           应用入口（启动时建表 + 排行榜定时刷新）
│   └── tests/                94 项 pytest（共享数据一致性 / 数值引擎 / 接口集成）
└── frontend/                 Vue3 前端
    └── src/
        ├── api/              axios 封装
        ├── stores/           Pinia：auth / game / toast / itemActions
        ├── game/core/        战斗模拟、伤害、怪物属性、类型定义
        ├── components/       通用组件（物品卡、弹窗、指引、日志）
        └── views/            12 个页面
```

---

## 快速开始

### 1. 启动数据库

```bash
docker compose up -d db
```

> 没有 Docker 时可用 SQLite：把 `DATABASE_URL` 设为 `sqlite+aiosqlite:///./dev.db`。

### 2. 启动后端

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env            # 按需修改 DATABASE_URL / JWT_SECRET

# 方式 A：Alembic 迁移（推荐用于 PostgreSQL）
.venv/bin/alembic upgrade head

# 方式 B：跳过迁移，服务启动时会自动建表
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- 健康检查：<http://localhost:8000/health>
- 接口文档：<http://localhost:8000/docs>

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

前端通过 `VITE_API_BASE`（默认 `http://localhost:8000/api/v1`）访问后端。

---

## 常用命令

```bash
# 后端测试
cd backend && .venv/bin/python -m pytest tests/ -q

# 前端测试 / 类型检查 / 构建
cd frontend && npm run test && npm run typecheck && npm run build
```

---

## 核心设计

### 权威边界

- 客户端按 100ms tick 模拟战斗并渲染（伤害浮动、技能 CD、日志）。
- 每 1.5 秒把事件批量上报：`{regionId, elapsedMs, kills[], skillCasts[], bossKilled, died}`。
- **服务端是唯一权威**：金币/经验上限校验、掉落装备 RNG、图鉴解锁、进度推进全部在服务端完成。
  客户端上报的击杀数与金币会被截断或拒绝（写 `audit_logs`）。
- 击杀额度按「理论击杀速率 × 时间」跨上报累积，短上报不会误杀合法击杀。

### 不做离线收益

按需求确认，离开页面即暂停战斗，服务端不存在离线回补逻辑。

### 装备归属账号

装备挂在账号而非英雄上：解雇/替换英雄时装备自动卸下并保留在背包（PRD 招募 2.4）。

### 数值锚定

PRD 中怪物与英雄的成长曲线若直接采用会导致数值发散（BOSS 战长达数分钟）。
本项目改为以「参考英雄曲线」为锚推导怪物属性，系数集中在 `shared/data/monsters.json`：

- 单体小怪约 5 秒，小怪阶段约 30-90 秒（8-36 只）；
- BOSS 战约 20-30 秒；
- 英雄装备不足时会被击杀，从而触发「阵亡重置」机制。

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
| 抽箱 | 6 种箱子、单抽/十连、品阶概率、10/50/200 抽保底 |
| 合成 | 16 件同品阶同类 → 高 1 阶，含一键合成与预览 |
| 出售 | 底价 × 品阶系数 × 属性评分 × 词条价值 × ±10%，支持批量与自动出售 |
| 重造 | 重掷基础属性与副属性，保留品阶/类型/词条 |
| 附魔 | 重掷全部词条，稀有 1.0% / 太古 0.1%，支持自动追梦 |
| 英雄招募 | 酒馆刷新与金币招募，资质 6 阶，三维按偏向分配 |
| 图鉴 | 装备（按底材 × 品阶）、怪物、词条（普通/稀有/太古三档） |
| 排行榜 | 等级榜 / 关卡榜（必做）+ 战力榜 / 金币榜，每 5 分钟服务端刷新 |
| 新手指引 | 15 步强制引导，可跳过（无奖励）与设置内重播 |
| 账号 | 账号密码注册登录 + JWT |

---

## 与 PRD 的差异说明

| 项 | 说明 |
| --- | --- |
| 装备栏位 | PRD 文字写「10 格」但列举为 11 格，按确认实现为 **11 格**（含双戒指） |
| 栏位解锁 | PRD 2.10.3 的「栏位解锁消耗」取消，初始 **全部解锁** |
| 离线收益 | PRD 2.7.4 作废，**不做离线结算** |
| BOSS 属性倍率 | PRD 4.2 写 HP 为小怪 50-80 倍，与 8.5「BOSS 战 10-30 秒」矛盾；改取可玩倍率 |
| 暴击率来源 | 三属性系统已合并「暴击率/暴击伤害」，敏捷不再提供暴击率 |
| 技能完整表 | PRD 仅给出 5 个职业示例，其余 16 个职业按同格式补全，数值为占位待平衡 |
| 怪物数值 | 改为锚定式推导，见上文「数值锚定」 |

---

## 已知限制

- 第三方登录未实现（PRD 标注「开发阶段确定」）。
- 排行榜防作弊仅做速率与区间校验，未做离线行为分析与人工审核后台。
- 图鉴完成度奖励（称号/头像框/徽章）目前只展示进度，未实现奖励发放。
- 数值平衡为初版，虽有回归测试保护节奏区间，仍建议按 PRD 做一轮平衡性测试。

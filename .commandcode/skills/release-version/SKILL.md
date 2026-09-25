---
name: release-version
description: 发布本仓库的新版本 —— 在 CHANGELOG.md 顶部新增 `## Vx.y.z — YYYY-MM-DD` 条目，把「尚未提交 git」的更新日志条目归到新版本下，并同步 package.json / frontend/package.json / backend/pyproject.toml / backend/app/main.py 的版本号。当用户要求「升级版本号」「发布新版本」「打版本」「把未提交的更新日志挪到 vX.Y.Z」时使用。
argument-hint: "[x.y.z] [YYYY-MM-DD]"
---

# 发布新版本（release-version）

把一次「cut release」的操作收敛成固定步骤，避免版本号不同步或把未提交条目留在旧版本下。

## 事实来源与不变量

- 根目录 `CHANGELOG.md` 是**唯一事实来源**：前端顶栏版本号与「更新公告」弹窗都由它派生
  （`frontend/src/version.ts` 取**顶部第一条**版本 → `APP_VERSION`）。**因此无需另行改前端版本号。**
- `CHANGELOG.md` 内容**原样展示给玩家**，只写玩家可感知内容；禁止出现文件名 / 路径 / 类名 /
  函数名 / 常量 / 数据库迁移 / 依赖 / 脚本 / 测试 / 重构 / 文档 / 部署等内部信息。
  守卫测试 `frontend/src/utils/changelog.spec.ts` 会断言条目不含这些 token：
  `.md` `.json` `.ts` `.py` `.vue` `changelog` `localstorage` `package` `frontend/` `backend/`。
- **未提交 git 的更新日志条目属于即将发布的新版本**：必须从旧版本条目下**移动**到新版本条目下
  （不是复制、不是留在原处）。未提交条目会一直累积到下一次发版。
- 维护者可能手动补充过更新简报：**保留其内容与顺序，不要覆盖或重排**。
- 全部版本标题用 `## Vx.y.z — YYYY-MM-DD`（破折号是 `—`，不是 `-`）；新版本放在**最上方**。

## 前置信息（先取，再动手）

1. 目标版本号：用户给了就用（如 `1.0.3`）；没给则按语义化默认**补丁位 +1**（`1.0.2 → 1.0.3`），
   并说明用了默认值。
2. 日期：用**今天**的 `YYYY-MM-DD`。
3. 未提交条目：跑 `scripts/release-status.sh`（或手动 `git diff -- CHANGELOG.md`）拿到待移动的条目。

## 步骤

1. **列出未提交条目**：`git diff -U0 -- CHANGELOG.md`（含已暂存则再加 `git diff --cached -U0 -- CHANGELOG.md`），
   取出所有新增的 `- ` 行。这些就是新版本的内容，**保持原有先后顺序**。
   - 若一条都没有：先跟用户确认是否仍要发版；不要凭空编造条目。
2. **改写 CHANGELOG.md**：
   - 从旧版本（通常是上一版）条目下**删除**这些条目；
   - 在**最上方、所有版本标题之前**（维护者说明段落之后）插入：
     ```
     ## Vx.y.z — YYYY-MM-DD
     <空行>
     - <原来的条目 1>
     - <原来的条目 2>
     <空行>
     ```
   - 旧版本应回到它**已提交时**的样子（末尾即上一个已提交条目）。
3. **同步 4 个版本号字段**（AGENT.md「协作约定」指定，缺一不可）：
   - `package.json` → `"version": "x.y.z"`
   - `frontend/package.json` → `"version": "x.y.z"`
   - `backend/pyproject.toml` → `version = "x.y.z"`
   - `backend/app/main.py` → `FastAPI(... version="x.y.z" ...)`
4. **不要动 `package-lock.json`**：它的根版本长期停在旧值（`0.1.0`），且其中的 `1.0.x`
   命中都是依赖自身的版本号，与本项目版本无关。

## 验证（必做）

```bash
# 1) 四处版本号已同步、且 CHANGELOG 顶部是新版本
grep -n '"version"' package.json frontend/package.json
grep -n '^version' backend/pyproject.toml
grep -n 'version="[0-9]' backend/app/main.py
grep -n '^## ' CHANGELOG.md | head -3

# 2) 公告解析与守卫测试 + 类型检查
npm run test -w frontend -- src/utils/changelog.spec.ts   # 或 cd frontend && npx vitest run src/utils/changelog.spec.ts
npm run typecheck
```

- 顶部标题应为新版本（前端 `APP_VERSION` 会随之变为 `x.y.z`）。
- 确认待移动条目**只在**新版本下出现一次，旧版本已恢复。

## 边界情况

- **条目含内部信息**：若某条目违反玩家可见规则（含文件名 / 类名 / 依赖等），先改写为玩家语言再移动，
  不要原样搬运；同时确保不引入守卫测试的禁用 token。
- **同日多次发版**：允许出现多条相同日期的版本标题，按版本号从高到低排列。
- **只有纯内部技术变动**：不写进 CHANGELOG，但仍按用户要求发版（新版本条目可为空或仅含实际内容）。
- **用户明确说「只升级版本号」**：跳过步骤 1–2 的条目移动，只做步骤 3 的四处同步。

## 示例（本仓库真实一次：V1.0.2 → V1.0.3）

- `git diff -- CHANGELOG.md` 显示 V1.0.2 末尾多了 5 条未提交条目（断点续传 / 鱼获分开 /
  自动卖鱼 / 满级移除经验加成 / 职能词缀定位）。
- 把这 5 条**移动**到新插入的 `## V1.0.3 — 2026-09-25` 下，V1.0.2 恢复为已提交内容。
- 四处版本号 `1.0.2 → 1.0.3`。
- 结果：`git diff --stat -- CHANGELOG.md` 只显示新增（`+8`，0 删除），因为那 5 条文本相对 HEAD 本就是新增。

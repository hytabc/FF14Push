# 战斗职业素材

`<jobId>.png`（职业小人，52×60）与 `icons/<jobId>.png`（职业图标，64×64），
文件名即 `shared/data/jobs.json` 里的 `job.id`；由 `npm run fetch:jobs`（`scripts/fetch-job-assets.mjs`）下载。

| 素材 | 来源 |
| --- | --- |
| 职业小人 | 《最终幻想14》国服「正统优雷卡排行榜」`static.web.sdo.com/.../deathrank0509/subtype/icon_r_<ClassJob>.png` |
| 职业图标 | [最终幻想XIV中文维基 · 职业](https://ff14.huijiwiki.com/wiki/职业) |

**版权归 SQUARE ENIX 所有**，仅用于本同人项目本地展示，请勿再分发或商用。

素材已随仓库提交，构建 / CI 不需要联网；只有在新增职业或需要更新素材时重跑 `npm run fetch:jobs`。
`frontend/src/utils/jobs.spec.ts` 会断言每个战斗职业都有各自独立的小人与图标，防止漏配。

# 天气素材

`<weatherId>.png` 为《最终幻想14》官方天气图标（0602xx 系列，40×40），
文件名即 `shared/data/weather.json` 里 `types[].id`；由 `npm run fetch:weather`（`scripts/fetch-weather-assets.mjs`）下载。

| 素材 | 来源 |
| --- | --- |
| 天气图标 | [最终幻想XIV中文维基 · 天气](https://ff14.huijiwiki.com/wiki/天气)（灰机 CDN `huiji-public.huijistatic.com/ff14/uploads/0602xx.png`） |

**版权归 SQUARE ENIX 所有**，仅用于本同人项目本地展示，请勿再分发或商用。

素材已随仓库提交，构建 / CI 不需要联网；只有在新增天气类型或需要更新素材时重跑 `npm run fetch:weather`。
`frontend/src/utils/weatherIcons.spec.ts` 会断言 `weather.json` 的每个天气类型都有对应图标，防止漏配。

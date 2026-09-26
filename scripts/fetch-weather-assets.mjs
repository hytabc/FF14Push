#!/usr/bin/env node
/**
 * 艾欧泽亚放置录 — 天气图标下载器
 *
 *   node scripts/fetch-weather-assets.mjs      # 仅在需要更新素材时手动运行
 *
 * 下载《最终幻想14》官方天气图标到 frontend/src/assets/weather/<weatherId>.png，
 * 文件名即 shared/data/weather.json 里 `types[].id`。
 *
 * 素材来源（最终幻想XIV中文维基「天气」词条，版权归 SQUARE ENIX 所有，仅供本同人项目本地展示）：
 *   https://ff14.huijiwiki.com/wiki/天气
 * 直链由灰机 CDN huiji-public.huijistatic.com 提供（脚本只取 CDN，不碰带 Cloudflare 校验的 api.php）。
 *
 * 下载结果随仓库提交，因此构建 / CI 不需要联网；只在素材需要更新时重跑本脚本。
 */

import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const OUT_DIR = join(ROOT, 'frontend/src/assets/weather')
const CDN_BASE = 'https://huiji-public.huijistatic.com/ff14/uploads'

/** weather.json 的 type.id → FF14 官方天气图标（0602xx）+ 灰机 CDN 路径前缀。 */
const WEATHERS = {
  clearSkies: { file: '060201', hash: 'f/f6', name: '碧空' },
  fairSkies: { file: '060202', hash: 'd/de', name: '晴朗' },
  clouds: { file: '060203', hash: '3/33', name: '阴云' },
  fog: { file: '060204', hash: '6/63', name: '薄雾' },
  wind: { file: '060205', hash: '6/6c', name: '微风' },
  gales: { file: '060206', hash: '1/19', name: '强风' },
  rain: { file: '060207', hash: '9/9a', name: '小雨' },
  showers: { file: '060208', hash: '9/96', name: '暴雨' },
  thunder: { file: '060209', hash: 'd/d5', name: '打雷' },
  thunderstorms: { file: '060210', hash: 'd/db', name: '雷雨' },
  dustStorms: { file: '060211', hash: '3/32', name: '扬沙' },
  heatWaves: { file: '060214', hash: '6/6c', name: '热浪' },
  snow: { file: '060215', hash: '6/6e', name: '小雪' },
  blizzards: { file: '060216', hash: '9/9a', name: '暴雪' },
}

async function download(url, outPath) {
  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0', Referer: 'https://ff14.huijiwiki.com/' },
  })
  if (!res.ok) throw new Error(`${res.status} ${url}`)
  const buf = Buffer.from(await res.arrayBuffer())
  if (buf.subarray(1, 4).toString('ascii') !== 'PNG') throw new Error(`不是 PNG：${url}`)
  writeFileSync(outPath, buf)
  return buf.length
}

async function main() {
  mkdirSync(OUT_DIR, { recursive: true })
  const entries = Object.entries(WEATHERS)
  let bytes = 0
  for (const [weatherId, w] of entries) {
    const url = `${CDN_BASE}/${w.hash}/${w.file}.png`
    const size = await download(url, join(OUT_DIR, `${weatherId}.png`))
    bytes += size
    console.log(`[fetch-weather] ${weatherId} ${w.name}（${w.file}.png, ${(size / 1024).toFixed(1)} KB）`)
  }
  console.log(`[fetch-weather] 下载 ${entries.length} 张，合计 ${(bytes / 1024).toFixed(1)} KB → ${OUT_DIR}`)
}

main().catch((err) => {
  console.error(`[fetch-weather] 失败：${err.message}`)
  process.exitCode = 1
})

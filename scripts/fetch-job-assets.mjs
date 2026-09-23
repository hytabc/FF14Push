#!/usr/bin/env node
/**
 * 艾欧泽亚放置录 — 战斗职业素材下载器
 *
 *   node scripts/fetch-job-assets.mjs        # 仅在需要更新素材时手动运行
 *
 * 下载两类素材到 frontend/src/assets/jobs/：
 *   <jobId>.png        职业小人（FF14 官方 52×60 丘比立绘）
 *   icons/<jobId>.png  职业图标（FF14 彩色职业图标，64×64）
 *
 * 素材来源（均为《最终幻想14》官方 / 中文维基公开图片，版权归 SQUARE ENIX 所有，仅供本同人项目本地展示）：
 *   - 小人：国服「正统优雷卡排行榜」 static.web.sdo.com/jijiamobile/pic/ff14/deathrank0509/data32/icon_r_<job>.png
 *   - 图标：最终幻想XIV中文维基 https://ff14.huijiwiki.com/wiki/职业
 *
 * 下载结果会随仓库提交，因此构建 / CI 不需要联网；只在素材需要更新时重跑本脚本。
 */

import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const OUT_DIR = join(ROOT, 'frontend/src/assets/jobs')
const ICON_DIR = join(OUT_DIR, 'icons')

/** 战斗职业 → FF14 ClassJob id（小人）+ 中文维基图片路径（图标，uploads/<hash>/<hash>/职业图标_<name>.png） */
const JOBS = {
  PLD: { classJob: 1, wiki: 'd/d4/职业图标_骑士', name: '骑士' },
  WAR: { classJob: 3, wiki: 'a/ac/职业图标_战士', name: '战士' },
  DRK: { classJob: 12, wiki: 'e/e9/职业图标_暗黑骑士', name: '暗黑骑士' },
  GNB: { classJob: 16, wiki: '2/24/职业图标_绝枪战士', name: '绝枪战士' },
  WHM: { classJob: 6, wiki: 'd/d3/职业图标_白魔法师', name: '白魔法师' },
  SCH: { classJob: 9, wiki: 'a/ad/职业图标_学者', name: '学者' },
  AST: { classJob: 13, wiki: 'f/fe/职业图标_占星术士', name: '占星术士' },
  SGE: { classJob: 19, wiki: '7/75/职业图标_贤者', name: '贤者' },
  MNK: { classJob: 2, wiki: 'f/ff/职业图标_武僧', name: '武僧' },
  DRG: { classJob: 4, wiki: '4/4a/职业图标_龙骑士', name: '龙骑士' },
  NIN: { classJob: 10, wiki: '1/13/职业图标_忍者', name: '忍者' },
  SAM: { classJob: 14, wiki: '9/92/职业图标_武士', name: '武士' },
  RPR: { classJob: 18, wiki: '8/80/职业图标_钐镰客', name: '钐镰客' },
  VPR: { classJob: 20, wiki: '6/6f/职业图标_蝰蛇剑士', name: '蝰蛇剑士' },
  BRD: { classJob: 5, wiki: '2/24/职业图标_吟游诗人', name: '吟游诗人' },
  MCH: { classJob: 11, wiki: 'a/a1/职业图标_机工士', name: '机工士' },
  DNC: { classJob: 17, wiki: 'a/a5/职业图标_舞者', name: '舞者' },
  BLM: { classJob: 7, wiki: '8/8f/职业图标_黑魔法师', name: '黑魔法师' },
  SMN: { classJob: 8, wiki: 'e/e0/职业图标_召唤师', name: '召唤师' },
  RDM: { classJob: 15, wiki: 'e/ed/职业图标_赤魔法师', name: '赤魔法师' },
  PCT: { classJob: 21, wiki: 'a/ac/职业图标_绘灵法师', name: '绘灵法师' },
}

const FIGURE_BASE = 'https://static.web.sdo.com/jijiamobile/pic/ff14/deathrank0509/subtype'
const ICON_BASE = 'https://huiji-public.huijistatic.com/ff14/uploads'

async function download(url, outPath) {
  const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0', Referer: 'https://ff14.huijiwiki.com/' } })
  if (!res.ok) throw new Error(`${res.status} ${url}`)
  const buf = Buffer.from(await res.arrayBuffer())
  if (buf.subarray(1, 4).toString('ascii') !== 'PNG') throw new Error(`不是 PNG：${url}`)
  writeFileSync(outPath, buf)
  return buf.length
}

async function main() {
  mkdirSync(ICON_DIR, { recursive: true })
  const jobs = Object.entries(JOBS)
  let bytes = 0
  for (const [jobId, job] of jobs) {
    const figureUrl = `${FIGURE_BASE}/icon_r_${job.classJob}.png`
    const iconUrl = `${ICON_BASE}/${job.wiki.split('/').map(encodeURIComponent).join('/')}.png`
    bytes += await download(figureUrl, join(OUT_DIR, `${jobId}.png`))
    bytes += await download(iconUrl, join(ICON_DIR, `${jobId}.png`))
    console.log(`[fetch-jobs] ${jobId} ${job.name}（小人 ClassJob ${job.classJob} + 图标）`)
  }
  console.log(`[fetch-jobs] 下载 ${jobs.length} 个职业 × 2 张 = ${jobs.length * 2} 张，合计 ${(bytes / 1024).toFixed(1)} KB → ${OUT_DIR}`)
}

main().catch((err) => {
  console.error(`[fetch-jobs] 失败：${err.message}`)
  process.exitCode = 1
})

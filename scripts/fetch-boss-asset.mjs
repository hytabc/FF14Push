#!/usr/bin/env node
/**
 * 艾欧泽亚放置录 — 世界BOSS 立绘下载器
 *
 *   node scripts/fetch-boss-asset.mjs        # 仅在需要更新素材时手动运行
 *
 * 下载世界BOSS 立绘到 frontend/src/assets/boss/<bossId>.png：
 *   golden_bahamut.png  「黄金巴哈姆特」（龙神）官方立绘
 *
 * 素材来源（《最终幻想14》官方立绘，中文维基公开图片，版权归 SQUARE ENIX 所有，仅供本同人项目本地展示）：
 *   - 最终幻想XIV中文维基 https://ff14.huijiwiki.com/wiki/巴哈姆特 词条头图
 *   - 直链由灰机 CDN huiji-public.huijistatic.com 提供（wiki 的 api.php 有 Cloudflare 校验，脚本只取 CDN）
 *
 * 下载结果会随仓库提交，因此构建 / CI 不需要联网；只在素材需要更新时重跑本脚本。
 */

import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const OUT_DIR = join(ROOT, 'frontend/src/assets/boss')

const CDN_BASE = 'https://huiji-public.huijistatic.com/ff14/uploads'

/** BOSS id（shared/data/worldboss.json 的 boss.id）→ 灰机 CDN 上的文件名。 */
const BOSSES = {
  golden_bahamut: { name: '黄金巴哈姆特', file: '巴哈姆特.png' },
}

/** 灰机 CDN 路径形如 /uploads/<a>/<ab>/<文件名>，两级哈希取自文件 MD5 前两字节。 */
const HASH_BY_FILE = {
  '巴哈姆特.png': '7/70',
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
  const entries = Object.entries(BOSSES)
  let bytes = 0
  for (const [bossId, boss] of entries) {
    const hash = HASH_BY_FILE[boss.file]
    if (!hash) throw new Error(`缺少「${boss.file}」的 CDN 哈希前缀，请在 HASH_BY_FILE 中登记`)
    const url = `${CDN_BASE}/${hash.split('/').map(encodeURIComponent).join('/')}/${encodeURIComponent(boss.file)}`
    const size = await download(url, join(OUT_DIR, `${bossId}.png`))
    bytes += size
    console.log(`[fetch-boss] ${bossId} ${boss.name}（${(size / 1024).toFixed(1)} KB）`)
  }
  console.log(`[fetch-boss] 下载 ${entries.length} 张，合计 ${(bytes / 1024).toFixed(1)} KB → ${OUT_DIR}`)
}

main().catch((err) => {
  console.error(`[fetch-boss] 失败：${err.message}`)
  process.exitCode = 1
})

/**
 * 从 `assets/` 生成 HarmonyOS 工程需要的图标资源。
 *
 *   node scripts/gen-harmony-icons.mjs
 *
 * 素材与 Android / iOS 同源（`assets/` 由 `scripts/gen-app-icon.mjs` 产出），保证三端一致。
 * 产出（写进 `harmony/`）：
 *   AppScope/resources/base/media/app_icon.png        应用图标
 *   entry/src/main/resources/base/media/icon.png      能力图标
 *   entry/src/main/resources/base/media/startIcon.png 启动图标
 *
 * 说明：这里用的是扁平图标（`icon-only.png`）。若将来要做鸿蒙的分层图标
 * （layered_image：前景 + 背景），再改 `assets/icon-foreground.png` /
 * `icon-background.png` 与 `layered_image.json` 即可，当前不做。
 */
import { access, mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import sharp from 'sharp'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
/** 鸿蒙图标基准尺寸（216×216，系统会按设备密度缩放）。 */
const SIZE = 216
const SOURCE = resolve(ROOT, 'assets/icon-only.png')
const OUTPUTS = [
  'harmony/AppScope/resources/base/media/app_icon.png',
  'harmony/entry/src/main/resources/base/media/icon.png',
  'harmony/entry/src/main/resources/base/media/startIcon.png',
]

async function main() {
  try {
    await access(SOURCE)
  } catch {
    console.error(`[harmony-icons] 找不到 ${SOURCE}，请先执行：npm run gen:icons`)
    process.exit(1)
  }
  for (const relative of OUTPUTS) {
    const target = resolve(ROOT, relative)
    await mkdir(dirname(target), { recursive: true })
    await sharp(SOURCE).resize(SIZE, SIZE, { fit: 'cover' }).png().toFile(target)
    console.log(`[harmony-icons] 写入 ${relative}`)
  }
}

await main()

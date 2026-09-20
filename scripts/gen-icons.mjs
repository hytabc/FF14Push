#!/usr/bin/env node
/**
 * 艾欧泽亚放置录 — 装备像素图标生成器
 *
 *   node scripts/gen-icons.mjs
 *
 * 为 shared/data/base-items.json 展开出的全部 180 件底材生成 16×16 像素 PNG，
 * 输出到 frontend/src/assets/icons/<baseId>.png。
 *
 * 组合方式（这样 180 张图既能两两不同、又能长期维护）：
 *   最终图案 = 部位底形（30 个，16×16） + 档位装饰戳（6 个，5×5，贴在底形中部）
 *   最终颜色 = 档位材质调色板（铁制 → 星辉）
 *
 * 品阶色不在这里烘焙，由前端 ItemIcon.vue 用 CSS 描边/光晕表现。
 *
 * 只依赖 Node 内置模块（node:zlib + 手写 PNG 编码），不引入原生依赖。
 */

import { deflateSync } from 'node:zlib'
import { mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const DATA_FILE = join(ROOT, 'shared/data/base-items.json')
const OUT_DIR = join(ROOT, 'frontend/src/assets/icons')

/** 画布边长（像素） */
const SIZE = 16
/** 透明像素字符 */
const EMPTY = '.'

// ──────────────────────────────── 调色板 ────────────────────────────────

/** 跨档位固定色（与档位材质无关的部分） */
const FIXED_COLORS = {
  o: [0x14, 0x18, 0x21], // 描边
  w: [0x6b, 0x4a, 0x2f], // 木质 / 皮革暗部
  W: [0x8a, 0x5f, 0x3c], // 木质 / 皮革亮部
  s: [0xb8, 0xc0, 0xcc], // 金属配件
  g: [0xea, 0xf2, 0xff], // 宝石（中性亮色，品阶色由 CSS 描边提供）
}

/**
 * 档位材质调色板，下标 = tierIndex。
 *   m 主体 / d 暗部 / l 亮部
 */
const TIER_PALETTES = [
  { name: '铁制', m: [0x8a, 0x8f, 0x98], d: [0x5c, 0x61, 0x69], l: [0xb9, 0xc0, 0xc9] },
  { name: '白钢', m: [0xc9, 0xd2, 0xdd], d: [0x8d, 0x97, 0xa5], l: [0xf0, 0xf5, 0xfb] },
  { name: '秘银', m: [0x9f, 0xe8, 0xe0], d: [0x5f, 0xb3, 0xac], l: [0xd6, 0xff, 0xfb] },
  { name: '钛合金', m: [0xb9, 0xa7, 0xff], d: [0x7a, 0x68, 0xc9], l: [0xe2, 0xd9, 0xff] },
  { name: '精金', m: [0xf5, 0xc5, 0x42], d: [0xb8, 0x86, 0x0b], l: [0xff, 0xe9, 0xa3] },
  { name: '星辉', m: [0x7f, 0xd4, 0xff], d: [0x3f, 0x8f, 0xd0], l: [0xd6, 0xf2, 0xff] },
]

// ──────────────────────────────── 像素定义 ────────────────────────────────
//
// 字形：. 透明  o 描边  m 主体  d 暗部  l 亮部  w/W 木革  s 金属  g 宝石
//
// 每个底形按「自然尺寸」书写，生成时自动居中贴进 16×16 画布。
// 想改某件装备的造型，直接改这里的字符画即可。

/** 30 个部位底形 */
const SHAPES = {
  // ── 武器 21（key = weaponFamilies.weaponType）──
  sword_shield: [
    '...oo...',
    '..olmo..',
    '..olmo..',
    '..olmo..',
    '..olmo..',
    '..olmo..',
    '..omdo..',
    'olmmmmlo',
    '..owWo..',
    '..owWo..',
    '..owWo..',
    '..osso..',
  ],
  axe: [
    'oo.......',
    'wWoo.....',
    'wWommo...',
    'wWommlo..',
    'wWommlo..',
    'wWommo...',
    'wWoo.....',
    'wW.......',
    'wW.......',
    'wW.......',
    'wW.......',
    'wW.......',
    'oo.......',
  ],
  greatsword: [
    '....oo...',
    '...olmo..',
    '...olmo..',
    '...olmo..',
    '...olmo..',
    '...olmo..',
    '...olmo..',
    '...olmo..',
    'olmmmmmlo',
    '...owWo..',
    '...owWo..',
    '...owWo..',
    '...osso..',
  ],
  gunblade: [
    '.....oo......',
    '....olmo.....',
    '....olmo.....',
    '....olmo.....',
    '....olmo.....',
    '....omdo.....',
    '..oooooooooo.',
    'soolmmmmmmlo.',
    'soommmmmmmmo.',
    '..oooooooooo.',
    '....owWo.....',
    '....owWo.....',
    '....oo.......',
  ],
  staff: [
    '..ooooo..',
    '.olmmmdo.',
    '.olmmmdo.',
    '.olmmmdo.',
    '..ooooo..',
    '...wW....',
    '...wW....',
    '...wW....',
    '...wW....',
    '...wW....',
    '...wW....',
    '...wW....',
    '...wW....',
    '...oo....',
  ],
  book: [
    'oooooooooo',
    'oWolmmmmdo',
    'oWolmmmmdo',
    'oWolmmmmdo',
    'oWolmmmmdo',
    'oWolmmmmdo',
    'oWolmmmmdo',
    'oWolmmmmdo',
    'oWolmmmmdo',
    'oWolmmmmdo',
    'oWolmmmmdo',
    'oooooooooo',
  ],
  globe: [
    '....oooo....',
    '..oolllloo..',
    '.olmmmmmmdo.',
    'olmmmmmmmmdo',
    'olmmmmmmmmdo',
    'olmmmmmmmmdo',
    'olmmmmmmmmdo',
    '.olmmmmmmdo.',
    '..oooooooo..',
    '....wW......',
    '....wW......',
    '...oooo.....',
    '..oooooo....',
  ],
  noulith: [
    '..o........o..',
    '.omo......omo.',
    'omlmo....omlmo',
    '.omo......omo.',
    '..o........o..',
    '..............',
    '..............',
    '..............',
    '..............',
    '......o.......',
    '.....omo......',
    '....omlmo.....',
    '.....omo......',
    '......o.......',
  ],
  fist: [
    '....oooooo..',
    '...olmmmmdo.',
    '...olmmmmdo.',
    '...olmmmmdo.',
    '...olmmmmdo.',
    '...oooooooo.',
    '...wWwWwWwW.',
    '...oooooooo.',
  ],
  lance: [
    '...oo....',
    '..olmo...',
    '..olmo...',
    '..olmo...',
    '..olmo...',
    '..omdo...',
    '..omdo...',
    'olmmmmlo.',
    '..owWo...',
    '..owWo...',
    '..owWo...',
    '..owWo...',
    '..owWo...',
    '..owWo...',
    '..oo.....',
  ],
  dualDagger: [
    '.oo.....oo..',
    '.olmo..olmo.',
    '.olmo..olmo.',
    '.olmo..olmo.',
    '.omdo..omdo.',
    '.omdo..omdo.',
    '.oooo..oooo.',
    '.owo....owo.',
    '.owo....owo.',
    '.oso....oso.',
    '.ooo....ooo.',
  ],
  katana: [
    '...........oo.',
    '..........olo.',
    '.........omo..',
    '........omo...',
    '.......omo....',
    '......omo.....',
    '.....omo......',
    '....omo.......',
    '...omo........',
    '..omo.........',
    '.olmo.........',
    'owWo..........',
    'ooo...........',
  ],
  scythe: [
    '...oooooo...',
    '..olmmmmmlo.',
    '..ommmmo....',
    '...omo......',
    '....oo......',
    '....wW......',
    '....wW......',
    '....wW......',
    '....wW......',
    '....wW......',
    '....wW......',
    '....wW......',
    '....wW......',
    '....wW......',
    '....oo......',
  ],
  twinblade: [
    '...oooo.',
    '..olmdo.',
    '..olmdo.',
    '..olmdo.',
    '...oooo.',
    '..owWo..',
    '..owWo..',
    '...oooo.',
    '..olmdo.',
    '..olmdo.',
    '..olmdo.',
    '...oooo.',
  ],
  bow: [
    '....oooo..',
    '..oolmmo..',
    '.olmmo.s..',
    '.omo...s..',
    'omo....s..',
    'omo....s..',
    'omo....s..',
    'omo....s..',
    'omo....s..',
    'omo....s..',
    'omo....s..',
    '.omo...s..',
    '.olmmo.s..',
    '..oolmmo..',
    '....oooo..',
  ],
  gun: [
    '...oooooooooo.',
    '...olmmmmmmmlo',
    '...ommmmmmmmmo',
    '...oooooooooo.',
    '.....owWo.....',
    '.....owWo.....',
    '.....owWo.....',
    '.....oooo.....',
  ],
  chakram: [
    '..oooooooo..',
    '.olmmmmmmlo.',
    'olmmmmmmmmmo',
    'omml....lmmo',
    'oml......lmo',
    'oml......lmo',
    'oml......lmo',
    'oml......lmo',
    'omml....lmmo',
    'olmmmmmmmmmo',
    '.olmmmmmmlo.',
    '..oooooooo..',
  ],
  rod: [
    '...oooo....',
    '..olmmdo...',
    '.olmmmmlo..',
    'olmmmmmmdo.',
    'olmmmmmmdo.',
    '.olmmmmlo..',
    '..olmmdo...',
    '...oooo....',
    '...owWo....',
    '...owWo....',
    '...owWo....',
    '...owWo....',
    '...owWo....',
    '...oo......',
  ],
  grimoire: [
    '.oooooooooo.',
    '.owolmmmmlo.',
    '.owolmmmmlo.',
    '.owolmmmmlo.',
    '.owolmmmmlo.',
    '.owollllllo.',
    '.owolmmmmlo.',
    '.owolmmmmlo.',
    '.owollllllo.',
    '.owolmmmmlo.',
    '.owolmmmmlo.',
    '.owolmmmmlo.',
    '.oooooooooo.',
  ],
  rapier: [
    '...oo....',
    '..olmo...',
    '..olmo...',
    '..olmo...',
    '..olmo...',
    '..olmo...',
    '..olmo...',
    '.oooooo..',
    '.olmmmo..',
    '.oooooo..',
    '...wW....',
    '...wW....',
    '...wW....',
    '...oo....',
  ],
  brush: [
    '...oooo...',
    '..olmmdo..',
    '..olmmdo..',
    '..olmmdo..',
    '..oooooo..',
    '...sWWs...',
    '...sWWs...',
    '...oooo...',
    '...wW.....',
    '...wW.....',
    '...wW.....',
    '...wW.....',
    '...wW.....',
    '...wW.....',
    '...oo.....',
  ],

  // ── 防具 5（key = armorFamilies.slot）──
  head: [
    '...oooooo...',
    '..olmmmmdo..',
    '.olmmmmmmdo.',
    'olmmmmmmmmdo',
    'olmmmmmmmmdo',
    'olmmmmmmmmdo',
    'olmmmmmmmmdo',
    'olmmmmmmmmdo',
    'oooooooooooo',
    '.olmmmmmmdo.',
    '..olmmmmdo..',
    '...oooooo...',
  ],
  body: [
    '..oooooooooo..',
    '.olmmmmmmmmlo.',
    'olmmmmmmmmmmlo',
    'olmmmmmmmmmmlo',
    'olmmmmmmmmmmlo',
    'olmmmmmmmmmmlo',
    'ollllllllllllo',
    'olmmmmmmmmmmlo',
    'olmmmmmmmmmmlo',
    '.olmmmmmmmmlo.',
    '..oooooooooo..',
  ],
  hands: [
    '...oooooo...',
    '..olmmmmdo..',
    '.olmmmmmmdo.',
    '.olmmmmmmdo.',
    '.olmmmmmmdo.',
    '.olmmmmmmdo.',
    '.oooooooooo.',
    '.owWwWwWwWo.',
    '.owWwWwWwWo.',
    '.oooooooooo.',
  ],
  legs: [
    '.oooooooooo.',
    '.olmmmmmmlo.',
    '.olmmmmmmlo.',
    '.olmmmmmmlo.',
    '.olmm..mmlo.',
    '.olmo..omlo.',
    '.olmo..omlo.',
    '.olmo..omlo.',
    '.olmo..omlo.',
    '.olmo..omlo.',
    '.olmo..omlo.',
    '.oooo..oooo.',
  ],
  feet: [
    '.oooooooo....',
    '.olmmmmdo....',
    '.olmmmmdo....',
    '.olmmmmdo....',
    '.olmmmmdo....',
    '.olmmmmdo....',
    '.olmmmmdo....',
    '.olmmmmmooo..',
    '.olmmmmmmmdo.',
    '.olmmmmmmmmdo',
    '.oooooooooooo',
  ],

  // ── 饰品 4（key = accessoryFamilies.slot）──
  necklace: [
    '..oo....oo..',
    '.o..o..o..o.',
    '.o...oo...o.',
    '.o........o.',
    '..o......o..',
    '..o......o..',
    '...o....o...',
    '....oooo....',
    '...olmmdo...',
    '...ommmmo...',
    '...ommmmo...',
    '....oooo....',
  ],
  earring: [
    '...ooo...',
    '..o...o..',
    '..o...o..',
    '..o...o..',
    '...ooo...',
    '....s....',
    '....s....',
    '...ooo...',
    '..olmlo..',
    '..ommmo..',
    '..ommmo..',
    '...ooo...',
  ],
  bracelet: [
    '..oooooooooo..',
    '.ollmmmmmmmlo.',
    '.ommo....ommo.',
    '.omo......omo.',
    '.omo......omo.',
    '.ommo....ommo.',
    '.ollmmmmmmmlo.',
    '..oooooooooo..',
  ],
  ring: [
    '....ooo....',
    '...olmlo...',
    '...ommmo...',
    '...ooooo...',
    '..ooooooo..',
    '.olo...olo.',
    '.olo...olo.',
    '.olo...olo.',
    '..ooooooo..',
  ],
}

/**
 * 档位装饰戳（5×5），下标 = tierIndex。
 * 会被贴在底形的不透明区域中部（自动找锚点），只覆盖底形已有的像素，
 * 所以宝石不会飘到轮廓外面。
 */
const ORNAMENTS = [
  null, // 0 铁制：朴素，无装饰
  [
    '.....',
    '.....',
    '..l..',
    '.....',
    '.....',
  ], // 1 白钢：一颗铆钉
  [
    '.....',
    '..o..',
    '.ogo.',
    '..o..',
    '.....',
  ], // 2 秘银：小宝石
  [
    '.....',
    '.ooo.',
    '.ogo.',
    '.ooo.',
    '.....',
  ], // 3 钛合金：护环 + 宝石
  [
    '..o..',
    '.ogo.',
    'oglgo',
    '.ogo.',
    '..o..',
  ], // 4 精金：大宝石
  [
    '..l..',
    '.lgl.',
    'lgggl',
    '.lgl.',
    '..l..',
  ], // 5 星辉：星芒
]

// ──────────────────────────────── 像素工具 ────────────────────────────────

function blankGrid() {
  return Array.from({ length: SIZE }, () => Array.from({ length: SIZE }, () => EMPTY))
}

/** 校验字符画尺寸，并把自然尺寸的底形居中贴进画布 */
function drawCentered(grid, macro, label) {
  const height = macro.length
  const width = Math.max(...macro.map((row) => row.length))
  if (height > SIZE || width > SIZE) {
    throw new Error(`${label} 尺寸 ${width}×${height} 超出画布 ${SIZE}×${SIZE}`)
  }
  const offsetX = Math.floor((SIZE - width) / 2)
  const offsetY = Math.floor((SIZE - height) / 2)
  macro.forEach((row, y) => {
    [...row].forEach((char, x) => {
      if (char === EMPTY || char === ' ') return
      assertKnownChar(char, label)
      grid[offsetY + y][offsetX + x] = char
    })
  })
}

function assertKnownChar(char, label) {
  const known = char in FIXED_COLORS || 'mdl'.includes(char)
  if (!known) throw new Error(`${label} 出现未定义的像素字符「${char}」`)
}

/** 底形不透明像素的质心，取最接近质心的不透明格作为装饰锚点 */
function findAnchor(grid) {
  const cells = []
  let sumX = 0
  let sumY = 0
  for (let y = 0; y < SIZE; y += 1) {
    for (let x = 0; x < SIZE; x += 1) {
      if (grid[y][x] === EMPTY) continue
      cells.push([x, y])
      sumX += x
      sumY += y
    }
  }
  if (!cells.length) return null
  const cx = sumX / cells.length
  const cy = sumY / cells.length
  let best = cells[0]
  let bestDist = Number.POSITIVE_INFINITY
  for (const [x, y] of cells) {
    const dist = (x - cx) ** 2 + (y - cy) ** 2
    if (dist < bestDist) {
      bestDist = dist
      best = [x, y]
    }
  }
  return best
}

/** 把装饰戳贴在锚点上，仅覆盖底形已有像素 */
function applyOrnament(grid, stamp, label) {
  if (!stamp) return
  const anchor = findAnchor(grid)
  if (!anchor) return
  const [anchorX, anchorY] = anchor
  const height = stamp.length
  const width = Math.max(...stamp.map((row) => row.length))
  stamp.forEach((row, y) => {
    [...row].forEach((char, x) => {
      if (char === EMPTY || char === ' ') return
      assertKnownChar(char, `${label} 装饰`)
      const targetX = anchorX + x - Math.floor(width / 2)
      const targetY = anchorY + y - Math.floor(height / 2)
      if (targetX < 0 || targetY < 0 || targetX >= SIZE || targetY >= SIZE) return
      if (grid[targetY][targetX] === EMPTY) return
      grid[targetY][targetX] = char
    })
  })
}

/** 调色板字符 → RGBA 缓冲 */
function colorize(grid, palette) {
  const buffer = Buffer.alloc(SIZE * SIZE * 4)
  for (let y = 0; y < SIZE; y += 1) {
    for (let x = 0; x < SIZE; x += 1) {
      const char = grid[y][x]
      if (char === EMPTY) continue
      const rgb = char in FIXED_COLORS ? FIXED_COLORS[char] : palette[char]
      if (!rgb) throw new Error(`调色板缺少字符「${char}」`)
      const offset = (y * SIZE + x) * 4
      buffer[offset] = rgb[0]
      buffer[offset + 1] = rgb[1]
      buffer[offset + 2] = rgb[2]
      buffer[offset + 3] = 0xff
    }
  }
  return buffer
}

// ──────────────────────────────── PNG 编码 ────────────────────────────────

const CRC_TABLE = (() => {
  const table = new Int32Array(256)
  for (let n = 0; n < 256; n += 1) {
    let c = n
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    table[n] = c
  }
  return table
})()

function crc32(buffer) {
  let crc = -1
  for (const byte of buffer) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8)
  return (crc ^ -1) >>> 0
}

function pngChunk(type, data) {
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length, 0)
  const typeBuffer = Buffer.from(type, 'ascii')
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuffer, data])), 0)
  return Buffer.concat([length, typeBuffer, data, crc])
}

/** 最小 PNG 编码器：8 位 RGBA、无隔行、filter 全 0 */
function encodePng(width, height, rgba) {
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])

  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(width, 0)
  ihdr.writeUInt32BE(height, 4)
  ihdr[8] = 8 // 位深
  ihdr[9] = 6 // 颜色类型：RGBA
  ihdr[10] = 0 // 压缩方法
  ihdr[11] = 0 // 滤波方法
  ihdr[12] = 0 // 隔行：无

  const stride = width * 4
  const raw = Buffer.alloc(height * (stride + 1))
  for (let y = 0; y < height; y += 1) {
    raw[y * (stride + 1)] = 0
    rgba.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride)
  }

  return Buffer.concat([
    signature,
    pngChunk('IHDR', ihdr),
    pngChunk('IDAT', deflateSync(raw, { level: 9 })),
    pngChunk('IEND', Buffer.alloc(0)),
  ])
}

// ──────────────────────────────── 主流程 ────────────────────────────────

/** 与 shared/schema/index.ts 的 expandBaseItems() 保持一致的 id 规则 */
function listBaseItems(data) {
  const items = []
  for (const family of data.weaponFamilies) {
    for (const tier of data.tiers) {
      items.push({ id: `w_${family.weaponType}_${tier.index}`, shape: family.weaponType, tier: tier.index })
    }
  }
  for (const family of data.armorFamilies) {
    for (const tier of data.tiers) {
      items.push({ id: `a_${family.slot}_${tier.index}`, shape: family.slot, tier: tier.index })
    }
  }
  for (const family of data.accessoryFamilies) {
    for (const tier of data.tiers) {
      items.push({ id: `c_${family.slot}_${tier.index}`, shape: family.slot, tier: tier.index })
    }
  }
  return items
}

function main() {
  const data = JSON.parse(readFileSync(DATA_FILE, 'utf8'))
  const items = listBaseItems(data)

  const weapons = data.weaponFamilies.length
  const armors = data.armorFamilies.length
  const accessories = data.accessoryFamilies.length
  const tiers = data.tiers.length
  const expected = (weapons + armors + accessories) * tiers
  if (items.length !== expected) {
    throw new Error(`底材数量不符：期望 ${expected}，实际 ${items.length}`)
  }

  mkdirSync(OUT_DIR, { recursive: true })

  let totalBytes = 0
  const written = new Set()

  for (const item of items) {
    const macro = SHAPES[item.shape]
    if (!macro) throw new Error(`缺少「${item.shape}」的底形定义（${item.id}）`)

    const grid = blankGrid()
    drawCentered(grid, macro, item.id)
    applyOrnament(grid, ORNAMENTS[item.tier], item.id)

    const palette = TIER_PALETTES[item.tier]
    if (!palette) throw new Error(`缺少档位 ${item.tier} 的调色板`)

    const png = encodePng(SIZE, SIZE, colorize(grid, palette))
    writeFileSync(join(OUT_DIR, `${item.id}.png`), png)
    written.add(`${item.id}.png`)
    totalBytes += png.length
  }

  // 清掉改名 / 删档位后遗留的陈旧图标
  let pruned = 0
  for (const file of readdirSync(OUT_DIR)) {
    if (!file.endsWith('.png') || written.has(file)) continue
    rmSync(join(OUT_DIR, file))
    pruned += 1
  }

  console.log(`[gen-icons] 生成 ${written.size} 张 ${SIZE}×${SIZE} PNG → ${OUT_DIR}`)
  console.log(`[gen-icons] 合计 ${(totalBytes / 1024).toFixed(1)} KB（平均 ${Math.round(totalBytes / written.size)} 字节/张）`)
  if (pruned) console.log(`[gen-icons] 清理陈旧图标 ${pruned} 张`)
  console.log(`[gen-icons] 底形 ${weapons + armors + accessories} 个 = 武器 ${weapons} + 防具 ${armors} + 饰品 ${accessories}，档位 ${tiers} 个`)
}

main()

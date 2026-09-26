#!/usr/bin/env node
/**
 * 艾欧泽亚放置录 — 移动端 App 图标 / 启动图生成器
 *
 *   node scripts/gen-app-icon.mjs
 *
 * 产出到 assets/（再由 @capacitor/assets 展开成 Android 各密度资源，见 npm run app:icons）：
 *   icon-only.png        1024×1024  不透明，带圆角底板（旧式图标 / 圆形图标源图）
 *   icon-foreground.png  1024×1024  透明，内容收在自适应图标安全区内
 *   icon-background.png  1024×1024  自适应图标的渐变底板
 *   splash.png           2732×2732  启动图
 *   splash-dark.png      2732×2732  深色启动图（与上者同款，本项目只有深色皮肤）
 *
 * 主题取艾欧泽亚「母水晶」：深空底色 + 星野 + 金色光环 + 中央发光水晶。
 * 配色直接沿用游戏本体（frontend/src/style.css 的 ink 色阶、精金 / 星辉 / 妖精银）。
 *
 * 只依赖 Node 内置模块（node:zlib + 手写 PNG 编码）。所有造型用「到多边形的有符号
 * 距离」解析式抗锯齿绘制，因此任意分辨率下边缘都干净，无需超采样。
 */

import { deflateSync } from 'node:zlib'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const OUT_DIR = join(ROOT, 'assets')

/** 图标源图边长 */
const ICON_SIZE = 1024
/** 启动图边长（@capacitor/assets 要求 2732） */
const SPLASH_SIZE = 2732
/** 几何坐标系边长：造型一律按 1024 网格描述，再按目标尺寸缩放 */
const UNIT = 1024

// ──────────────────────────────── 配色 ────────────────────────────────

const PALETTE = {
  // 深空底色（游戏 body 背景的浓缩版）
  skyTop: '#233256',
  skyCore: '#1b2440',
  skyEdge: '#0a0d16',
  nebulaBlue: '#2f5c9e',
  nebulaPurple: '#6a3aa0',
  star: '#cfe4ff',
  // 精金 / 妖精银（金色光环）
  gold: '#f5c542',
  goldLight: '#fff0b8',
  goldDark: '#a8750a',
  // 母水晶（星辉 → 妖精银 → 白）
  crystalEdge: '#dcf3ff',
  crystalTopLeft: '#3d8fd0',
  crystalTopRight: '#8fd8f8',
  crystalLowLeft: '#2b68a6',
  crystalLowRight: '#63bcee',
  crystalCore: '#dff6ff',
  crystalHalo: '#5fb8ff',
}

/** '#rrggbb' → [r, g, b] */
function rgb(hex) {
  const v = parseInt(hex.slice(1), 16)
  return [(v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff]
}

// ──────────────────────────────── 几何工具 ────────────────────────────────

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v)
const lerp = (a, b, t) => a + (b - a) * t
const lerpRgb = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)]

function pointInPolygon(x, y, pts) {
  let inside = false
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i]
    const [xj, yj] = pts[j]
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

function distToSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax
  const dy = by - ay
  const len2 = dx * dx + dy * dy
  const t = len2 > 0 ? clamp01(((px - ax) * dx + (py - ay) * dy) / len2) : 0
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}

/** 到多边形边界的最短距离，内部为负、外部为正（解析式抗锯齿与描边的基础） */
function signedDistToPolygon(px, py, pts) {
  let best = Infinity
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    best = Math.min(best, distToSegment(px, py, pts[j][0], pts[j][1], pts[i][0], pts[i][1]))
  }
  return pointInPolygon(px, py, pts) ? -best : best
}

function bounds(pts, pad = 0) {
  let x0 = Infinity
  let y0 = Infinity
  let x1 = -Infinity
  let y1 = -Infinity
  for (const [x, y] of pts) {
    x0 = Math.min(x0, x)
    y0 = Math.min(y0, y)
    x1 = Math.max(x1, x)
    y1 = Math.max(y1, y)
  }
  return [x0 - pad, y0 - pad, x1 + pad, y1 + pad]
}

/** FNV-1a → 0..1，用于星野等确定性随机（同一输入永远得到同一张图） */
function hashUnit(seed, index) {
  let h = 0x811c9dc5 ^ index
  const text = `${seed}:${index}`
  for (const ch of text) {
    h ^= ch.codePointAt(0)
    h = Math.imul(h, 0x01000193)
  }
  return ((h >>> 0) % 100000) / 100000
}

// ──────────────────────────────── 画布 ────────────────────────────────

/** 预乘 alpha 画布：[pr, pg, pb, pa]；rgb 为 0..255 的预乘值，a 为 0..1 */
class Canvas {
  constructor(size) {
    this.size = size
    this.data = new Float32Array(size * size * 4)
  }

  /** 常规 alpha 混合 */
  over(x, y, color, alpha) {
    if (alpha <= 0) return
    const a = alpha > 1 ? 1 : alpha
    const i = (y * this.size + x) * 4
    const d = this.data
    const inv = 1 - a
    d[i] = color[0] * a + d[i] * inv
    d[i + 1] = color[1] * a + d[i + 1] * inv
    d[i + 2] = color[2] * a + d[i + 2] * inv
    d[i + 3] = a + d[i + 3] * inv
  }

  /** 加色混合（辉光 / 星芒） */
  add(x, y, color, amount) {
    if (amount <= 0) return
    const i = (y * this.size + x) * 4
    const d = this.data
    d[i] += color[0] * amount
    d[i + 1] += color[1] * amount
    d[i + 2] += color[2] * amount
    d[i + 3] = Math.min(1, d[i + 3] + amount)
  }

  /** 只压暗颜色、保留 alpha（暗角） */
  shade(x, y, factor) {
    const i = (y * this.size + x) * 4
    this.data[i] *= factor
    this.data[i + 1] *= factor
    this.data[i + 2] *= factor
  }

  /** 整体乘算（圆角遮罩） */
  mask(x, y, factor) {
    const i = (y * this.size + x) * 4
    this.data[i] *= factor
    this.data[i + 1] *= factor
    this.data[i + 2] *= factor
    this.data[i + 3] *= factor
  }

  /** 遍历一个包围盒（自动裁到画布内、按像素取整） */
  eachPx(box, cb) {
    const x0 = Math.max(0, Math.floor(box[0]))
    const y0 = Math.max(0, Math.floor(box[1]))
    const x1 = Math.min(this.size - 1, Math.ceil(box[2]))
    const y1 = Math.min(this.size - 1, Math.ceil(box[3]))
    for (let y = y0; y <= y1; y += 1) {
      for (let x = x0; x <= x1; x += 1) cb(x, y)
    }
  }

  fillPolygon(pts, color, alpha = 1, colorAt = null) {
    this.eachPx(bounds(pts, 1.5), (x, y) => {
      const cov = clamp01(0.5 - signedDistToPolygon(x + 0.5, y + 0.5, pts))
      if (cov <= 0) return
      this.over(x, y, colorAt ? colorAt(x + 0.5, y + 0.5) : color, alpha * cov)
    })
  }

  strokePolygon(pts, width, color, alpha = 1, colorAt = null) {
    this.eachPx(bounds(pts, width + 2), (x, y) => {
      const cov = clamp01(0.5 - (Math.abs(signedDistToPolygon(x + 0.5, y + 0.5, pts)) - width / 2))
      if (cov <= 0) return
      this.over(x, y, colorAt ? colorAt(x + 0.5, y + 0.5) : color, alpha * cov)
    })
  }

  /**
   * 多边形外侧柔光。内部一律不加亮 —— 若只按 max(sd, 0) 衰减，内部距离恒为 0
   * 会得到满强度叠加，把切面颜色整个冲淡。
   */
  glowPolygon(pts, sigma, color, strength) {
    const denom = 2 * sigma * sigma
    this.eachPx(bounds(pts, sigma * 2.5), (x, y) => {
      const sd = signedDistToPolygon(x + 0.5, y + 0.5, pts)
      if (sd <= 0) return
      const amount = strength * Math.exp(-(sd * sd) / denom)
      if (amount > 0.0015) this.add(x, y, color, amount)
    })
  }

  /** 以某点为圆心的点状柔光（星野 / 星云） */
  glowCircle(cx, cy, sigma, color, strength) {
    const denom = 2 * sigma * sigma
    this.eachPx([cx - sigma * 3, cy - sigma * 3, cx + sigma * 3, cy + sigma * 3], (x, y) => {
      const d = Math.hypot(x + 0.5 - cx, y + 0.5 - cy)
      const amount = strength * Math.exp(-(d * d) / denom)
      if (amount > 0.0015) this.add(x, y, color, amount)
    })
  }

  /** 沿圆周两侧的柔光（给金色光环用） */
  glowRing(cx, cy, radius, sigma, color, strength) {
    const denom = 2 * sigma * sigma
    const pad = sigma * 3
    this.eachPx([cx - radius - pad, cy - radius - pad, cx + radius + pad, cy + radius + pad], (x, y) => {
      const d = Math.abs(Math.hypot(x + 0.5 - cx, y + 0.5 - cy) - radius)
      const amount = strength * Math.exp(-(d * d) / denom)
      if (amount > 0.0015) this.add(x, y, color, amount)
    })
  }

  strokeCircle(cx, cy, radius, width, color, alpha = 1, colorAt = null) {
    const pad = width + 2
    this.eachPx([cx - radius - pad, cy - radius - pad, cx + radius + pad, cy + radius + pad], (x, y) => {
      const sd = Math.abs(Math.hypot(x + 0.5 - cx, y + 0.5 - cy) - radius)
      const cov = clamp01(0.5 - (sd - width / 2))
      if (cov <= 0) return
      this.over(x, y, colorAt ? colorAt(x + 0.5, y + 0.5) : color, alpha * cov)
    })
  }

  /** 径向渐变铺满整个画布（背景） */
  radialFill(cx, cy, radius, stops) {
    this.eachPx([0, 0, this.size - 1, this.size - 1], (x, y) => {
      const t = clamp01(Math.hypot(x + 0.5 - cx, y + 0.5 - cy) / radius)
      this.over(x, y, sampleStops(stops, t), 1)
    })
  }

  /** 暗角：距圆心越远压得越黑（保留 alpha） */
  vignette(cx, cy, inner, outer, maxDarken) {
    this.eachPx([0, 0, this.size - 1, this.size - 1], (x, y) => {
      const d = Math.hypot(x + 0.5 - cx, y + 0.5 - cy)
      const t = clamp01((d - inner) / (outer - inner))
      if (t <= 0) return
      this.shade(x, y, 1 - maxDarken * t * t)
    })
  }

  /** 圆角矩形遮罩（旧式图标底板） */
  roundRectMask(radius, feather = 1.2) {
    const size = this.size
    const r = radius
    this.eachPx([0, 0, size - 1, size - 1], (x, y) => {
      const px = Math.abs(x + 0.5 - size / 2)
      const py = Math.abs(y + 0.5 - size / 2)
      // 到圆角矩形边界的近似有符号距离
      const qx = px - (size / 2 - r)
      const qy = py - (size / 2 - r)
      const sd = Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) - r
      const cov = clamp01(0.5 - sd / feather)
      if (cov < 1) this.mask(x, y, cov)
    })
  }

  /** 输出为直通 alpha 的 RGBA 缓冲 */
  toRgba() {
    const size = this.size
    const out = Buffer.alloc(size * size * 4)
    const d = this.data
    for (let i = 0, o = 0; i < d.length; i += 4, o += 4) {
      const a = d[i + 3]
      if (a <= 0.0005) continue
      const inv = 1 / Math.min(a, 1)
      out[o] = Math.min(255, Math.round(d[i] * inv))
      out[o + 1] = Math.min(255, Math.round(d[i + 1] * inv))
      out[o + 2] = Math.min(255, Math.round(d[i + 2] * inv))
      out[o + 3] = Math.round(clamp01(a) * 255)
    }
    return out
  }
}

function sampleStops(stops, t) {
  if (t <= stops[0][0]) return stops[0][1]
  for (let i = 1; i < stops.length; i += 1) {
    const [t1, c1] = stops[i]
    if (t <= t1) {
      const [t0, c0] = stops[i - 1]
      return lerpRgb(c0, c1, (t - t0) / (t1 - t0))
    }
  }
  return stops[stops.length - 1][1]
}

// ──────────────────────────────── 造型定义 ────────────────────────────────
//
// 全部按 1024 网格描述。水晶沿用「上金字塔 + 下亭部」四切面结构，
// 腰线（waist）是上下分界，中间一道亮芯把两个三角分开。

/** 母水晶轮廓（六边形，尖顶） */
const CRYSTAL = [
  [512, 226],
  [664, 366],
  [688, 632],
  [512, 798],
  [336, 632],
  [360, 366],
]

const WAIST = [512, 456]

/** 四个切面：上左 / 上右 / 下左 / 下右 */
const FACETS = [
  { pts: [[512, 226], [360, 366], WAIST], color: rgb(PALETTE.crystalTopLeft) },
  { pts: [[512, 226], [664, 366], WAIST], color: rgb(PALETTE.crystalTopRight) },
  { pts: [[360, 366], [336, 632], [512, 798], WAIST], color: rgb(PALETTE.crystalLowLeft) },
  { pts: [[664, 366], [688, 632], [512, 798], WAIST], color: rgb(PALETTE.crystalLowRight) },
]

/** 中央亮芯（把两个三角镶起来的细长六边形） */
const CORE = [
  [512, 250],
  [548, 372],
  [556, 640],
  [512, 782],
  [468, 640],
  [476, 372],
]

/** 顶面反光 */
const GLINT = [
  [428, 336],
  [472, 302],
  [492, 352],
  [448, 386],
]

/** 金色光环 */
const HALO_RADIUS = 352
const HALO_CENTER = [512, 512]

// ──────────────────────────────── 绘制 ────────────────────────────────

/** 把 1024 网格坐标映射到目标画布像素坐标 */
function makeMapper(size, contentScale) {
  const s = (size / UNIT) * contentScale
  const c = size / 2
  return (x, y) => [c + (x - UNIT / 2) * s, c + (y - UNIT / 2) * s]
}

function drawSky(canvas, rounded) {
  const size = canvas.size
  const u = (v) => (v / UNIT) * size

  canvas.radialFill(size / 2, u(470), u(980), [
    [0, rgb(PALETTE.skyTop)],
    [0.42, rgb(PALETTE.skyCore)],
    [1, rgb(PALETTE.skyEdge)],
  ])

  // 星云：偏冷的蓝在上左、偏紫的紫在右，呼应游戏正文背景
  canvas.glowCircle(u(300), u(250), u(360), rgb(PALETTE.nebulaBlue), 0.26)
  canvas.glowCircle(u(770), u(330), u(340), rgb(PALETTE.nebulaPurple), 0.24)

  canvas.vignette(size / 2, size / 2, u(420), u(900), 0.62)

  // 星野：只在光环外侧撒点，不干扰主体
  const star = rgb(PALETTE.star)
  for (let i = 0; i < 150; i += 1) {
    const angle = hashUnit('star-angle', i) * Math.PI * 2
    const dist = u(430 + hashUnit('star-dist', i) * 620)
    const cx = size / 2 + Math.cos(angle) * dist
    const cy = size / 2 + Math.sin(angle) * dist
    if (cx < 0 || cy < 0 || cx >= size || cy >= size) continue
    const radius = (1.1 + hashUnit('star-size', i) * 2.4) * (size / UNIT)
    const brightness = 0.18 + hashUnit('star-alpha', i) * 0.55
    canvas.glowCircle(cx, cy, radius, star, brightness)
    if (hashUnit('star-big', i) > 0.82) {
      // 少量亮星带十字星芒
      const arm = radius * 4.5
      const thin = radius * 0.7
      for (const pts of [
        [[cx, cy - arm], [cx + thin, cy], [cx, cy + arm], [cx - thin, cy]],
        [[cx - arm, cy], [cx, cy + thin], [cx + arm, cy], [cx, cy - thin]],
      ]) {
        canvas.fillPolygon(pts, star, 0.35 * brightness)
      }
    }
  }

  if (rounded) canvas.roundRectMask(size * 0.168)
}

function drawEmblem(canvas, contentScale) {
  const size = canvas.size
  const P = makeMapper(size, contentScale)
  const px = size / UNIT
  const scale = (v) => v * px * contentScale

  const [hcx, hcy] = P(HALO_CENTER[0], HALO_CENTER[1])
  const hr = scale(HALO_RADIUS)

  // 光环辉光与水晶辉光
  canvas.glowRing(hcx, hcy, hr, scale(30), rgb(PALETTE.gold), 0.6)
  const crystalPts = CRYSTAL.map(([x, y]) => P(x, y))
  canvas.glowPolygon(crystalPts, scale(62), rgb(PALETTE.crystalHalo), 0.5)
  // 轮廓柔光晕：外圈铺光，内侧一半随后会被切面盖住，只留一圈光边
  canvas.strokePolygon(crystalPts, scale(46), rgb(PALETTE.crystalHalo), 0.2)

  // 金色光环：上下渐变的金属感 + 内侧细环。
  // 描边宽度按 1024 网格给到 26（约 1.7dp），再细在 mdpi/ldpi 这类低密度下会被
  // 缩放抹掉（0.98px 的线缩到 48px 时金色直接被背景吃掉）。
  const gold = rgb(PALETTE.gold)
  const goldLight = rgb(PALETTE.goldLight)
  const goldDark = rgb(PALETTE.goldDark)
  canvas.strokeCircle(hcx, hcy, hr, scale(26), gold, 1, (x, y) => {
    const t = clamp01(0.5 - (y - hcy) / (2 * hr))
    return lerpRgb(goldDark, goldLight, t)
  })
  canvas.strokeCircle(hcx, hcy, scale(322), scale(3), gold, 0.42)

  // 水晶本体
  for (const facet of FACETS) {
    canvas.fillPolygon(facet.pts.map(([x, y]) => P(x, y)), facet.color, 1)
  }
  canvas.fillPolygon(CORE.map(([x, y]) => P(x, y)), rgb(PALETTE.crystalCore), 0.42)
  canvas.fillPolygon(
    [[506, 268], [518, 268], [524, 636], [512, 766], [500, 636]].map(([x, y]) => P(x, y)),
    [255, 255, 255],
    0.72,
  )
  canvas.fillPolygon(GLINT.map(([x, y]) => P(x, y)), [255, 255, 255], 0.5)

  // 轮廓 + 棱线
  canvas.strokePolygon(crystalPts, scale(8), rgb(PALETTE.crystalEdge), 0.92)
  const [wx, wy] = P(WAIST[0], WAIST[1])
  canvas.strokePolygon([P(360, 366), [wx, wy]], scale(3.5), rgb(PALETTE.crystalEdge), 0.3)
  canvas.strokePolygon([P(664, 366), [wx, wy]], scale(3.5), rgb(PALETTE.crystalEdge), 0.3)

  // 两点星芒，让构图不呆板
  for (const [cx, cy, r, arm, alpha] of [
    [762, 268, 46, 11, 0.7],
    [258, 748, 40, 9, 0.6],
  ]) {
    const [sx, sy] = P(cx, cy)
    const rs = scale(r)
    const as = scale(arm)
    canvas.glowCircle(sx, sy, scale(r * 0.9), [255, 255, 255], alpha * 0.34)
    for (const rot of [0, Math.PI / 4]) {
      const c = Math.cos(rot)
      const s = Math.sin(rot)
      const pts = [
        [sx, sy - rs],
        [sx + as, sy],
        [sx, sy + rs],
        [sx - as, sy],
      ].map(([x, y]) => [sx + (x - sx) * c - (y - sy) * s, sy + (x - sx) * s + (y - sy) * c])
      canvas.fillPolygon(pts, [255, 255, 255], rot === 0 ? alpha : alpha * 0.55)
    }
  }
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
  ihdr[8] = 8
  ihdr[9] = 6
  ihdr[10] = 0
  ihdr[11] = 0
  ihdr[12] = 0

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

function renderIcon({ size, background, rounded, contentScale }) {
  const canvas = new Canvas(size)
  if (background) drawSky(canvas, rounded)
  drawEmblem(canvas, contentScale)
  return canvas
}

function renderSplash(size) {
  const canvas = new Canvas(size)
  drawSky(canvas, false)
  drawEmblem(canvas, 0.46)
  return canvas
}

function main() {
  mkdirSync(OUT_DIR, { recursive: true })

  const outputs = [
    // 旧式图标：带圆角底板，主体给得足一些
    { file: 'icon-only.png', canvas: renderIcon({ size: ICON_SIZE, background: true, rounded: true, contentScale: 1.05 }) },
    // 自适应图标：前景透明且收在安全区内（约 60%），背景独立铺满
    { file: 'icon-foreground.png', canvas: renderIcon({ size: ICON_SIZE, background: false, rounded: false, contentScale: 0.86 }) },
    { file: 'icon-background.png', canvas: renderIcon({ size: ICON_SIZE, background: true, rounded: false, contentScale: 0 }) },
    { file: 'splash.png', canvas: renderSplash(SPLASH_SIZE) },
    { file: 'splash-dark.png', canvas: renderSplash(SPLASH_SIZE) },
  ]

  for (const { file, canvas } of outputs) {
    const rgba = canvas.toRgba()
    const png = encodePng(canvas.size, canvas.size, rgba)
    writeFileSync(join(OUT_DIR, file), png)
    console.log(`[gen-app-icon] ${file.padEnd(20)} ${canvas.size}×${canvas.size}  ${(png.length / 1024).toFixed(1)} KB`)
  }

  console.log(`[gen-app-icon] 输出目录 ${OUT_DIR}`)
}

main()

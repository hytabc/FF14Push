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
const MATERIALS_FILE = join(ROOT, 'shared/data/materials.json')
const DOHDOL_EQUIP_FILE = join(ROOT, 'shared/data/dohdol-equipment.json')
const FISH_FILE = join(ROOT, 'shared/data/fish.json')
const CONSUMABLES_FILE = join(ROOT, 'shared/data/consumables.json')
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

  // ── 采集材料 10（key 由 materialShape() 决定）──
  mat_ore: [
    '..oooooo..',
    '.olmmmmlo.',
    'olmmmmmmdo',
    'olmmmmmmdo',
    'olmmmmmmdo',
    'olmmmmmmdo',
    '.ommmmmmdo',
    '..oooooo..',
  ],
  mat_crystal: [
    '.....oo.....',
    '....olmo....',
    '...olmmmo...',
    '..olmmmmdo..',
    '.olmmmmmmdo.',
    'olmmmmmmmmdo',
    '.olmmmmmmdo.',
    '..olmmmmdo..',
    '...oooooo...',
  ],
  mat_stone: [
    '...oooooo...',
    '..olmmmmdo..',
    '.olmmmmmmdo.',
    'olmmmmmmmmdo',
    'olmmmmmmmmdo',
    '.olmmmmmmdo.',
    '..olmmmmdo..',
    '...oooooo...',
  ],
  mat_powder: [
    '....oooo....',
    '...olmmdo...',
    '..olmmmmdo..',
    '.olmmmmmmdo.',
    'olmmmmmmmmdo',
    'oooooooooooo',
  ],
  mat_log: [
    '..oooooooo..',
    '.olmmmmmmdo.',
    'omlmmmmmmlmo',
    'ommlmmmmlmmo',
    'ommlmmmmlmmo',
    'omlmmmmmmlmo',
    '.olmmmmmmdo.',
    '..oooooooo..',
  ],
  mat_fiber: [
    '.m..m..m..',
    '.m..m..m..',
    '.ml.ml.ml.',
    '.m..m..m..',
    'ddddddddd.',
    '.m..m..m..',
    '.m..m..m..',
    '.ml.ml.ml.',
    '.m..m..m..',
    '.m..m..m..',
  ],
  mat_herb: [
    '...oo....',
    '..olmo...',
    '.olmmmo..',
    'olmmmmmo.',
    'olmmmmmdo',
    '.olmmmdo.',
    '..olmmdo.',
    '...oooo..',
    '....wW...',
    '....wW...',
  ],
  mat_flower: [
    '..oo..oo..',
    '.ogoo.ogo.',
    '..ogoogo..',
    '.olgmmlo..',
    'olmmmmmmdo',
    'olmmmmmmdo',
    '.olmmmmdo.',
    '...wWwW...',
    '....wW....',
    '....wW....',
  ],
  mat_fruit: [
    '....oo....',
    '..oolmmo..',
    '.olmmmmdo.',
    'ommmmmmmdo',
    'omgmmmmmdo',
    'ommmmmmmdo',
    '.olmmmmdo.',
    '..oooooo..',
  ],
  mat_mushroom: [
    '..oooooo..',
    '.olmmmmdo.',
    'olmmgmmmdo',
    'olmmmmmmdo',
    '.olmmmmdo.',
    '..oooooo..',
    '...wW.....',
    '...wW.....',
    '...wW.....',
  ],

  // ── 半成品 9（key 由 HALF_SHAPE_BY_ID 决定）──
  half_plank: [
    'oooooooooooo',
    'olmmmmmmmmdo',
    'olmmmmmmmmdo',
    'oooooooooooo',
    'olmmmmmmmmdo',
    'olmmmmmmmmdo',
    'oooooooooooo',
  ],
  half_ingot: [
    '...oooooo...',
    '..olmmmmdo..',
    '.olmmmmmmdo.',
    'olmmmmmmmmdo',
    'oooooooooooo',
  ],
  half_plate: [
    'oooooooooooo',
    'olmmmmmmmmdo',
    'olsmmmmmmsdo',
    'olmmmmmmmmdo',
    'oooooooooooo',
  ],
  half_gemcut: [
    '....oo....',
    '...olmo...',
    '..olmmmo..',
    '.olmmmmdo.',
    'olmmmmmmdo',
    '.olmmmmdo.',
    '..olmmdo..',
    '...oooo...',
  ],
  half_glass: [
    'oooooooooo',
    'oglgggglgo',
    'ogglooglgg',
    'oglgggglgo',
    'oooooooooo',
  ],
  half_leather: [
    'oooooooooo',
    'owWmmmmmWo',
    'owmmmmmmWo',
    'owWmmmmmWo',
    'oooooooooo',
  ],
  half_cloth: [
    'oooooooooo',
    'olmmmmmmlo',
    'owWwWwWwWo',
    'olmmmmmmlo',
    'oooooooooo',
  ],
  half_bottle: [
    '..oooo..',
    '..ommo..',
    '..ommo..',
    '.olmmdo.',
    'olmmmmdo',
    'ommmmmmo',
    'ommgmmmo',
    'ommmmmmo',
    '.oooooo.',
  ],
  half_sack: [
    '...oo...',
    '..ommo..',
    '.olmmdo.',
    'olmmmmdo',
    'ommmmmmo',
    'ommmmmmo',
    'ommmmmmo',
    '.oooooo.',
  ],

  // ── 鱼获 3（key 由 kind 决定）──
  fish_normal: [
    '...oooooo...',
    '..olmmmmdo..',
    '.olmommmmdo.',
    'olmmmmmmmoo.',
    'olmmmmmmoooo',
    'olmmmmmmoooo',
    'olmmmmmmmoo.',
    '.olmmmmmmdo.',
    '..olmmmmdo..',
    '...oooooo...',
  ],
  fish_king: [
    '.o.o.o.o....',
    '.ooooooo....',
    '...oooooo...',
    '..olmmmmdo..',
    '.olmommmmdo.',
    'olmmmmmmmoo.',
    'olmmmmmmoooo',
    'olmmmmmmoooo',
    'olmmmmmmmoo.',
    '.olmmmmmmdo.',
    '..olmmmmdo..',
    '...oooooo...',
  ],
  fish_emperor: [
    'g.o.o.o.o..g',
    '.ooooooo....',
    '...oooooo...',
    '..olmmmmdo..',
    '.olmommmmdo.',
    'olmmmmmmmoo.',
    'olmmmmmmoooo',
    'olmmmmmmoooo',
    'olmmmmmmmoo.',
    '.olmmmmmmdo.',
    '..olmmmmdo..',
    'g..oooooo...',
  ],

  // ── 药水 / 食物 2 ──
  cons_potion: [
    '...oooo...',
    '...ommo...',
    '...ommo...',
    '..olmmdo..',
    '.olmmmmdo.',
    '.ommmmmmo.',
    '.ommgmmmo.',
    '.ommmmmmo.',
    '.ommmmmmo.',
    '..oooooo..',
  ],
  cons_food: [
    '...oooo...',
    '..olmmdo..',
    '.olmmmmdo.',
    '.ommgmmmo.',
    '.ommmmmmo.',
    'oooooooooo',
    'oooooooooo',
    '.oooooooo.',
  ],

  // ── 生产/采集工具 4（防具槽复用 head/body/hands/legs/feet）──
  tool_doh_main: [
    '...oooooo...',
    '..olmmmmdo..',
    '..olmmmmdo..',
    '..olmmmmdo..',
    '...oooooo...',
    '....owWo....',
    '....owWo....',
    '....owWo....',
    '....owWo....',
    '....owWo....',
    '....oooo....',
  ],
  tool_doh_off: [
    '..oo...oo..',
    '.olmo.omlo.',
    '.olmo.omlo.',
    '..oooooooo.',
    '....osso...',
    '....osso...',
    '....osso...',
    '....osso...',
    '....oooo...',
  ],
  tool_dol_main: [
    'oooo..........',
    'olmmmoooooo...',
    '.olmmmmmmmmo..',
    '..ooooooommmo.',
    '........olmo..',
    '........olmo..',
    '........owWo..',
    '........owWo..',
    '........owWo..',
    '........owWo..',
    '........oooo..',
  ],
  tool_dol_off: [
    '..oooooo...',
    '.olmmmmdo..',
    'olmmmmmmdo.',
    'olmmmmmmdo.',
    '.olmmmmdo..',
    '..oooooo...',
    '...owWo....',
    '...owWo....',
    '...owWo....',
    '...owWo....',
    '...owWo....',
    '...oooo....',
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

// ──────────────────── 采集/半成品/鱼/消耗品/专用装备 调色板 ────────────────────

/** 生产专用装备（暖棕橙）3 档 */
const DOH_PALETTES = [
  { m: [0xa8, 0x76, 0x3f], d: [0x6f, 0x4a, 0x24], l: [0xd0, 0xa4, 0x68] },
  { m: [0xc9, 0x8a, 0x3a], d: [0x8a, 0x5a, 0x20], l: [0xe8, 0xb9, 0x6a] },
  { m: [0xd9, 0xa9, 0x4a], d: [0x9a, 0x6a, 0x1a], l: [0xf0, 0xd0, 0x8a] },
]

/** 采集专用装备（青绿）3 档 */
const DOL_PALETTES = [
  { m: [0x5f, 0x8f, 0x5a], d: [0x3a, 0x5f, 0x36], l: [0x94, 0xc0, 0x8a] },
  { m: [0x4a, 0x9f, 0x88], d: [0x2a, 0x6a, 0x5a], l: [0x86, 0xd0, 0xb8] },
  { m: [0x3f, 0xb0, 0xc0], d: [0x1f, 0x70, 0x80], l: [0x86, 0xe0, 0xe8] },
]

/** 鱼：普通 / 鱼王 / 鱼皇 */
const FISH_PALETTES = {
  normal: { m: [0x6f, 0x9f, 0xd0], d: [0x3f, 0x6f, 0xa0], l: [0xa8, 0xcc, 0xec] },
  king: { m: [0xe0, 0xb8, 0x40], d: [0xa0, 0x7a, 0x10], l: [0xff, 0xe0, 0x8a] },
  emperor: { m: [0xb0, 0x60, 0xd0], d: [0x70, 0x30, 0xa0], l: [0xe0, 0xa0, 0xf0] },
}

/** 钓场地区生态色（给同种鱼做微差） */
const REGION_TINTS = [
  [0x6a, 0xa8, 0xc0], [0xc0, 0xa8, 0x6a], [0x6a, 0xa0, 0x6a], [0xb0, 0xb8, 0xc8],
  [0xc0, 0x8a, 0x6a], [0x8a, 0x9a, 0xc0], [0xa0, 0xc0, 0x88], [0xc0, 0x9a, 0xc0],
]

/** 药水/食物按效果取色 */
const STAT_COLORS = {
  expGainPct: [0xb4, 0x8f, 0xd0],
  goldGainPct: [0xe8, 0xc3, 0x4a],
  chestLuck: [0xe0, 0x6a, 0xc0],
  craftQualityPct: [0xd9, 0x8a, 0x3a],
  fishInsightPct: [0x5a, 0xc0, 0xd0],
  fishChancePct: [0x5a, 0xc0, 0xd0],
  gatherYieldPct: [0x6a, 0xb0, 0x4a],
}

/** 形状族兜底色（关键词未命中时使用） */
const SHAPE_FALLBACK = {
  mat_ore: [0x8f, 0x93, 0x9c],
  mat_crystal: [0x9f, 0xd8, 0xe8],
  mat_stone: [0xb0, 0xa8, 0xa0],
  mat_powder: [0xe0, 0xdc, 0xcc],
  mat_log: [0x8a, 0x5f, 0x3c],
  mat_fiber: [0xd8, 0xcc, 0xa8],
  mat_herb: [0x6a, 0xb0, 0x5a],
  mat_flower: [0xe0, 0x6a, 0x9a],
  mat_fruit: [0xd0, 0x6a, 0x4a],
  mat_mushroom: [0xc9, 0xa0, 0x6a],
}

/** 关键词色表：按顺序取首个命中（长词在前，避免「铜」吃掉「黄铜」） */
const KEYWORD_COLORS = [
  // 金属 / 矿物
  { match: '黄铜', color: [0xc9, 0xa8, 0x3a] }, { match: '蓝铜', color: [0x3f, 0x7f, 0xc0] },
  { match: '铜', color: [0xb8, 0x73, 0x33] }, { match: '秘银', color: [0x9f, 0xe8, 0xe0] },
  { match: '精金', color: [0xf5, 0xc5, 0x42] }, { match: '星辉', color: [0x7f, 0xd4, 0xff] },
  { match: '硬铝', color: [0xae, 0xb7, 0xc4] }, { match: '磁铁', color: [0x4a, 0x4a, 0x58] },
  { match: '赤铁', color: [0xa8, 0x54, 0x3f] }, { match: '褐铁', color: [0x9a, 0x7b, 0x4a] },
  { match: '钛', color: [0xb9, 0xa7, 0xff] }, { match: '锰', color: [0x7a, 0x70, 0x88] },
  { match: '钨', color: [0x5c, 0x61, 0x69] }, { match: '钴', color: [0x3f, 0x5f, 0xd0] },
  { match: '镍', color: [0xb0, 0xb8, 0xb0] }, { match: '铬', color: [0xcf, 0xd8, 0xe0] },
  { match: '银', color: [0xcc, 0xd2, 0xdc] }, { match: '金', color: [0xe8, 0xc3, 0x4a] },
  { match: '锡', color: [0xb8, 0xc0, 0xcc] }, { match: '铅', color: [0x6f, 0x74, 0x80] },
  { match: '锌', color: [0x8f, 0x98, 0xa8] }, { match: '钢', color: [0xc9, 0xd2, 0xdd] },
  { match: '铁', color: [0x9a, 0xa4, 0xb2] }, { match: '辰砂', color: [0xd2, 0x3b, 0x2f] },
  { match: '硫磺', color: [0xe6, 0xd2, 0x3a] }, { match: '硝石', color: [0xe6, 0xe8, 0xdc] },
  { match: '岩盐', color: [0xf0, 0xf0, 0xf0] }, { match: '明矾', color: [0xdd, 0xe4, 0xe8] },
  { match: '石膏', color: [0xe8, 0xe4, 0xd8] }, { match: '石灰', color: [0xd8, 0xd4, 0xc4] },
  { match: '花岗', color: [0xa8, 0xa0, 0xa0] }, { match: '砂岩', color: [0xd0, 0xb4, 0x83] },
  { match: '大理', color: [0xe2, 0xe0, 0xda] }, { match: '滑石', color: [0xc8, 0xd0, 0xcc] },
  { match: '云母', color: [0xd4, 0xdd, 0xe6] }, { match: '萤石', color: [0x6f, 0xd8, 0xbf] },
  { match: '黑曜', color: [0x2f, 0x2a, 0x3a] }, { match: '石英', color: [0xe6, 0xee, 0xf7] },
  { match: '月长石', color: [0xcd, 0xd6, 0xea] }, { match: '翡翠', color: [0x2f, 0xbf, 0x71] },
  { match: '石榴石', color: [0xb0, 0x3a, 0x4a] }, { match: '橄榄石', color: [0x9f, 0xcf, 0x4a] },
  { match: '紫水晶', color: [0x9a, 0x6f, 0xd0] }, { match: '水晶', color: [0xb0, 0xa0, 0xe8] },
  { match: '天青', color: [0x2f, 0x6f, 0xd0] }, { match: '绯红', color: [0xd0, 0x32, 0x4a] },
  // 木材
  { match: '红木', color: [0x7a, 0x34, 0x28] }, { match: '桃花心', color: [0x7a, 0x34, 0x28] },
  { match: '黑檀', color: [0x3a, 0x2a, 0x22] }, { match: '白桦', color: [0xd8, 0xc8, 0xa8] },
  { match: '铁木', color: [0x6a, 0x5a, 0x4a] }, { match: '竹', color: [0x9f, 0xbf, 0x6a] },
  { match: '藤', color: [0x4a, 0x7a, 0x3a] }, { match: '芦苇', color: [0xc2, 0xb8, 0x78] },
  { match: '松', color: [0xc0, 0x8a, 0x4a] }, { match: '杉', color: [0xa8, 0x74, 0x3f] },
  { match: '橡', color: [0x8a, 0x5a, 0x30] }, { match: '梣', color: [0xb0, 0x88, 0x58] },
  { match: '榉', color: [0xa0, 0x7a, 0x4a] }, { match: '木', color: [0x8a, 0x5f, 0x3c] },
  // 植物 / 草药 / 花 / 果
  { match: '薰衣草', color: [0xb4, 0x8f, 0xd0] }, { match: '亚麻', color: [0xde, 0xd6, 0xb8] },
  { match: '棉花', color: [0xe8, 0xe2, 0xcc] }, { match: '大麻', color: [0xc8, 0xc0, 0x98] },
  { match: '苔藓', color: [0x6a, 0x8a, 0x4a] }, { match: '蘑菇', color: [0xc9, 0xa0, 0x6a] },
  { match: '灵芝', color: [0x8a, 0x3a, 0x2a] }, { match: '冬虫夏草', color: [0xc0, 0xa0, 0x60] },
  { match: '山金车', color: [0xe8, 0xb8, 0x3a] }, { match: '龙血草', color: [0xb0, 0x2a, 0x2a] },
  { match: '苜蓿', color: [0x6a, 0xb0, 0x4a] }, { match: '银叶', color: [0xc8, 0xd0, 0xc0] },
  { match: '苦艾', color: [0x8a, 0x9a, 0x5a] }, { match: '曼陀罗', color: [0xa0, 0x6a, 0xc0] },
  { match: '菊石', color: [0xb0, 0xa0, 0x6a] }, { match: '蓝铃', color: [0x6a, 0x8a, 0xe0] },
  { match: '山茶', color: [0xd8, 0x4a, 0x6a] }, { match: '芦荟', color: [0x5a, 0xa8, 0x7a] },
  { match: '椰子', color: [0x8a, 0x6a, 0x4a] }, { match: '无花果', color: [0x6a, 0x4a, 0x6a] },
  { match: '玫瑰', color: [0xe0, 0x50, 0x70] }, { match: '风茄', color: [0x7a, 0x5a, 0x8a] },
  { match: '秋葵', color: [0x7a, 0xa8, 0x3a] }, { match: '杜松', color: [0x4a, 0x6a, 0x3a] },
  { match: '薄荷', color: [0x5a, 0xc0, 0x9a] }, { match: '鼠尾草', color: [0x8a, 0xa0, 0x8a] },
  { match: '洋甘菊', color: [0xe8, 0xe0, 0xb0] }, { match: '藏红花', color: [0xe0, 0x78, 0x2a] },
  { match: '仙人掌', color: [0x6a, 0xa8, 0x5a] }, { match: '花', color: [0xe0, 0x6a, 0x9a] },
  { match: '草', color: [0x6a, 0xb0, 0x5a] },
  // 半成品补充
  { match: '装甲板', color: [0x8f, 0x99, 0xa6] }, { match: '合金', color: [0xb0, 0xc0, 0xd0] },
  { match: '宝石', color: [0xd0, 0x6a, 0xc0] }, { match: '玻璃', color: [0xcf, 0xe8, 0xf0] },
  { match: '皮革', color: [0x8a, 0x5a, 0x3a] }, { match: '布', color: [0xc8, 0xb8, 0xa0] },
  { match: '墨水', color: [0x3a, 0x3a, 0x6a] }, { match: '精油', color: [0xc8, 0xa0, 0x4a] },
  { match: '面粉', color: [0xe8, 0xe0, 0xcc] },
]

/** 半成品 id → 形状 */
const HALF_SHAPE_BY_ID = {
  h_plank: 'half_plank',
  h_ingot: 'half_ingot',
  h_steel: 'half_ingot',
  h_plate: 'half_plate',
  h_alloy: 'half_ingot',
  h_gemcut: 'half_gemcut',
  h_glass: 'half_glass',
  h_leather: 'half_leather',
  h_cloth: 'half_cloth',
  h_ink: 'half_bottle',
  h_oil: 'half_bottle',
  h_flour: 'half_sack',
}

// 关键词 → 形状族（按顺序命中；长词在前）
const MIN_CRYSTAL_KEYWORDS = ['石英', '水晶', '翡翠', '石榴石', '橄榄石', '天青', '绯红', '萤石', '云母', '月长石', '秘银', '精金', '星辉', '宝石']
const MIN_POWDER_KEYWORDS = ['岩盐', '硝石', '明矾', '石膏', '硫磺']
const MIN_STONE_KEYWORDS = ['花岗', '大理', '滑石', '石灰', '黑曜', '岩', '砂', '石']
const BTN_MUSHROOM_KEYWORDS = ['冬虫夏草', '蘑菇', '灵芝']
const BTN_FIBER_KEYWORDS = ['亚麻', '棉', '藤', '芦苇', '麻']
const BTN_FRUIT_KEYWORDS = ['仙人掌', '椰子', '无花果', '秋葵', '果']
const BTN_FLOWER_KEYWORDS = ['薰衣草', '洋甘菊', '藏红花', '蓝铃', '玫瑰', '山茶', '花']
const BTN_LOG_KEYWORDS = ['桃花心', '白桦', '竹', '檀', '木', '桦']

// ──────────────────────────────── 配色工具 ────────────────────────────────

/** 由单个基色派生调色板：d 暗部、l 亮部 */
function makePalette(base) {
  const clamp = (v) => Math.max(0, Math.min(255, Math.round(v)))
  return {
    m: base.map(clamp),
    d: base.map((c) => clamp(c * 0.62)),
    l: base.map((c) => clamp(c * 1.3 + 18)),
  }
}

/** base 向 tint 混合 t（0..1） */
function mix(base, tint, t) {
  return base.map((c, i) => Math.round(c * (1 - t) + tint[i] * t))
}

/** FNV-1a → 0..1，用于同族物品的确定性微差 */
function hashUnit(str) {
  let h = 0x811c9dc5
  for (const ch of str) {
    h ^= ch.codePointAt(0)
    h = Math.imul(h, 0x01000193)
  }
  return ((h >>> 0) % 1000) / 1000
}

function lookupColor(name) {
  for (const { match, color } of KEYWORD_COLORS) {
    if (name.includes(match)) return color
  }
  return null
}

/** 名字 + id → 调色板：关键词命中优先，否则用形状族兜底色；统一叠加明度微调 */
function colorOf(name, id, fallback) {
  const base = lookupColor(name) ?? fallback
  const jitter = 0.9 + hashUnit(id) * 0.2
  return makePalette(base.map((c) => c * jitter))
}

function firstHit(name, keywords) {
  return keywords.find((k) => name.includes(k))
}

/** 采集材料 → 形状 key */
function materialShape(m) {
  if (m.jobId === 'MIN') {
    if (firstHit(m.name, MIN_CRYSTAL_KEYWORDS)) return 'mat_crystal'
    if (firstHit(m.name, MIN_POWDER_KEYWORDS)) return 'mat_powder'
    if (firstHit(m.name, MIN_STONE_KEYWORDS)) return 'mat_stone'
    return 'mat_ore'
  }
  if (firstHit(m.name, BTN_MUSHROOM_KEYWORDS)) return 'mat_mushroom'
  if (firstHit(m.name, BTN_FIBER_KEYWORDS)) return 'mat_fiber'
  if (firstHit(m.name, BTN_FRUIT_KEYWORDS)) return 'mat_fruit'
  if (firstHit(m.name, BTN_FLOWER_KEYWORDS)) return 'mat_flower'
  if (firstHit(m.name, BTN_LOG_KEYWORDS)) return 'mat_log'
  return 'mat_herb'
}

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
  const push = (id, shape, tier) => {
    items.push({ id, shape, palette: TIER_PALETTES[tier], ornament: ORNAMENTS[tier] })
  }
  for (const family of data.weaponFamilies) {
    for (const tier of data.tiers) push(`w_${family.weaponType}_${tier.index}`, family.weaponType, tier.index)
  }
  for (const family of data.armorFamilies) {
    for (const tier of data.tiers) push(`a_${family.slot}_${tier.index}`, family.slot, tier.index)
  }
  for (const family of data.accessoryFamilies) {
    for (const tier of data.tiers) push(`c_${family.slot}_${tier.index}`, family.slot, tier.index)
  }
  return items
}

/** 采集材料 + 半成品（materials.json） */
function listMaterials(materialsJson) {
  return materialsJson.materials.map((m) => {
    if (m.kind === 'half') {
      const shape = HALF_SHAPE_BY_ID[m.id] ?? 'half_ingot'
      return { id: m.id, shape, palette: colorOf(m.name, m.id, SHAPE_FALLBACK.mat_ore), ornament: null }
    }
    const shape = materialShape(m)
    return { id: m.id, shape, palette: colorOf(m.name, m.id, SHAPE_FALLBACK[shape]), ornament: null }
  })
}

/** 生产/采集专用装备（dohdol-equipment.json）：工具槽用工具底形，防具槽复用战斗防具底形 */
const TOOL_SHAPE_BY_SLOT = {
  dohTool: 'tool_doh_main',
  dohOffTool: 'tool_doh_off',
  dolTool: 'tool_dol_main',
  dolOffTool: 'tool_dol_off',
}
function listDohdolItems(equipJson) {
  return equipJson.items.map((it) => {
    const shape = TOOL_SHAPE_BY_SLOT[it.slot] ?? it.slot.replace(/^doh|^dol/, '').toLowerCase()
    const palettes = it.kind === 'doh' ? DOH_PALETTES : DOL_PALETTES
    return { id: it.id, shape, palette: palettes[it.tierIndex] ?? palettes[0], ornament: null }
  })
}

/** 鱼获（fish.json）：普通 f{r}_{n} / 鱼王 k{r} / 鱼皇 e{r} */
const FISH_SHAPE_BY_KIND = { normal: 'fish_normal', king: 'fish_king', emperor: 'fish_emperor' }
function listFish(fishJson) {
  const out = []
  const make = (id, kind, regionId) => {
    const tint = REGION_TINTS[regionId % REGION_TINTS.length]
    const base = mix(FISH_PALETTES[kind].m, tint, 0.3)
    out.push({ id, shape: FISH_SHAPE_BY_KIND[kind], palette: makePalette(base), ornament: null })
  }
  for (const region of fishJson.regions) {
    for (const f of region.normal) make(f.id, 'normal', region.regionId)
    make(region.king.id, 'king', region.regionId)
    make(region.emperor.id, 'emperor', region.regionId)
  }
  return out
}

/** 药水 / 食物（consumables.json） */
function listConsumables(consumablesJson) {
  return consumablesJson.items.map((c) => {
    const stat = c.effects?.[0]?.stat
    const base = STAT_COLORS[stat] ?? (c.kind === 'potion' ? [0xc0, 0x60, 0xb0] : [0xd0, 0xa0, 0x40])
    const shape = c.kind === 'potion' ? 'cons_potion' : 'cons_food'
    const jitter = 0.9 + hashUnit(c.id) * 0.2
    return { id: c.id, shape, palette: makePalette(base.map((v) => v * jitter)), ornament: null }
  })
}

function main() {
  const data = JSON.parse(readFileSync(DATA_FILE, 'utf8'))
  const materialsJson = JSON.parse(readFileSync(MATERIALS_FILE, 'utf8'))
  const dohdolEquipJson = JSON.parse(readFileSync(DOHDOL_EQUIP_FILE, 'utf8'))
  const fishJson = JSON.parse(readFileSync(FISH_FILE, 'utf8'))
  const consumablesJson = JSON.parse(readFileSync(CONSUMABLES_FILE, 'utf8'))

  const weapons = data.weaponFamilies.length
  const armors = data.armorFamilies.length
  const accessories = data.accessoryFamilies.length
  const tiers = data.tiers.length

  const baseItems = listBaseItems(data)
  const materials = listMaterials(materialsJson)
  const dohdolItems = listDohdolItems(dohdolEquipJson)
  const fish = listFish(fishJson)
  const consumables = listConsumables(consumablesJson)

  const expectedBase = (weapons + armors + accessories) * tiers
  if (baseItems.length !== expectedBase) {
    throw new Error(`底材数量不符：期望 ${expectedBase}，实际 ${baseItems.length}`)
  }

  const items = [...baseItems, ...materials, ...dohdolItems, ...fish, ...consumables]

  mkdirSync(OUT_DIR, { recursive: true })

  let totalBytes = 0
  const written = new Set()

  for (const item of items) {
    const macro = SHAPES[item.shape]
    if (!macro) throw new Error(`缺少「${item.shape}」的底形定义（${item.id}）`)

    const grid = blankGrid()
    drawCentered(grid, macro, item.id)
    if (item.ornament) applyOrnament(grid, item.ornament, item.id)

    const palette = item.palette
    if (!palette) throw new Error(`缺少「${item.id}」的调色板`)

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
  console.log(
    `[gen-icons] 战斗装备 ${baseItems.length}（底形 ${weapons + armors + accessories} × 档位 ${tiers}）` +
      ` + 材料/半成品 ${materials.length} + 专用装备 ${dohdolItems.length}` +
      ` + 鱼获 ${fish.length} + 药水食物 ${consumables.length}`,
  )
}

main()

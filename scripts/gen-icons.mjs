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
const EXCLUSIVE_FILE = join(ROOT, 'shared/data/exclusive-equipment.json')
const MATERIALS_FILE = join(ROOT, 'shared/data/materials.json')
const DOHDOL_EQUIP_FILE = join(ROOT, 'shared/data/dohdol-equipment.json')
const FISH_FILE = join(ROOT, 'shared/data/fish.json')
const CONSUMABLES_FILE = join(ROOT, 'shared/data/consumables.json')
const MATERIA_FILE = join(ROOT, 'shared/data/materia.json')
const FARM_FILE = join(ROOT, 'shared/data/farm.json')
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
  { name: '龙鳞', m: [0x6f, 0xc0, 0x8a], d: [0x3a, 0x7a, 0x52], l: [0xb8, 0xf0, 0xd0] },
  { name: '苍穹', m: [0x8a, 0xa8, 0xe8], d: [0x4a, 0x68, 0xa8], l: [0xd0, 0xe0, 0xff] },
  { name: '星辉', m: [0x7f, 0xd4, 0xff], d: [0x3f, 0x8f, 0xd0], l: [0xd6, 0xf2, 0xff] },
  { name: '终末', m: [0xe0, 0x8a, 0x5a], d: [0x9a, 0x4a, 0x2a], l: [0xff, 0xd0, 0xa0] },
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
  fish_legend: [
    'g.o.o.o.o..g',
    '.ooooooo....',
    'g..oooooo..g',
    '..olmmmmdo..',
    '.olmommmmdo.',
    'olmmmmmmmoo.',
    'olmmmmmmoooo',
    'olmmmmmmoooo',
    'olmmmmmmmoo.',
    '.olmmmmmmdo.',
    'g..olmmmdo..',
    '...oooooo..g',
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

  // ── 魔晶石 / 作物种子 ──
  mat_materia: [
    '...oooooo...',
    '..olmmmmdo..',
    '.olmggggmdo.',
    'olmggggggmdo',
    'olmggggggmdo',
    'olmggggggmdo',
    '.olmggggmdo.',
    '..olmmmmdo..',
    '...oooooo...',
  ],
  mat_seed: [
    '....oo....',
    '..oolmoo..',
    '.olmmmmdo.',
    '.ommmmmmo.',
    '.ommmmmmo.',
    '..ommmmo..',
    '..olmmdo..',
    '...oooo...',
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
  ], // 5 龙鳞：菱形鳞纹
  [
    '.g.g.',
    'glglg',
    '.glg.',
    'glglg',
    '.g.g.',
  ], // 6 苍穹：编织
  [
    '..l..',
    '.lgl.',
    'lgggl',
    '.lgl.',
    '..l..',
  ], // 7 星辉：星芒
  [
    'l.g.l',
    '.lgl.',
    'ggggg',
    '.lgl.',
    'l.g.l',
  ], // 8 终末：终焉之印
]

/** 绝境龙神（世界BOSS 专属系列）：龙金 + 赤红识别色（不随档位变化）。 */
const EXCLUSIVE_PALETTE = {
  m: [0xf0, 0xc0, 0x40],
  d: [0xb0, 0x7a, 0x10],
  l: [0xff, 0xf0, 0xa0],
  g: [0xff, 0xf2, 0xc0],
  a: [0xe0, 0x40, 0x40],
}

/** 绝境龙神装饰戳（5×5）：龙鳞王冠。 */
const EXCLUSIVE_ORNAMENT = ['a.g.a', '.glg.', 'ggggg', '.glg.', 'a.g.a']

/** 绝境龙神变体角标（3×3）：key = 变体 id。 */
const EXCLUSIVE_MARKS = {
  atk: ['.a.', 'aaa', '.a.'],
  def: ['aaa', '.a.', 'aaa'],
}

/**
 * 职能识别色：战斗装备变体的名称中段是 FF14 官方职能词缀（御敌/强袭/制敌/游击/精准/治愈/咏咒），
 * 图标据此染色 —— 同一职能无论武器 / 防具 / 饰品都取同一色，玩家一眼即可把图对上名字。
 * key = 变体 name；基础型（''）不染色。
 */
const ROLE_TINTS = {
  御敌: [0xb0, 0x96, 0x5a],
  强袭: [0xe0, 0x52, 0x48],
  制敌: [0xb0, 0x70, 0xe8],
  游击: [0x58, 0xc8, 0x68],
  精准: [0x3e, 0xc8, 0xe0],
  治愈: [0xf2, 0xdc, 0x86],
  咏咒: [0x58, 0x88, 0xe8],
}

/**
 * 职能角标（3×3），画在图标右上角空白处，用 'a' 字符（职能强调色）。
 * 只有空白像素才落笔，因此不会破坏底形。
 */
const ROLE_MARKS = {
  御敌: ['aaa', 'a.a', 'aaa'],
  强袭: ['aa.', 'aa.', '...'],
  制敌: ['.a.', 'aaa', '.a.'],
  游击: ['.aa', '..a', '.a.'],
  精准: ['aa.', 'a..', '...'],
  治愈: ['aaa', '.a.', 'aaa'],
  咏咒: ['aaa', '..a', 'aaa'],
}

/**
 * 专用装备（生产/采集）变体识别色：key = 变体 id；基础变体（''）不染色。
 */
const DOHDOL_TINTS = {
  yield: [0x68, 0xb8, 0x48],
  xp: [0xc0, 0x90, 0xe0],
  quality: [0xd8, 0xa8, 0x40],
  speed: [0xe8, 0x78, 0x38],
  master: [0xf0, 0xd8, 0x70],
  fish: [0x50, 0xc0, 0xd0],
}

/** 专用装备变体角标（3×3）：key = 变体 id。 */
const DOHDOL_MARKS = {
  yield: ['.a.', 'aaa', '...'],
  xp: ['a.a', 'aaa', '.a.'],
  quality: ['.a.', 'aaa', '.a.'],
  speed: ['a..', 'aa.', 'aaa'],
  master: ['aaa', 'aaa', 'aaa'],
  fish: ['aaa', '..a', '.aa'],
}

/** 把档位调色板向识别色混合（t=0.32），并附加角标色 a；tint 为空则不染色。 */
function tintPalette(palette, tint) {
  if (!tint) return palette
  const t = 0.32
  const blend = (c, i) => Math.round(c * (1 - t) + tint[i] * t)
  return {
    m: palette.m.map(blend),
    d: palette.d.map(blend),
    l: palette.l.map(blend),
    a: tint.map((c) => Math.min(255, Math.round(c * 1.15 + 25))),
  }
}

// ──────────────────── 采集/半成品/鱼/消耗品/专用装备 调色板 ────────────────────

/** 生产专用装备（暖棕 → 琥珀）11 档 */
const DOH_PALETTES = [
  { m: [0xa8, 0x76, 0x3f], d: [0x6f, 0x4a, 0x24], l: [0xd0, 0xa4, 0x68] },
  { m: [0xb4, 0x80, 0x40], d: [0x78, 0x50, 0x24], l: [0xdc, 0xb0, 0x70] },
  { m: [0xc0, 0x8a, 0x3e], d: [0x82, 0x58, 0x22], l: [0xe4, 0xba, 0x72] },
  { m: [0xc9, 0x8a, 0x3a], d: [0x8a, 0x5a, 0x20], l: [0xe8, 0xb9, 0x6a] },
  { m: [0xd2, 0x96, 0x40], d: [0x92, 0x60, 0x1e], l: [0xec, 0xc0, 0x74] },
  { m: [0xd9, 0xa9, 0x4a], d: [0x9a, 0x6a, 0x1a], l: [0xf0, 0xd0, 0x8a] },
  { m: [0xdd, 0xa0, 0x50], d: [0xa0, 0x64, 0x20], l: [0xf2, 0xc8, 0x86] },
  { m: [0xe0, 0x9a, 0x54], d: [0xa6, 0x60, 0x24], l: [0xf6, 0xc4, 0x88] },
  { m: [0xe4, 0x96, 0x58], d: [0xac, 0x5e, 0x28], l: [0xf8, 0xc0, 0x8c] },
  { m: [0xe8, 0x92, 0x5c], d: [0xb0, 0x5c, 0x2c], l: [0xfa, 0xbc, 0x90] },
  { m: [0xec, 0x8e, 0x60], d: [0xb4, 0x5a, 0x30], l: [0xfc, 0xb8, 0x94] },
]

/** 采集专用装备（草绿 → 青蓝）11 档 */
const DOL_PALETTES = [
  { m: [0x5f, 0x8f, 0x5a], d: [0x3a, 0x5f, 0x36], l: [0x94, 0xc0, 0x8a] },
  { m: [0x5c, 0x94, 0x62], d: [0x38, 0x62, 0x3c], l: [0x92, 0xc6, 0x92] },
  { m: [0x58, 0x99, 0x6e], d: [0x36, 0x66, 0x44], l: [0x90, 0xcc, 0x9a] },
  { m: [0x54, 0x9e, 0x7a], d: [0x34, 0x6a, 0x4c], l: [0x8e, 0xd0, 0xa2] },
  { m: [0x50, 0xa3, 0x86], d: [0x32, 0x6e, 0x54], l: [0x8c, 0xd4, 0xaa] },
  { m: [0x4a, 0x9f, 0x88], d: [0x2a, 0x6a, 0x5a], l: [0x86, 0xd0, 0xb8] },
  { m: [0x46, 0xa4, 0x94], d: [0x28, 0x6e, 0x62], l: [0x84, 0xd4, 0xc2] },
  { m: [0x42, 0xa9, 0xa0], d: [0x26, 0x72, 0x6a], l: [0x82, 0xd8, 0xcc] },
  { m: [0x3f, 0xae, 0xac], d: [0x24, 0x76, 0x72], l: [0x80, 0xdc, 0xd6] },
  { m: [0x3f, 0xb0, 0xbb], d: [0x22, 0x74, 0x7e], l: [0x84, 0xde, 0xdc] },
  { m: [0x3f, 0xb0, 0xc0], d: [0x1f, 0x70, 0x80], l: [0x86, 0xe0, 0xe8] },
]

/** 鱼：普通鱼（白 / 蓝 / 紫档位）+ 鱼王 / 鱼皇 / 困难鱼 */
const FISH_PALETTES = {
  white: { m: [0x6f, 0x9f, 0xd0], d: [0x3f, 0x6f, 0xa0], l: [0xa8, 0xcc, 0xec] },
  blue: { m: [0x4f, 0x7f, 0xe0], d: [0x24, 0x4a, 0xa0], l: [0x9c, 0xc0, 0xff] },
  purple: { m: [0x9a, 0x6f, 0xd8], d: [0x5a, 0x34, 0x9a], l: [0xd0, 0xb0, 0xf4] },
  king: { m: [0xe0, 0xb8, 0x40], d: [0xa0, 0x7a, 0x10], l: [0xff, 0xe0, 0x8a] },
  emperor: { m: [0xb0, 0x60, 0xd0], d: [0x70, 0x30, 0xa0], l: [0xe0, 0xa0, 0xf0] },
  legend: { m: [0xe8, 0x5a, 0x8a], d: [0xa0, 0x28, 0x58], l: [0xff, 0xa8, 0xc4] },
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
  // a = 变体强调色（来自变体调色板的 a 通道）
  const known = char in FIXED_COLORS || 'mdla'.includes(char)
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

/** 变体角标：画在右上角，只落笔在空白像素上，不破坏底形 */
function applyVariantMark(grid, stamp, label) {
  if (!stamp) return
  const height = stamp.length
  const width = Math.max(...stamp.map((row) => row.length))
  const offsetX = SIZE - width
  const offsetY = 0
  stamp.forEach((row, y) => {
    [...row].forEach((char, x) => {
      if (char === EMPTY || char === ' ') return
      assertKnownChar(char, `${label} 角标`)
      const targetX = offsetX + x
      const targetY = offsetY + y
      if (targetX < 0 || targetY < 0 || targetX >= SIZE || targetY >= SIZE) return
      if (grid[targetY][targetX] !== EMPTY) return
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

/** 与 shared/schema/index.ts 的 expandBaseItems() 保持一致的 id 规则（族 × 档位 × 变体） */
const BASE_VARIANT = { id: '', minTier: 0 }

function decoratedPalette(tier, tint) {
  const base = TIER_PALETTES[tier]
  if (!base) throw new Error(`缺少档位 ${tier} 的调色板`)
  return tintPalette(base, tint)
}

function listBaseItems(data) {
  const items = []
  const variants = data.variants ?? {}
  // 变体的视觉标识取自 name（FF14 职能词缀），而非 id：同一职能跨武器/防具/饰品统一配色，
  // 改名后图与名始终对应。基础型（name 为空）不染色。
  const push = (id, shape, tier, role) => {
    if (role && !ROLE_TINTS[role]) {
      throw new Error(`未知职能「${role}」（${id}），请在 ROLE_TINTS / ROLE_MARKS 中登记`)
    }
    items.push({
      id,
      shape,
      palette: decoratedPalette(tier, ROLE_TINTS[role]),
      ornament: ORNAMENTS[tier],
      variantMark: role ? ROLE_MARKS[role] : null,
    })
  }
  const forEachVariant = (list, tier, cb) => {
    for (const v of list ?? [BASE_VARIANT]) {
      if ((v.minTier ?? 0) > tier) continue
      cb(v)
    }
  }
  for (const family of data.weaponFamilies) {
    for (const tier of data.tiers) {
      forEachVariant(variants.weapon, tier.index, (v) =>
        push(`w_${family.weaponType}${v.id ? `_${v.id}` : ''}_${tier.index}`, family.weaponType, tier.index, v.name ?? ''),
      )
    }
  }
  for (const family of data.armorFamilies) {
    for (const tier of data.tiers) {
      forEachVariant(variants.armor, tier.index, (v) =>
        push(`a_${family.slot}${v.id ? `_${v.id}` : ''}_${tier.index}`, family.slot, tier.index, v.name ?? ''),
      )
    }
  }
  for (const family of data.accessoryFamilies) {
    for (const tier of data.tiers) {
      forEachVariant(variants.accessory, tier.index, (v) =>
        push(`c_${family.slot}${v.id ? `_${v.id}` : ''}_${tier.index}`, family.slot, tier.index, v.name ?? ''),
      )
    }
  }
  return items
}

/** 与 listBaseItems 同源的期望数量（用于断言镜像未漂移） */
function expectedBaseCount(data) {
  const variants = data.variants ?? {}
  const perFamily = (list) =>
    data.tiers.reduce(
      (sum, t) => sum + (list ?? [BASE_VARIANT]).filter((v) => (v.minTier ?? 0) <= t.index).length,
      0,
    )
  return (
    data.weaponFamilies.length * perFamily(variants.weapon) +
    data.armorFamilies.length * perFamily(variants.armor) +
    data.accessoryFamilies.length * perFamily(variants.accessory)
  )
}

/**
 * 绝境龙神（世界BOSS 专属系列，exclusive-equipment.json）：单一档位，武器每职业 1 件、
 * 防具/饰品每部位 2 件（强攻 / 守护）。全部使用龙金调色板 + 龙鳞王冠装饰，
 * 变体以角标区分 —— 39 件各有独立 PNG。
 * id 规则与 shared/schema 的 expandBaseItems 保持一致（族 × 档位 × 变体）。
 */
function listExclusiveItems(json) {
  const items = []
  const variants = json.variants ?? {}
  const tier = json.tiers[0].index
  const push = (id, shape, variantId) =>
    items.push({
      id,
      shape,
      palette: EXCLUSIVE_PALETTE,
      ornament: EXCLUSIVE_ORNAMENT,
      variantMark: variantId ? EXCLUSIVE_MARKS[variantId] ?? null : null,
    })
  const suffix = (v) => (v.id ? `_${v.id}` : '')
  for (const fam of json.weaponFamilies) {
    for (const v of variants.weapon ?? [{}]) push(`w_${fam.weaponType}${suffix(v)}_${tier}`, fam.weaponType, v.id)
  }
  for (const fam of json.armorFamilies) {
    for (const v of variants.armor ?? [{}]) push(`a_${fam.slot}${suffix(v)}_${tier}`, fam.slot, v.id)
  }
  for (const fam of json.accessoryFamilies) {
    for (const v of variants.accessory ?? [{}]) push(`c_${fam.slot}${suffix(v)}_${tier}`, fam.slot, v.id)
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
    const base = palettes[it.tierIndex] ?? palettes[palettes.length - 1]
    const variantId = it.variant ?? ''
    return {
      id: it.id,
      shape,
      palette: tintPalette(base, DOHDOL_TINTS[variantId]),
      ornament: null,
      variantMark: variantId ? DOHDOL_MARKS[variantId] ?? null : null,
    }
  })
}

/** 鱼获（fish.json）：普通 f{r}_{n}（按白/蓝/紫档位取色）/ 特殊鱼（鱼王 k / 鱼皇 e / 困难鱼 l） */
const FISH_SHAPE_BY_KIND = {
  normal: 'fish_normal',
  king: 'fish_king',
  emperor: 'fish_emperor',
  legend: 'fish_legend',
}
function listFish(fishJson) {
  const out = []
  const make = (id, kind, regionId, rarity) => {
    const tint = REGION_TINTS[regionId % REGION_TINTS.length]
    const key = kind === 'normal' ? rarity ?? 'white' : kind
    const spec = FISH_PALETTES[key] ?? FISH_PALETTES.white
    const base = mix(spec.m, tint, 0.3)
    out.push({ id, shape: FISH_SHAPE_BY_KIND[kind], palette: makePalette(base), ornament: null })
  }
  for (const region of fishJson.regions) {
    for (const f of region.normal) make(f.id, 'normal', region.regionId, f.rarity)
    for (const s of region.specials) make(s.id, s.kind, region.regionId)
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

/** 魔晶石（materia.json）：6 种 × 5 级；等级用装饰标记 + 亮度区分。 */
const MATERIA_COLORS = {
  str: [0xd0, 0x52, 0x4a], // 刚力（力量）
  dex: [0x5a, 0xc0, 0x6a], // 巧力（敏捷）
  int: [0x6a, 0x8a, 0xe0], // 智力
  crit: [0xe8, 0x8a, 0x30], // 武略（暴击）
  det: [0xc0, 0x8a, 0xe8], // 雄略（信念）
  dh: [0x4a, 0xc8, 0xd0], // 神眼（直击）
}

/** 魔晶石等级标记（1-5 级依次为 无 / 点 / 竖 / 十字 / 叉）。 */
const MATERIA_LEVEL_MARKS = [
  null,
  ['.....', '.....', '..o..', '.....', '.....'],
  ['.....', '..o..', '..o..', '..o..', '.....'],
  ['.....', '..o..', 'ooooo', '..o..', '.....'],
  ['o...o', '.o.o.', '..o..', '.o.o.', 'o...o'],
]

function listMateria(materiaJson) {
  const out = []
  for (const type of materiaJson.types) {
    const base = MATERIA_COLORS[type.id] ?? [0xb0, 0xa0, 0xe8]
    for (let level = 1; level <= materiaJson.grades.length; level += 1) {
      const brightness = 0.7 + level * 0.12
      out.push({
        id: `m_${type.id}_${level}`,
        shape: 'mat_materia',
        palette: makePalette(base.map((v) => v * brightness)),
        ornament: MATERIA_LEVEL_MARKS[level - 1] ?? null,
      })
    }
  }
  return out
}

/** 作物种子（farm.json：金币 / 经验种子）。 */
const SEED_COLORS = {
  seed_gold: [0xe8, 0xc3, 0x4a],
  seed_exp: [0x9a, 0x7f, 0xe0],
}

function listSeeds(farmJson) {
  return farmJson.seeds.map((seed) => {
    const base = SEED_COLORS[seed.id] ?? [0xc9, 0xa0, 0x6a]
    return { id: seed.id, shape: 'mat_seed', palette: makePalette(base), ornament: null }
  })
}

function main() {
  const data = JSON.parse(readFileSync(DATA_FILE, 'utf8'))
  const exclusiveJson = JSON.parse(readFileSync(EXCLUSIVE_FILE, 'utf8'))
  const materialsJson = JSON.parse(readFileSync(MATERIALS_FILE, 'utf8'))
  const dohdolEquipJson = JSON.parse(readFileSync(DOHDOL_EQUIP_FILE, 'utf8'))
  const fishJson = JSON.parse(readFileSync(FISH_FILE, 'utf8'))
  const consumablesJson = JSON.parse(readFileSync(CONSUMABLES_FILE, 'utf8'))
  const materiaJson = JSON.parse(readFileSync(MATERIA_FILE, 'utf8'))
  const farmJson = JSON.parse(readFileSync(FARM_FILE, 'utf8'))

  const weapons = data.weaponFamilies.length
  const armors = data.armorFamilies.length
  const accessories = data.accessoryFamilies.length
  const tiers = data.tiers.length

  const baseItems = listBaseItems(data)
  const exclusiveItems = listExclusiveItems(exclusiveJson)
  const materials = listMaterials(materialsJson)
  const dohdolItems = listDohdolItems(dohdolEquipJson)
  const fish = listFish(fishJson)
  const consumables = listConsumables(consumablesJson)
  const materia = listMateria(materiaJson)
  const seeds = listSeeds(farmJson)

  const expectedBase = expectedBaseCount(data)
  if (baseItems.length !== expectedBase) {
    throw new Error(`底材数量不符：期望 ${expectedBase}，实际 ${baseItems.length}`)
  }

  const items = [
    ...baseItems,
    ...exclusiveItems,
    ...materials,
    ...dohdolItems,
    ...fish,
    ...consumables,
    ...materia,
    ...seeds,
  ]

  mkdirSync(OUT_DIR, { recursive: true })

  let totalBytes = 0
  const written = new Set()

  for (const item of items) {
    const macro = SHAPES[item.shape]
    if (!macro) throw new Error(`缺少「${item.shape}」的底形定义（${item.id}）`)

    const grid = blankGrid()
    drawCentered(grid, macro, item.id)
    if (item.ornament) applyOrnament(grid, item.ornament, item.id)
    if (item.variantMark) applyVariantMark(grid, item.variantMark, item.id)

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
      ` + 绝境龙神 ${exclusiveItems.length} + 材料/半成品 ${materials.length} + 专用装备 ${dohdolItems.length}` +
      ` + 鱼获 ${fish.length} + 药水食物 ${consumables.length} + 魔晶石 ${materia.length} + 种子 ${seeds.length}`,
  )
}

main()

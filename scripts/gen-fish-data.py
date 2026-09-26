#!/usr/bin/env python3
"""生成 `shared/data/fish.json`（钓鱼系统 2.0）。

设计：**加性改造，保留旧 id 与旧数值**。
  - 旧数据冻结在 `scripts/fish-base.json`（唯一真源），脚本始终从它重建，保证可重复生成。
  - 旧 `king` / `emperor` 迁移进 `specials[]`，`id` 不变（k1..k40 / e1..e40），标记 `legacy: true`，
    并把 `prereqFishIds` / `insightSeconds` / `chance` 改写为统一的 `intuition` 结构。
  - 每个地区新增 2 条蓝鱼 + 1 条紫鱼（`normal`，`rarity: blue|purple`，可选天气/时间门槛）。
  - 新增 `kind: "legend"` 的困难鱼（含七彩家族链、镜中蝶等），天气/时间门槛 + 计数型前置。
  - 平衡调整：所有「捕鱼人之识」BUFF 持续时间统一为 30s；鱼王 / 鱼皇出现概率 ×2。
    该调整在生成阶段统一施加（`INSIGHT_DURATION_SEC` / `KING_EMPEROR_CHANCE_MULT`），
    `fish-base.json` 仍冻结旧数值。
  - 困难鱼定价：不再用固定倍率，而是以同区鱼王 / 鱼皇单价为锚、按「实际有效概率」定价——
    把天气/时段窗口开启率、攒前置鱼的开销、鱼识 BUFF 判定一起折算成预期抛竿数 E，
    单价 = 鱼王单价 × (E / E_鱼王)^β（β 逐区由鱼王 / 鱼皇两点拟合），越难钓越贵。见 `_region_effort`。

运行：`python scripts/gen-fish-data.py`
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = ROOT / "scripts" / "fish-base.json"
WEATHER = ROOT / "shared" / "data" / "weather.json"
OUT = ROOT / "shared" / "data" / "fish.json"

# ───────────────────────────── 每个地区的新增普通鱼 ─────────────────────────────
# blue ×2 + purple ×1。weather / timeOfDay 为可选门槛（必须落在该地区天气表内）。
EXTRA_NORMAL: dict[int, dict[str, Any]] = {
    1: {"blue": [{"name": "珊瑚蝶鱼", "weather": ["clearSkies", "fairSkies"]}, {"name": "银鳞鲳", "weather": ["rain"]}],
        "purple": {"name": "月光水母", "timeOfDay": ["night"]}},
    2: {"blue": [{"name": "蓝鳍梭鱼", "weather": ["clearSkies", "fairSkies"]}, {"name": "浪花鲹", "weather": ["fog"]}],
        "purple": {"name": "海月水母", "timeOfDay": ["night"]}},
    3: {"blue": [{"name": "斑点鲼", "weather": ["fog"]}, {"name": "石首鱼", "weather": ["clouds"]}],
        "purple": {"name": "深渊提灯鱼", "timeOfDay": ["night"]}},
    4: {"blue": [{"name": "沙漠鲹", "weather": ["heatWaves"]}, {"name": "沙丘鳅", "weather": ["dustStorms"]}],
        "purple": {"name": "赤沙王鲷", "timeOfDay": ["night"]}},
    5: {"blue": [{"name": "灼热鲈", "weather": ["heatWaves"]}, {"name": "砂砾鲶", "weather": ["dustStorms"]}],
        "purple": {"name": "幻影蜥鱼", "timeOfDay": ["night"]}},
    6: {"blue": [{"name": "苔藓鳟", "weather": ["rain"]}, {"name": "林间鳜", "weather": ["fog"]}],
        "purple": {"name": "幽林木灵鱼", "timeOfDay": ["night"]}},
    7: {"blue": [{"name": "落叶鲑", "weather": ["rain"]}, {"name": "树影鲫", "weather": ["fog"]}],
        "purple": {"name": "夜枭鱼", "timeOfDay": ["night"]}},
    8: {"blue": [{"name": "风蚀鲤", "weather": ["dustStorms"]}, {"name": "旱地鳅", "weather": ["heatWaves"]}],
        "purple": {"name": "金沙鳞鱼", "timeOfDay": ["night"]}},
    9: {"blue": [{"name": "沙暴鲈", "weather": ["dustStorms"]}, {"name": "绿洲鳟", "weather": ["clearSkies", "fairSkies"]}],
        "purple": {"name": "蜃楼鱼", "weather": ["heatWaves"]}},
    10: {"blue": [{"name": "迷雾鳟", "weather": ["rain"]}, {"name": "高地鲈", "weather": ["gales"]}],
         "purple": {"name": "星尘水母", "timeOfDay": ["night"]}},
    11: {"blue": [{"name": "冰晶鲑", "weather": ["snow"]}, {"name": "寒霜鳕", "weather": ["blizzards"]}],
         "purple": {"name": "极光蝶鱼", "timeOfDay": ["night"]}},
    12: {"blue": [{"name": "雪原鳟", "weather": ["snow"]}, {"name": "霜牙梭子鱼", "weather": ["blizzards"]}],
         "purple": {"name": "冬夜鲟", "timeOfDay": ["night"]}},
    13: {"blue": [{"name": "苍穹旗鱼", "weather": ["gales"]}, {"name": "云海鳟", "weather": ["clouds"]}],
         "purple": {"name": "龙鳞鱼", "timeOfDay": ["day"]}},
    14: {"blue": [{"name": "云雾鲳", "weather": ["clouds"]}, {"name": "风语鳟", "weather": ["gales"]}],
         "purple": {"name": "天穹水母", "timeOfDay": ["night"]}},
    15: {"blue": [{"name": "苔原鲈", "weather": ["clouds"]}, {"name": "溪谷虹鳟", "weather": ["rain"]}],
         "purple": {"name": "古龙鳕", "timeOfDay": ["night"]}},
    16: {"blue": [{"name": "田园鲫", "weather": ["clearSkies", "fairSkies"]}, {"name": "牧草鲑", "weather": ["rain"]}],
         "purple": {"name": "萤火提灯鱼", "timeOfDay": ["dawn"]}},
    17: {"blue": [{"name": "高原鳟", "weather": ["clearSkies", "fairSkies"]}, {"name": "岩壁鲈", "weather": ["gales"]}],
         "purple": {"name": "翡翠水母", "timeOfDay": ["night"]}},
    18: {"blue": [{"name": "山涧虹鳟", "weather": ["rain"]}, {"name": "峭壁鲶", "weather": ["gales"]}],
         "purple": {"name": "石纹鲵", "timeOfDay": ["night"]}},
    19: {"blue": [{"name": "红玉鲷", "weather": ["clearSkies", "fairSkies"]}, {"name": "碧波旗鱼", "weather": ["rain"]}],
         "purple": {"name": "珊瑚夜光鱼", "timeOfDay": ["night"]}},
    20: {"blue": [{"name": "樱花鲑", "weather": ["clearSkies", "fairSkies"]}, {"name": "潮汐鲳", "weather": ["thunderstorms"]}],
         "purple": {"name": "月下章鱼", "timeOfDay": ["dusk"]}},
    21: {"blue": [{"name": "草原鳟", "weather": ["clearSkies", "fairSkies"]}, {"name": "疾风鲈", "weather": ["gales"]}],
         "purple": {"name": "草原夜光鲤", "timeOfDay": ["night"]}},
    22: {"blue": [{"name": "黄金鲹", "weather": ["clearSkies", "fairSkies"]}, {"name": "港町鲭", "weather": ["rain"]}],
         "purple": {"name": "宵灯水母", "timeOfDay": ["night"]}},
    23: {"blue": [{"name": "雾岛鲑", "weather": ["fog"]}, {"name": "湖光鳟", "weather": ["clouds"]}],
         "purple": {"name": "幽谷大鲵", "timeOfDay": ["night"]}},
    24: {"blue": [{"name": "灼沙鲈", "weather": ["heatWaves"]}, {"name": "荒漠鲶", "weather": ["dustStorms"]}],
         "purple": {"name": "沙海幻鱼", "timeOfDay": ["night"]}},
    25: {"blue": [{"name": "蝶翼鳟", "weather": ["clearSkies", "fairSkies"]}, {"name": "仙灵鲑", "weather": ["fog"]}],
         "purple": {"name": "妖精湖灯鱼", "timeOfDay": ["night"]}},
    26: {"blue": [{"name": "雷云鳟", "weather": ["clouds"]}, {"name": "雪岭鳕", "weather": ["snow"]}],
         "purple": {"name": "永夜鲟", "timeOfDay": ["night"]}},
    27: {"blue": [{"name": "雨林鳜", "weather": ["rain"]}, {"name": "藤蔓鲶", "weather": ["fog"]}],
         "purple": {"name": "丛林幽光鱼", "timeOfDay": ["night"]}},
    28: {"blue": [{"name": "黑风旗鱼", "weather": ["gales"]}, {"name": "雷暴鲹", "weather": ["thunderstorms"]}],
         "purple": {"name": "深渊灯笼鱼", "timeOfDay": ["night"]}},
    29: {"blue": [{"name": "象鲷", "weather": ["clearSkies", "fairSkies"]}, {"name": "遗辉鲳", "weather": ["rain"]}],
         "purple": {"name": "神殿夜光鱼", "timeOfDay": ["night"]}},
    30: {"blue": [{"name": "寒钢鳟", "weather": ["gales"]}, {"name": "军港鲈", "weather": ["clouds"]}],
         "purple": {"name": "冰宫水母", "timeOfDay": ["night"]}},
    31: {"blue": [{"name": "悲叹鲹", "weather": ["rain"]}, {"name": "泪海旗鱼", "weather": ["thunderstorms"]}],
         "purple": {"name": "深海幽灵鱼", "timeOfDay": ["night"]}},
    32: {"blue": [{"name": "星霜鳕", "weather": ["snow"]}, {"name": "天外鲑", "weather": ["blizzards"]}],
         "purple": {"name": "极星水母", "timeOfDay": ["night"]}},
    33: {"blue": [{"name": "乐园鲷", "weather": ["clearSkies", "fairSkies"]}, {"name": "花海鳟", "weather": ["rain"]}],
         "purple": {"name": "神域灯鱼", "timeOfDay": ["day"]}},
    34: {"blue": [{"name": "迷宫鳜", "weather": ["fog"]}, {"name": "幽径鲶", "weather": ["rain"]}],
         "purple": {"name": "幻境水母", "timeOfDay": ["night"]}},
    35: {"blue": [{"name": "图拉尔旗鱼", "weather": ["clearSkies", "fairSkies"]}, {"name": "礁湖鲳", "weather": ["rain"]}],
         "purple": {"name": "浅海夜光鱼", "timeOfDay": ["night"]}},
    36: {"blue": [{"name": "雨林象鱼", "weather": ["rain"]}, {"name": "藤桥鲶", "weather": ["thunderstorms"]}],
         "purple": {"name": "密林幽光鱼", "timeOfDay": ["night"]}},
    37: {"blue": [{"name": "遗迹鲈", "weather": ["dustStorms"]}, {"name": "王墓鳅", "weather": ["heatWaves"]}],
         "purple": {"name": "王都夜光鱼", "timeOfDay": ["dusk"]}},
    38: {"blue": [{"name": "熔岩鳟", "weather": ["heatWaves"]}, {"name": "火山鲶", "weather": ["clearSkies", "fairSkies"]}],
         "purple": {"name": "熔核水母", "timeOfDay": ["night"]}},
    39: {"blue": [{"name": "王都鲷", "weather": ["clearSkies", "fairSkies"]}, {"name": "护城旗鱼", "weather": ["clouds"]}],
         "purple": {"name": "星芒水母", "timeOfDay": ["night"]}},
    40: {"blue": [{"name": "圣域鳟", "weather": ["clearSkies", "fairSkies"]}, {"name": "天启鲑", "weather": ["rain"]}],
         "purple": {"name": "原初水母", "timeOfDay": ["night"]}},
}

# ───────────────────────────── 困难鱼（legend） ─────────────────────────────
# 字段：id/name/weather/timeOfDay/requires[(fishId,count)]/duration/chance + 可选 sizeMul/expMul。
# 默认（普通 legend）：size = base_size×(2.4, 3.6)，exp = base_exp×25。
# sell 不再由倍率给出，统一按有效概率折算的预期抛竿数定价（见 `_region_effort`）。
LEGENDS: dict[int, list[dict[str, Any]]] = {
    3: [{"id": "l3_sea_god", "name": "海神", "weather": ["rain"], "timeOfDay": ["night"],
         "requires": [("f3_7", 1)], "duration": [50, 80], "chance": 0.0012}],
    5: [{"id": "l5_mirage", "name": "幻影王鲷", "weather": ["heatWaves", "dustStorms"],
         "requires": [("f5_7", 1)], "duration": [50, 80], "chance": 0.0012}],
    6: [{"id": "l6_wood_catfish", "name": "幽林巨鲶", "weather": ["fog"], "timeOfDay": ["night"],
         "requires": [("f6_7", 1)], "duration": [50, 80], "chance": 0.0012}],
    10: [{"id": "l10_skull", "name": "骷髅王鲶", "weather": ["gales"],
          "requires": [("f10_7", 1)], "duration": [50, 80], "chance": 0.001}],
    11: [{"id": "l11_glacier_sturgeon", "name": "冰川鲟", "weather": ["blizzards"],
          "requires": [("f11_7", 1)], "duration": [50, 80], "chance": 0.001}],
    12: [{"id": "l12_aurora_whale", "name": "极光鲸", "weather": ["blizzards"], "timeOfDay": ["night"],
          "requires": [("f12_7", 1)], "duration": [60, 90], "chance": 0.0008}],
    13: [{"id": "l13_cloud_butterfly", "name": "云蝶", "weather": ["gales"], "timeOfDay": ["day"],
          "requires": [("f13_7", 1)], "duration": [40, 60], "chance": 0.0008}],
    16: [{"id": "l16_pegasus", "name": "天马", "weather": ["clearSkies", "fairSkies"], "timeOfDay": ["dawn"],
          "requires": [("f16_7", 1)], "duration": [40, 70], "chance": 0.001}],
    19: [{"id": "l19_megalodon", "name": "巨齿鲨", "weather": ["thunderstorms"],
          "requires": [("f19_7", 1)], "duration": [50, 80], "chance": 0.001}],
    20: [{"id": "l20_sail", "name": "帆", "weather": ["thunderstorms"], "timeOfDay": ["dusk"],
          "requires": [("f20_7", 1)], "duration": [45, 70], "chance": 0.0008}],
    21: [
        {"id": "l21_purple", "name": "紫彩鱼", "requires": [("f21_1", 1)],
         "duration": [40, 60], "chance": 0.06, "sizeMul": [0.9, 1.4], "expMul": 8},
        {"id": "l21_blue", "name": "蓝彩鱼", "requires": [("l21_purple", 1)],
         "duration": [40, 60], "chance": 0.05, "sizeMul": [0.9, 1.4], "expMul": 8},
        {"id": "l21_red", "name": "红彩鱼", "requires": [("f21_2", 1)],
         "duration": [40, 60], "chance": 0.06, "sizeMul": [0.9, 1.4], "expMul": 8},
        {"id": "l21_orange", "name": "橙彩鱼", "requires": [("l21_red", 1)],
         "duration": [40, 60], "chance": 0.05, "sizeMul": [0.9, 1.4], "expMul": 8},
        {"id": "l21_green", "name": "绿彩鱼", "requires": [("f21_5", 1)],
         "duration": [40, 60], "chance": 0.05, "sizeMul": [0.9, 1.4], "expMul": 8},
        {"id": "l21_hue_lord", "name": "七彩天主", "weather": ["clearSkies", "fairSkies"],
         "requires": [("l21_blue", 3), ("l21_orange", 3), ("l21_green", 5)],
         "duration": [60, 90], "chance": 0.0004,
         "sizeMul": [3.0, 4.5], "expMul": 60},
    ],
    25: [{"id": "l25_mirror_butterfly", "name": "镜中蝶", "weather": ["clearSkies", "fairSkies"], "timeOfDay": ["night"],
          "requires": [("f25_7", 2)], "duration": [30, 45], "chance": 0.0006}],
    28: [{"id": "l28_kraken", "name": "大王乌贼", "weather": ["gales", "thunderstorms"],
          "requires": [("f28_7", 1)], "duration": [50, 80], "chance": 0.001}],
    29: [{"id": "l29_phantom_dragon", "name": "幻龙", "weather": ["rain"],
          "requires": [("f29_7", 1)], "duration": [50, 80], "chance": 0.001}],
    31: [{"id": "l31_abyss_king", "name": "深渊王", "weather": ["thunderstorms"], "timeOfDay": ["night"],
          "requires": [("f31_7", 1)], "duration": [60, 90], "chance": 0.0008}],
    32: [{"id": "l32_white_whale", "name": "白鲸", "weather": ["snow", "blizzards"],
          "requires": [("f32_7", 1)], "duration": [50, 80], "chance": 0.001}],
    33: [{"id": "l33_holy_dragon", "name": "圣龙", "weather": ["clearSkies", "fairSkies"], "timeOfDay": ["day"],
          "requires": [("f33_7", 1)], "duration": [50, 80], "chance": 0.0008}],
    34: [{"id": "l34_star_whale", "name": "星鲸", "weather": ["fog"], "timeOfDay": ["night"],
          "requires": [("f34_7", 1)], "duration": [45, 70], "chance": 0.0006}],
    37: [{"id": "l37_golden_god", "name": "黄金神鱼", "weather": ["dustStorms"], "timeOfDay": ["dusk"],
          "requires": [("f37_7", 1)], "duration": [50, 80], "chance": 0.0008}],
    38: [{"id": "l38_lava_leviathan", "name": "熔岩鲲", "weather": ["heatWaves", "clearSkies", "fairSkies"],
          "requires": [("f38_7", 1)], "duration": [50, 80], "chance": 0.0008}],
    39: [{"id": "l39_black_tortoise", "name": "玄武巨龟", "weather": ["rain"], "timeOfDay": ["night"],
          "requires": [("f39_7", 1)], "duration": [60, 90], "chance": 0.0008}],
    40: [{"id": "l40_creator", "name": "创世神鱼", "weather": ["thunderstorms"], "timeOfDay": ["night"],
          "requires": [("f40_7", 1)], "duration": [60, 90], "chance": 0.0006}],
}

BLUE_WEIGHTS = (5, 3)
PURPLE_WEIGHT = 2

# ───────────────────────────── 新增特殊鱼（真实 FF14 鱼名） ─────────────────────────────
# 在旧内容（legacy 鱼王 / 鱼皇 + 第一批困难鱼）之上，给每个地区再补：
#   1 条新鱼王 + 1 条新鱼皇 + 若干条新困难鱼（真实 FF14「崽种鱼」，落到真实地图）。
# 字段：kind(king/emperor/legend)、id、name、chance，
#   可选 weather / timeOfDay（必须落在该区天气表内）、requires[(fishId,count)]（计数型前置，
#   触发「捕鱼人之识」）、intuitionName（默认鱼王/鱼皇用「捕鱼人之识」，困难鱼用「{name}之识」）、
#   sizeMul / expMul（默认按 kind）。
# 概率刻意逐条不同（不要所有鱼王/鱼皇一个概率），且均比同区 legacy 鱼王/鱼皇更稀有——
# 既保证「越难钓越贵」，也保证不会成为比旧鱼王更优的刷钱路线。
_DEFAULT_SIZE_MUL: dict[str, list[float]] = {
    "king": [1.6, 2.4],
    "emperor": [2.0, 3.0],
    "legend": [2.4, 3.6],
}
_DEFAULT_EXP_MUL: dict[str, int] = {"king": 15, "emperor": 20, "legend": 25}

NEW_SPECIALS: dict[int, list[dict[str, Any]]] = {
    # 名字取自 FF14 真实钓场之王 / 钓场之皇（灰机 wiki / eorzea-weather / 饥饿的猫），落到对应真实地图；
    # 困难鱼的天气 / 时段门槛尽量还原该鱼在 FF14 的真实窗口。概率逐条不同。
    1: [
        {"kind": "king", "id": "k2_1", "name": "扎尔艾拉", "chance": 0.018, "requires": [("f1_1", 1)]},
        {"kind": "emperor", "id": "e2_1", "name": "无赖王", "chance": 0.005, "requires": [("f1_2", 1)]},
    ],
    2: [
        {"kind": "king", "id": "k2_2", "name": "拾荒鮟鱇", "chance": 0.012, "requires": [("f2_1", 1)]},
        {"kind": "emperor", "id": "e2_2", "name": "皱鳃鲨", "chance": 0.004, "requires": [("f2_2", 1)]},
        {"kind": "legend", "id": "l2_antipode", "name": "内角石", "chance": 0.0009,
         "weather": ["clouds"], "timeOfDay": ["night"], "requires": [("f2_1", 1)]},
    ],
    3: [
        {"kind": "king", "id": "k2_3", "name": "高声鲶鱼", "chance": 0.016, "requires": [("f3_1", 1)]},
        {"kind": "emperor", "id": "e2_3", "name": "银君", "chance": 0.006, "requires": [("f3_2", 1)]},
    ],
    4: [
        {"kind": "king", "id": "k2_4", "name": "滑溜帝王", "chance": 0.010, "requires": [("f4_1", 1)]},
        {"kind": "emperor", "id": "e2_4", "name": "暗骑士", "chance": 0.003, "requires": [("f4_2", 1)]},
    ],
    5: [
        {"kind": "king", "id": "k2_5", "name": "铜镜", "chance": 0.014, "requires": [("f5_1", 1)]},
        {"kind": "emperor", "id": "e2_5", "name": "断指龙虾", "chance": 0.005, "requires": [("f5_2", 1)]},
    ],
    6: [
        {"kind": "king", "id": "k2_6", "name": "外科医生", "chance": 0.008, "requires": [("f6_1", 1)]},
        {"kind": "emperor", "id": "e2_6", "name": "人面鲤", "chance": 0.002, "requires": [("f6_2", 1)]},
        {"kind": "legend", "id": "l6_otaro", "name": "波太郎", "chance": 0.0008,
         "weather": ["fog"], "timeOfDay": ["night"], "requires": [("f6_1", 1)]},
    ],
    7: [
        {"kind": "king", "id": "k2_7", "name": "暗兵鳢", "chance": 0.015, "requires": [("f7_1", 1)]},
        {"kind": "emperor", "id": "e2_7", "name": "终结者", "chance": 0.006, "requires": [("f7_2", 1)]},
    ],
    8: [
        {"kind": "king", "id": "k2_8", "name": "净髓蜗牛", "chance": 0.011, "requires": [("f8_1", 1)]},
        {"kind": "emperor", "id": "e2_8", "name": "千年殇", "chance": 0.003, "requires": [("f8_2", 1)]},
    ],
    9: [
        {"kind": "king", "id": "k2_9", "name": "虚空之眼", "chance": 0.013, "requires": [("f9_1", 1)]},
        {"kind": "emperor", "id": "e2_9", "name": "铁饼", "chance": 0.005, "requires": [("f9_2", 1)]},
        {"kind": "legend", "id": "l9_helicoprion", "name": "旋齿鲨", "chance": 0.0010,
         "weather": ["heatWaves"], "timeOfDay": ["day"], "requires": [("f9_1", 1)]},
    ],
    10: [
        {"kind": "king", "id": "k2_10", "name": "血红龙", "chance": 0.007, "requires": [("f10_1", 1)]},
        {"kind": "emperor", "id": "e2_10", "name": "加诺", "chance": 0.002, "requires": [("f10_2", 1)]},
        {"kind": "legend", "id": "l10_kuuno", "name": "杀手库诺", "chance": 0.0010,
         "weather": ["gales"], "timeOfDay": ["day"], "requires": [("f10_1", 1)]},
    ],
    11: [
        {"kind": "king", "id": "k2_11", "name": "暗星", "chance": 0.017, "requires": [("f11_1", 1)]},
        {"kind": "emperor", "id": "e2_11", "name": "黎明少女", "chance": 0.004, "requires": [("f11_2", 1)]},
        {"kind": "legend", "id": "l11_shoni", "name": "秀尼鱼龙", "chance": 0.0008,
         "weather": ["blizzards"], "timeOfDay": ["day"], "requires": [("f11_1", 1)]},
    ],
    12: [
        {"kind": "king", "id": "k2_12", "name": "核爆鱼", "chance": 0.009, "requires": [("f12_1", 1)]},
        {"kind": "emperor", "id": "e2_12", "name": "冰之巫女", "chance": 0.003, "requires": [("f12_2", 1)]},
        {"kind": "legend", "id": "l12_shariben", "name": "沙里贝涅", "chance": 0.0006,
         "weather": ["blizzards"], "timeOfDay": ["night"], "requires": [("f12_1", 1)]},
    ],
    13: [
        {"kind": "king", "id": "k2_13", "name": "熔岩帝王", "chance": 0.012, "requires": [("f13_1", 1)]},
        {"kind": "emperor", "id": "e2_13", "name": "龙鳞撕裂者", "chance": 0.006, "requires": [("f13_2", 1)]},
        {"kind": "legend", "id": "l13_lava", "name": "莫名熔岩鱼", "chance": 0.0008,
         "weather": ["clearSkies", "fairSkies"], "timeOfDay": ["day"], "requires": [("f13_1", 1)]},
    ],
    14: [
        {"kind": "king", "id": "k2_14", "name": "维德弗尼尔", "chance": 0.019, "requires": [("f14_1", 1)]},
        {"kind": "emperor", "id": "e2_14", "name": "风暴血骑士", "chance": 0.005, "requires": [("f14_2", 1)]},
        {"kind": "legend", "id": "l14_vandrel", "name": "兰代勒翼龙", "chance": 0.0007,
         "weather": ["gales"], "timeOfDay": ["dawn"], "requires": [("f14_1", 1)]},
        {"kind": "legend", "id": "l14_butterfly_snail", "name": "云海蝴蝶螺", "chance": 0.0006,
         "weather": ["gales"], "timeOfDay": ["day"], "requires": [("f14_2", 1)]},
    ],
    15: [
        {"kind": "king", "id": "k2_15", "name": "水瓶王", "chance": 0.006, "requires": [("f15_1", 1)]},
        {"kind": "emperor", "id": "e2_15", "name": "蝴蝶夫人", "chance": 0.002, "requires": [("f15_2", 1)]},
        {"kind": "legend", "id": "l15_kai", "name": "铠鱼", "chance": 0.0009,
         "weather": ["clearSkies", "fairSkies"], "timeOfDay": ["night"], "requires": [("f15_1", 1)]},
        {"kind": "legend", "id": "l15_eobabin", "name": "欧巴宾海蝎", "chance": 0.0006,
         "weather": ["clouds"], "timeOfDay": ["night"], "requires": [("f15_2", 1)]},
    ],
    16: [
        {"kind": "king", "id": "k2_16", "name": "能言者", "chance": 0.014, "requires": [("f16_1", 1)]},
        {"kind": "emperor", "id": "e2_16", "name": "万事通鲈", "chance": 0.004, "requires": [("f16_2", 1)]},
    ],
    17: [
        {"kind": "king", "id": "k2_17", "name": "教皇鱼", "chance": 0.010, "requires": [("f17_1", 1)]},
        {"kind": "emperor", "id": "e2_17", "name": "骸鲢鱼", "chance": 0.003, "requires": [("f17_2", 1)]},
        {"kind": "legend", "id": "l17_ishiken", "name": "异刺鲨", "chance": 0.0008,
         "weather": ["gales"], "timeOfDay": ["dusk"], "requires": [("f17_1", 1)]},
        {"kind": "legend", "id": "l17_thorax", "name": "胸脊鲨", "chance": 0.0006,
         "weather": ["clearSkies", "fairSkies"], "timeOfDay": ["day"], "requires": [("f17_2", 1)]},
    ],
    18: [
        {"kind": "king", "id": "k2_18", "name": "最后一滴泪", "chance": 0.016, "requires": [("f18_1", 1)]},
        {"kind": "emperor", "id": "e2_18", "name": "黑蒙鱼", "chance": 0.006, "requires": [("f18_2", 1)]},
        {"kind": "legend", "id": "l18_sickle", "name": "镰甲鱼", "chance": 0.0007,
         "weather": ["gales"], "timeOfDay": ["day"], "requires": [("f18_1", 1)]},
    ],
    19: [
        {"kind": "king", "id": "k2_19", "name": "菜食王", "chance": 0.008, "requires": [("f19_1", 1)]},
        {"kind": "emperor", "id": "e2_19", "name": "七星", "chance": 0.002, "requires": [("f19_2", 1)]},
        {"kind": "legend", "id": "l19_red_dragon", "name": "红龙", "chance": 0.0006,
         "weather": ["clouds"], "timeOfDay": ["dawn"], "requires": [("f19_1", 1)]},
    ],
    20: [
        {"kind": "king", "id": "k2_20", "name": "鬼视", "chance": 0.013, "requires": [("f20_1", 1)]},
        {"kind": "emperor", "id": "e2_20", "name": "水天一碧", "chance": 0.005, "requires": [("f20_2", 1)]},
    ],
    21: [
        {"kind": "king", "id": "k2_21", "name": "晨曦旗鱼", "chance": 0.011, "requires": [("f21_1", 1)]},
        {"kind": "emperor", "id": "e2_21", "name": "月神的爱宠", "chance": 0.003, "requires": [("f21_2", 1)]},
        {"kind": "legend", "id": "l21_gods_love", "name": "众神之爱", "chance": 0.0007,
         "weather": ["clearSkies", "fairSkies"], "timeOfDay": ["dawn"], "requires": [("f21_1", 1)]},
    ],
    22: [
        {"kind": "king", "id": "k2_22", "name": "花海龙", "chance": 0.018, "requires": [("f22_1", 1)]},
        {"kind": "emperor", "id": "e2_22", "name": "赌命河豚", "chance": 0.004, "requires": [("f22_2", 1)]},
    ],
    23: [
        {"kind": "king", "id": "k2_23", "name": "元首的军扇", "chance": 0.009, "requires": [("f23_1", 1)]},
        {"kind": "emperor", "id": "e2_23", "name": "战盾剑齿龙鳖", "chance": 0.006, "requires": [("f23_2", 1)]},
        {"kind": "legend", "id": "l23_automaton", "name": "自走鱼偶", "chance": 0.0007,
         "weather": ["fog"], "timeOfDay": ["day"], "requires": [("f23_1", 1)]},
    ],
    24: [
        {"kind": "king", "id": "k2_24", "name": "冠骨鱼", "chance": 0.015, "requires": [("f24_1", 1)]},
        {"kind": "emperor", "id": "e2_24", "name": "刺钉蜥蜴", "chance": 0.002, "requires": [("f24_2", 1)]},
        {"kind": "legend", "id": "l24_surprise_egg", "name": "惊喜蛋", "chance": 0.0005,
         "weather": ["dustStorms"], "timeOfDay": ["night"], "requires": [("f24_1", 1)]},
    ],
    25: [
        {"kind": "king", "id": "k2_25", "name": "狂怒斗鱼", "chance": 0.007, "requires": [("f25_1", 1)]},
        {"kind": "emperor", "id": "e2_25", "name": "深泳的古书", "chance": 0.005, "requires": [("f25_2", 1)]},
    ],
    26: [
        {"kind": "king", "id": "k2_26", "name": "食人鳄", "chance": 0.012, "requires": [("f26_1", 1)]},
        {"kind": "emperor", "id": "e2_26", "name": "蟒斑盘丽鱼", "chance": 0.003, "requires": [("f26_2", 1)]},
        {"kind": "legend", "id": "l26_listrac", "name": "利斯塔克鲨", "chance": 0.0006,
         "weather": ["clouds"], "timeOfDay": ["dusk"], "requires": [("f26_1", 1)]},
    ],
    27: [
        {"kind": "king", "id": "k2_27", "name": "珍珠皮皮拉鱼", "chance": 0.020, "requires": [("f27_1", 1)]},
        {"kind": "emperor", "id": "e2_27", "name": "黑色喷气乱流", "chance": 0.004, "requires": [("f27_2", 1)]},
        {"kind": "legend", "id": "l27_lonka", "name": "隆卡的大水蛇？", "chance": 0.0008,
         "weather": ["fog"], "timeOfDay": ["day"], "requires": [("f27_1", 1)]},
    ],
    28: [
        {"kind": "king", "id": "k2_28", "name": "猎星鱼", "chance": 0.010, "requires": [("f28_1", 1)]},
        {"kind": "emperor", "id": "e2_28", "name": "头领薄饼章鱼", "chance": 0.006, "requires": [("f28_2", 1)]},
        {"kind": "legend", "id": "l28_sailfish", "name": "长吻帆蜥鱼", "chance": 0.0007,
         "weather": ["clouds"], "timeOfDay": ["night"], "requires": [("f28_1", 1)]},
    ],
    29: [
        {"kind": "king", "id": "k2_29", "name": "杜蒂娜鱼", "chance": 0.014, "requires": [("f29_1", 1)]},
        {"kind": "emperor", "id": "e2_29", "name": "雷云隆头鱼", "chance": 0.002, "requires": [("f29_2", 1)]},
        {"kind": "legend", "id": "l29_gaer", "name": "嘎儿鱼", "chance": 0.0006,
         "weather": ["rain"], "timeOfDay": ["dusk"], "requires": [("f29_1", 1)]},
    ],
    30: [
        {"kind": "king", "id": "k2_30", "name": "雾凇狗鱼", "chance": 0.008, "requires": [("f30_1", 1)]},
        {"kind": "emperor", "id": "e2_30", "name": "暗影帝冠", "chance": 0.005, "requires": [("f30_2", 1)]},
        {"kind": "legend", "id": "l30_snowthorn", "name": "异形雪棘", "chance": 0.0006,
         "weather": ["clearSkies", "fairSkies"], "timeOfDay": ["dusk"], "requires": [("f30_1", 1)]},
    ],
    31: [
        {"kind": "king", "id": "k2_31", "name": "荧光死亡蠕虫", "chance": 0.016, "requires": [("f31_1", 1)]},
        {"kind": "emperor", "id": "e2_31", "name": "冰月壤龟", "chance": 0.003, "requires": [("f31_2", 1)]},
        {"kind": "legend", "id": "l31_rabbit_ear", "name": "优雅兔耳", "chance": 0.0007,
         "weather": ["clearSkies", "fairSkies"], "timeOfDay": ["day"], "requires": [("f31_1", 1)]},
    ],
    32: [
        {"kind": "king", "id": "k2_32", "name": "骇惊威", "chance": 0.011, "requires": [("f32_1", 1)]},
        {"kind": "emperor", "id": "e2_32", "name": "运行星", "chance": 0.004, "requires": [("f32_2", 1)]},
    ],
    33: [
        {"kind": "king", "id": "k2_33", "name": "金光皮颏鱵", "chance": 0.013, "requires": [("f33_1", 1)]},
        {"kind": "emperor", "id": "e2_33", "name": "大丽花冠鮨", "chance": 0.006, "requires": [("f33_2", 1)]},
        {"kind": "legend", "id": "l33_forktail", "name": "餐叉尾", "chance": 0.0007,
         "weather": ["thunderstorms"], "timeOfDay": ["day"], "requires": [("f33_1", 1)]},
    ],
    34: [
        {"kind": "king", "id": "k2_34", "name": "巨身锯盖鱼", "chance": 0.007, "requires": [("f34_1", 1)]},
        {"kind": "emperor", "id": "e2_34", "name": "黑玛瑙刀背鱼", "chance": 0.002, "requires": [("f34_2", 1)]},
        {"kind": "legend", "id": "l34_serpent", "name": "潜龙", "chance": 0.0005,
         "weather": ["clearSkies", "fairSkies"], "timeOfDay": ["day"], "requires": [("f34_1", 1)]},
    ],
    35: [
        {"kind": "king", "id": "k2_35", "name": "麻瘩玛塔蛇颈龟", "chance": 0.017, "requires": [("f35_1", 1)]},
        {"kind": "emperor", "id": "e2_35", "name": "锅盖蟹", "chance": 0.005, "requires": [("f35_2", 1)]},
        {"kind": "legend", "id": "l35_jade", "name": "水没翠玉", "chance": 0.0006,
         "weather": ["rain"], "timeOfDay": ["day"], "requires": [("f35_1", 1)]},
    ],
    36: [
        {"kind": "king", "id": "k2_36", "name": "战地巨雀鳝", "chance": 0.009, "requires": [("f36_1", 1)]},
        {"kind": "emperor", "id": "e2_36", "name": "星尘睡鱼", "chance": 0.003, "requires": [("f36_2", 1)]},
        {"kind": "legend", "id": "l36_heart", "name": "碧空之心", "chance": 0.0007,
         "weather": ["rain"], "timeOfDay": ["dusk"], "requires": [("f36_1", 1)]},
    ],
    37: [
        {"kind": "king", "id": "k2_37", "name": "南瓜芽太阳鱼", "chance": 0.015, "requires": [("f37_1", 1)]},
        {"kind": "emperor", "id": "e2_37", "name": "遗产石斑鱼", "chance": 0.004, "requires": [("f37_2", 1)]},
        {"kind": "legend", "id": "l37_ball", "name": "闪电球", "chance": 0.0005,
         "weather": ["dustStorms"], "timeOfDay": ["night"], "requires": [("f37_1", 1)]},
    ],
    38: [
        {"kind": "king", "id": "k2_38", "name": "抓月虾", "chance": 0.012, "requires": [("f38_1", 1)]},
        {"kind": "emperor", "id": "e2_38", "name": "奥雷奥雷奥雷", "chance": 0.006, "requires": [("f38_2", 1)]},
        {"kind": "legend", "id": "l38_nelado", "name": "内拉朵", "chance": 0.0007,
         "weather": ["gales"], "timeOfDay": ["day"], "requires": [("f38_1", 1)]},
    ],
    39: [
        {"kind": "king", "id": "k2_39", "name": "得卡特", "chance": 0.019, "requires": [("f39_1", 1)]},
        {"kind": "emperor", "id": "e2_39", "name": "灰达尤南丽鱼", "chance": 0.005, "requires": [("f39_2", 1)]},
        {"kind": "legend", "id": "l39_pony", "name": "犎牛多鳍鱼", "chance": 0.0006,
         "weather": ["rain"], "timeOfDay": ["night"], "requires": [("f39_1", 1)]},
    ],
    40: [
        {"kind": "king", "id": "k2_40", "name": "滑稽女王", "chance": 0.006, "requires": [("f40_1", 1)]},
        {"kind": "emperor", "id": "e2_40", "name": "希望鲤鱼", "chance": 0.002, "requires": [("f40_2", 1)]},
        {"kind": "legend", "id": "l40_tiger", "name": "三刃海虎", "chance": 0.0005,
         "weather": ["clouds"], "timeOfDay": ["day"], "requires": [("f40_1", 1)]},
    ],
}

# ───────────────────────────── 平衡调整 ─────────────────────────────
# 所有「捕鱼人之识」BUFF 的持续时间统一为 30s（原为 30~90s 的区间）。
INSIGHT_DURATION_SEC = [30, 30]
# 鱼王 / 鱼皇的出现概率提升至原来的 200%（困难鱼不受影响）。
KING_EMPEROR_CHANCE_MULT = 2.0

# ───────────────────────────── 困难鱼定价 ─────────────────────────────
# 困难鱼单价以同区鱼王 / 鱼皇为锚，按其「实际有效概率」定价。有效概率不是裸的 intuition.chance，
# 而是把三件事一起折算成「钓起 1 条该鱼的预期抛竿数 E」（含窗口外的等待）：
#   1) 天气 / 时段窗口开启率（只在窗口内才计前置、才可能判定）；
#   2) 攒齐前置鱼的开销（前置鱼按权重随机出现；前置本身是困难鱼时递归计入，如七彩链）；
#   3) 鱼识 BUFF 期间的判定（BUFF 持续 insight_sec，每次抛竿以 chance 判定，未命中则重建）。
# 曲线：单价 = 鱼王单价 × (E / E_鱼王)^β，β 由该区鱼王 / 鱼皇两点拟合（精确复现两锚点）。


def _time_of_day_fractions(wcfg: dict[str, Any]) -> dict[str, float]:
    """拂晓 / 白昼 / 黄昏 / 深夜各占一天的比例。"""
    out: dict[str, float] = {}
    for name, (start, end) in wcfg["timeOfDay"].items():
        hours = (end - start + 1) if start <= end else (24 - start) + (end + 1)
        out[name] = hours / 24.0
    return out


def _conditions(region_id: int, wcfg: dict[str, Any], tod_frac: dict[str, float]) -> list[tuple[float, str, str]]:
    """该地区的 (概率, 天气, 时段) 联合分布（天气与时段相互独立）。"""
    weights = {k: int(v) for k, v in _region_weights(wcfg, region_id).items()}
    total = sum(weights.values())
    return [(w / total * t, wid, tod) for wid, w in weights.items() for tod, t in tod_frac.items()]


def _region_weights(wcfg: dict[str, Any], region_id: int) -> dict[str, int]:
    for region in wcfg["regions"]:
        if int(region["regionId"]) == int(region_id):
            return region["weights"]
    return {}


def _gate_ok(weather_id: str, tod_id: str, weather_ids, tod_ids) -> bool:
    """与 services/weather.gate_matches 同义：未声明即不限制，声明了必须命中其一。"""
    if weather_ids and weather_id not in weather_ids:
        return False
    if tod_ids and tod_id not in tod_ids:
        return False
    return True


def _normal_shares(normal: list[dict[str, Any]], weather_id: str, tod_id: str) -> dict[str, float]:
    """某条件下普通鱼池中各鱼的权重占比（全被门槛排除时回落到全部普通鱼）。"""
    pool = [f for f in normal if _gate_ok(weather_id, tod_id, f.get("weather"), f.get("timeOfDay"))]
    if not pool:
        pool = normal
    total = sum(float(f.get("weight", 1.0)) for f in pool)
    if total <= 0:
        return {}
    return {f["id"]: float(f.get("weight", 1.0)) / total for f in pool}


def _region_effort(region: dict[str, Any], wcfg: dict[str, Any], tod_frac: dict[str, float],
                   cast_seconds: float, insight_sec: float) -> dict[str, dict[str, float]]:
    """该区每条特殊鱼的定价用指标（预期抛竿数 E 及其构成）。递归支持「前置本身是困难鱼」的七彩链。"""
    conds = _conditions(region["regionId"], wcfg, tod_frac)
    special_by_id = {s["id"]: s for s in region["specials"]}
    memo: dict[str, dict[str, float]] = {}
    resolving: set[str] = set()

    def effort(sid: str) -> dict[str, float]:
        if sid in memo:
            return memo[sid]
        if sid in resolving:  # 防御：理论上无环
            return {"effort": float("inf"), "gate": 1.0, "build": 0.0, "buffCasts": 0.0}
        special = special_by_id[sid]
        resolving.add(sid)
        try:
            raw = [
                (p, w, t) for p, w, t in conds
                if _gate_ok(w, t, special.get("weather"), special.get("timeOfDay"))
            ]
            gate = sum(p for p, _, _ in raw) or 1e-9
            # 前置只在窗口内累计：把条件概率归一化到「窗口开启」的条件下。
            open_conds = [(p / gate, w, t) for p, w, t in raw]
            build = 0.0
            for req in special["intuition"]["requires"]:
                fish_id, count = req["fishId"], int(req["count"])
                if fish_id in special_by_id:
                    per_cast = 1.0 / effort(fish_id)["effort"]
                else:
                    shares = [
                        _normal_shares(region["normal"], w, t).get(fish_id, 0.0)
                        for _, w, t in open_conds
                    ]
                    per_cast = sum(p * sh for (p, _, _), sh in zip(open_conds, shares))
                build += count / max(per_cast, 1e-12)
            buff_casts = max(1, round(insight_sec / cast_seconds))
            p_hit = float(special["intuition"]["chance"])
            p_success = 1.0 - (1.0 - p_hit) ** buff_casts
            memo[sid] = {
                "effort": (build + buff_casts) / max(p_success, 1e-12) / gate,
                "gate": gate,
                "build": build,
                "buffCasts": float(buff_casts),
            }
        finally:
            resolving.discard(sid)
        return memo[sid]

    return {s["id"]: effort(s["id"]) for s in region["specials"]}


def _price_exponent(price_low: float, price_high: float, effort_low: float, effort_high: float) -> float:
    """由鱼王 / 鱼皇两点拟合的幂律指数。"""
    return math.log(price_high / price_low) / math.log(effort_high / effort_low)


def _fish_stats(base_size: int, base_exp: int, base_sell: int, size_mul, exp_mul, sell_mul) -> dict[str, int]:
    return {
        "sizeMin": max(1, round(base_size * size_mul[0])),
        "sizeMax": max(2, round(base_size * size_mul[1])),
        "exp": max(1, round(base_exp * exp_mul)),
        "sell": max(1, round(base_sell * sell_mul)),
    }


def build() -> dict[str, Any]:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    weather = json.loads(WEATHER.read_text(encoding="utf-8"))
    weather_keys = {int(r["regionId"]): set(r["weights"]) for r in weather["regions"]}
    insight_name = base.get("insightBuffName", "捕鱼人之识")
    tod_frac = _time_of_day_fractions(weather)
    cast_seconds = float(base["castSeconds"])

    regions_out: list[dict[str, Any]] = []
    all_ids: set[str] = set()

    for region in base["regions"]:
        rid = int(region["regionId"])
        normal = [{**f, "rarity": "white"} for f in region["normal"]]
        for f in normal:
            all_ids.add(f["id"])

        base_size = max(int(f["sizeMax"]) for f in normal)
        base_exp = int(normal[0]["exp"])
        base_sell = int(normal[0]["sell"])

        extra = EXTRA_NORMAL.get(rid, {})
        idx = len(normal)
        for i, spec in enumerate(extra.get("blue", [])):
            idx += 1
            stats = _fish_stats(base_size, base_exp, base_sell, (0.5, 0.9), 2, 4)
            normal.append({
                "id": f"f{rid}_{idx}", "name": spec["name"], "rarity": "blue",
                "weight": BLUE_WEIGHTS[i % len(BLUE_WEIGHTS)],
                **({"weather": spec["weather"]} if spec.get("weather") else {}),
                **({"timeOfDay": spec["timeOfDay"]} if spec.get("timeOfDay") else {}),
                **stats,
            })
            all_ids.add(f"f{rid}_{idx}")
        purple = extra.get("purple")
        if purple:
            idx += 1
            stats = _fish_stats(base_size, base_exp, base_sell, (0.7, 1.15), 4, 12)
            normal.append({
                "id": f"f{rid}_{idx}", "name": purple["name"], "rarity": "purple",
                "weight": PURPLE_WEIGHT,
                **({"weather": purple["weather"]} if purple.get("weather") else {}),
                **({"timeOfDay": purple["timeOfDay"]} if purple.get("timeOfDay") else {}),
                **stats,
            })
            all_ids.add(f"f{rid}_{idx}")

        specials: list[dict[str, Any]] = []
        for kind in ("king", "emperor"):
            old = region[kind]
            specials.append({
                "id": old["id"], "name": old["name"], "kind": kind, "legacy": True,
                "intuition": {
                    "name": insight_name,
                    "requires": [{"fishId": fid, "count": 1} for fid in old["prereqFishIds"]],
                    "durationSec": list(INSIGHT_DURATION_SEC),
                    "chance": old["chance"] * KING_EMPEROR_CHANCE_MULT,
                },
                "sizeMin": old["sizeMin"], "sizeMax": old["sizeMax"],
                "exp": old["exp"], "sell": old["sell"],
            })
            all_ids.add(old["id"])

        for spec in NEW_SPECIALS.get(rid, []):
            kind = spec["kind"]
            size_mul = spec.get("sizeMul", _DEFAULT_SIZE_MUL[kind])
            exp_mul = spec.get("expMul", _DEFAULT_EXP_MUL[kind])
            stats = _fish_stats(base_size, base_exp, base_sell, size_mul, exp_mul, 1)
            intuition_name = spec.get("intuitionName") or (
                insight_name if kind in ("king", "emperor") else f"{spec['name']}之识"
            )
            specials.append({
                "id": spec["id"], "name": spec["name"], "kind": kind,
                **({"weather": spec["weather"]} if spec.get("weather") else {}),
                **({"timeOfDay": spec["timeOfDay"]} if spec.get("timeOfDay") else {}),
                "intuition": {
                    "name": intuition_name,
                    "requires": [{"fishId": fid, "count": cnt} for fid, cnt in spec["requires"]],
                    "durationSec": list(INSIGHT_DURATION_SEC),
                    "chance": float(spec["chance"]),
                },
                **stats,
            })
            all_ids.add(spec["id"])

        for leg in LEGENDS.get(rid, []):
            size_mul = leg.get("sizeMul", [2.4, 3.6])
            stats = _fish_stats(
                base_size, base_exp, base_sell,
                size_mul, leg.get("expMul", 25), 1,
            )
            specials.append({
                "id": leg["id"], "name": leg["name"], "kind": "legend", "legacy": True,
                **({"weather": leg["weather"]} if leg.get("weather") else {}),
                **({"timeOfDay": leg["timeOfDay"]} if leg.get("timeOfDay") else {}),
                "intuition": {
                    "name": f"{leg['name']}之识",
                    "requires": [{"fishId": fid, "count": cnt} for fid, cnt in leg["requires"]],
                    "durationSec": list(INSIGHT_DURATION_SEC),
                    "chance": leg["chance"],
                },
                **stats,
            })
            all_ids.add(leg["id"])

        region_out = {
            "regionId": rid, "name": region["name"], "levelReq": region["levelReq"],
            "normal": normal, "specials": specials,
        }
        # 困难鱼定价：用有效概率（窗口开启率 + 前置开销 + BUFF 判定）折算的预期抛竿数 E 定价。
        effort = _region_effort(region_out, weather, tod_frac, cast_seconds, INSIGHT_DURATION_SEC[0])
        king = next(s for s in specials if s["kind"] == "king")
        emperor = next(s for s in specials if s["kind"] == "emperor")
        king_effort = effort[king["id"]]["effort"]
        beta = _price_exponent(
            king["sell"], emperor["sell"], king_effort, effort[emperor["id"]]["effort"]
        )
        for special in specials:
            # legacy 鱼王 / 鱼皇沿用冻结单价；其余（新增鱼王 / 鱼皇 + 全部困难鱼）按有效概率定价。
            if special["kind"] in ("king", "emperor") and special.get("legacy"):
                continue
            info = effort[special["id"]]
            special["sell"] = max(1, round(int(king["sell"]) * (info["effort"] / king_effort) ** beta))
            # 供前端「?」展示定价依据：单价 = 锚点鱼王单价 × (E/E_鱼王)^β。
            special["priceBasis"] = {
                "effort": round(info["effort"], 2),
                "gatePct": round(info["gate"] * 100.0, 2),
                "buildCasts": round(info["build"], 1),
                "buffCasts": int(info["buffCasts"]),
                "anchorSell": int(king["sell"]),
                "anchorEffort": round(king_effort, 2),
                "exponent": round(beta, 6),
            }
        regions_out.append(region_out)

    # ── 校验：id 唯一、天气门槛落在该地区天气表内、前置引用存在 ──
    # 注：普通鱼名可跨地区复用（原数据即如此，三文鱼/河鲈等为通用鱼），故不校验名称唯一性。
    seen_ids: set[str] = set()
    for region in regions_out:
        rid = region["regionId"]
        for f in region["normal"]:
            assert f["id"] not in seen_ids, f"重复鱼 id：{f['id']}"
            seen_ids.add(f["id"])
            for w in f.get("weather", []):
                assert w in weather_keys[rid], f"地区 {rid} 无天气 {w}"
        for s in region["specials"]:
            assert s["id"] not in seen_ids, f"重复鱼 id：{s['id']}"
            seen_ids.add(s["id"])
            for w in s.get("weather", []):
                assert w in weather_keys[rid], f"地区 {rid} 无天气 {w}"
            for req in s["intuition"]["requires"]:
                assert req["fishId"] in all_ids, f"{s['id']} 前置引用不存在：{req['fishId']}"

    # ── 校验：特殊鱼的天气 / 时段门槛必须与每条前置鱼可同时命中 ──
    # 前置计数只在特殊鱼自身的门槛窗口内累计（services/fishing.py::_advance_intuition），
    # 两者互斥（如困难鱼要求白昼、其前置紫鱼只在深夜）则该鱼永远无法触发。
    gate_by_id: dict[str, tuple[list[str] | None, list[str] | None]] = {
        f["id"]: (f.get("weather"), f.get("timeOfDay"))
        for region in regions_out
        for f in [*region["normal"], *region["specials"]]
    }

    def _overlaps(a: list[str] | None, b: list[str] | None) -> bool:
        return not a or not b or bool(set(a) & set(b))

    for region in regions_out:
        for s in region["specials"]:
            for req in s["intuition"]["requires"]:
                pw, pt = gate_by_id[req["fishId"]]
                assert _overlaps(s.get("weather"), pw) and _overlaps(s.get("timeOfDay"), pt), (
                    f"{s['id']} 与前置 {req['fishId']} 的天气/时段窗口互斥，永远无法触发"
                    f"（{s['id']}: weather={s.get('weather')} timeOfDay={s.get('timeOfDay')}；"
                    f"前置: weather={pw} timeOfDay={pt}）"
                )

    # ── 校验：新增特殊鱼的覆盖 / 稀有度 / 概率多样性 ──
    # 新增鱼王 / 鱼皇必须比同区 legacy 鱼王 / 鱼皇更稀有（否则会成为比旧鱼王更优的刷钱路线），
    # 新增鱼王概率必须高于同区新增鱼皇；且同档位的概率各不相同（不要所有鱼王一个概率）。
    new_kings: list[float] = []
    new_emperors: list[float] = []
    for region in regions_out:
        legacy_king = next(s for s in region["specials"] if s["kind"] == "king" and s.get("legacy"))
        legacy_emperor = next(s for s in region["specials"] if s["kind"] == "emperor" and s.get("legacy"))
        kings = [s for s in region["specials"] if s["kind"] == "king" and not s.get("legacy")]
        emperors = [s for s in region["specials"] if s["kind"] == "emperor" and not s.get("legacy")]
        if NEW_SPECIALS:
            assert kings and emperors, f"地区 {region['regionId']} 缺少新增鱼王 / 鱼皇"
        for s in kings:
            c = float(s["intuition"]["chance"])
            assert c < float(legacy_king["intuition"]["chance"]), f"{s['id']} 新增鱼王不比旧鱼王稀有"
            assert all(c > float(e["intuition"]["chance"]) for e in emperors), (
                f"{s['id']} 新增鱼王概率应高于同区新增鱼皇"
            )
            new_kings.append(c)
        for s in emperors:
            c = float(s["intuition"]["chance"])
            assert c < float(legacy_emperor["intuition"]["chance"]), f"{s['id']} 新增鱼皇不比旧鱼皇稀有"
            new_emperors.append(c)
    if NEW_SPECIALS:
        assert len(set(new_kings)) > 1, "新增鱼王概率不应全部相同"
        assert len(set(new_emperors)) > 1, "新增鱼皇概率不应全部相同"

    return {
        "$comment": (
            "钓场。普通鱼分白/蓝/紫三档（rarity），可带天气(weather)/时间(timeOfDay)门槛；"
            "special: 鱼王/鱼皇 与 困难鱼(legend) 共用统一的 intuition 结构——"
            "每种直觉只绑定一条鱼，钓齐 requires(计数型前置) 后开启，不刷新，结束后才可再次触发。"
            "legacy:true 标记旧内容（原 40 区鱼王/鱼皇 + 第一批困难鱼），旧称号只统计 legacy 集合，"
            "因此新增鱼不影响已有称号；新增鱼王/鱼皇/困难鱼沿用真实 FF14 鱼名，概率逐条不同且更稀有。"
            "平衡调整：所有鱼识 BUFF 持续 30s；旧鱼王/鱼皇出现概率为原值的 200% 且保持不变；"
            "非 legacy 特殊鱼（新增鱼王/鱼皇 + 全部困难鱼）单价按其「有效概率」定价："
            "鱼王单价 × (E/E_鱼王)^β，E 为含「天气/时段窗口开启率 + 攒前置鱼开销 + 鱼识 BUFF 判定」"
            "的预期抛竿数，越难钓越贵。"
        ),
        "castSeconds": base["castSeconds"],
        "insightBuffName": insight_name,
        "rarityNames": {"white": "白鱼", "blue": "蓝鱼", "purple": "紫鱼"},
        "regions": regions_out,
    }


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    normals = sum(len(r["normal"]) for r in data["regions"])
    specials = sum(len(r["specials"]) for r in data["regions"])
    legends = sum(1 for r in data["regions"] for s in r["specials"] if s["kind"] == "legend")
    print(f"wrote {OUT.relative_to(ROOT)}：{len(data['regions'])} 区 / 普通鱼 {normals} / 特殊鱼 {specials}（其中 legend {legends}）")


if __name__ == "__main__":
    sys.exit(main())

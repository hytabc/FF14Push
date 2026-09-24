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

运行：`python scripts/gen-fish-data.py`
"""

from __future__ import annotations

import json
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
    1: {"blue": [{"name": "珊瑚蝶鱼", "weather": ["clear"]}, {"name": "银鳞鲳", "weather": ["rain"]}],
        "purple": {"name": "月光水母", "timeOfDay": ["night"]}},
    2: {"blue": [{"name": "蓝鳍梭鱼", "weather": ["clear"]}, {"name": "浪花鲹", "weather": ["fog"]}],
        "purple": {"name": "海月水母", "timeOfDay": ["night"]}},
    3: {"blue": [{"name": "斑点鲼", "weather": ["fog"]}, {"name": "石首鱼", "weather": ["clouds"]}],
        "purple": {"name": "深渊提灯鱼", "timeOfDay": ["night"]}},
    4: {"blue": [{"name": "沙漠鲹", "weather": ["heat"]}, {"name": "沙丘鳅", "weather": ["dust"]}],
        "purple": {"name": "赤沙王鲷", "timeOfDay": ["night"]}},
    5: {"blue": [{"name": "灼热鲈", "weather": ["heat"]}, {"name": "砂砾鲶", "weather": ["dust"]}],
        "purple": {"name": "幻影蜥鱼", "timeOfDay": ["night"]}},
    6: {"blue": [{"name": "苔藓鳟", "weather": ["rain"]}, {"name": "林间鳜", "weather": ["fog"]}],
        "purple": {"name": "幽林木灵鱼", "timeOfDay": ["night"]}},
    7: {"blue": [{"name": "落叶鲑", "weather": ["rain"]}, {"name": "树影鲫", "weather": ["fog"]}],
        "purple": {"name": "夜枭鱼", "timeOfDay": ["night"]}},
    8: {"blue": [{"name": "风蚀鲤", "weather": ["dust"]}, {"name": "旱地鳅", "weather": ["heat"]}],
        "purple": {"name": "金沙鳞鱼", "timeOfDay": ["night"]}},
    9: {"blue": [{"name": "沙暴鲈", "weather": ["dust"]}, {"name": "绿洲鳟", "weather": ["clear"]}],
        "purple": {"name": "蜃楼鱼", "weather": ["heat"]}},
    10: {"blue": [{"name": "迷雾鳟", "weather": ["rain"]}, {"name": "高地鲈", "weather": ["wind"]}],
         "purple": {"name": "星尘水母", "timeOfDay": ["night"]}},
    11: {"blue": [{"name": "冰晶鲑", "weather": ["snow"]}, {"name": "寒霜鳕", "weather": ["blizzard"]}],
         "purple": {"name": "极光蝶鱼", "timeOfDay": ["night"]}},
    12: {"blue": [{"name": "雪原鳟", "weather": ["snow"]}, {"name": "霜牙梭子鱼", "weather": ["blizzard"]}],
         "purple": {"name": "冬夜鲟", "timeOfDay": ["night"]}},
    13: {"blue": [{"name": "苍穹旗鱼", "weather": ["wind"]}, {"name": "云海鳟", "weather": ["clouds"]}],
         "purple": {"name": "龙鳞鱼", "timeOfDay": ["night"]}},
    14: {"blue": [{"name": "云雾鲳", "weather": ["clouds"]}, {"name": "风语鳟", "weather": ["wind"]}],
         "purple": {"name": "天穹水母", "timeOfDay": ["night"]}},
    15: {"blue": [{"name": "苔原鲈", "weather": ["clouds"]}, {"name": "溪谷虹鳟", "weather": ["rain"]}],
         "purple": {"name": "古龙鳕", "timeOfDay": ["night"]}},
    16: {"blue": [{"name": "田园鲫", "weather": ["clear"]}, {"name": "牧草鲑", "weather": ["rain"]}],
         "purple": {"name": "萤火提灯鱼", "timeOfDay": ["night"]}},
    17: {"blue": [{"name": "高原鳟", "weather": ["clear"]}, {"name": "岩壁鲈", "weather": ["wind"]}],
         "purple": {"name": "翡翠水母", "timeOfDay": ["night"]}},
    18: {"blue": [{"name": "山涧虹鳟", "weather": ["rain"]}, {"name": "峭壁鲶", "weather": ["wind"]}],
         "purple": {"name": "石纹鲵", "timeOfDay": ["night"]}},
    19: {"blue": [{"name": "红玉鲷", "weather": ["clear"]}, {"name": "碧波旗鱼", "weather": ["rain"]}],
         "purple": {"name": "珊瑚夜光鱼", "timeOfDay": ["night"]}},
    20: {"blue": [{"name": "樱花鲑", "weather": ["clear"]}, {"name": "潮汐鲳", "weather": ["thunder"]}],
         "purple": {"name": "月下章鱼", "timeOfDay": ["night"]}},
    21: {"blue": [{"name": "草原鳟", "weather": ["clear"]}, {"name": "疾风鲈", "weather": ["wind"]}],
         "purple": {"name": "草原夜光鲤", "timeOfDay": ["night"]}},
    22: {"blue": [{"name": "黄金鲹", "weather": ["clear"]}, {"name": "港町鲭", "weather": ["rain"]}],
         "purple": {"name": "宵灯水母", "timeOfDay": ["night"]}},
    23: {"blue": [{"name": "雾岛鲑", "weather": ["fog"]}, {"name": "湖光鳟", "weather": ["clouds"]}],
         "purple": {"name": "幽谷大鲵", "timeOfDay": ["night"]}},
    24: {"blue": [{"name": "灼沙鲈", "weather": ["heat"]}, {"name": "荒漠鲶", "weather": ["dust"]}],
         "purple": {"name": "沙海幻鱼", "timeOfDay": ["night"]}},
    25: {"blue": [{"name": "蝶翼鳟", "weather": ["clear"]}, {"name": "仙灵鲑", "weather": ["fog"]}],
         "purple": {"name": "妖精湖灯鱼", "timeOfDay": ["night"]}},
    26: {"blue": [{"name": "雷云鳟", "weather": ["clouds"]}, {"name": "雪岭鳕", "weather": ["snow"]}],
         "purple": {"name": "永夜鲟", "timeOfDay": ["night"]}},
    27: {"blue": [{"name": "雨林鳜", "weather": ["rain"]}, {"name": "藤蔓鲶", "weather": ["fog"]}],
         "purple": {"name": "丛林幽光鱼", "timeOfDay": ["night"]}},
    28: {"blue": [{"name": "黑风旗鱼", "weather": ["wind"]}, {"name": "雷暴鲹", "weather": ["thunder"]}],
         "purple": {"name": "深渊灯笼鱼", "timeOfDay": ["night"]}},
    29: {"blue": [{"name": "象鲷", "weather": ["clear"]}, {"name": "遗辉鲳", "weather": ["rain"]}],
         "purple": {"name": "神殿夜光鱼", "timeOfDay": ["night"]}},
    30: {"blue": [{"name": "寒钢鳟", "weather": ["wind"]}, {"name": "军港鲈", "weather": ["clouds"]}],
         "purple": {"name": "冰宫水母", "timeOfDay": ["night"]}},
    31: {"blue": [{"name": "悲叹鲹", "weather": ["rain"]}, {"name": "泪海旗鱼", "weather": ["thunder"]}],
         "purple": {"name": "深海幽灵鱼", "timeOfDay": ["night"]}},
    32: {"blue": [{"name": "星霜鳕", "weather": ["snow"]}, {"name": "天外鲑", "weather": ["blizzard"]}],
         "purple": {"name": "极星水母", "timeOfDay": ["night"]}},
    33: {"blue": [{"name": "乐园鲷", "weather": ["clear"]}, {"name": "花海鳟", "weather": ["rain"]}],
         "purple": {"name": "神域灯鱼", "timeOfDay": ["night"]}},
    34: {"blue": [{"name": "迷宫鳜", "weather": ["fog"]}, {"name": "幽径鲶", "weather": ["rain"]}],
         "purple": {"name": "幻境水母", "timeOfDay": ["night"]}},
    35: {"blue": [{"name": "图拉尔旗鱼", "weather": ["clear"]}, {"name": "礁湖鲳", "weather": ["rain"]}],
         "purple": {"name": "浅海夜光鱼", "timeOfDay": ["night"]}},
    36: {"blue": [{"name": "雨林象鱼", "weather": ["rain"]}, {"name": "藤桥鲶", "weather": ["thunder"]}],
         "purple": {"name": "密林幽光鱼", "timeOfDay": ["night"]}},
    37: {"blue": [{"name": "遗迹鲈", "weather": ["dust"]}, {"name": "王墓鳅", "weather": ["heat"]}],
         "purple": {"name": "王都夜光鱼", "timeOfDay": ["night"]}},
    38: {"blue": [{"name": "熔岩鳟", "weather": ["heat"]}, {"name": "火山鲶", "weather": ["clear"]}],
         "purple": {"name": "熔核水母", "timeOfDay": ["night"]}},
    39: {"blue": [{"name": "王都鲷", "weather": ["clear"]}, {"name": "护城旗鱼", "weather": ["clouds"]}],
         "purple": {"name": "星芒水母", "timeOfDay": ["night"]}},
    40: {"blue": [{"name": "圣域鳟", "weather": ["clear"]}, {"name": "天启鲑", "weather": ["rain"]}],
         "purple": {"name": "原初水母", "timeOfDay": ["night"]}},
}

# ───────────────────────────── 困难鱼（legend） ─────────────────────────────
# 字段：id/name/weather/timeOfDay/requires[(fishId,count)]/duration/chance + 可选倍率。
# 默认（普通 legend）：size = base_size×(2.4, 3.6)，exp = base_exp×25，sell = base_sell×60。
LEGENDS: dict[int, list[dict[str, Any]]] = {
    3: [{"id": "l3_sea_god", "name": "海神", "weather": ["rain"], "timeOfDay": ["night"],
         "requires": [("f3_7", 1)], "duration": [50, 80], "chance": 0.0012}],
    5: [{"id": "l5_mirage", "name": "幻影王鲷", "weather": ["heat", "dust"],
         "requires": [("f5_7", 1)], "duration": [50, 80], "chance": 0.0012}],
    6: [{"id": "l6_wood_catfish", "name": "幽林巨鲶", "weather": ["fog"], "timeOfDay": ["night"],
         "requires": [("f6_7", 1)], "duration": [50, 80], "chance": 0.0012}],
    10: [{"id": "l10_skull", "name": "骷髅王鲶", "weather": ["wind"],
          "requires": [("f10_7", 1)], "duration": [50, 80], "chance": 0.001}],
    11: [{"id": "l11_glacier_sturgeon", "name": "冰川鲟", "weather": ["blizzard"],
          "requires": [("f11_7", 1)], "duration": [50, 80], "chance": 0.001}],
    12: [{"id": "l12_aurora_whale", "name": "极光鲸", "weather": ["blizzard"], "timeOfDay": ["night"],
          "requires": [("f12_7", 1)], "duration": [60, 90], "chance": 0.0008}],
    13: [{"id": "l13_cloud_butterfly", "name": "云蝶", "weather": ["wind"], "timeOfDay": ["day"],
          "requires": [("f13_7", 1)], "duration": [40, 60], "chance": 0.0008}],
    16: [{"id": "l16_pegasus", "name": "天马", "weather": ["clear"], "timeOfDay": ["dawn"],
          "requires": [("f16_7", 1)], "duration": [40, 70], "chance": 0.001}],
    19: [{"id": "l19_megalodon", "name": "巨齿鲨", "weather": ["thunder"],
          "requires": [("f19_7", 1)], "duration": [50, 80], "chance": 0.001}],
    20: [{"id": "l20_sail", "name": "帆", "weather": ["thunder"], "timeOfDay": ["dusk"],
          "requires": [("f20_7", 1)], "duration": [45, 70], "chance": 0.0008}],
    21: [
        {"id": "l21_purple", "name": "紫彩鱼", "requires": [("f21_1", 1)],
         "duration": [40, 60], "chance": 0.06, "sizeMul": [0.9, 1.4], "expMul": 8, "sellMul": 12},
        {"id": "l21_blue", "name": "蓝彩鱼", "requires": [("l21_purple", 1)],
         "duration": [40, 60], "chance": 0.05, "sizeMul": [0.9, 1.4], "expMul": 8, "sellMul": 14},
        {"id": "l21_red", "name": "红彩鱼", "requires": [("f21_2", 1)],
         "duration": [40, 60], "chance": 0.06, "sizeMul": [0.9, 1.4], "expMul": 8, "sellMul": 12},
        {"id": "l21_orange", "name": "橙彩鱼", "requires": [("l21_red", 1)],
         "duration": [40, 60], "chance": 0.05, "sizeMul": [0.9, 1.4], "expMul": 8, "sellMul": 14},
        {"id": "l21_green", "name": "绿彩鱼", "requires": [("f21_5", 1)],
         "duration": [40, 60], "chance": 0.05, "sizeMul": [0.9, 1.4], "expMul": 8, "sellMul": 14},
        {"id": "l21_hue_lord", "name": "七彩天主", "weather": ["clear"],
         "requires": [("l21_blue", 3), ("l21_orange", 3), ("l21_green", 5)],
         "duration": [60, 90], "chance": 0.0004,
         "sizeMul": [3.0, 4.5], "expMul": 60, "sellMul": 200},
    ],
    25: [{"id": "l25_mirror_butterfly", "name": "镜中蝶", "weather": ["clear"], "timeOfDay": ["night"],
          "requires": [("f25_7", 2)], "duration": [30, 45], "chance": 0.0006}],
    28: [{"id": "l28_kraken", "name": "大王乌贼", "weather": ["wind", "thunder"],
          "requires": [("f28_7", 1)], "duration": [50, 80], "chance": 0.001}],
    29: [{"id": "l29_phantom_dragon", "name": "幻龙", "weather": ["rain"],
          "requires": [("f29_7", 1)], "duration": [50, 80], "chance": 0.001}],
    31: [{"id": "l31_abyss_king", "name": "深渊王", "weather": ["thunder"], "timeOfDay": ["night"],
          "requires": [("f31_7", 1)], "duration": [60, 90], "chance": 0.0008}],
    32: [{"id": "l32_white_whale", "name": "白鲸", "weather": ["snow", "blizzard"],
          "requires": [("f32_7", 1)], "duration": [50, 80], "chance": 0.001}],
    33: [{"id": "l33_holy_dragon", "name": "圣龙", "weather": ["clear"], "timeOfDay": ["day"],
          "requires": [("f33_7", 1)], "duration": [50, 80], "chance": 0.0008}],
    34: [{"id": "l34_star_whale", "name": "星鲸", "weather": ["fog"], "timeOfDay": ["night"],
          "requires": [("f34_7", 1)], "duration": [45, 70], "chance": 0.0006}],
    37: [{"id": "l37_golden_god", "name": "黄金神鱼", "weather": ["dust"], "timeOfDay": ["dusk"],
          "requires": [("f37_7", 1)], "duration": [50, 80], "chance": 0.0008}],
    38: [{"id": "l38_lava_leviathan", "name": "熔岩鲲", "weather": ["heat", "clear"],
          "requires": [("f38_7", 1)], "duration": [50, 80], "chance": 0.0008}],
    39: [{"id": "l39_black_tortoise", "name": "玄武巨龟", "weather": ["rain"], "timeOfDay": ["night"],
          "requires": [("f39_7", 1)], "duration": [60, 90], "chance": 0.0008}],
    40: [{"id": "l40_creator", "name": "创世神鱼", "weather": ["thunder"], "timeOfDay": ["night"],
          "requires": [("f40_7", 1)], "duration": [60, 90], "chance": 0.0006}],
}

BLUE_WEIGHTS = (5, 3)
PURPLE_WEIGHT = 2

# ───────────────────────────── 平衡调整 ─────────────────────────────
# 所有「捕鱼人之识」BUFF 的持续时间统一为 30s（原为 30~90s 的区间）。
INSIGHT_DURATION_SEC = [30, 30]
# 鱼王 / 鱼皇的出现概率提升至原来的 200%（困难鱼不受影响）。
KING_EMPEROR_CHANCE_MULT = 2.0


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

        for leg in LEGENDS.get(rid, []):
            size_mul = leg.get("sizeMul", [2.4, 3.6])
            stats = _fish_stats(
                base_size, base_exp, base_sell,
                size_mul, leg.get("expMul", 25), leg.get("sellMul", 60),
            )
            specials.append({
                "id": leg["id"], "name": leg["name"], "kind": "legend",
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

        regions_out.append({
            "regionId": rid, "name": region["name"], "levelReq": region["levelReq"],
            "normal": normal, "specials": specials,
        })

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

    return {
        "$comment": (
            "钓场。普通鱼分白/蓝/紫三档（rarity），可带天气(weather)/时间(timeOfDay)门槛；"
            "special: 鱼王/鱼皇(legacy)与困难鱼(legend)共用统一的 intuition 结构——"
            "每种直觉只绑定一条鱼，钓齐 requires(计数型前置) 后开启，不刷新，结束后才可再次触发。"
            "旧 king/emperor 已迁入 specials[]，id 保持不变。"
            "平衡调整：所有鱼识 BUFF 持续 30s；鱼王/鱼皇出现概率为原值的 200%。"
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

# -*- coding: utf-8 -*-
"""生成生产/采集 DLC 的 shared/data JSON。

用法（仓库根目录）：`python scripts/gen-dohdol-data.py`

生成：materials.json / gather-nodes.json / dohdol-equipment.json / fish.json /
consumables.json / recipes.json / titles.json

设计：每个地区有专属的矿物与植物各一件（FF14 风格命名，跨地区不重复），
另加少量通用材料（半成品原料）。与 scripts/gen-icons.mjs 一样属于内容生成器，
改动内容后重跑本脚本即可（fish/consumables/titles 也一并重写）。
"""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "shared" / "data"


def dump(name, obj):
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", name)


regions = json.loads((DATA / "regions.json").read_text(encoding="utf-8"))["regions"]

# 战斗装备底材（族 / 档位 / 职能变体），供高档配方生成时保持同步。
BASE_ITEMS = json.loads((DATA / "base-items.json").read_text(encoding="utf-8"))

# 地区档位 → 出售单价（金币）。材料/鱼不随地区等级变强，仅种类不同，价格按档位递增。
# 定价规则：越高档涨幅越大（第 2 档起每档翻倍），让非战斗收入稳定在「同档战斗收入的一成上下」
# 且绝不反超战斗——既保住收集动机，又不让它变成不打怪也能刷钱的路线。
# 回归保护：backend/tests/test_dohdol.py:TestDohdolSellBalance。
BAND_SELL = {1: 6, 9: 16, 17: 32, 23: 64, 29: 128, 35: 256}          # 采集素材（地区专属）
FISH_SELL = {1: 8, 9: 20, 17: 40, 23: 80, 29: 160, 35: 320}          # 普通渔获
KING_SELL = {1: 160, 9: 400, 17: 800, 23: 1600, 29: 3200, 35: 6400}  # 鱼王（20 × 普通渔获）
EMPEROR_SELL = {1: 640, 9: 1600, 17: 3200, 23: 6400, 29: 12800, 35: 25600}  # 鱼皇（80 × 普通渔获）
HALF_SELL = 50                                                       # 半成品（统一固定，不随档位变化）


def _band(rid: int, table: dict[int, int]) -> int:
    value = table[1]
    for start, price in sorted(table.items()):
        if rid >= start:
            value = price
    return value


def mat_sell(rid: int) -> int:
    return _band(rid, BAND_SELL)


def fish_sell(rid: int) -> int:
    return _band(rid, FISH_SELL)


def king_sell(rid: int) -> int:
    return _band(rid, KING_SELL)


def emperor_sell(rid: int) -> int:
    return _band(rid, EMPEROR_SELL)

# ---------------------------------------------------------------- 材料
materials = []

# 通用材料（多地都能采到，作为半成品的原料）
COMMONS = [
    ("g_ore", "铁矿", "MIN"), ("g_stone", "石灰岩", "MIN"), ("g_gem", "石英", "MIN"),
    ("g_wood", "榆木", "BTN"), ("g_herb", "薰衣草", "BTN"), ("g_fiber", "亚麻", "BTN"),
]
for mid, name, job in COMMONS:
    materials.append({"id": mid, "name": name, "kind": "gather", "jobId": job, "tier": 0, "common": True, "sell": 3})

# 地区专属材料：每个地区一件矿物 + 一件植物，全部不重复（FF14 风格命名）
ORE_NAMES = [
    "铜矿", "锡矿", "锌矿", "铅矿", "银矿", "金矿", "黄铜矿", "蓝铜矿", "辰砂", "黑曜石",
    "花岗岩", "砂岩", "大理石", "滑石", "云母", "萤石", "硫磺", "硝石", "岩盐", "明矾",
    "石膏", "磁铁矿", "赤铁矿", "褐铁矿", "锰矿", "钨矿", "钴矿", "镍矿", "铬矿", "钛铁矿",
    "硬铝矿", "秘银矿", "精金矿", "星辉石", "绯红石", "天青石", "翡翠原石", "石榴石", "橄榄石", "紫水晶",
]
BTN_NAMES = [
    "松木", "杉木", "橡木", "白桦", "梣木", "铁木", "红木", "桃花心木", "黑檀", "榉木",
    "竹", "芦苇", "藤蔓", "苔藓", "蘑菇", "山金车花", "龙血草", "苜蓿", "棉花", "大麻",
    "银叶草", "苦艾", "曼陀罗", "菊石草", "蓝铃花", "山茶", "芦荟", "椰子", "无花果", "月长石玫瑰",
    "风茄", "秋葵", "杜松", "薄荷", "鼠尾草", "洋甘菊", "藏红花", "灵芝", "冬虫夏草", "仙人掌果",
]
assert len(ORE_NAMES) >= len(regions) and len(BTN_NAMES) >= len(regions)

for idx, r in enumerate(regions):
    materials.append({
        "id": f"ore{r['id']}", "name": ORE_NAMES[idx], "kind": "gather",
        "jobId": "MIN", "regionId": r["id"], "tier": 1, "common": False, "sell": mat_sell(r["id"]),
    })
    materials.append({
        "id": f"flora{r['id']}", "name": BTN_NAMES[idx], "kind": "gather",
        "jobId": "BTN", "regionId": r["id"], "tier": 1, "common": False, "sell": mat_sell(r["id"]),
    })

HALVES = [
    ("h_plank", "木板", "CRP"), ("h_ingot", "铁锭", "BSM"), ("h_steel", "钢锭", "BSM"),
    ("h_plate", "装甲板", "ARM"), ("h_alloy", "合金锭", "ARM"), ("h_gemcut", "雕琢宝石", "GSM"),
    ("h_glass", "玻璃板", "GSM"), ("h_leather", "皮革", "LTW"), ("h_cloth", "布料", "WVR"),
    ("h_ink", "浓缩墨水", "ALC"), ("h_oil", "精油", "ALC"), ("h_flour", "面粉", "CUL"),
]
for hid, name, job in HALVES:
    materials.append({"id": hid, "name": name, "kind": "half", "jobId": job, "tier": 2, "sell": HALF_SELL})

dump("materials.json", {
    "$comment": "采集材料与半成品。材料不随地区等级递增，仅按种类区分：每个地区有专属的矿物与植物各一件（regionId 标注，彼此不重复），另有少量通用材料。sell 为出售单价（金币），材料/鱼获可卖给系统换金币。地区专属材料按 BAND_SELL 档位表递增（越高档涨幅越大，低阶几乎不变），通用材料恒为 3 作为半成品原料，半成品恒为 HALF_SELL。",
    "materials": materials,
})

# ---------------------------------------------------------------- 采集点
def band_level(rid: int) -> int:
    """地区序号 → 采集等级门槛，覆盖 1-100（40 个地区线性铺满）。"""
    return min(100, 1 + (rid - 1) * 99 // 39)


MIN_COMMONS = ["g_ore", "g_stone", "g_gem"]
BTN_COMMONS = ["g_wood", "g_herb", "g_fiber"]

nodes = []
for r in regions:
    rid = r["id"]
    c1 = MIN_COMMONS[rid % 3]
    c2 = MIN_COMMONS[(rid + 1) % 3]
    b1 = BTN_COMMONS[rid % 3]
    b2 = BTN_COMMONS[(rid + 1) % 3]
    nodes.append({
        "regionId": rid, "jobId": "MIN", "levelReq": band_level(rid),
        "yields": [
            {"materialId": f"ore{rid}", "weight": 5, "min": 1, "max": 2},
            {"materialId": c1, "weight": 3, "min": 1, "max": 2},
            {"materialId": c2, "weight": 1, "min": 1, "max": 1},
        ],
    })
    nodes.append({
        "regionId": rid, "jobId": "BTN", "levelReq": band_level(rid),
        "yields": [
            {"materialId": f"flora{rid}", "weight": 5, "min": 1, "max": 2},
            {"materialId": b1, "weight": 3, "min": 1, "max": 2},
            {"materialId": b2, "weight": 1, "min": 1, "max": 1},
        ],
    })

dump("gather-nodes.json", {
    "$comment": "采集点：regionId + 采集职业 → 可采材料与数量区间。地区专属材料只在对应职业下产出，权重最高。",
    "baseSecondsPerAction": 2.5,
    "yieldPerLevelPct": 0.5,
    "maxYieldLevelBonusPct": 50,
    "nodes": nodes,
})

# ---------------------------------------------------------------- 专用装备
# 覆盖生产/采集 0-100 级；power 决定 bonus 数值（≈1.26^index）。
DOHDOL_TIERS = [
    {"index": 0, "name": "制式", "levelReq": 1, "power": 1.0},
    {"index": 1, "name": "标准", "levelReq": 10, "power": 1.3},
    {"index": 2, "name": "精制", "levelReq": 20, "power": 1.6},
    {"index": 3, "name": "良品", "levelReq": 30, "power": 2.0},
    {"index": 4, "name": "高级", "levelReq": 40, "power": 2.5},
    {"index": 5, "name": "秘传", "levelReq": 50, "power": 3.2},
    {"index": 6, "name": "名匠", "levelReq": 60, "power": 4.0},
    {"index": 7, "name": "大师", "levelReq": 70, "power": 5.0},
    {"index": 8, "name": "传说", "levelReq": 80, "power": 6.4},
    {"index": 9, "name": "神话", "levelReq": 90, "power": 8.0},
    {"index": 10, "name": "终末", "levelReq": 100, "power": 10.1},
]

# 同一档位的多套装备（变体）：bias 为对应 bonus 数值的乘数。minTier 控制出现档位，
# 档位越高变体越多（基础型 → 专项 → 全项）。
DOH_VARIANTS = [
    {"id": "", "name": "", "minTier": 0, "bias": {}},
    {"id": "quality", "name": "匠心", "minTier": 2, "bias": {"craftQualityPct": 1.4, "craftRarityPct": 1.3}},
    {"id": "speed", "name": "迅捷", "minTier": 2, "bias": {"craftSpeedPct": 1.5}},
    {"id": "xp", "name": "悟道", "minTier": 4, "bias": {"craftXpPct": 1.6}},
    {"id": "master", "name": "大师", "minTier": 6,
     "bias": {"craftQualityPct": 1.3, "craftRarityPct": 1.3, "craftSpeedPct": 1.3, "craftXpPct": 1.3}},
]
DOL_VARIANTS = [
    {"id": "", "name": "", "minTier": 0, "bias": {}},
    {"id": "yield", "name": "丰饶", "minTier": 2, "bias": {"gatherYieldPct": 1.4}},
    {"id": "speed", "name": "疾行", "minTier": 2, "bias": {"gatherSpeedPct": 1.5}},
    {"id": "xp", "name": "博识", "minTier": 4, "bias": {"gatherXpPct": 1.6}},
    {"id": "fish", "name": "渔猎", "minTier": 4, "bias": {"fishInsightPct": 1.5, "fishChancePct": 1.5}},
    {"id": "master", "name": "大师", "minTier": 6,
     "bias": {"gatherYieldPct": 1.3, "gatherSpeedPct": 1.3, "gatherXpPct": 1.3,
              "fishInsightPct": 1.3, "fishChancePct": 1.3}},
]
VARIANTS_BY_KIND = {"doh": DOH_VARIANTS, "dol": DOL_VARIANTS}
SLOTS = [
    ("Tool", "主手工具", "tool"),
    ("OffTool", "副手工具", "tool"),
    ("Head", "工作头饰", "gear"),
    ("Body", "工作服", "gear"),
    ("Hands", "工作手套", "gear"),
    ("Legs", "工作裤", "gear"),
    ("Feet", "工作靴", "gear"),
]
BONUS_NAMES = {
    "gatherYieldPct": "采集产量",
    "gatherSpeedPct": "采集速度",
    "gatherXpPct": "采集经验",
    "craftQualityPct": "制造品质",
    "craftRarityPct": "制造品阶幸运",
    "craftSpeedPct": "制造速度",
    "craftXpPct": "制造经验",
    "fishInsightPct": "捕鱼人之识时长",
    "fishChancePct": "鱼王/鱼皇概率",
}
SLOT_BONUS = {
    ("doh", "Tool"): {"craftQualityPct": 4.0, "craftRarityPct": 3.0},
    ("doh", "OffTool"): {"craftSpeedPct": 6.0, "craftRarityPct": 1.5},
    ("doh", "Head"): {"craftQualityPct": 1.2, "craftRarityPct": 0.6},
    ("doh", "Body"): {"craftQualityPct": 1.8, "craftSpeedPct": 2.0, "craftRarityPct": 0.9},
    ("doh", "Hands"): {"craftSpeedPct": 1.6, "craftRarityPct": 0.5},
    ("doh", "Legs"): {"craftSpeedPct": 2.0, "craftRarityPct": 0.5},
    ("doh", "Feet"): {"craftQualityPct": 1.0, "craftRarityPct": 0.5},
    ("dol", "Tool"): {"gatherYieldPct": 6.0, "fishChancePct": 3.0},
    ("dol", "OffTool"): {"gatherSpeedPct": 6.0, "fishInsightPct": 5.0},
    ("dol", "Head"): {"gatherYieldPct": 1.5},
    ("dol", "Body"): {"gatherYieldPct": 2.0, "fishInsightPct": 2.0},
    ("dol", "Hands"): {"gatherSpeedPct": 1.6},
    ("dol", "Legs"): {"gatherSpeedPct": 2.0},
    ("dol", "Feet"): {"gatherYieldPct": 1.2},
}

# 专用装备 Buff/Debuff 词条池（普通/稀有/太古品质规则与战斗词条共用 terms.json）。
# slots 限定为专用栏位：战斗装备生成（roll_terms）只读 terms.json，因此两套词条互不串味。
DOH_SLOTS = [f"doh{s}" for s in ("Tool", "OffTool", "Head", "Body", "Hands", "Legs", "Feet")]
DOL_SLOTS = [f"dol{s}" for s in ("Tool", "OffTool", "Head", "Body", "Hands", "Legs", "Feet")]
DOHDOL_TERMS = [
    {"id": "dohRarityLuck", "name": "品阶幸运", "type": "buff", "trigger": "常驻",
     "stat": "craftRarityPct", "range": [2, 10], "slots": DOH_SLOTS, "desc": "制造品阶概率 +{v}%"},
    {"id": "dohQualityInsight", "name": "品质洞察", "type": "buff", "trigger": "常驻",
     "stat": "craftQualityPct", "range": [3, 12], "slots": DOH_SLOTS, "desc": "制造品质概率 +{v}%"},
    {"id": "dohDexterous", "name": "巧手", "type": "buff", "trigger": "常驻",
     "stat": "craftSpeedPct", "range": [3, 15], "slots": DOH_SLOTS, "desc": "制造速度 +{v}%"},
    {"id": "dohInspiration", "name": "灵感", "type": "buff", "trigger": "常驻",
     "stat": "craftXpPct", "range": [5, 20], "slots": DOH_SLOTS, "desc": "制造经验 +{v}%"},
    {"id": "dohRarityMisaligned", "name": "品阶失衡", "type": "debuff", "trigger": "常驻",
     "stat": "craftRarityPct", "range": [-8, -2], "slots": DOH_SLOTS, "desc": "制造品阶概率 {v}%"},
    {"id": "dohQualityDull", "name": "品质钝化", "type": "debuff", "trigger": "常驻",
     "stat": "craftQualityPct", "range": [-10, -3], "slots": DOH_SLOTS, "desc": "制造品质概率 {v}%"},
    {"id": "dohClumsy", "name": "笨拙", "type": "debuff", "trigger": "常驻",
     "stat": "craftSpeedPct", "range": [-12, -3], "slots": DOH_SLOTS, "desc": "制造速度 {v}%"},
    {"id": "dolHarvest", "name": "丰收", "type": "buff", "trigger": "常驻",
     "stat": "gatherYieldPct", "range": [3, 15], "slots": DOL_SLOTS, "desc": "采集产量 +{v}%"},
    {"id": "dolSwiftGather", "name": "疾采", "type": "buff", "trigger": "常驻",
     "stat": "gatherSpeedPct", "range": [3, 12], "slots": DOL_SLOTS, "desc": "采集速度 +{v}%"},
    {"id": "dolAnglingJoy", "name": "钓趣", "type": "buff", "trigger": "常驻",
     "stat": "fishInsightPct", "range": [5, 20], "slots": DOL_SLOTS, "desc": "捕鱼人之识时长 +{v}%"},
    {"id": "dolKingInstinct", "name": "渔王的直觉", "type": "buff", "trigger": "常驻",
     "stat": "fishChancePct", "range": [3, 10], "slots": DOL_SLOTS, "desc": "鱼王 / 鱼皇概率 +{v}%"},
    {"id": "dolKeenSense", "name": "博识", "type": "buff", "trigger": "常驻",
     "stat": "gatherXpPct", "range": [5, 20], "slots": DOL_SLOTS, "desc": "采集 / 钓鱼经验 +{v}%"},
    {"id": "dolPoorHarvest", "name": "歉收", "type": "debuff", "trigger": "常驻",
     "stat": "gatherYieldPct", "range": [-12, -3], "slots": DOL_SLOTS, "desc": "采集产量 {v}%"},
    {"id": "dolSluggishGather", "name": "迟缓", "type": "debuff", "trigger": "常驻",
     "stat": "gatherSpeedPct", "range": [-10, -3], "slots": DOL_SLOTS, "desc": "采集速度 {v}%"},
]

dohdol_items = []
for kind in ("doh", "dol"):
    cat_tool = f"{kind}_tool"
    cat_gear = f"{kind}_gear"
    flavor = "巧匠" if kind == "doh" else "大地"
    for suffix, name, stype in SLOTS:
        for t in DOHDOL_TIERS:
            for v in VARIANTS_BY_KIND[kind]:
                if v["minTier"] > t["index"]:
                    continue
                # 变体 bias 既能缩放栏位已有的属性，也能引入该栏位没有的属性
                # （如「悟道」的 craftXpPct、「迅捷」的 craftSpeedPct）：缺省基准系数 1.0。
                slot_bonus = SLOT_BONUS[(kind, suffix)]
                stats = list(slot_bonus) + [s for s in v["bias"] if s not in slot_bonus]
                bonus = {
                    stat: round(
                        slot_bonus.get(stat, 1.0) * float(t["power"]) * float(v["bias"].get(stat, 1.0)), 1
                    )
                    for stat in stats
                }
                vid = v["id"]
                dohdol_items.append({
                    "id": f"dh_{kind}{suffix}{f'_{vid}' if vid else ''}_{t['index']}",
                    "name": f"{t['name']}{v['name']}{flavor}{name}",
                    "category": cat_tool if stype == "tool" else cat_gear,
                    "slot": f"{kind}{suffix}",
                    "kind": kind,
                    "variant": vid,
                    "tierIndex": t["index"],
                    "levelReq": t["levelReq"],
                    "bonus": bonus,
                })

dump("dohdol-equipment.json", {
    "$comment": "生产/采集专用装备：仅能通过生产制造获取，只影响采集/制造/钓鱼，不参与战斗结算与战力。",
    "slots": [
        {"id": "dohTool", "name": "生产主手工具", "category": "doh_tool", "order": 0},
        {"id": "dohOffTool", "name": "生产副手工具", "category": "doh_tool", "order": 1},
        {"id": "dohHead", "name": "生产头饰", "category": "doh_gear", "order": 2},
        {"id": "dohBody", "name": "生产工作服", "category": "doh_gear", "order": 3},
        {"id": "dohHands", "name": "生产手套", "category": "doh_gear", "order": 4},
        {"id": "dohLegs", "name": "生产工作裤", "category": "doh_gear", "order": 5},
        {"id": "dohFeet", "name": "生产工作靴", "category": "doh_gear", "order": 6},
        {"id": "dolTool", "name": "采集主手工具", "category": "dol_tool", "order": 7},
        {"id": "dolOffTool", "name": "采集副手工具", "category": "dol_tool", "order": 8},
        {"id": "dolHead", "name": "采集头饰", "category": "dol_gear", "order": 9},
        {"id": "dolBody", "name": "采集服", "category": "dol_gear", "order": 10},
        {"id": "dolHands", "name": "采集手套", "category": "dol_gear", "order": 11},
        {"id": "dolLegs", "name": "采集裤", "category": "dol_gear", "order": 12},
        {"id": "dolFeet", "name": "采集靴", "category": "dol_gear", "order": 13},
    ],
    "categories": [
        {"id": "doh_tool", "name": "生产工具", "kind": "doh"},
        {"id": "doh_gear", "name": "生产防具", "kind": "doh"},
        {"id": "dol_tool", "name": "采集工具", "kind": "dol"},
        {"id": "dol_gear", "name": "采集防具", "kind": "dol"},
    ],
    "bonusNames": BONUS_NAMES,
    "terms": DOHDOL_TERMS,
    "items": dohdol_items,
})

# ---------------------------------------------------------------- 鱼类
# 鱼名参考《最终幻想 XIV》的鱼类命名（普通鱼在多个钓场重复出现是正常的；
# 鱼王 / 鱼皇每个地区各一条，名称互不重复）。
FISH_NORMAL_NAMES = [
    "河鲈", "海鲈", "三文鱼", "鲤鱼", "泥鳅", "银鱼", "香鱼", "鳟鱼",
    "白鲑", "茴鱼", "鲱鱼", "沙丁鱼", "鲭鱼", "鲣鱼", "金枪鱼", "旗鱼",
    "鲷鱼", "石斑鱼", "比目鱼", "鲽鱼", "鳐鱼", "鲨鱼", "河豚", "灯笼鱼",
    "海马", "神仙鱼", "蝴蝶鱼", "小丑鱼", "章鱼", "乌贼", "水母", "海星",
    "螃蟹", "龙虾", "扇贝", "牡蛎", "海胆", "鲍鱼", "珊瑚鱼", "深海鳕",
]
FISH_KING_NAMES = [
    "涅普特之龙", "利维亚桑的眷属", "蓝宝石恶魔", "红玉蛇", "熔岩王", "冰霜帝王",
    "沙海之主", "苍天霸主", "深渊恐惧", "幽灵船长", "千年鲟", "湖之主",
    "雷鸣鲶", "白银之鳞", "黄金鲷", "黑曜石鲨", "翡翠巨龙", "紫电鳗",
    "苍翼飞鱼", "血月鳐", "星辉水母", "虚空鲸", "太古腔棘鱼", "沸腾章鱼",
    "极光鲑", "沙漠鲵", "沼泽之主", "森林守卫", "遗迹守护者", "巨型三角鱼",
    "风暴旗鱼", "冰海巨兽", "火焰鲡", "云端鲲", "幽谷潜者", "圣泉之鱼",
    "王都锦鲤", "熔心鲟", "天外怪兽", "终末鲸",
]
FISH_EMPEROR_NAMES = [
    "海皇利维亚桑", "神龙之影", "世界蛇", "太古利维坦", "群星之鲸", "混沌之鱼",
    "终焉之鲟", "苍穹之翼", "大地之脾", "月读的守望", "火神之鳞", "风神之息",
    "水神之泪", "雷神之怒", "冰神之牙", "土神之核", "圣兽白虎", "朱雀之羽",
    "青龙之鳞", "玄武之甲", "森罗万象", "时间之鱼", "虚空之王", "星海之主",
    "永劫之鲛", "创世之鲲", "灭世之鲸", "天启之鳞", "究极神鱼", "完美之鱼",
    "无瑕之鳞", "黄金之王", "极乐鸟鱼", "幻海之主", "万象之鱼", "万物之始",
    "终末之鲛", "原初之鱼", "十二神之鳞", "艾欧泽亚之王",
]
assert len(FISH_KING_NAMES) >= len(regions) and len(FISH_EMPEROR_NAMES) >= len(regions)
assert len(FISH_NORMAL_NAMES) >= 4

fish_regions = []
for index, r in enumerate(regions):
    rid = r["id"]
    # 每个钓场 4 种普通鱼，按地区错开取名（同一鱼种在多个钓场出现是正常的）
    normal = []
    for slot in range(4):
        name = FISH_NORMAL_NAMES[(index * 2 + slot) % len(FISH_NORMAL_NAMES)]
        weight = [55, 28, 14, 3][slot]
        smin, smax = [(20, 60), (30, 90), (50, 130), (60, 150)][slot]
        normal.append({
            "id": f"f{rid}_{slot + 1}", "name": name,
            "weight": weight, "sizeMin": smin, "sizeMax": smax,
            "exp": 4 + rid // 4, "sell": fish_sell(rid),
        })
    fish_regions.append({
        "regionId": rid,
        "name": r["name"],
        "normal": normal,
        "king": {
            "id": f"k{rid}", "name": FISH_KING_NAMES[index],
            "prereqFishIds": [f"f{rid}_1", f"f{rid}_2"],
            "insightSeconds": [30, 45], "chance": 0.014,
            "sizeMin": 160, "sizeMax": 240, "exp": 40 + rid, "sell": king_sell(rid),
        },
        "emperor": {
            "id": f"e{rid}", "name": FISH_EMPEROR_NAMES[index],
            "prereqFishIds": [f"f{rid}_1", f"f{rid}_2", f"f{rid}_3", f"f{rid}_4"],
            "insightSeconds": [45, 60], "chance": 0.004,
            "sizeMin": 240, "sizeMax": 360, "exp": 120 + rid * 2, "sell": emperor_sell(rid),
        },
    })

dump("fish.json", {
        "$comment": "钓场。每个地区一个钓场：普通鱼按权重、随机尺寸；鱼王/鱼皇需先钓起指定普通鱼以开启「捕鱼人之识」，期间才有小概率出现。鱼皇概率低于鱼王。sell 为出售单价（金币），按 FISH_SELL / KING_SELL / EMPEROR_SELL 档位表递增（越高档涨幅越大，低阶几乎不变），鱼王/鱼皇分别约为同档普通鱼的 20× / 80×。",
    "castSeconds": 3.0,
    "insightBuffName": "捕鱼人之识",
    "regions": fish_regions,
})

# ---------------------------------------------------------------- 消耗品
# 药食分三档：I 档（生产 Lv1，现有）、II 档（Lv40）、III 档（Lv80）。效果按 scale 放大，
# 但单个物品的持续时长不变（由 kinds 决定：药水 60s / 食物 1800s）。
CONSUMABLE_TIERS = [
    {"suffix": "", "label": "", "level": 1, "scale": 1.0, "seconds": 2.5, "xp": 40},
    {"suffix": "2", "label": " II", "level": 40, "scale": 2.0, "seconds": 5.0, "xp": 80},
    {"suffix": "3", "label": " III", "level": 80, "scale": 4.0, "seconds": 8.0, "xp": 160},
]
POTION_EFFECTS = [
    ("expGainPct", 25, "经验获取"), ("goldGainPct", 25, "金币获取"),
    ("chestLuck", 0.15, "抽箱品阶概率"), ("craftQualityPct", 10, "制造品质概率"),
    ("craftRarityPct", 15, "制造品阶概率"),
    ("fishInsightPct", 50, "捕鱼人之识时长"), ("gatherYieldPct", 30, "采集产量"),
]
FOOD_EFFECTS = [
    ("expGainPct", 10, "经验获取"), ("goldGainPct", 10, "金币获取"),
    ("chestLuck", 0.06, "抽箱品阶概率"), ("craftQualityPct", 4, "制造品质概率"),
    ("craftRarityPct", 6, "制造品阶概率"),
    ("fishInsightPct", 20, "捕鱼人之识时长"), ("gatherYieldPct", 12, "采集产量"),
]


def scaled_effect(value, scale):
    """按档位放大效果值；I 档原样返回，整数保持整数（避免无谓的 JSON 漂移）。"""
    if scale == 1.0:
        return value
    out = value * scale
    return int(out) if isinstance(value, int) else round(out, 2)


consumables = []
CONSUMABLE_TIER_BY_ID = {}
for tier in CONSUMABLE_TIERS:
    scale = tier["scale"]
    for stat, value, label in POTION_EFFECTS:
        effects = [{"stat": stat, "value": scaled_effect(value, scale)}]
        if stat == "fishInsightPct":
            effects.append({"stat": "fishChancePct", "value": scaled_effect(3.0, scale)})
        cid = f"p_{stat}{tier['suffix']}"
        consumables.append({
            "id": cid, "name": f"{label}秘药{tier['label']}", "kind": "potion",
            "effects": effects, "desc": f"60 秒内{label}提升。",
            "sell": int(round(120 * scale)),
        })
        CONSUMABLE_TIER_BY_ID[cid] = tier
    for stat, value, label in FOOD_EFFECTS:
        effects = [{"stat": stat, "value": scaled_effect(value, scale)}]
        if stat == "fishInsightPct":
            effects.append({"stat": "fishChancePct", "value": scaled_effect(1.2, scale)})
        cid = f"f_{stat}{tier['suffix']}"
        consumables.append({
            "id": cid, "name": f"{label}料理{tier['label']}", "kind": "food",
            "effects": effects,
            "desc": f"1800 秒内{label}{'小幅' if scale == 1.0 else '大幅'}提升，可与药水共存。",
            "sell": int(round(50 * scale)),
        })
        CONSUMABLE_TIER_BY_ID[cid] = tier


def consumable_stat_max(stat):
    """某 stat 的可达上限：药水 / 食物各占一个槽位，故按 kind 取最大值再求和。"""
    best = {}
    for c in consumables:
        for e in c["effects"]:
            if e["stat"] == stat:
                best[c["kind"]] = max(best.get(c["kind"], 0.0), float(e["value"]))
    return sum(best.values())

dump("consumables.json", {
    "$comment": "药水（60s，效果强）与食物（1800s，效果弱）。分 I/II/III 三档，档位越高效果越强（×1/×2/×4），但单个物品的持续时长不变；II/III 档配方需生产等级 40/80。可同时生效（各占一个槽位），由玩家手动使用。效果不影响战力与地区/副本门槛。sell 为出售单价（金币）。",
    "kinds": {
        "potion": {"name": "药水", "durationSec": 60},
        "food": {"name": "食物", "durationSec": 1800},
    },
    "effectNames": {
        "expGainPct": "经验获取", "goldGainPct": "金币获取", "chestLuck": "抽箱品阶概率",
        "craftQualityPct": "制造品质概率", "craftRarityPct": "制造品阶概率",
        "fishInsightPct": "捕鱼人之识时长",
        "fishChancePct": "鱼王/鱼皇概率", "gatherYieldPct": "采集产量",
    },
    "items": consumables,
})

# ---------------------------------------------------------------- 配方
recipes = []


def add(rid, job, level, secs, xp, inputs, output):
    recipes.append({
        "id": rid, "jobId": job, "requiredLevel": level, "craftSeconds": secs, "xp": xp,
        "inputs": [{"itemId": i, "count": c} for i, c in inputs], "output": output,
    })


half_inputs = {
    "h_plank": [("g_wood", 3)],
    "h_ingot": [("g_ore", 3)],
    "h_steel": [("h_ingot", 2), ("g_stone", 1)],
    "h_plate": [("g_ore", 2), ("g_stone", 2)],
    "h_alloy": [("h_plate", 2), ("g_gem", 1)],
    "h_gemcut": [("g_gem", 2), ("g_stone", 1)],
    "h_glass": [("g_stone", 2), ("g_gem", 1)],
    "h_leather": [("g_fiber", 3)],
    "h_cloth": [("g_fiber", 2), ("g_herb", 1)],
    "h_ink": [("g_herb", 3)],
    "h_oil": [("g_herb", 2), ("g_wood", 1)],
    "h_flour": [("g_herb", 2), ("g_fiber", 1)],
}
half_job = {h[0]: h[2] for h in HALVES}
half_level = {"h_steel": 5, "h_plate": 5, "h_alloy": 12, "h_gemcut": 8, "h_glass": 8, "h_oil": 6}
for hid, inputs in half_inputs.items():
    add(f"r_{hid}", half_job[hid], half_level.get(hid, 1), 2.0, 16 + half_level.get(hid, 1) * 8, inputs,
        {"kind": "material", "itemId": hid, "count": 1})

GEAR_INPUTS = {
    "Tool": [("h_plank", 2), ("h_ingot", 2)],
    "OffTool": [("h_leather", 2), ("h_ingot", 1)],
    "Head": [("h_leather", 2), ("h_cloth", 1)],
    "Body": [("h_cloth", 3), ("h_leather", 2)],
    "Hands": [("h_leather", 2), ("h_plate", 1)],
    "Legs": [("h_cloth", 2), ("h_leather", 2)],
    "Feet": [("h_leather", 3)],
}
GEAR_JOB = {
    ("doh", "Tool"): "CRP", ("doh", "OffTool"): "BSM", ("doh", "Head"): "LTW",
    ("doh", "Body"): "WVR", ("doh", "Hands"): "LTW", ("doh", "Legs"): "WVR", ("doh", "Feet"): "LTW",
    ("dol", "Tool"): "BSM", ("dol", "OffTool"): "CRP", ("dol", "Head"): "LTW",
    ("dol", "Body"): "WVR", ("dol", "Hands"): "LTW", ("dol", "Legs"): "WVR", ("dol", "Feet"): "LTW",
}
TIER_LEVEL = {t["index"]: t["levelReq"] for t in DOHDOL_TIERS}
# 每件装备都消耗一份地区专属材料，并按游标轮转，保证 40 个地区的 ore / flora 全部被配方用到。
REGION_COUNT = len(regions)
ore_cursor = 0
flora_cursor = 0
for item in dohdol_items:
    suffix = item["slot"][3:]
    kind = item["kind"]
    t = item["tierIndex"]
    inputs = [(m, c * (t + 1)) for m, c in GEAR_INPUTS[suffix]]
    if suffix in ("Tool", "Hands"):
        region_mat = f"ore{(ore_cursor % REGION_COUNT) + 1}"
        ore_cursor += 1
    else:
        region_mat = f"flora{(flora_cursor % REGION_COUNT) + 1}"
        flora_cursor += 1
    inputs.append((region_mat, 1 + t))
    add(f"r_{item['id']}", GEAR_JOB[(kind, suffix)], TIER_LEVEL[t], 3.0 + t * 0.6, 30 + t * 80,
        inputs, {"kind": "equipment", "baseId": item["id"]})

COMBAT_RECIPES = [
    ("CRP", ["w_bow_2", "w_rod_2", "w_lance_2", "w_katana_4", "w_brush_4"]),
    ("BSM", ["w_sword_shield_2", "w_axe_4", "w_greatsword_4", "w_gunblade_2", "w_dualDagger_2"]),
    ("ARM", ["a_head_4", "a_body_4", "a_hands_4", "a_legs_4", "a_feet_4"]),
    ("GSM", ["c_ring_4", "c_necklace_4", "c_earring_4", "c_bracelet_4"]),
]
for job, ids in COMBAT_RECIPES:
    for base_id in ids:
        tier = 4 if base_id.endswith("_4") else 2
        rid = ((tier * 11) % 40) + 1
        add(f"r_{base_id}", job, 10 + tier * 12, 4.0 + tier, 60 + tier * 50,
            [("h_ingot", 3 + tier), ("h_alloy" if tier >= 3 else "h_plate", 2),
             ("g_gem", 2), ("ore" + str(rid), 2 + tier)],
            {"kind": "equipment", "baseId": base_id})

# 战斗职业装备配方：档位 6/7/8（苍穹/星辉/终末 = Lv90/95/100）。
# 覆盖全部武器族 / 防具部位 / 饰品部位及其职能变体；生产门槛 = 装备等级。
CRP_WEAPONS = {"bow", "rod", "staff", "lance", "katana", "brush", "chakram", "globe", "grimoire", "book"}
COMBAT_MAIN_HALF = {"CRP": "h_plank", "BSM": "h_ingot", "ARM": "h_plate", "GSM": "h_gemcut"}


def _variant_suffix(v):
    return f"_{v['id']}" if v["id"] else ""


_combat_ore = 0
_combat_flora = 0


def combat_inputs(job, tier_index, weight=1):
    global _combat_ore, _combat_flora
    base = tier_index - 4  # 6→2, 7→3, 8→4
    if job == "CRP":
        _combat_flora += 1
        region_mat = f"flora{(_combat_flora - 1) % REGION_COUNT + 1}"
    else:
        _combat_ore += 1
        region_mat = f"ore{(_combat_ore - 1) % REGION_COUNT + 1}"
    return [
        (COMBAT_MAIN_HALF[job], weight * 2 * base),
        ("h_alloy", weight * base),
        ("g_gem", 2 + base),
        (region_mat, weight * 2 * base),
    ]


# 防具按部位给主料加权，越重的部位消耗越多
ARMOR_WEIGHT = {"head": 1, "body": 2, "hands": 1, "legs": 2, "feet": 1}

for t in (t for t in BASE_ITEMS["tiers"] if t["index"] in (6, 7, 8)):
    for fam in BASE_ITEMS["weaponFamilies"]:
        job = "CRP" if fam["weaponType"] in CRP_WEAPONS else "BSM"
        for v in BASE_ITEMS["variants"]["weapon"]:
            if v.get("minTier", 0) > t["index"]:
                continue
            bid = f"w_{fam['weaponType']}{_variant_suffix(v)}_{t['index']}"
            add(f"r_{bid}", job, t["levelReq"], 8.0 + t["index"], 200 + t["index"] * 30,
                combat_inputs(job, t["index"]), {"kind": "equipment", "baseId": bid})
    for fam in BASE_ITEMS["armorFamilies"]:
        for v in BASE_ITEMS["variants"]["armor"]:
            if v.get("minTier", 0) > t["index"]:
                continue
            bid = f"a_{fam['slot']}{_variant_suffix(v)}_{t['index']}"
            add(f"r_{bid}", "ARM", t["levelReq"], 8.0 + t["index"], 200 + t["index"] * 30,
                combat_inputs("ARM", t["index"], weight=ARMOR_WEIGHT[fam["slot"]]),
                {"kind": "equipment", "baseId": bid})
    for fam in BASE_ITEMS["accessoryFamilies"]:
        for v in BASE_ITEMS["variants"]["accessory"]:
            if v.get("minTier", 0) > t["index"]:
                continue
            bid = f"c_{fam['slot']}{_variant_suffix(v)}_{t['index']}"
            add(f"r_{bid}", "GSM", t["levelReq"], 8.0 + t["index"], 200 + t["index"] * 30,
                combat_inputs("GSM", t["index"]), {"kind": "equipment", "baseId": bid})

# I 档（现有）用通用材料；II/III 档换用对应地区的采集材料（flora17/ore17、flora32/ore32），
# 且输入出售价合计不低于产出，避免「采集 → 制造 → 出售」成为刷金币路线。
CONSUMABLE_INPUTS = {
    "p_expGainPct": [("h_ink", 2), ("g_herb", 3)], "p_goldGainPct": [("h_ink", 2), ("g_gem", 2)],
    "p_chestLuck": [("h_gemcut", 2), ("h_ink", 2)], "p_craftQualityPct": [("h_oil", 2), ("h_ink", 2)],
    "p_craftRarityPct": [("h_gemcut", 2), ("h_oil", 2)],
    "p_fishInsightPct": [("h_oil", 3), ("g_herb", 3)], "p_gatherYieldPct": [("h_oil", 2), ("g_fiber", 3)],
    "f_expGainPct": [("h_flour", 2), ("g_herb", 2)], "f_goldGainPct": [("h_flour", 2), ("g_gem", 1)],
    "f_chestLuck": [("h_flour", 2), ("h_gemcut", 1)], "f_craftQualityPct": [("h_flour", 2), ("h_oil", 1)],
    "f_craftRarityPct": [("h_flour", 2), ("h_gemcut", 1)],
    "f_fishInsightPct": [("h_flour", 3), ("g_herb", 2)], "f_gatherYieldPct": [("h_flour", 2), ("g_fiber", 2)],

    # II 档（生产 Lv40，地区 17 材料，单价 32）
    "p_expGainPct2": [("h_ink", 2), ("flora17", 5)], "p_goldGainPct2": [("h_ink", 2), ("ore17", 5)],
    "p_chestLuck2": [("h_gemcut", 2), ("h_ink", 2), ("flora17", 2)],
    "p_craftQualityPct2": [("h_oil", 2), ("h_ink", 2), ("ore17", 2)],
    "p_craftRarityPct2": [("h_gemcut", 2), ("h_oil", 2), ("ore17", 2)],
    "p_fishInsightPct2": [("h_oil", 3), ("flora17", 4)], "p_gatherYieldPct2": [("h_oil", 2), ("flora17", 5)],
    "f_expGainPct2": [("h_flour", 2), ("flora17", 2)], "f_goldGainPct2": [("h_flour", 2), ("ore17", 2)],
    "f_chestLuck2": [("h_flour", 2), ("flora17", 2)], "f_craftQualityPct2": [("h_flour", 2), ("ore17", 2)],
    "f_craftRarityPct2": [("h_flour", 2), ("ore17", 2)],
    "f_fishInsightPct2": [("h_flour", 3), ("flora17", 2)], "f_gatherYieldPct2": [("h_flour", 2), ("flora17", 2)],

    # III 档（生产 Lv80，地区 32 材料，单价 128）
    "p_expGainPct3": [("h_ink", 2), ("flora32", 3)], "p_goldGainPct3": [("h_ink", 2), ("ore32", 3)],
    "p_chestLuck3": [("h_gemcut", 2), ("h_ink", 2), ("flora32", 3)],
    "p_craftQualityPct3": [("h_oil", 2), ("h_ink", 2), ("ore32", 3)],
    "p_craftRarityPct3": [("h_gemcut", 2), ("h_oil", 2), ("ore32", 3)],
    "p_fishInsightPct3": [("h_oil", 3), ("flora32", 3)], "p_gatherYieldPct3": [("h_oil", 2), ("flora32", 3)],
    "f_expGainPct3": [("h_flour", 2), ("flora32", 1)], "f_goldGainPct3": [("h_flour", 2), ("ore32", 1)],
    "f_chestLuck3": [("h_flour", 2), ("flora32", 1)], "f_craftQualityPct3": [("h_flour", 2), ("ore32", 1)],
    "f_craftRarityPct3": [("h_flour", 2), ("ore32", 1)],
    "f_fishInsightPct3": [("h_flour", 3), ("flora32", 1)], "f_gatherYieldPct3": [("h_flour", 2), ("flora32", 1)],
}
for c in consumables:
    job = "ALC" if c["kind"] == "potion" else "CUL"
    tier = CONSUMABLE_TIER_BY_ID[c["id"]]
    add(f"r_{c['id']}", job, tier["level"], tier["seconds"], tier["xp"], CONSUMABLE_INPUTS[c["id"]],
        {"kind": "consumable", "itemId": c["id"], "count": 1})

dump("recipes.json", {
    "$comment": "生产配方。按生产等级解锁；inputs 引用材料/半成品/鱼，output 可为材料/半成品/装备/消耗品。",
    "$commentEquipment": "制造装备恒为「高品质」：属性区间整体上移，且必带太古词条；品阶按 rarityScaling 动态抽取（全部来源满值 → 神话 20%）。",
    "equipment": {
        "highQualityMultiplier": 1.15,
        "guaranteedAncientTerms": 1,
        "$commentXpRarityMultiplier": "制造装备的经验系数：按实际抽到的品阶乘在配方基础 xp 上，品阶越高经验越多（材料 / 半成品 / 消耗品无品阶，恒按 1.0）。",
        "xpRarityMultiplier": {
            "common": 1.0, "uncommon": 1.2, "rare": 1.5, "epic": 1.9, "legendary": 2.4, "mythic": 3.0,
        },
        "rarityWeights": {
            "common": 0.30, "uncommon": 0.30, "rare": 0.22, "epic": 0.12, "legendary": 0.05, "mythic": 0.01,
        },
        "$commentRarityScaling": "制造品阶概率随进度提升：t = Σ weight × clamp(值 / ref, 0, 1)（权重合计 = 1，仅全部来源拉满时 t=1）；分布 = 基准 ×(1−t) + 目标 × t。来源：英雄等级 / 通关地区数 / 生产等级 / 专用装备品阶幸运(craftRarityPct) / 制造品阶概率药食(craftRarityPct) / 远征通关(难度加权首通) / 高难通关(难度加权首通)。各 ref 为对应来源的真实最大值（含太古词条），因此「上限」只有全来源满才能达到 → 神话 = mythicCap（20%，硬上限）。",
        "rarityScaling": {
            "mythicCap": 0.2,
            "sources": {
                "heroLevel": {"weight": 0.15, "ref": 100},
                "clearedRegions": {"weight": 0.10, "ref": 40},
                "prodLevel": {"weight": 0.15, "ref": 100},
                "gearPct": {"weight": 0.25, "ref": 186.1},
                "consumablePct": {"weight": 0.10, "ref": int(consumable_stat_max("craftRarityPct"))},
                "coopClears": {"weight": 0.15, "ref": 33},
                "raidClears": {"weight": 0.10, "ref": 10},
            },
            "targetWeights": {
                "common": 0.02, "uncommon": 0.03, "rare": 0.14, "epic": 0.29, "legendary": 0.32, "mythic": 0.20,
            },
        },
    },
    "recipes": recipes,
})

# ---------------------------------------------------------------- 称号
dump("titles.json", {
    "$comment": "称号。钓起全部地区的鱼王 / 鱼皇各解锁一个称号，展示在排行榜。",
    "titles": [
        {"id": "fish_king_all", "name": "鱼王猎手", "desc": "钓起全部地区的鱼王", "condition": {"type": "all_king"}},
        {"id": "fish_emperor_all", "name": "海皇", "desc": "钓起全部地区的鱼皇", "condition": {"type": "all_emperor"}},
    ],
})

print("done")

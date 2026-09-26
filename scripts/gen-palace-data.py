# -*- coding: utf-8 -*-
"""生成「死者宫殿」玩法的 shared/data JSON。

用法（仓库根目录）：`python scripts/gen-palace-data.py`

生成：
- `palace.json`       主配置：层 / 步、节点权重、怪物曲线、战斗奖励、层 BOSS 奖励、副本 BUFF 池、
                      商店、代币兑换表、副本等级上限与复活次数。
- `palace-growth.json` 局外成长树：类别 × 层级（脚本按规则铺满，关键类别数值在下方表格手工精调）。
- `palace-events.json` 事件库（手工撰写，≥32 条）。

设计：数值全部集中在 JSON，本脚本只做「按规则铺量 + 关键项手工精调」，改内容后重跑即可。
回归保护：backend/tests/test_shared_data.py::test_palace_config_is_consistent。
"""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "shared" / "data"


def dump(name, obj):
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", name)


# ---------------------------------------------------------------- 主配置 palace.json

# 每层普通怪的基准数值（精英 / BOSS 用倍率）。曲线按「零成长 ≤5 层、满成长可秒杀前几层」标定。
FLOOR_STATS = [
    # floor, hp,     attack, defense, xp,     gold
    (1, 200, 20, 8, 55, 30),
    (2, 620, 48, 24, 140, 70),
    (3, 1900, 112, 60, 340, 150),
    (4, 5800, 260, 150, 820, 320),
    (5, 18000, 620, 400, 2200, 700),
    (6, 52000, 1500, 1050, 6000, 1500),
    (7, 150000, 3400, 2600, 16000, 3200),
    (8, 420000, 7600, 6000, 44000, 7000),
    (9, 1150000, 16500, 13500, 120000, 15000),
    (10, 3100000, 35000, 30000, 330000, 32000),
]

# 副本内持久 BUFF 池（战斗奖励 / 事件获得）。stat 键与 services/palace_stats.py 的映射一一对应，
# value 为百分比加值（attackPct/defensePct/hpPct 为乘算，其余为直接加值）。
RUN_BUFFS = [
    {"id": "pb_atk", "name": "狂怒", "stat": "attackPct", "value": 8, "desc": "攻击力 +8%"},
    {"id": "pb_def", "name": "坚壁", "stat": "defensePct", "value": 8, "desc": "防御力 +8%"},
    {"id": "pb_hp", "name": "强健", "stat": "hpPct", "value": 12, "desc": "生命上限 +12%"},
    {"id": "pb_crit", "name": "锐眼", "stat": "critRatePct", "value": 4, "desc": "暴击率 +4%"},
    {"id": "pb_dh", "name": "致命", "stat": "dhRatePct", "value": 4, "desc": "直击率 +4%"},
    {"id": "pb_spd", "name": "疾风", "stat": "attackSpeedPct", "value": 6, "desc": "攻击速度 +6%"},
    {"id": "pb_vamp", "name": "吸血", "stat": "lifestealPct", "value": 3, "desc": "吸血 +3%"},
    {"id": "pb_guard", "name": "坚韧", "stat": "tenacityPct", "value": 5, "desc": "伤害减免 +5%"},
    {"id": "pb_haste", "name": "急速", "stat": "hastePct", "value": 6, "desc": "技能急速 +6%"},
    {"id": "pb_dodge", "name": "闪避", "stat": "dodgePct", "value": 5, "desc": "闪避率 +5%"},
    {"id": "pb_det", "name": "信念", "stat": "detBonusPct", "value": 5, "desc": "信念增伤 +5%"},
    {"id": "pb_spring", "name": "灵泉", "stat": "mpRegenPct", "value": 25, "desc": "魔力回复 +25%"},
]

# 商店商品模板（副本金币消费，价格随层上涨）。kind=grant_buff / heal / grant_equip。
SHOP_OFFERS = [
    {"id": "sh_heal", "name": "治疗药水", "kind": "heal", "value": 0.4, "price": 60, "desc": "回复 40% 生命"},
    {"id": "sh_buff_atk", "name": "狂怒药剂", "kind": "grant_buff", "buffId": "pb_atk", "price": 90},
    {"id": "sh_buff_def", "name": "坚壁药剂", "kind": "grant_buff", "buffId": "pb_def", "price": 90},
    {"id": "sh_buff_hp", "name": "强健药剂", "kind": "grant_buff", "buffId": "pb_hp", "price": 110},
    {"id": "sh_equip", "name": "神秘装备", "kind": "grant_equip", "price": 220, "desc": "获得一件随机装备"},
    {"id": "sh_buff_spd", "name": "疾风药剂", "kind": "grant_buff", "buffId": "pb_spd", "price": 100},
]

# 代币兑换表：纹章（1-5 层）/ 南瓜（6-10 层）→ 账号背包物品。
EXCHANGE = [
    {"id": "ex_seed_gold", "name": "金币种子", "cost": {"flameCrest": 2, "glassPumpkin": 0},
     "grant": {"kind": "stack", "itemId": "seed_gold", "count": 1}},
    {"id": "ex_seed_exp", "name": "经验种子", "cost": {"flameCrest": 3, "glassPumpkin": 0},
     "grant": {"kind": "stack", "itemId": "seed_exp", "count": 1}},
    {"id": "ex_materia_l5", "name": "伍型魔晶石（随机）", "cost": {"flameCrest": 0, "glassPumpkin": 3},
     "grant": {"kind": "materia", "level": 5, "count": 1}},
    {"id": "ex_recraft_card", "name": "重新打造卡", "cost": {"flameCrest": 0, "glassPumpkin": 1},
     "grant": {"kind": "stack", "itemId": "recraft_card", "count": 1}},
    {"id": "ex_potion3", "name": "叁级秘药（随机）", "cost": {"flameCrest": 4, "glassPumpkin": 0},
     "grant": {"kind": "random_consumable", "consumableKind": "potion", "tier": 3, "count": 1}},
    {"id": "ex_food3", "name": "叁级料理（随机）", "cost": {"flameCrest": 4, "glassPumpkin": 0},
     "grant": {"kind": "random_consumable", "consumableKind": "food", "tier": 3, "count": 1}},
]

palace = {
    "$comment": (
        "死者宫殿：与账号战力完全隔离的 roguelike 深层迷宫。10 层 × 每层至多 10 步（第 10 步为层 BOSS）；"
        "副本内英雄 1 级起步、装备与金币自成一套。数值由 scripts/gen-palace-data.py 生成，"
        "标定见 scripts/palace-balance.py 与 backend/tests/test_balance.py。"
    ),
    "version": "1.0.0",
    "floors": 10,
    "stepsPerFloor": 10,
    "levelCap": 50,
    "revives": 1,
    "heroCandidates": 3,
    "weaponCandidates": 3,
    "rewardChoices": 3,
    "$commentNodes": "节点类型权重（按步段区分；第 10 步固定 boss）。各行权重之和必须为 1。",
    "nodeTypeWeights": [
        {"maxStep": 4, "weights": {"battle": 0.50, "elite": 0.10, "event": 0.22, "shop": 0.06, "chest": 0.08, "rest": 0.04}},
        {"maxStep": 7, "weights": {"battle": 0.45, "elite": 0.15, "event": 0.20, "shop": 0.08, "chest": 0.08, "rest": 0.04}},
        {"maxStep": 9, "weights": {"battle": 0.40, "elite": 0.20, "event": 0.18, "shop": 0.08, "chest": 0.08, "rest": 0.06}},
    ],
    "$commentMonsters": "每层普通怪基准值；elite / boss 为倍率。xp / gold 为节点产出基准。",
    "monsters": {
        "floors": [
            {"floor": f, "hp": hp, "attack": atk, "defense": df, "xp": xp, "gold": gold}
            for (f, hp, atk, df, xp, gold) in FLOOR_STATS
        ],
        "elite": {"hp": 2.2, "attack": 1.3, "defense": 1.5, "xp": 2.0, "gold": 2.0},
        "boss": {"hp": 6.5, "attack": 1.6, "defense": 1.7, "xp": 6.0, "gold": 6.0},
    },
    "$commentBossReward": "击败层 BOSS 的成长点 / 代币（按层 1..10）；击败第 10 层额外 clearBonusGrowthPoints。",
    "bossReward": {
        "growthPoints": [2, 2, 3, 3, 4, 4, 5, 5, 6, 10],
        "flameCrest": [1, 1, 1, 2, 2, 0, 0, 0, 0, 0],
        "glassPumpkin": [0, 0, 0, 0, 0, 1, 1, 2, 2, 3],
        "clearBonusGrowthPoints": 10,
    },
    "$commentRewardWeights": "战斗奖励三选一的种类权重：装备 / BUFF / 两者。",
    "rewardWeights": {"equip": 0.45, "buff": 0.35, "both": 0.20},
    "eliteRewardBonus": {"extraRolls": 1, "rarityLuck": 0.15},
    "bossRewardBonus": {"extraRolls": 2, "rarityLuck": 0.35},
    "buffs": RUN_BUFFS,
    "shop": {"offersPerShop": 4, "pool": SHOP_OFFERS, "pricePerFloor": 0.25},
    "exchange": EXCHANGE,
    "$commentGen": "开局英雄 / 武器生成。武器档位 = baseLevelBand + 局外成长 equipLevel（取整）。",
    "heroGen": {"baseLevel": 1},
    "weaponGen": {"baseLevelBand": 1, "boxTier": "normal"},
    "$commentRevive": "阵亡时可消耗复活次数原地续战；用尽则本次 run 结束（已入账奖励保留）。",
    "deathEndsRun": True,
}

dump("palace.json", palace)


# ---------------------------------------------------------------- 局外成长树 palace-growth.json

# (类别 id, 中文名, 说明, 效果 stat, 每级数值, 数值模式 add|mul)
GROWTH_CATEGORIES = [
    ("hero_talent", "英雄资质", "提高进入副本时出现高品质英雄的概率。", "heroTalentWeight", 0.06, "add"),
    ("hero_attack", "英雄攻击", "提高副本内英雄攻击力。", "heroAttackPct", 0.06, "mul"),
    ("hero_defense", "英雄防御", "提高副本内英雄防御力。", "heroDefensePct", 0.06, "mul"),
    ("hero_hp", "英雄生命", "提高副本内英雄生命上限。", "heroHpPct", 0.07, "mul"),
    ("hero_str", "英雄力量", "提高副本内英雄力量。", "heroStrPct", 0.05, "mul"),
    ("hero_dex", "英雄敏捷", "提高副本内英雄敏捷。", "heroDexPct", 0.05, "mul"),
    ("hero_int", "英雄智力", "提高副本内英雄智力。", "heroIntPct", 0.05, "mul"),
    ("start_level", "初始等级", "提高副本内英雄的起始等级。", "startLevel", 0.5, "add"),
    ("start_gold", "初始金币", "提高进入副本时的副本金币。", "startGold", 25, "add"),
    ("crit", "暴击", "提高副本内暴击率。", "critRatePct", 1.0, "add"),
    ("dh", "直击", "提高副本内直击率。", "dhRatePct", 1.0, "add"),
    ("attack_speed", "攻击速度", "提高副本内攻击速度。", "attackSpeedPct", 1.5, "add"),
    ("healing", "坚韧", "提高副本内受到的伤害减免。", "tenacityPct", 0.8, "add"),
    ("equip_quality", "装备品质", "提高副本内掉落装备出现高品质的概率。", "equipQualityWeight", 0.05, "add"),
    ("equip_level", "起手武器", "提高起手武器与副本内装备的等级档位。", "equipLevel", 1.0, "add"),
    ("drop_count", "掉落数量", "提高战斗奖励出现装备的概率。", "dropCountPct", 5.0, "add"),
    ("drop_quality", "掉落品质", "提高副本内掉落装备的词条品质。", "dropQualityWeight", 0.05, "add"),
    ("gold_gain", "副本金币", "提高副本内金币获取。", "goldGainPct", 5.0, "add"),
    ("event_luck", "事件好运", "提高事件中出现有利结果的概率。", "eventLuck", 0.02, "add"),
    ("shop_discount", "商店折扣", "降低副本商店的价格。", "shopDiscount", 0.02, "add"),
    ("start_buff", "起始祝福", "进入副本时获得额外起始 BUFF。", "startBuffCount", 0.2, "add"),
    ("revive_count", "复活次数", "提高副本内可复活次数。", "reviveCount", 0.1, "add"),
    ("boss_growth", "讨伐者", "提高击败层 BOSS 获得的成长点。", "bossGrowthPct", 0.05, "mul"),
    ("growth_gain", "成长增幅", "提高成长点获取。", "growthGainPct", 0.05, "mul"),
]

# 单类别 10 级的点数花费曲线（合计 22；24 类合计 528 > 400）。
TIER_COSTS = [1, 1, 1, 2, 2, 2, 3, 3, 3, 4]

growth_categories = []
for cid, name, desc, stat, per_tier, mode in GROWTH_CATEGORIES:
    nodes = []
    prev = None
    for tier, cost in enumerate(TIER_COSTS, start=1):
        value = round(per_tier * tier, 4)
        node_id = f"{cid}_{tier}"
        nodes.append({
            "id": node_id,
            "tier": tier,
            "name": f"{name} {'I' * 0 if tier == 0 else ''}{'ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ'[tier - 1]}",
            "cost": cost,
            "requires": prev,
            "effect": {"stat": stat, "value": value, "mode": mode},
        })
        prev = node_id
    growth_categories.append({"id": cid, "name": name, "desc": desc, "nodes": nodes})

growth = {
    "$comment": (
        "死者宫殿局外成长树：类别 × 10 级。消耗成长点（击败层 BOSS 获得）解锁；"
        "同类别需按层级链式解锁。数值由 scripts/gen-palace-data.py 生成，"
        "标定见 backend/tests/test_shared_data.py::test_palace_config_is_consistent。"
    ),
    "version": "1.0.0",
    "categories": growth_categories,
}

dump("palace-growth.json", growth)


# ---------------------------------------------------------------- 事件库 palace-events.json
# 每条：id / name / type / weight / floorRange / desc / choices[{label, effects[]}]
EVENTS = [
    ("ev_forge", "幽灵铁匠", "equip_level_up", 8, "装备强化",
     "幽灵铁匠愿为你手中的兵器再淬一次火。",
     [("强化武器等级", [{"kind": "equip_level_up", "target": "weapon", "value": 1}]),
      ("离开", [])]),
    ("ev_enchanter", "遗落的附魔师", "equip_rarity_up", 6, "品质升华",
     "附魔师端详你的装备，喃喃自语。",
     [("提升一件装备品质", [{"kind": "equip_rarity_up", "target": "random", "value": 1}]),
      ("婉拒", [])]),
    ("ev_altar_str", "力量祭坛", "hero_attr_up", 7, "力量",
     "黑曜石祭坛上刻满了古老的符文。",
     [("献上鲜血换取力量", [{"kind": "lose_hp", "value": 0.25}, {"kind": "hero_attr_up", "attr": "str", "value": 5}]),
      ("离开", [])]),
    ("ev_altar_dex", "疾风祭坛", "hero_attr_up", 7, "敏捷",
     "风在祭坛四周低语。",
     [("献上鲜血换取敏捷", [{"kind": "lose_hp", "value": 0.25}, {"kind": "hero_attr_up", "attr": "dex", "value": 5}]),
      ("离开", [])]),
    ("ev_altar_int", "智慧祭坛", "hero_attr_up", 7, "智力",
     "祭坛上的水晶泛着幽光。",
     [("献上鲜血换取智慧", [{"kind": "lose_hp", "value": 0.25}, {"kind": "hero_attr_up", "attr": "int", "value": 5}]),
      ("离开", [])]),
    ("ev_training", "训练场", "skill_effect_up", 6, "技艺精进",
     "废弃的训练场里，木桩仍在等待挥砍。",
     [("磨练技艺", [{"kind": "skill_effect_up", "value": 0.08}]), ("离开", [])]),
    ("ev_curse_atk", "枯竭诅咒", "curse", 5, "攻",
     "一缕怨念缠上了你的武器。",
     [("承受诅咒", [{"kind": "curse", "stat": "attackPct", "value": -0.08}, {"kind": "grant_gold", "value": 150}]),
      ("抵抗（可能失败）", [{"kind": "chance", "p": 0.5, "onWin": [{"kind": "grant_gold", "value": 200}],
                             "onLose": [{"kind": "curse", "stat": "attackPct", "value": -0.12}]}])]),
    ("ev_curse_def", "脆弱诅咒", "curse", 5, "防",
     "你的护甲仿佛在低语。",
     [("承受诅咒", [{"kind": "curse", "stat": "defensePct", "value": -0.08}, {"kind": "grant_gold", "value": 150}]),
      ("离开", [])]),
    ("ev_curse_hp", "腐化诅咒", "curse", 4, "生命",
     "生命的气息被缓缓抽走。",
     [("承受诅咒", [{"kind": "curse", "stat": "hpPct", "value": -0.10}, {"kind": "grant_equip"}]),
      ("离开", [])]),
    ("ev_treasure", "遗落的宝箱", "chest", 9, "宝箱",
     "角落里静静躺着一只蒙尘的箱子。",
     [("打开", [{"kind": "grant_equip"}]), ("打开（可能翻倍）",
      [{"kind": "chance", "p": 0.4, "onWin": [{"kind": "grant_equip"}, {"kind": "grant_equip"}],
        "onLose": [{"kind": "grant_gold", "value": 80}]}])]),
    ("ev_trapped", "陷阱宝箱", "trap", 5, "陷阱",
     "箱子下方连着细细的丝线。",
     [("小心打开", [{"kind": "chance", "p": 0.6, "onWin": [{"kind": "grant_equip"}],
                     "onLose": [{"kind": "lose_hp", "value": 0.3}]}]),
      ("直接砸开", [{"kind": "lose_hp", "value": 0.15}, {"kind": "grant_equip"}])]),
    ("ev_merchant", "街头商人", "shop", 6, "商人",
     "戴着兜帽的商人冲你伸出三根手指。",
     [("买下祝福", [{"kind": "lose_gold", "value": 120}, {"kind": "grant_buff"}]),
      ("离开", [])]),
    ("ev_gambler", "赌徒", "gamble", 6, "赌博",
     "赌徒摇晃着骰盅，笑意盈盈。",
     [("押上全部", [{"kind": "chance", "p": 0.5, "onWin": [{"kind": "grant_gold", "value": 500}],
                     "onLose": [{"kind": "lose_gold", "value": 99999}]}]),
      ("不赌", [{"kind": "grant_gold", "value": 30}])]),
    ("ev_fountain", "静谧之泉", "heal", 8, "回复",
     "泉水清澈见底，泛起微光。",
     [("饮下泉水", [{"kind": "heal", "value": 0.5}]), ("灌满行囊（换金币）",
      [{"kind": "heal", "value": 0.2}, {"kind": "grant_gold", "value": 60}])]),
    ("ev_revive", "亡者之息", "grant_revive", 4, "亡者",
     "一具骸骨的手里攥着一枚温热的徽记。",
     [("拾起徽记", [{"kind": "grant_revive", "value": 1}]), ("安葬骸骨", [{"kind": "grant_gold", "value": 90}])]),
    ("ev_scholar", "古籍学者", "level_up", 5, "经验",
     "学者递来一本残破的手札。",
     [("研读手札", [{"kind": "grant_exp", "value": 0.5}]), ("带走变卖", [{"kind": "grant_gold", "value": 120}])]),
    ("ev_soul_pact", "灵魂契约", "soul", 4, "契约",
     "一团幽蓝的灵魂之火在你面前张开了手。",
     [("缔结契约", [{"kind": "curse", "stat": "hpPct", "value": -0.08}, {"kind": "grant_buff"}, {"kind": "grant_buff"}]),
      ("拒绝", [])]),
    ("ev_ambush", "伏击", "ambush", 7, "伏击",
     "黑暗中亮起数双眼睛。",
     [("迎战", [{"kind": "grant_gold", "value": 140}, {"kind": "lose_hp", "value": 0.12}])]),
    ("ev_vault", "废弃金库", "gold", 6, "金币",
     "厚重的金库门虚掩着。",
     [("搜刮", [{"kind": "grant_gold", "value": 220}]), ("仔细搜查（有风险）",
      [{"kind": "chance", "p": 0.55, "onWin": [{"kind": "grant_gold", "value": 420}],
        "onLose": [{"kind": "lose_hp", "value": 0.2}]}])]),
    ("ev_alchemist", "游方炼金术士", "buff", 6, "炼金",
     "术士的背包里塞满了各色小瓶。",
     [("讨要一瓶", [{"kind": "grant_buff"}]), ("购买两瓶", [{"kind": "lose_gold", "value": 150}, {"kind": "grant_buff"}, {"kind": "grant_buff"}])]),
    ("ev_relic", "远古遗物", "relic", 4, "遗物",
     "石台上悬浮着一件不属于这个时代的器物。",
     [("触碰", [{"kind": "grant_equip"}, {"kind": "grant_equip"}]), ("谨慎记录", [{"kind": "gain_growth", "value": 1}])]),
    ("ev_echo", "回响之厅", "echo", 3, "回响",
     "厅内回荡着往昔战斗的余音。",
     [("凝神倾听", [{"kind": "skill_effect_up", "value": 0.05}, {"kind": "grant_exp", "value": 0.3}]),
      ("快步穿过", [])]),
    ("ev_mirror", "魔镜", "mirror", 3, "魔镜",
     "镜中映出的并非你的模样。",
     [("凝视镜面", [{"kind": "chance", "p": 0.5, "onWin": [{"kind": "grant_equip"}],
                     "onLose": [{"kind": "curse", "stat": "attackPct", "value": -0.05}]}]),
      ("打碎镜子", [{"kind": "lose_hp", "value": 0.1}, {"kind": "grant_gold", "value": 80}])]),
    ("ev_necropolis", "亡者之城", "growth", 2, "亡者",
     "无数死者的低语汇成了成长的养分。",
     [("汲取", [{"kind": "gain_growth", "value": 2}]), ("超度亡魂", [{"kind": "heal", "value": 0.3}, {"kind": "grant_gold", "value": 60}])]),
    ("ev_blacksmith", "无名锻造台", "equip_upgrade", 5, "锻造",
     "锻造台上还留有余温。",
     [("锻造防具", [{"kind": "equip_level_up", "target": "armor", "value": 1}]),
      ("锻造饰品", [{"kind": "equip_level_up", "target": "accessory", "value": 1}])]),
    ("ev_wishing", "许愿池", "wish", 4, "许愿",
     "池底堆满了发亮的硬币。",
     [("许愿（花金币）", [{"kind": "lose_gold", "value": 100}, {"kind": "chance", "p": 0.5,
       "onWin": [{"kind": "grant_equip"}, {"kind": "grant_buff"}], "onLose": [{"kind": "grant_gold", "value": 120}]}]),
      ("捞硬币", [{"kind": "grant_gold", "value": 70}])]),
    ("ev_cursed_idol", "受诅咒的雕像", "idol", 4, "雕像",
     "雕像的眼睛似乎在跟着你转动。",
     [("取走宝石", [{"kind": "grant_gold", "value": 300}, {"kind": "curse", "stat": "defensePct", "value": -0.06}]),
      ("原样离开", [{"kind": "grant_exp", "value": 0.2}])]),
    ("ev_arena", "灵魂竞技场", "arena", 5, "竞技",
     "看台上坐着无数沉默的灵魂。",
     [("接受挑战", [{"kind": "lose_hp", "value": 0.2}, {"kind": "grant_equip"}, {"kind": "grant_gold", "value": 160}]),
      ("退场", [])]),
    ("ev_library", "湮没的图书馆", "library", 4, "图书馆",
     "书架高耸入黑暗，看不见顶端。",
     [("研读战术", [{"kind": "skill_effect_up", "value": 0.06}]), ("寻找藏宝图", [{"kind": "grant_gold", "value": 140}])]),
    ("ev_campsite", "旅人营地", "rest", 8, "营地",
     "一堆将熄未熄的篝火。",
     [("休整", [{"kind": "heal", "value": 0.35}]), ("交换情报", [{"kind": "grant_exp", "value": 0.25}, {"kind": "grant_gold", "value": 40}])]),
    ("ev_rift", "空间裂隙", "rift", 3, "裂隙",
     "空气中撕开一道不稳定的裂口。",
     [("跃入", [{"kind": "chance", "p": 0.5, "onWin": [{"kind": "grant_equip"}, {"kind": "grant_equip"}],
                 "onLose": [{"kind": "lose_hp", "value": 0.35}]}]),
      ("远离", [])]),
    ("ev_grimoire", "禁忌魔典", "grimoire", 3, "魔典",
     "书页自行翻动，停在了某一页。",
     [("诵读", [{"kind": "skill_effect_up", "value": 0.1}, {"kind": "lose_hp", "value": 0.15}]),
      ("合上", [{"kind": "grant_gold", "value": 50}])]),
    ("ev_bone_pile", "骸骨堆", "bones", 6, "骸骨",
     "骸骨堆里似乎藏着什么。",
     [("翻找", [{"kind": "chance", "p": 0.7, "onWin": [{"kind": "grant_gold", "value": 130}],
                 "onLose": [{"kind": "lose_hp", "value": 0.15}]}]),
      ("绕开", [])]),
    ("ev_puppet", "提线人偶", "puppet", 3, "人偶",
     "人偶没有线，却自己动着。",
     [("拆解研究", [{"kind": "grant_exp", "value": 0.35}]), ("放它离开", [{"kind": "grant_buff"}])]),
    ("ev_well", "枯井", "well", 5, "枯井",
     "井底传来回声，很深。",
     [("放下绳索", [{"kind": "chance", "p": 0.6, "onWin": [{"kind": "grant_equip"}],
                     "onLose": [{"kind": "lose_hp", "value": 0.1}]}]),
      ("投币许愿", [{"kind": "lose_gold", "value": 60}, {"kind": "gain_growth", "value": 1}])]),
    ("ev_hermit", "隐士", "hermit", 4, "隐士",
     "隐士睁开浑浊的双眼。",
     [("请教", [{"kind": "grant_exp", "value": 0.4}, {"kind": "grant_buff"}]),
      ("留下食物", [{"kind": "heal", "value": 0.25}, {"kind": "grant_gold", "value": 50}])]),
]

events = {
    "$comment": (
        "死者宫殿事件库。效果 kind 由 backend/app/services/palace.py 结算；"
        "lose_hp 不会致死（下限保留 1 点血）。数值由 scripts/gen-palace-data.py 生成。"
    ),
    "version": "1.0.0",
    "events": [
        {
            "id": eid,
            "name": name,
            "type": etype,
            "weight": weight,
            "floorRange": [1, 10],
            "tag": tag,
            "desc": desc,
            "choices": [{"label": label, "effects": effects} for label, effects in choices],
        }
        for (eid, name, etype, weight, tag, desc, choices) in EVENTS
    ],
}

dump("palace-events.json", events)

# 规模自检
n_nodes = sum(len(c["nodes"]) for c in growth["categories"])
n_cost = sum(n["cost"] for c in growth["categories"] for n in c["nodes"])
print(f"growth categories={len(growth['categories'])} nodes={n_nodes} totalCost={n_cost}")
print(f"events={len(events['events'])}")
assert len(growth["categories"]) > 20, "成长类别需 > 20"
assert n_nodes > 200, "成长节点需 > 200"
assert n_cost > 400, "成长点总消耗需 > 400"
assert len(events["events"]) > 30, "事件需 > 30"
for band in palace["nodeTypeWeights"]:
    assert abs(sum(band["weights"].values()) - 1.0) < 1e-9, band

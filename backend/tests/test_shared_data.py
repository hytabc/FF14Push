"""共享数据层一致性：JSON 与加载器、前后端契约。"""

from __future__ import annotations

import pytest

from app.services.game_config import CONFIG


def test_draw_counts_unlock_costs() -> None:
    """连抽档位与一次性解锁价：单抽/十连免费，50 连 500 万、100 连 2000 万。"""
    costs = {int(d["count"]): int(d["unlockCost"]) for d in CONFIG.chests["drawCounts"]}
    assert costs == {1: 0, 10: 0, 50: 5_000_000, 100: 20_000_000}


def test_rarity_probabilities_sum_to_one() -> None:
    for tier in ("normal", "advanced", "boss"):
        total = sum(CONFIG.rarities[r]["boxChance"][tier] for r in CONFIG.rarity_order)
        assert abs(total - 1.0) < 1e-6, f"{tier} 品阶概率合计应为 1，实际 {total}"


def test_boss_chest_has_better_odds_than_advanced() -> None:
    """高难宝箱（boss 档）的品阶期望必须高于高级抽奖箱。"""

    def expected_tier(tier: str) -> float:
        return sum(
            index * CONFIG.rarities[rarity]["boxChance"][tier]
            for index, rarity in enumerate(CONFIG.rarity_order)
        )

    assert expected_tier("boss") > expected_tier("advanced")
    assert expected_tier("advanced") > expected_tier("normal")


def test_hard_raids_use_slot_choice_boss_chest() -> None:
    for raid in CONFIG.raids["raids"]:
        if raid.get("difficulty") != "hard":
            continue
        reward = raid["reward"]
        assert reward.get("slotChoice") is True, raid["id"]
        assert reward.get("boxTier") == "boss", raid["id"]
        assert int(reward["boxCount"]) > 0


def test_rarity_order_and_tiers() -> None:
    tiers = [CONFIG.rarities[r]["tier"] for r in CONFIG.rarity_order]
    assert tiers == sorted(tiers) == list(range(6))
    multipliers = [CONFIG.rarities[r]["multiplier"] for r in CONFIG.rarity_order]
    assert multipliers == sorted(multipliers)


def test_all_jobs_have_seven_skills() -> None:
    assert len(CONFIG.jobs["jobs"]) == 21
    assert CONFIG.jobs["maxSkills"] == 7
    for job in CONFIG.jobs["jobs"]:
        assert len(job["skills"]) == CONFIG.jobs["maxSkills"], job["id"]
        assert len({s["id"] for s in job["skills"]}) == 7


def test_weapon_types_cover_jobs() -> None:
    weapon_types = {j["weaponType"] for j in CONFIG.jobs["jobs"]}
    base_weapon_types = {b.weapon_type for b in CONFIG.base_items if b.category == "weapon"}
    assert weapon_types == base_weapon_types


def test_base_items_expanded() -> None:
    """底材 = 族 × 档位 × 变体(minTier ≤ 档位)，且 id 唯一。"""
    raw = CONFIG.raw["baseItems"]
    tiers = raw["tiers"]
    variants = raw.get("variants", {})

    def per_family(specs) -> int:
        return sum(sum(1 for v in specs if v["minTier"] <= t["index"]) for t in tiers)

    expected = (
        len(raw["weaponFamilies"]) * per_family(variants["weapon"])
        + len(raw["armorFamilies"]) * per_family(variants["armor"])
        + len(raw["accessoryFamilies"]) * per_family(variants["accessory"])
    )
    ids = [item.id for item in CONFIG.base_items]
    assert len(ids) == expected
    assert len(ids) == len(set(ids)), "底材 id 必须唯一"
    for item in CONFIG.base_items:
        assert item.base_attrs, item.id
        assert item.sub_attr_pool, item.id
        for entry in item.base_attrs:
            assert entry["base"] > 0


def test_regions_are_ordered_and_linked() -> None:
    regions = CONFIG.regions["regions"]
    assert len(regions) == 40
    assert [r["id"] for r in regions] == list(range(1, 41))
    boss_types = {t["id"] for t in CONFIG.bosses["types"]}
    for region in regions:
        assert region["bossType"] in boss_types, region["name"]
        assert region["levelMin"] < region["levelMax"] or region["levelMin"] <= region["levelMax"]


def test_terms_have_valid_ranges() -> None:
    for term in CONFIG.terms["terms"]:
        low, high = term["range"]
        assert low != 0 and high != 0
        assert term["type"] in ("buff", "debuff")
        assert term["stat"]


def test_slot_mapping_covers_all_base_items() -> None:
    slot_ids = {s["id"] for s in CONFIG.slots}
    assert len(CONFIG.slots) == 11
    for item in CONFIG.base_items:
        if item.slot == "ring":
            assert {"ring1", "ring2"} <= slot_ids
        else:
            assert item.slot in slot_ids


def test_crafting_routes_are_contiguous() -> None:
    routes = {r["from"]: r["to"] for r in CONFIG.crafting["routes"]}
    order = CONFIG.rarity_order
    for index, rarity in enumerate(order[:-1]):
        assert routes[rarity] == order[index + 1]
    assert order[-1] not in routes


def test_healer_skills_are_nerfed() -> None:
    """治疗职业的治疗/护盾数值已下调，且不再有满血复活。"""
    for job in CONFIG.jobs["jobs"]:
        if job["role"] != "healer":
            continue
        for skill in job["skills"]:
            for effect in skill.get("effects", []):
                kind = effect.get("type")
                if kind == "heal":
                    # 小/中治疗（CD < 120s）不超过 12%；大招允许 50%
                    limit = 0.5 if float(skill["cd"]) >= 120 else 0.12
                    assert float(effect["value"]) <= limit, (job["id"], skill["id"])
                if kind == "healOverTime":
                    assert float(effect["value"]) <= 0.02, (job["id"], skill["id"])
                if kind == "shield":
                    assert float(effect["value"]) <= 0.12, (job["id"], skill["id"])
                assert kind != "fullHeal", (job["id"], skill["id"])


def test_mp_is_sustainable() -> None:
    """蓝量要「有压力但不枯竭」。

    历史问题：满级物理系蓝池 664、回复却只有 0.82/s —— 放几个技能就见底，
    之后退化成「普攻 + 最低威力技能」的循环。这里用显式数值边界锁住修复：
    """
    attrs = CONFIG.heroes["attributes"]
    growth = CONFIG.heroes["levelUpGain"]

    # 蓝池不能只由智力决定（物理职业智力低，否则蓝池小到放几个技能就空）
    assert float(attrs["maxMp"]["coef"]["int"]) <= 1.0

    # 回复必须随等级成长，否则满级蓝池变大而回复原地踏步
    assert "mpRegen" in growth
    assert float(growth["mpRegen"]["basePct"]) > 0

    # 基础回复 ≥ 最密集技能消耗（耗蓝 ÷ CD）：连短 CD 技能都负担不起时只会剩普攻
    hardest = max(
        float(s["mpCost"]) / max(0.1, float(s["cd"]))
        for job in CONFIG.jobs["jobs"]
        for s in job["skills"]
    )
    assert float(attrs["mpRegen"]["base"]) >= hardest

    # 零耗蓝普攻要能回蓝，作为见底时的兜底手段
    assert float(CONFIG.heroes["mp"]["basicAttackRestorePct"]) > 0


def test_level_penalty_config_is_hard() -> None:
    cfg = CONFIG.regions["levelPenalty"]
    assert float(cfg["maxDamageDealtPenaltyPct"]) >= 95
    assert float(cfg["maxDamageTakenBonusPct"]) >= 1000
    assert float(cfg["maxDefenseIgnorePct"]) == 100
    # 落后 10 级时防御已归零
    assert 10 * float(cfg["defenseIgnorePctPerLevel"]) >= 100


def test_melee_skills_scale_with_main_attr() -> None:
    """力量/敏捷职业的**伤害技能**不应使用魔法伤害（否则按智力结算、DPS 差数倍）。"""
    for job in CONFIG.jobs["jobs"]:
        if job["mainAttr"] == "int":
            continue
        for skill in job["skills"]:
            if int(skill.get("potency", 0)) <= 0:
                continue
            assert skill["damageType"] != "magical", (job["id"], skill["id"])


def test_tutorial_has_fifteen_steps() -> None:
    steps = CONFIG.tutorial["steps"]
    assert len(steps) == 15
    assert [s["step"] for s in steps] == list(range(1, 16))


def test_three_attribute_ranges_follow_prd() -> None:
    """PRD 三属性 5.2：暴击/直击/信念各品阶区间"""
    expected = {
        "common": [10, 30],
        "uncommon": [30, 60],
        "rare": [60, 120],
        "epic": [120, 250],
        "legendary": [250, 500],
        "mythic": [500, 900],
    }
    for attr_id in ("crit", "dh", "det"):
        attr = CONFIG.attribute_by_id[attr_id]
        for rarity, rng in expected.items():
            assert list(attr["ranges"][rarity]) == rng, f"{attr_id}/{rarity}"


def test_craft_rarity_scaling_is_consistent() -> None:
    """制造品阶进度缩放配置：权重/分布归一，神话目标 = 硬上限，参考值有效。"""
    equip = CONFIG.recipes["equipment"]
    scaling = equip["rarityScaling"]
    cap = float(scaling["mythicCap"])
    assert 0 < cap <= 1
    assert abs(cap - 0.2) < 1e-9, "极限神话概率应为 20%"

    assert abs(sum(float(s["weight"]) for s in scaling["sources"].values()) - 1.0) < 1e-9
    assert abs(sum(float(v) for v in scaling["targetWeights"].values()) - 1.0) < 1e-9
    assert abs(float(scaling["targetWeights"]["mythic"]) - cap) < 1e-9
    for spec in scaling["sources"].values():
        assert float(spec["ref"]) > 0

    def expected_tier(weights: dict) -> float:
        return sum(i * float(weights.get(r, 0.0)) for i, r in enumerate(CONFIG.rarity_order))

    assert expected_tier(scaling["targetWeights"]) > expected_tier(equip["rarityWeights"])


def test_dedicated_terms_are_scoped_and_valid() -> None:
    """专用装备词条池：仅限专用栏位、stat 为生产加成键、正负号与类型一致，且不与战斗词条重名。"""
    slots = {s["id"] for s in CONFIG.dohdol_equipment["slots"]}
    bonus_names = CONFIG.dohdol_equipment["bonusNames"]
    terms = CONFIG.dohdol_equipment["terms"]
    assert terms

    ids = [t["id"] for t in terms]
    assert len(ids) == len(set(ids))
    assert set(ids).isdisjoint({t["id"] for t in CONFIG.terms["terms"]})

    for term in terms:
        assert term["type"] in ("buff", "debuff")
        assert term["stat"] in bonus_names, term["stat"]
        assert term["slots"] and set(term["slots"]) <= slots, term["id"]
        low, high = term["range"]
        if term["type"] == "buff":
            assert low > 0 and high > 0, term["id"]
        else:
            assert low < 0 and high < 0, term["id"]


def test_dohdol_bonus_names_cover_item_bonuses() -> None:
    """每个专用装备加成键都要有中文名，避免原始 key 泄漏到界面。"""
    names = CONFIG.dohdol_equipment["bonusNames"]
    for item in CONFIG.dohdol_equipment["items"]:
        for stat in item["bonus"]:
            assert stat in names, f"{item['id']}/{stat}"


def test_rarity_luck_sources_are_consistent() -> None:
    """抽箱 / 生产两套品阶概率来源：权重合计 = 1、ref 为真实最大值（含太古）、难度表覆盖全难度。"""
    from app.services.item_factory import ANCIENT_FACTOR
    from app.services.luck_sources import coop_clear_ref, raid_clear_ref
    from app.services.multiplayer_config import DUNGEONS, MULTIPLAYER

    # 难度权重表：覆盖全部难度，且难度越高权重越高
    coop_weights = MULTIPLAYER["difficultyWeights"]
    raid_weights = CONFIG.raids["difficultyWeights"]
    assert {d["difficulty"] for d in DUNGEONS.values()} <= set(coop_weights)
    assert {r["difficulty"] for r in CONFIG.raids["raids"]} <= set(raid_weights)
    assert list(coop_weights.values()) == sorted(coop_weights.values())
    assert list(raid_weights.values()) == sorted(raid_weights.values())

    def consumable_max(stat: str) -> float:
        # 药水 / 食物各占一个槽位，可达上限 = 各 kind 的最高档之和（而非所有物品累加）。
        best: dict[str, float] = {}
        for item in CONFIG.consumables["items"]:
            for effect in item["effects"]:
                if effect["stat"] == stat:
                    best[item["kind"]] = max(best.get(item["kind"], 0.0), float(effect["value"]))
        return sum(best.values())

    # 抽箱来源
    chest = CONFIG.chests["rarityLuck"]
    chest_sources = chest["sources"]
    assert float(chest["luckMax"]) > 0
    assert sum(float(s["weight"]) for s in chest_sources.values()) == pytest.approx(1.0)
    assert chest_sources["coopClears"]["ref"] == pytest.approx(coop_clear_ref())
    assert chest_sources["raidClears"]["ref"] == pytest.approx(raid_clear_ref())
    assert chest_sources["consumablePct"]["ref"] == pytest.approx(consumable_max("chestLuck"))
    # 装备品阶幸运上限 = 全部战斗栏位 × 太古值
    chest_term = next(t for t in CONFIG.terms["terms"] if t["stat"] == "chestRarityPct")
    assert len(chest_term["slots"]) == len(CONFIG.slots)
    assert chest_sources["gearPct"]["ref"] == pytest.approx(
        len(chest_term["slots"]) * float(chest_term["range"][1]) * ANCIENT_FACTOR
    )

    # 生产来源
    scaling = CONFIG.recipes["equipment"]["rarityScaling"]["sources"]
    assert sum(float(s["weight"]) for s in scaling.values()) == pytest.approx(1.0)
    assert scaling["coopClears"]["ref"] == pytest.approx(coop_clear_ref())
    assert scaling["raidClears"]["ref"] == pytest.approx(raid_clear_ref())
    assert scaling["consumablePct"]["ref"] == pytest.approx(consumable_max("craftRarityPct"))
    # 专用装备品阶幸运上限 = 各 doh 栏位最佳固定加成 + 每栏位一条太古词条
    doh_term = next(
        t
        for t in CONFIG.dohdol_equipment["terms"]
        if t["stat"] == "craftRarityPct" and t["type"] == "buff"
    )
    best: dict[str, float] = {}
    for item in CONFIG.dohdol_equipment["items"]:
        if item["slot"] not in doh_term["slots"]:
            continue
        bonus = float(item["bonus"].get("craftRarityPct", 0.0))
        best[item["slot"]] = max(best.get(item["slot"], 0.0), bonus)
    assert set(best) == set(doh_term["slots"])
    gear_max = sum(best.values()) + len(best) * float(doh_term["range"][1]) * ANCIENT_FACTOR
    assert scaling["gearPct"]["ref"] == pytest.approx(gear_max)


def test_exp_gain_term_covers_all_accessories() -> None:
    """「经验获取效率」可出现在全部战斗饰品栏位（项链 / 耳环 / 手镯 / 戒指）。"""
    accessory_slots = {s["id"] for s in CONFIG.slots if s["category"] == "accessory"}
    assert accessory_slots == {"necklace", "earring", "bracelet", "ring1", "ring2"}
    assert set(CONFIG.term_by_id["expGain"]["slots"]) == accessory_slots


def test_consumable_tiers_keep_durations() -> None:
    """高等级药食只放大效果，单个物品的持续时长仍由 kind 决定（秘药 60s / 料理 1800s）。"""
    kinds = CONFIG.consumables["kinds"]
    assert int(kinds["potion"]["durationSec"]) == 60
    assert int(kinds["food"]["durationSec"]) == 1800

    by_stat: dict[tuple[str, str], list[float]] = {}
    for item in CONFIG.consumables["items"]:
        for effect in item["effects"]:
            if effect["stat"] == "fishChancePct":
                continue
            by_stat.setdefault((item["kind"], effect["stat"]), []).append(float(effect["value"]))
    assert by_stat, "药食效果表为空"
    for key, values in by_stat.items():
        assert len(values) == 3, f"{key} 应为 I/II/III 三档，实际 {values}"
        assert values == sorted(values) and values[0] < values[-1], f"{key} 数值未逐档递增：{values}"


def test_high_tier_consumables_are_sell_safe() -> None:
    """高等级药食（II/III）配方：产出出售价不得超过输入材料出售价，杜绝「采集→制造→出售」刷金币。"""
    for recipe in CONFIG.recipes["recipes"]:
        output = recipe["output"]
        if output["kind"] != "consumable" or int(recipe["requiredLevel"]) <= 1:
            continue
        produced = int(CONFIG.consumable_by_id[output["itemId"]].get("sell", 0)) * int(
            output.get("count", 1)
        )
        consumed = sum(
            int((CONFIG.material_by_id.get(e["itemId"]) or {}).get("sell", 0)) * int(e["count"])
            for e in recipe["inputs"]
        )
        assert consumed > 0, recipe["id"]
        assert produced <= consumed, f"{recipe['id']} 产出 {produced} 超过输入 {consumed}"

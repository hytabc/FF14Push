"""核心数值引擎：属性、伤害、掉落保底、售价、合成。"""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from app.services.combat_model import (
    max_gold_for_kill,
    max_kills_in_seconds,
    theoretical_boss_seconds,
    theoretical_dps,
    theoretical_kill_seconds,
)
from app.services.economy import REQUIRED, build_craft_plan, enchant_cost, refine_cost
from app.services.game_config import CONFIG, BaseItem
from app.services.item_factory import (
    base_attr_range,
    generate_item,
    regenerate_attrs,
    roll_sub_attr_value,
    roll_terms_for_enchant,
    sub_attr_cap,
    sub_attr_range,
)
from app.services.loot import (
    RARITY_ORDER,
    PityState,
    chest_by_id,
    draw_rarity,
    drop_rate_multiplier,
    rarity_weights,
    roll_rarity,
)
from app.services.drop_luck import chest_luck_max
from app.services.combat_model import theoretical_dps
from app.services.egg_heroes import (
    craft_extra_chance,
    exp_bonus_pct,
    normal_mob_potency100_bonus,
    skills_for,
)
from app.services.recruiting import (
    ancient_pity_count,
    generate_candidate,
    generate_candidates,
    normalize_candidate,
)
from app.services.regions_util import (
    apply_exp_bonus,
    exp_bonus_from_terms,
    level_penalty,
    level_penalty_for_level,
    monster_base_stats,
    region_scale,
)
from app.services.raid_util import (
    all_raids,
    boss_stats_for_raid,
    challenge_level,
    daily_reward_clears,
    raid_penalty,
)
from app.services.slots_util import possible_slots
from app.services.stats import compute_stats, convert_three_attrs
from app.services.validator import validate_report
from app.services.valuation import (
    attr_factor,
    attrs_score,
    hero_power,
    item_score,
    sell_price,
    sell_price_range,
)

from tests.fakes import FakeHero, FakeItem, GeneratedItem


class TestThreeAttributes:
    def test_prd_level100_example(self) -> None:
        """PRD 三属性 3.1：Lv.100 基准 420、分母 1900。"""
        crit_rate, crit_dmg, dh_rate, det_bonus = convert_three_attrs(100, 420, 420, 390)
        assert crit_rate == pytest.approx(5.0)
        assert crit_dmg == pytest.approx(140.0)
        assert dh_rate == pytest.approx(0.0)
        assert det_bonus == pytest.approx(0.0)

    def test_crit_scales_linearly_in_this_model(self) -> None:
        crit_rate, crit_dmg, _, _ = convert_three_attrs(100, 420 + 1900, 0, 0)
        assert crit_rate == pytest.approx(25.0)
        assert crit_dmg == pytest.approx(160.0)

    def test_direct_hit_cap_and_det(self) -> None:
        _, _, dh_rate, _ = convert_three_attrs(100, 0, 420 + 1900, 0)
        assert dh_rate == pytest.approx(55.0)
        _, _, _, det_bonus = convert_three_attrs(100, 0, 0, 390 + 1900)
        assert det_bonus == pytest.approx(13.0)

    def test_prd_level50_example(self) -> None:
        """PRD 3.2 例：Lv.50 时 暴击率 = 5% + (暴击值 − 250) / 1000 × 20%。"""
        crit_rate, _, _, _ = convert_three_attrs(50, 250 + 1000, 0, 0)
        assert crit_rate == pytest.approx(25.0)

    def test_low_level_tier(self) -> None:
        crit_rate, _, _, _ = convert_three_attrs(10, 50, 0, 0)
        assert crit_rate == pytest.approx(5.0)


class TestHeroStats:
    def test_level_curve_is_monotonic(self) -> None:
        prev_hp = 0.0
        prev_atk = 0.0
        for level in (1, 10, 30, 50, 80, 100):
            stats = compute_stats(FakeHero(level=level), [])
            assert stats.max_hp > prev_hp
            assert stats.attack > prev_atk
            prev_hp, prev_atk = stats.max_hp, stats.attack

    def test_off_attribute_gain_is_halved(self) -> None:
        """PRD 招募 4.2：主属性 100%，非主属性 50%。"""
        hero = FakeHero(level=1, attr_bias="str", strength=10, agility=10, intellect=10)
        base = compute_stats(hero, [])

        # 力量是主属性：+100 力量 → 命中为 0 贡献，改用生命验证
        main_item = FakeItem(sub_attrs=[{"attr": "str", "value": 100.0, "type": "flat"}])
        off_item = FakeItem(sub_attrs=[{"attr": "int", "value": 100.0, "type": "flat"}])

        main_gain = compute_stats(hero, [main_item]).max_hp - base.max_hp
        # 智力为非主属性，只提供 50% 魔法值收益
        off_gain = compute_stats(hero, [off_item]).max_mp - base.max_mp
        full_gain = 100 * float(CONFIG.heroes["attributes"]["maxMp"]["coef"]["int"])

        assert main_gain == pytest.approx(100 * 10)  # str 对 maxHp 的系数为 10
        assert off_gain == pytest.approx(full_gain * 0.5)

    def test_equipment_attributes_reach_panel(self) -> None:
        hero = FakeHero(level=50)
        item = FakeItem(
            base_attrs=[{"attr": "attack", "value": 500.0}],
            sub_attrs=[{"attr": "crit", "value": 600.0, "type": "flat"}],
        )
        base = compute_stats(hero, [])
        with_item = compute_stats(hero, [item])
        assert with_item.attack == pytest.approx(base.attack + 500.0)
        assert with_item.crit_value == pytest.approx(600.0)
        assert with_item.crit_rate_pct > base.crit_rate_pct

    def test_buff_terms_apply(self) -> None:
        hero = FakeHero(level=50)
        item = FakeItem(terms=[{"id": "hpResonance", "stat": "maxHpPct", "value": 20.0, "type": "buff"}])
        base = compute_stats(hero, [])
        with_item = compute_stats(hero, [item])
        assert with_item.max_hp == pytest.approx(base.max_hp * 1.2)

    def test_only_equipped_items_count(self) -> None:
        hero = FakeHero(level=10)
        equipped = FakeItem(base_attrs=[{"attr": "attack", "value": 100.0}], equipped_slot="mainHand")
        bagged = FakeItem(base_attrs=[{"attr": "attack", "value": 999.0}], equipped_slot=None)
        stats = compute_stats(hero, [equipped, bagged])
        bare = compute_stats(hero, [])
        assert stats.attack == pytest.approx(bare.attack + 100.0)

    def test_attack_grows_for_dex_based_jobs(self) -> None:
        """敏捷系职业的攻击成长不能丢失（PRD 6.1：力量或敏捷 × 1）。"""
        from tests.fakes import FakeItem

        weapon = FakeItem(
            category="weapon",
            base_id="w_dualDagger_0",
            slot="mainHand",
            equipped_slot="mainHand",
            base_attrs=[{"attr": "attack", "value": 12.0}],
        )
        hero = FakeHero(level=1, attr_bias="balanced")
        low = compute_stats(hero, [weapon])
        hero.level = 60
        high = compute_stats(hero, [weapon])
        assert low.job_id == "NIN"
        assert low.main_attr == "dex"
        # 59 级成长应至少带来 59 × 敏捷 的增量
        assert high.attack > low.attack + 59 * hero.agility * 0.9

    def test_str_and_dex_jobs_scale_similarly(self) -> None:
        from tests.fakes import FakeItem

        def build(base_id: str) -> float:
            return compute_stats(
                FakeHero(level=50),
                [
                    FakeItem(
                        category="weapon",
                        base_id=base_id,
                        slot="mainHand",
                        equipped_slot="mainHand",
                        base_attrs=[{"attr": "attack", "value": 100.0}],
                    )
                ],
            ).attack

        str_job = build("w_lance_0")  # 龙骑士（力量）
        dex_job = build("w_katana_0")  # 武士（力量）
        nin = build("w_dualDagger_0")  # 忍者（敏捷）
        assert abs(str_job - dex_job) < 1e-6
        assert abs(nin - str_job) < 1e-6

    def test_hero_power_positive(self) -> None:
        assert hero_power(compute_stats(FakeHero(level=30), [])) > 0


class TestLoot:
    def test_rarity_distribution_matches_config(self) -> None:
        rng = random.Random(20240920)
        n = 300_000
        counts = {r: 0 for r in CONFIG.rarity_order}
        for _ in range(n):
            counts[roll_rarity("normal", rng)] += 1
        for rarity in CONFIG.rarity_order:
            expected = CONFIG.rarities[rarity]["boxChance"]["normal"]
            actual = counts[rarity] / n
            if expected >= 0.01:
                assert actual == pytest.approx(expected, abs=0.005), rarity

    @pytest.mark.parametrize(
        "count,minimum",
        [(10, "rare"), (50, "epic"), (200, "legendary")],
    )
    def test_pity_triggers(self, count: int, minimum: str) -> None:
        """PRD 2.8.3 保底：第 10 / 50 / 200 抽必出对应品阶以上。"""
        rng = random.Random(7)
        pity = PityState()
        results = []
        for _ in range(count):
            rarity, pity = draw_rarity("normal", pity, rng)
            results.append(rarity)
        tier = CONFIG.rarities[minimum]["tier"]
        assert any(CONFIG.rarities[r]["tier"] >= tier for r in results), results

    def test_pity_counters_reset(self) -> None:
        rng = random.Random(11)
        pity = PityState()
        for _ in range(300):
            rarity, pity = draw_rarity("advanced", pity, rng)
            assert pity.since_rare < 10
            assert pity.since_epic < 50
            assert pity.since_legendary < 200


class TestItemFactory:
    def test_generated_item_shape(self) -> None:
        for category in ("weapon", "armor", "accessory"):
            item, _ = generate_item(category, 50, rng=random.Random(1))
            assert item["category"] == category
            assert item["baseAttrs"]
            assert 1 <= len(item["subAttrs"]) <= 3
            assert 0 <= len(item["terms"]) <= 4

    def test_rarity_multiplier_increases_base_attr(self) -> None:
        common, _ = generate_item("weapon", 80, rarity="common", rng=random.Random(5))
        mythic, _ = generate_item("weapon", 80, rarity="mythic", rng=random.Random(5))
        assert mythic["baseAttrs"][0]["value"] > common["baseAttrs"][0]["value"] * 3

    def test_sub_attr_count_within_rarity_range(self) -> None:
        rng = random.Random(3)
        for rarity in CONFIG.rarity_order:
            spec = CONFIG.rarities[rarity]
            for _ in range(40):
                item, _ = generate_item("accessory", 60, rarity=rarity, rng=rng)
                assert spec["subAttrMin"] <= len(item["subAttrs"]) <= spec["subAttrMax"]

    def test_no_duplicate_terms(self) -> None:
        rng = random.Random(9)
        for _ in range(200):
            item, _ = generate_item("weapon", 90, rng=rng)
            ids = [t["id"] for t in item["terms"]]
            assert len(ids) == len(set(ids))

    def test_debuff_chance_decreases_with_rarity(self) -> None:
        rng = random.Random(13)
        chances = {}
        for rarity in ("common", "mythic"):
            debuffs = 0
            total = 0
            for _ in range(2000):
                item, _ = generate_item("armor", 70, rarity=rarity, rng=rng)
                total += len(item["terms"])
                debuffs += sum(1 for t in item["terms"] if t["type"] == "debuff")
            chances[rarity] = debuffs / max(1, total)
        assert chances["common"] > chances["mythic"]

    def test_weapon_type_matches_job(self) -> None:
        rng = random.Random(17)
        for _ in range(50):
            item, _ = generate_item("weapon", 95, rng=rng)
            base = CONFIG.base_item_by_id[item["baseId"]]
            assert base.job_id
            assert CONFIG.job_by_id[base.job_id]["weaponType"] == base.weapon_type


class TestValuation:
    def test_sell_price_range_contains_base(self) -> None:
        item = FakeItem(rarity="rare", base_attrs=[{"attr": "attack", "value": 40.0}])
        low, high = sell_price_range(item)
        assert low <= sell_price(item) <= high
        assert low >= 1

    def test_higher_rarity_sells_higher(self) -> None:
        common = FakeItem(rarity="common")
        mythic = FakeItem(rarity="mythic")
        assert sell_price(mythic) > sell_price(common) * 10

    def test_rarity_and_term_bonus_increase_price(self) -> None:
        plain = FakeItem(rarity="epic")
        with_terms = FakeItem(
            rarity="epic",
            terms=[
                {"id": "strBoost", "type": "buff", "quality": "ancient", "stat": "attackPct", "value": 18.0},
                {"id": "skillMastery", "type": "buff", "quality": "rare", "stat": "skillDamagePct", "value": 12.0},
            ],
        )
        assert sell_price(with_terms) > sell_price(plain)

    def test_attr_factor_is_bounded(self) -> None:
        """属性系数必须饱和封顶，否则高等级装备卖价会随属性无限膨胀。"""
        cap = 1.0 + float(CONFIG.economy["sell"]["attrBonusMax"])
        huge = FakeItem(rarity="common", base_attrs=[{"attr": "attack", "value": 10_000_000}])
        tiny = FakeItem(rarity="common", base_attrs=[{"attr": "attack", "value": 1}])
        assert attr_factor(tiny) >= 1.0
        assert attr_factor(huge) < cap
        assert attr_factor(huge) > attr_factor(tiny)


class TestSellEconomy:
    """出售价必须明显低于抽箱价，否则可「买箱卖装备」无限刷金币。来源：需求「防止金币无限叠加」。"""

    CHEST_IDS = ("weaponBox", "armorBox", "accessoryBox", "advWeaponBox", "advArmorBox", "advAccessoryBox")

    @pytest.mark.parametrize("level", [1, 25, 50, 100])
    def test_expected_sell_below_chest_price(self, level: int) -> None:
        for chest_id in self.CHEST_IDS:
            chest = chest_by_id(chest_id)
            assert chest is not None
            rng = random.Random(20240101)
            pity = PityState()
            n = 3000
            total = 0
            wins = 0
            for _ in range(n):
                data, pity = generate_item(
                    chest["category"], level, box_tier=chest["tier"], rng=rng, pity=pity
                )
                price = sell_price(GeneratedItem(data))
                total += price
                wins += 1 if price > chest["price"] else 0
            mean = total / n
            assert mean < chest["price"], f"{chest_id} Lv{level} 期望卖出 {mean:.1f} ≥ 箱子价 {chest['price']}"
            assert wins / n < 0.10, f"{chest_id} Lv{level} 抽到赚头的概率 {wins / n:.1%} 过高"


class TestCrafting:
    def test_plan_requires_sixteen(self) -> None:
        items = [FakeItem(category="weapon", rarity="common", equipped_slot=None) for _ in range(16)]
        plan = build_craft_plan(items, "weapon", auto=True)
        assert REQUIRED == 16
        assert plan["steps"][0]["crafts"] == 1
        assert plan["produced"].get("uncommon") == 1

    def test_plan_empty_below_threshold(self) -> None:
        items = [FakeItem(category="weapon", rarity="common", equipped_slot=None) for _ in range(15)]
        plan = build_craft_plan(items, "weapon", auto=True)
        assert plan["steps"] == []
        assert plan["totalFee"] == 0

    def test_auto_craft_chains_through_tiers(self) -> None:
        """256 件普通 → 16 件优秀 → 1 件稀有。"""
        items = [FakeItem(category="armor", rarity="common", equipped_slot=None) for _ in range(16 * 16)]
        plan = build_craft_plan(items, "armor", auto=True)
        assert plan["delta"]["common"] == -256
        assert plan["produced"] == {"rare": 1}
        assert plan["totalFee"] > 0

    def test_category_isolation(self) -> None:
        items = [FakeItem(category="weapon", rarity="common", equipped_slot=None) for _ in range(32)]
        plan = build_craft_plan(items, "armor", auto=True)
        assert plan["steps"] == []


class TestUpgradeCosts:
    """重造 / 附魔的单次消耗：随品阶单调递增、附魔始终比重造贵，并随物品等级线性提高。"""

    def test_costs_monotonic_by_rarity(self) -> None:
        refine = [int(CONFIG.rarities[r]["refineCost"]) for r in CONFIG.rarity_order]
        enchant = [int(CONFIG.rarities[r]["enchantCost"]) for r in CONFIG.rarity_order]

        assert refine == sorted(refine)
        assert enchant == sorted(enchant)
        assert all(e > r for r, e in zip(refine, enchant))
        # 1 级基准价落在旧「5 万以内」区间（等级系数 1 级恒为 1）
        cap = 50_000
        assert max(refine) <= cap and max(enchant) <= cap

    def test_costs_scale_with_item_level(self) -> None:
        """等级系数 = 1 + 2/27 ×(等级 − 1)：1 级不动，100 级 ×25/3 ≈ 8.33。"""
        for rarity in CONFIG.rarity_order:
            assert refine_cost(rarity, 0, "random", 100) > refine_cost(rarity, 0, "random", 1)
            assert enchant_cost(rarity, "random", 100) > enchant_cost(rarity, "random", 1)

        # 1 级 = 基准价（不额外加价）
        assert refine_cost("mythic", 0, "random", 1) == 30_000
        assert enchant_cost("mythic", "random", 1) == 50_000
        # 100 级神话「基于当前」首造 = 30000 × 3 × 25/3 = 750,000
        assert refine_cost("mythic", 0, "basedOnCurrent", 100) == 750_000
        # 等级内单调：同一品阶等级越高越贵
        assert refine_cost("mythic", 0, "basedOnCurrent", 100) > refine_cost(
            "mythic", 0, "basedOnCurrent", 50
        )


class TestSubAttrQuality:
    """副属性也支持品质：普通区间内随机、稀有取上限、太古取上限 ×1.25。"""

    class _Rng:
        """固定取值替身：uniform 取中值，使结果可预期。"""

        def uniform(self, lo: float, hi: float) -> float:
            return (lo + hi) / 2

    def test_quality_value_rules(self) -> None:
        rng = self._Rng()
        # 暴击 100-400：太古 = 400 × 1.25 = 500
        assert roll_sub_attr_value(rng, 100.0, 400.0, "ancient") == 500.0
        assert roll_sub_attr_value(rng, 100.0, 400.0, "rare") == 400.0
        assert 100.0 <= roll_sub_attr_value(rng, 100.0, 400.0, "common") <= 400.0 * 1.2

    def test_generated_sub_attrs_carry_quality(self) -> None:
        rng = random.Random(5)
        item, _ = generate_item("weapon", 50, rng=rng)
        assert item["subAttrs"]
        for entry in item["subAttrs"]:
            assert entry["quality"] in ("common", "rare", "ancient")

    def test_ancient_sub_attr_is_worth_more(self) -> None:
        """太古副属性数值更高，装备评分/售价随之提高。"""
        plain = FakeItem(rarity="epic", sub_attrs=[{"attr": "crit", "value": 400.0, "type": "flat"}])
        ancient = FakeItem(
            rarity="epic",
            sub_attrs=[{"attr": "crit", "value": 500.0, "type": "flat", "quality": "ancient"}],
        )
        assert sell_price(ancient) > sell_price(plain)


class TestRaidFixedDifficulty:
    """副本取消战力动态缩放：BOSS 数值固定锚定目标等级，低于目标等级由等级压制兜底。"""

    def test_boss_stats_ignore_player_level(self) -> None:
        for raid in all_raids():
            low = boss_stats_for_raid(raid, 1)[0]
            high = boss_stats_for_raid(raid, 100)[0]
            assert low["hp"] == high["hp"]
            assert low["attack"] == high["attack"]
            assert low["defense"] == high["defense"]
            assert low["level"] == challenge_level(raid, 1)

    def test_boss_stats_ignore_player_power(self) -> None:
        raid = CONFIG.raid_by_id["raid_h1"]
        pressure = TestRaidPressure()
        weak = compute_stats(FakeHero(level=100), pressure._bar_items(100, 2))
        strong = compute_stats(FakeHero(level=100), pressure._bar_items(100, 4))
        assert boss_stats_for_raid(raid, 100, weak)[0]["hp"] == boss_stats_for_raid(raid, 100, strong)[0]["hp"]

    def test_level_wall_uses_challenge_level(self) -> None:
        """达到目标等级时无等级压制；低于目标等级四项压制均被触发。"""
        for raid in all_raids():
            anchor = challenge_level(raid, 1)
            at_target = level_penalty_for_level(anchor, anchor)
            assert at_target["damageDealtPenaltyPct"] == 0
            assert at_target["damageTakenBonusPct"] == 0
            assert at_target["defenseIgnorePct"] == 0
            below = level_penalty_for_level(max(1, anchor - 10), anchor)
            assert below["damageDealtPenaltyPct"] > 0
            assert below["damageTakenBonusPct"] > 0
            assert below["defenseIgnorePct"] > 0

    def test_raid_penalty_merges_level_suppression(self) -> None:
        raid = CONFIG.raid_by_id["raid_3"]
        anchor = challenge_level(raid, 1)
        stats = compute_stats(FakeHero(level=anchor), TestRaidPressure()._bar_items(anchor, 2))
        below = raid_penalty(raid, anchor - 10, stats)
        expected = level_penalty_for_level(anchor - 10, anchor)
        assert below["damageDealtPenaltyPct"] >= expected["damageDealtPenaltyPct"]
        assert below["damageTakenBonusPct"] >= expected["damageTakenBonusPct"]
        assert below["defenseIgnorePct"] >= expected["defenseIgnorePct"]

    def test_challenge_level_and_daily_limit_configured(self) -> None:
        for raid in all_raids():
            anchor = challenge_level(raid, 1)
            assert anchor >= int(raid["requiredLevel"])
            assert daily_reward_clears(raid) >= 1
        assert daily_reward_clears(CONFIG.raid_by_id["raid_h1"]) == 1
        assert daily_reward_clears(CONFIG.raid_by_id["raid_1"]) == 3


class TestExpTerm:
    """经验获取效率词条：配置存在且加成按百分比计算。"""

    def test_term_configured(self) -> None:
        term = CONFIG.term_by_id.get("expGain")
        assert term is not None, "terms.json 缺少经验词条"
        assert term["stat"] == "expGainPct"
        assert term["type"] == "buff"
        assert term["range"][0] > 0

    def test_bonus_math(self) -> None:
        assert exp_bonus_from_terms({}) == 0.0
        assert exp_bonus_from_terms({"expGainPct": 12.0}) == 12.0
        assert apply_exp_bonus(100, {"expGainPct": 12.0}) == 112
        assert apply_exp_bonus(100, {}) == 100


class TestRaidPressure:
    """副本必须能打死人，且门槛（requiredPower）必须可达。

    「达标装」（达到该副本 requiredPower 的装备：全神话 + 太古词条 + 太古副属性）的承伤
    必须高于它的被动回复（生命回复 + 吸血），否则英雄永远不会掉血，可以无限拖时间通关。
    """

    RAID_SLOTS = [s["id"] for s in CONFIG.slots]

    class _Item:
        def __init__(self, generated: dict[str, Any], slot: str) -> None:
            self.base_id = generated["baseId"]
            self.category = generated["category"]
            self.slot = slot
            self.rarity = generated["rarity"]
            self.level_req = generated["levelReq"]
            self.base_attrs = generated["baseAttrs"]
            self.sub_attrs = generated["subAttrs"]
            self.terms = [dict(t) for t in generated["terms"]]
            self.equipped_slot = slot

    def _bar_items(self, level: int, ancient: int) -> list[Any]:
        """达标装：全神话底材 + ancient 个攻击类太古词条 + 全部副属性取太古上限。"""
        rng = random.Random(11)
        items = []
        for slot in self.RAID_SLOTS:
            usable = [
                b for b in CONFIG.base_items if slot in possible_slots(b) and b.level_req <= level
            ]
            base = max(usable, key=lambda b: (b.tier_index, b.level_req))
            generated, _ = generate_item(
                base.category, level, rarity="mythic", base_id=base.id, rng=rng
            )
            item = self._Item(generated, slot)
            item.terms = [
                {
                    "id": f"ancient{index}",
                    "name": "力量增幅",
                    "type": "buff",
                    "stat": "attackPct",
                    "trigger": "passive",
                    "value": 18.75,
                    "quality": "ancient",
                    "desc": "攻击力 +{v}%",
                }
                for index in range(ancient)
            ]
            scale = float(getattr(base, "sub_attr_scale", 1.0))
            for entry in item.sub_attrs:
                spec = CONFIG.attribute_by_id[entry["attr"]]
                lo, hi = spec["ranges"][item.rarity]
                entry["value"] = round(max(abs(float(lo) * scale), abs(float(hi) * scale)) * 1.25, 2)
                entry["quality"] = "ancient"
            items.append(item)
        return items

    def _bar_ancient(self, level: int) -> int:
        """达标装的太古词条数（与 BOSS 倍率标定时一致）。"""
        return 2 if level <= 60 else 3

    def test_required_power_is_reachable(self) -> None:
        """门槛必须是可达到的：满配（3 太古 + 太古副属性）战力不得低于 requiredPower。"""
        for raid in all_raids():
            level = int(raid["requiredLevel"])
            power = hero_power(compute_stats(FakeHero(level=level), self._bar_items(level, 3)))
            required = int(raid["requiredPower"])
            assert power >= required, f"{raid['id']} 达标装战力 {power} < 门槛 {required}"

    def test_required_power_scales_with_level(self) -> None:
        tiers = sorted(
            (int(r["requiredLevel"]), int(r["requiredPower"]))
            for r in all_raids()
            if r.get("difficulty") == "normal"
        )
        powers = [power for _, power in tiers]
        assert powers == sorted(powers)
        assert len(set(powers)) == len(powers), powers

    def test_ref_dps_matches_bar_gear(self) -> None:
        """达标装 DPS 必须明显高于等级锚定 DPS：BOSS 只按等级锚定，装备成长才有效。"""
        for raid in all_raids():
            level = challenge_level(raid, int(raid["requiredLevel"]))
            stats = compute_stats(FakeHero(level=level), self._bar_items(level, self._bar_ancient(level)))
            anchor = monster_base_stats(level)["hp"] / float(
                CONFIG.monsters["reference"]["targetKillSeconds"]
            )
            assert theoretical_dps(stats, 0.0, None) > anchor

    def test_incoming_damage_beats_passive_healing(self) -> None:
        for raid in all_raids():
            level = int(raid["requiredLevel"])
            stats = compute_stats(FakeHero(level=level), self._bar_items(level, self._bar_ancient(level)))
            bosses = boss_stats_for_raid(raid, level, stats)
            enrage = raid.get("enrage")
            # 双 BOSS 一方阵亡后存活者狂暴，按其攻击倍率保守估算承伤
            enrage_mult = (
                float(enrage["attackMultiplier"])
                if enrage and len(bosses) > 1
                else 1.0
            )

            taken = 1 + stats.term_mods.get("damageTakenPct", 0.0) / 100.0
            tenacity = 1 - min(0.6, stats.tenacity_pct / 100.0)
            dodge = 1 - min(60.0, stats.dodge_pct) / 100.0

            def per_hit(attack: float) -> float:
                raw = attack * taken * tenacity
                return max(raw * 0.1, raw - stats.phys_def)

            incoming = 0.0
            dealt = 0.0
            for boss in bosses:
                atk = float(boss["attack"]) * enrage_mult
                rate = per_hit(atk) / float(boss["attackInterval"]) * dodge
                dps = theoretical_dps(stats, float(boss["defense"]), None)
                interval = float(boss.get("skillInterval", 6) or 6)
                for skill in boss.get("skills", []):
                    effect = skill.get("effect")
                    if effect == "shield":
                        dps *= 1 - float(skill["damageReduce"]) * float(skill["duration"]) / interval
                    elif effect == "enrage":
                        rate *= 1 + float(skill["attackBuff"]) * float(skill["duration"]) / interval
                    elif effect in ("nuke", "aoe", "charge") and skill.get("potency"):
                        rate += per_hit(atk * float(skill["potency"]) / 100.0) / interval
                incoming += rate
                dealt += dps
            healing = stats.hp_regen + (dealt / len(bosses)) * (stats.lifesteal_pct / 100.0)

            assert incoming > healing, (
                f"{raid['id']} 达标装承伤 {incoming:.0f}/s 未超过被动回复 {healing:.0f}/s，可以无限拖时间"
            )


def _lance_base_for_level(level: int) -> BaseItem:
    """该等级可用的最高档长枪底材（统一用长枪族，使职业固定为龙骑士）。"""
    usable = [b for b in CONFIG.base_items if b.weapon_type == "lance" and b.level_req <= level]
    return max(usable, key=lambda b: b.tier_index)


def _gear_from_base(base: BaseItem, rarity: str) -> FakeItem:
    mult = float(CONFIG.rarities[rarity]["multiplier"])
    return FakeItem(
        category=base.category,
        rarity=rarity,
        base_id=base.id,
        slot=base.slot,
        level_req=base.level_req,
        base_attrs=[{"attr": e["attr"], "value": e["base"] * mult} for e in base.base_attrs],
        sub_attrs=[],
        terms=[],
        equipped_slot=base.slot,
    )


def _expected_gear(level: int, rarity: str = "rare") -> list[FakeItem]:
    """等级匹配的期望装备：该等级可用的最高档长枪（稀有品质）。"""
    return [_gear_from_base(_lance_base_for_level(level), rarity)]


def _starter_weapon() -> FakeItem:
    """开局赠送并装备的起始武器。"""
    base = CONFIG.base_item_by_id[str(CONFIG.heroes["initialHero"]["starterWeapon"])]
    return _gear_from_base(base, "common")


class TestCombatPacing:
    """数值平衡：起始英雄能推进地区 1；等级匹配 + 装备到位时约「小怪 3 下 / 精英 5 下 / BOSS 10 下」。

    手感以命中次数为准（见 monsters.json:reference.$commentHits），此处的耗时区间只是
    粗守卫；命中次数的回归保护见 frontend/src/game/core.spec.ts 的「地区击杀手感」。
    """

    def test_starter_hero_can_clear_first_region(self) -> None:
        """起始武器必须让 Lv1 英雄在阵亡重置前打满地区 1 的击杀要求。

        小怪血量按「普通怪约 3 下」上调后，单怪耗时比旧版更长（实测约 9.9s，
        真实模拟器整轮 0 阵亡），此处只守卫「不至于慢到打不满 8 杀」。
        """
        stats = compute_stats(FakeHero(level=1), [_starter_weapon()])
        kill = theoretical_kill_seconds(stats, 1)
        assert 3.0 <= kill <= 12.0, f"起始英雄单怪耗时 {kill:.1f}s"

    @pytest.mark.parametrize("level,region", [(20, 5), (45, 10), (80, 23), (100, 40)])
    def test_kill_time_is_playable(self, level: int, region: int) -> None:
        stats = compute_stats(FakeHero(level=level), _expected_gear(level))
        kill = theoretical_kill_seconds(stats, region)
        # 稳态耗时约 5-6s（下限防「秒杀」回归）；Lv60+ 地区怪物血量按 regionHighLevelScale 线性放大，上界同步放宽
        cap = 8.0 * region_scale(float(CONFIG.region_by_id[region]["levelMin"]))[0]
        assert 3.0 <= kill <= cap, f"Lv{level} r{region} 击杀耗时 {kill:.1f}s"

    @pytest.mark.parametrize("level,region", [(20, 5), (45, 10), (80, 23), (100, 40)])
    def test_boss_time_is_playable(self, level: int, region: int) -> None:
        stats = compute_stats(FakeHero(level=level), _expected_gear(level))
        boss = theoretical_boss_seconds(stats, region)
        cap = 35.0 * region_scale(float(CONFIG.region_by_id[region]["levelMin"]))[0]
        assert 8.0 <= boss <= cap, f"Lv{level} r{region} BOSS 耗时 {boss:.1f}s"

    @pytest.mark.parametrize("level,region", [(20, 5), (45, 10), (80, 23), (100, 40)])
    def test_expected_hero_kills_faster_than_naked(self, level: int, region: int) -> None:
        """装备到位应当明显更快，但不至于秒杀（裸英雄仍是数倍耗时）。"""
        geared = theoretical_kill_seconds(compute_stats(FakeHero(level=level), _expected_gear(level)), region)
        naked = theoretical_kill_seconds(compute_stats(FakeHero(level=level), []), region)
        assert geared < naked
        assert naked >= 3.0, f"Lv{level} r{region} 裸英雄仅 {naked:.1f}s，装备价值过低"

    def test_spawn_interval_decreases_with_region(self) -> None:
        regions = CONFIG.regions["regions"]
        assert regions[0]["spawnInterval"] == 3.0
        assert regions[-1]["spawnInterval"] == 1.0
        intervals = [r["spawnInterval"] for r in regions]
        assert intervals == sorted(intervals, reverse=True)

    def test_kill_requirements_increase(self) -> None:
        kills = [r["killsRequired"] for r in CONFIG.regions["regions"]]
        assert kills[0] == 8
        assert kills[-1] == 36
        assert kills == sorted(kills)


class TestLevelPenalty:
    """等级压制：保证玩家只能战胜对应等级的怪物（越级几乎必败）。"""

    def test_no_penalty_when_level_meets_region(self) -> None:
        for level, region in [(20, 5), (45, 10), (100, 40)]:
            assert level_penalty(level, region) == {
                "hitRatePenaltyPct": 0.0,
                "damageDealtPenaltyPct": 0.0,
                "damageTakenBonusPct": 0.0,
                "defenseIgnorePct": 0.0,
            }

    def test_penalty_scales_per_level(self) -> None:
        cfg = CONFIG.regions["levelPenalty"]
        penalty = level_penalty(35, 10)  # 地区下限 45 → 落后 10 级
        assert penalty["hitRatePenaltyPct"] == pytest.approx(10 * cfg["hitRatePenaltyPctPerLevel"])
        assert penalty["damageDealtPenaltyPct"] == pytest.approx(
            10 * cfg["damageDealtPenaltyPctPerLevel"]
        )
        assert penalty["damageTakenBonusPct"] == pytest.approx(
            10 * cfg["damageTakenBonusPctPerLevel"]
        )
        assert penalty["defenseIgnorePct"] == pytest.approx(
            min(cfg["maxDefenseIgnorePct"], 10 * cfg["defenseIgnorePctPerLevel"])
        )

    def test_penalty_is_capped(self) -> None:
        cfg = CONFIG.regions["levelPenalty"]
        penalty = level_penalty(1, 40)  # 落后 98 级
        assert penalty["hitRatePenaltyPct"] == cfg["maxHitRatePenaltyPct"]
        assert penalty["damageDealtPenaltyPct"] == cfg["maxDamageDealtPenaltyPct"]
        assert penalty["damageTakenBonusPct"] == cfg["maxDamageTakenBonusPct"]
        assert penalty["defenseIgnorePct"] == cfg["maxDefenseIgnorePct"]

    def test_deficit_10_is_brutal(self) -> None:
        """落后 10 级：输出惩罚 ≥80%，防御已完全失效。"""
        cfg = CONFIG.regions["levelPenalty"]
        penalty = level_penalty(60, 23)  # 地区下限 70 → 落后 10 级
        assert penalty["damageDealtPenaltyPct"] >= 80
        assert penalty["defenseIgnorePct"] >= cfg["maxDefenseIgnorePct"]

    def test_underleveled_output_collapses(self) -> None:
        """落后 20 级时有效输出不足等级匹配的 10%，且单怪耗时远超可玩区间。"""
        region = 23  # 地区下限 70
        stats = compute_stats(FakeHero(level=50), _expected_gear(50))
        matched = theoretical_dps(stats, 0.0, level_penalty(70, region))
        under = theoretical_dps(stats, 0.0, level_penalty(50, region))
        assert under < matched * 0.10, f"旧等级曲线输出 {under / matched:.1%}"
        kill = theoretical_kill_seconds(stats, region, penalty=level_penalty(50, region))
        assert kill > 40.0, f"落后 20 级单怪仅 {kill:.1f}s"

    def test_kill_allowance_shrinks_when_underleveled(self) -> None:
        """服务端击杀额度必须同步收紧，否则越级可上报等级匹配才有的击杀速率。"""
        stats = compute_stats(FakeHero(level=50), _expected_gear(50))
        matched = max_kills_in_seconds(stats, 23, 10.0, 1.0, 70)
        under = max_kills_in_seconds(stats, 23, 10.0, 1.0, 50)
        assert under == matched  # 相同战斗属性下，仅更改等级参数不能绕过战力差距曲线。
        assert 0 < under <= 10 / float(CONFIG.region_by_id[23]["spawnInterval"])


class TestRecruitingAncient:
    """英雄太古属性：0.1% 概率，随机 1 条三维 = 三条中最高值 × 1.25。"""

    class _Forced(random.Random):
        """random() 恒返回指定值，用于强制命中 / 不命中太古判定。"""

        def __init__(self, value: float, seed: int = 7) -> None:
            super().__init__(seed)
            self._value = value

        def random(self) -> float:  # type: ignore[override]
            return self._value

    def test_ancient_triggers_and_becomes_highest(self) -> None:
        candidate = generate_candidate(1, self._Forced(0.0))
        ancient = candidate["ancientAttr"]
        assert ancient in ("str", "dex", "int")
        values = {
            "str": candidate["strength"],
            "dex": candidate["agility"],
            "int": candidate["intellect"],
        }
        others = [v for k, v in values.items() if k != ancient]
        # 太古值 = 三条中最高值 × 1.25，因此必然是最高的一条
        assert values[ancient] >= max(others)

    def test_no_ancient_when_roll_misses(self) -> None:
        candidate = generate_candidate(1, self._Forced(0.999))
        assert candidate["ancientAttr"] is None

    def test_pity_guarantees_ancient_within_threshold(self) -> None:
        """每 ancientPityCount 个候选至少出一个太古：自然判定全不中时由保底兜底。"""
        threshold = ancient_pity_count()
        candidates, counter = generate_candidates(1, threshold, 0, self._Forced(0.999))
        hits = [index for index, c in enumerate(candidates) if c["ancientAttr"]]
        assert hits == [threshold - 1], "只有第 threshold 个由保底触发"
        assert counter == 0

    def test_pity_ancient_is_mythic_with_top_band_points(self) -> None:
        """保底太古必定为神话（红色）资质，计算前总点数落在神话区间 220-260。"""
        spec = CONFIG.talents["talents"]["mythic"]
        threshold = ancient_pity_count()
        candidates, _ = generate_candidates(1, threshold, 0, self._Forced(0.999))
        hero = candidates[-1]
        assert hero["ancientAttr"] in ("str", "dex", "int")
        assert hero["talent"] == "mythic"
        assert int(spec["pointMin"]) <= hero["totalPoints"] <= int(spec["pointMax"])
        # 太古 ×1.25 计算后，三维实际总和可超出计算前的总点数（乃至区间上限）
        total = hero["strength"] + hero["agility"] + hero["intellect"]
        assert total > hero["totalPoints"]

    def test_natural_ancient_also_becomes_mythic(self) -> None:
        """自然命中（非保底）的太古同样必定为神话，总点数落在神话区间。"""
        spec = CONFIG.talents["talents"]["mythic"]
        candidate = generate_candidate(1, self._Forced(0.0))
        assert candidate["ancientAttr"] in ("str", "dex", "int")
        assert candidate["talent"] == "mythic"
        assert int(spec["pointMin"]) <= candidate["totalPoints"] <= int(spec["pointMax"])

    def test_no_ancient_keeps_rolled_talent(self) -> None:
        """未出太古时仍按资质权重随机。"""
        candidate = generate_candidate(1, self._Forced(0.3))
        assert candidate["ancientAttr"] is None
        assert candidate["talent"] == "common"  # roll=0.3 落在 common 权重区间

    def test_pity_counter_advances_and_resets(self) -> None:
        rng = self._Forced(0.999)
        _, counter = generate_candidates(1, 10, 0, rng)
        assert counter == 10, "未出太古时计数逐次累加"
        _, counter = generate_candidates(1, 1, ancient_pity_count() - 1, rng)
        assert counter == 0, "保底命中后计数归零"

    def test_pity_threshold_is_positive(self) -> None:
        assert ancient_pity_count() >= 1


class TestRecruitingEgg:
    """彩蛋英雄：共用 eggChance 概率，命中后固定资质/偏向，且忽略太古。"""

    def test_roll_hit_produces_fixed_legendary(self, monkeypatch) -> None:
        monkeypatch.setitem(CONFIG.egg_heroes, "eggChance", 1.0)
        candidate = generate_candidate(1, random.Random(1))
        assert candidate["eggId"] is not None
        egg = {h["id"]: h for h in CONFIG.egg_heroes["heroes"]}[candidate["eggId"]]
        assert candidate["name"] == egg["name"]
        assert candidate["talent"] == egg["talent"] == "legendary"
        assert candidate["attrBias"] == egg["attrBias"]
        assert candidate["ancientAttr"] is None
        spec = CONFIG.talents["talents"]["legendary"]
        assert int(spec["pointMin"]) <= candidate["totalPoints"] <= int(spec["pointMax"])

    def test_roll_miss_keeps_normal_hero(self) -> None:
        # conftest 默认把 eggChance 置 0，等价于「未命中彩蛋」
        candidate = generate_candidate(1, random.Random(1))
        assert candidate["eggId"] is None
        assert candidate["ancientAttr"] is None

    def test_normalize_egg_forces_configured_talent(self) -> None:
        egg = CONFIG.egg_heroes["heroes"][0]
        candidate = normalize_candidate({"eggId": egg["id"], "talent": "common", "ancientAttr": "str"})
        assert candidate["talent"] == egg["talent"]
        assert candidate["ancientAttr"] is None


class TestEggHeroAdditions:
    """新增彩蛋英雄：被动与技能配置齐全，共用同一出现概率。"""

    def test_exp_passive_bonus_pct(self) -> None:
        assert exp_bonus_pct("liangshisi") == pytest.approx(25.0)
        assert exp_bonus_pct("zhongtian") == 0.0
        assert exp_bonus_pct(None) == 0.0

    def test_new_heroes_configured(self) -> None:
        by_id = {h["id"]: h for h in CONFIG.egg_heroes["heroes"]}
        expected = {
            "liangshisi": (None, "int"),
            "qingfeng": ("PLD", "str"),
            "meiruoyu": ("DRG", "str"),
            "aolongbaiban": ("SGE", "int"),
            "yazi": ("MCH", "dex"),
            "luojieaier": (None, "int"),
            "minglan": ("VPR", "dex"),
        }
        for hero_id, (job_id, bias) in expected.items():
            hero = by_id[hero_id]
            assert hero["talent"] == "legendary"
            assert hero["attrBias"] == bias
            assert hero["jobId"] == job_id

    def test_skills_bound_to_job(self) -> None:
        """技能型彩蛋只在绑定职业生效；无技能的被动型彩蛋不改变职业组。"""
        for hero_id, job_id in (("qingfeng", "PLD"), ("meiruoyu", "DRG"), ("aolongbaiban", "SGE")):
            assert skills_for(hero_id, job_id) is not None
            assert skills_for(hero_id, "adventurer") is None
        assert skills_for("liangshisi", "WAR") is None

    def test_normal_mob_potency100_bonus(self) -> None:
        assert normal_mob_potency100_bonus("yazi") == pytest.approx(1.0)
        assert normal_mob_potency100_bonus("liangshisi") == 0.0
        assert normal_mob_potency100_bonus(None) == 0.0

    def test_craft_extra_chance(self) -> None:
        assert craft_extra_chance("luojieaier") == pytest.approx(0.25)
        assert craft_extra_chance("yazi") == 0.0
        assert craft_extra_chance(None) == 0.0

    def test_minglan_skill_bound_to_viper(self) -> None:
        result = skills_for("minglan", "VPR")
        assert result is not None
        skills, replace_skills = result
        assert [s["id"] for s in skills] == ["eggSleep"]
        assert replace_skills is False
        assert skills_for("minglan", "MCH") is None

    def test_yazi_doubles_100_potency_only_vs_normal_mobs(self) -> None:
        """「战斗爽」只在对普通怪物时把威力 100% 的技能翻倍，精英 / BOSS 不受影响。"""
        bare = compute_stats(FakeHero(level=50), [])
        mch = replace(bare, job_id="MCH")
        yazi = replace(mch, egg_id="yazi")

        normal_plain = theoretical_dps(mch, 0.0, None, mob_kind="normal")
        normal_doubled = theoretical_dps(yazi, 0.0, None, mob_kind="normal")
        assert normal_doubled > normal_plain

        for kind in ("elite", "boss"):
            assert theoretical_dps(yazi, 0.0, None, mob_kind=kind) == pytest.approx(
                theoretical_dps(mch, 0.0, None, mob_kind=kind)
            )


class TestBasicAttackModel:
    """普攻与技能完全独立：理论模型计入普攻，且普攻间隔受攻速缩短。"""

    def test_dps_rises_with_attack_speed(self) -> None:
        stats = compute_stats(FakeHero(level=50), [])
        slow = theoretical_dps(replace(stats, attack_speed_pct=0.0), 0.0, None)
        fast = theoretical_dps(replace(stats, attack_speed_pct=100.0), 0.0, None)
        # 攻速只缩短普攻间隔（技能循环不随攻击速度放大），因此模型 DPS 仍应提高。
        assert fast > slow


class TestEnchantNewEffects:
    """新增附魔词条：中毒触发与双重施法计入理论 DPS，恢复速率词条折算进面板。"""

    def test_poison_proc_increases_dps(self) -> None:
        base = compute_stats(FakeHero(level=50), [])
        plain = theoretical_dps(base, 0.0, None)
        poisoned = theoretical_dps(
            replace(base, term_mods={**base.term_mods, "poisonProcPct": 100.0}), 0.0, None
        )
        assert poisoned > plain

    def test_double_cast_increases_dps(self) -> None:
        base = compute_stats(FakeHero(level=50), [])
        plain = theoretical_dps(base, 0.0, None)
        doubled = theoretical_dps(
            replace(base, term_mods={**base.term_mods, "doubleCastPct": 100.0}), 0.0, None
        )
        assert doubled > plain

    def test_regen_terms_scale_regen(self) -> None:
        item = FakeItem(
            terms=[
                {"id": "vitalitySurge", "stat": "hpRegenPct", "value": 50.0, "type": "buff"},
                {"id": "manaSurge", "stat": "mpRegenPct", "value": 50.0, "type": "buff"},
            ]
        )
        base = compute_stats(FakeHero(level=50), [])
        boosted = compute_stats(FakeHero(level=50), [item])
        assert boosted.hp_regen == pytest.approx(base.hp_regen * 1.5)
        assert boosted.mp_regen == pytest.approx(base.mp_regen * 1.5)


class TestReportDoubleCharges:
    """彩蛋「拔豆芽」：服务端按充能放宽单只怪物上限并扣减。"""

    def test_without_charges_gold_is_clamped(self) -> None:
        stats = compute_stats(FakeHero(level=50), [])
        cap = int(max_gold_for_kill(1, "normal", stats))
        gold = int(cap * 1.8)
        result = validate_report(stats, 1, 5000, [{"monsterId": "normal", "gold": gold, "exp": 1}], 10)
        assert result.doubled_kills == 0
        assert result.total_gold == cap
        assert any("截断" in issue for issue in result.issues)

    def test_charges_relax_cap_and_are_counted(self) -> None:
        stats = compute_stats(FakeHero(level=50), [])
        cap = int(max_gold_for_kill(1, "normal", stats))
        gold = int(cap * 1.8)  # 超过单倍上限，但在双倍上限内
        kills = [{"monsterId": "normal", "gold": gold, "exp": int(gold * 1.0)} for _ in range(2)]
        result = validate_report(stats, 1, 5000, kills, 10, double_charges=2)
        assert result.accepted
        assert result.doubled_kills == 2
        assert result.total_gold == gold * 2
        assert not any("截断" in issue for issue in result.issues)


BASE_ID = "w_sword_shield_0"


class TestBasedOnCurrentReroll:
    """「基于当前」的重造 / 附魔：每条在当前值附近独立浮动，可升可降，保留种类与品质。"""

    def test_refine_keeps_kinds_and_stays_in_range(self) -> None:
        base = CONFIG.base_item_by_id[BASE_ID]
        item = FakeItem(
            category="weapon",
            base_id=BASE_ID,
            rarity="rare",
            base_attrs=[{"attr": "attack", "value": 30.0}],
            sub_attrs=[{"attr": "crit", "value": 90.0, "type": "flat", "quality": "common"}],
        )
        rng = random.Random(1)
        seen: set[float] = set()
        for _ in range(30):
            result = regenerate_attrs(item, rng, "basedOnCurrent")
            assert [a["attr"] for a in result["baseAttrs"]] == ["attack"]
            assert [a["attr"] for a in result["subAttrs"]] == ["crit"]
            blo, bhi = base_attr_range(base, "rare", "attack")
            assert blo - 1e-6 <= result["baseAttrs"][0]["value"] <= bhi + 1e-6
            slo, shi = sub_attr_range(base, "rare", "crit")
            assert slo - 1e-6 <= result["subAttrs"][0]["value"] <= shi + 1e-6
            seen.add(result["subAttrs"][0]["value"])
            item.base_attrs, item.sub_attrs = result["baseAttrs"], result["subAttrs"]
        assert len(seen) > 1, "基于当前应逐次浮动，而非固定不变"

    def test_based_on_current_float_scales_with_current_value(self) -> None:
        """基于当前：单步幅度按「当前值」的百分比（默认 −5% ~ +10%）。"""
        base = CONFIG.base_item_by_id[BASE_ID]
        lo, hi = base_attr_range(base, "rare", "attack")
        mid = (lo + hi) / 2  # 区间中点，保证 ±10% 不会触碰夹取边界
        down = float(CONFIG.economy["refine"]["basedOnCurrentDownPct"])
        up = float(CONFIG.economy["refine"]["basedOnCurrentUpPct"])
        assert down == pytest.approx(0.05)
        assert up == pytest.approx(0.10)
        rng = random.Random(11)
        item = FakeItem(
            category="weapon",
            base_id=BASE_ID,
            rarity="rare",
            base_attrs=[{"attr": "attack", "value": mid}],
            sub_attrs=[],
        )
        for _ in range(50):
            result = regenerate_attrs(item, rng, "basedOnCurrent")
            value = result["baseAttrs"][0]["value"]
            assert mid * (1 - down) - 0.01 <= value <= mid * (1 + up) + 0.01

    def test_refine_preserves_quality_band(self) -> None:
        base = CONFIG.base_item_by_id[BASE_ID]
        cap = sub_attr_cap(base, "legendary", "crit")
        item = FakeItem(
            category="weapon",
            base_id=BASE_ID,
            rarity="legendary",
            base_attrs=[{"attr": "attack", "value": 30.0}],
            sub_attrs=[
                {"attr": "crit", "value": round(cap * 1.25, 2), "type": "flat", "quality": "ancient"},
            ],
        )
        rng = random.Random(2)
        for _ in range(20):
            result = regenerate_attrs(item, rng, "basedOnCurrent")
            entry = result["subAttrs"][0]
            assert entry["quality"] == "ancient", "品质应保留，不掉回普通"
            assert entry["value"] >= cap * 1.25 - 1e-6
            assert entry["value"] <= cap * 1.5 + 1e-6
            item.base_attrs, item.sub_attrs = result["baseAttrs"], result["subAttrs"]

    def test_refine_random_rerolls_all_attrs(self) -> None:
        """彻底随机：基础属性与副属性全部重新洗牌。"""
        base = CONFIG.base_item_by_id[BASE_ID]
        item = FakeItem(
            category="weapon",
            base_id=BASE_ID,
            rarity="rare",
            base_attrs=[{"attr": "attack", "value": 1.0}],
            sub_attrs=[],
        )
        rng = random.Random(9)
        result = regenerate_attrs(item, rng, "random")
        assert result["baseAttrs"][0]["attr"] == "attack"
        lo, hi = base_attr_range(base, "rare", "attack")
        assert lo - 1e-6 <= result["baseAttrs"][0]["value"] <= hi + 1e-6
        assert len(result["subAttrs"]) >= 1
        assert "terms" in result, "彻底随机重造现在也会重掷词条"

    def _common_buff_item(self, quality: str = "common", value: float = 8.0) -> FakeItem:
        return FakeItem(
            category="weapon",
            base_id=BASE_ID,
            rarity="legendary",
            base_attrs=[{"attr": "attack", "value": 30.0}],
            sub_attrs=[],
            terms=[
                {
                    "id": "strBoost", "name": "力量增幅", "type": "buff", "stat": "attackPct",
                    "trigger": "常驻", "value": value, "quality": quality, "desc": "",
                },
            ],
        )

    def test_based_on_current_can_upgrade_common_buff_to_ancient(self) -> None:
        """基于当前：有 5% 概率把一条普通 Buff 升为太古（数值 = 上限 ×1.25）。"""
        item = self._common_buff_item()
        rng = random.Random(4)
        upgraded = None
        for _ in range(400):
            result = regenerate_attrs(item, rng, "basedOnCurrent")
            term = result["terms"][0]
            if term["quality"] == "ancient":
                upgraded = term
                break
            item.terms = result["terms"]
        assert upgraded is not None, "多次基于当前应出现普通 Buff → 太古"
        lo, hi = CONFIG.term_by_id["strBoost"]["range"]
        assert upgraded["value"] == pytest.approx(round(hi * 1.25, 2))

    def test_based_on_current_keeps_ancient_floor(self) -> None:
        """已有太古词条时，基于当前浮动后太古词条数不得减少。"""
        item = self._common_buff_item(quality="ancient", value=18.75)
        rng = random.Random(5)
        for _ in range(40):
            result = regenerate_attrs(item, rng, "basedOnCurrent")
            ancients = [t for t in result["terms"] if t["quality"] == "ancient"]
            assert len(ancients) >= 1, "已有太古词条数不得减少"
            item.terms = result["terms"]

    def test_enchant_keeps_terms_and_forces_debuff_common(self) -> None:
        item = FakeItem(
            category="weapon",
            base_id=BASE_ID,
            rarity="epic",
            terms=[
                {
                    "id": "strBoost", "name": "力量增幅", "type": "buff", "stat": "attackPct",
                    "trigger": "常驻", "value": 8.0, "quality": "rare", "desc": "",
                },
                {
                    "id": "weaken", "name": "虚弱", "type": "debuff", "stat": "attackPct",
                    "trigger": "常驻", "value": -9.0, "quality": "rare", "desc": "",
                },
            ],
        )
        rng = random.Random(3)
        seen: set[float] = set()
        for _ in range(20):
            result = roll_terms_for_enchant(item, rng, "basedOnCurrent")
            assert [t["id"] for t in result] == ["strBoost", "weaken"]
            for term in result:
                lo, hi = CONFIG.term_by_id[term["id"]]["range"]
                assert lo - 1e-6 <= term["value"] <= hi + 1e-6
            assert result[0]["quality"] == "rare", "Buff 品质保留"
            assert result[1]["quality"] == "common", "Debuff 恒为普通"
            seen.add(result[1]["value"])  # 普通 Debuff 逐次浮动
            item.terms = result
        assert len(seen) > 1


class TestDebuffHasNoQuality:
    """Debuff 不参与稀有/太古判定：品质恒为普通（仅在随机池内随机）。"""

    def test_generated_debuffs_are_always_common(self) -> None:
        rng = random.Random(7)
        found = 0
        for rarity in CONFIG.rarity_order:
            for _ in range(200):
                item, _ = generate_item("weapon", 100, rarity=rarity, rng=rng)
                for term in item["terms"]:
                    if term["type"] == "debuff":
                        found += 1
                        assert term["quality"] == "common"
        assert found > 0, "样本里应出现 Debuff 才能验证"


class TestBasedOnCurrentCost:
    """「基于当前」比彻底随机更贵。"""

    def test_premium_mode_costs_more(self) -> None:
        for rarity in CONFIG.rarity_order:
            assert refine_cost(rarity, 0, "basedOnCurrent") > refine_cost(rarity, 0, "random")
            assert enchant_cost(rarity, "basedOnCurrent") > enchant_cost(rarity, "random")


class _SellProbe:
    """适配 sell_price 的对象。"""

    def __init__(self, data: dict[str, Any]) -> None:
        self.rarity = data["rarity"]
        self.base_attrs = data["baseAttrs"]
        self.sub_attrs = data["subAttrs"]
        self.terms = data["terms"]


def _ev_sell_per_draw(category: str, box_tier: str, band: int, luck: float, n: int = 6000, seed: int = 7) -> float:
    """含保底的期望出售价：连续开箱时保底会提升品阶，需一并计入。"""
    rng = random.Random(seed)
    pity = PityState()
    total = 0.0
    for _ in range(n):
        rarity, pity = draw_rarity(box_tier, pity, rng, luck)
        item, _ = generate_item(category, band, rarity=rarity, rng=rng)
        total += sell_price(_SellProbe(item))
    return total / n


class TestDropRate:
    """通关进度 → 品阶爆率倍率：提高装备品阶，且不能刷取金币。"""

    def test_multiplier_scales_and_caps(self) -> None:
        cap = float(CONFIG.chests["dropRate"]["maxMultiplier"])
        assert drop_rate_multiplier(0) == 1.0
        assert 1.0 < drop_rate_multiplier(10) < cap
        assert drop_rate_multiplier(10_000) == cap

    def test_weights_shift_toward_higher_rarity(self) -> None:
        base = rarity_weights("normal", 0.0)
        boosted = rarity_weights("normal", 0.5)
        assert abs(sum(boosted) - 1.0) < 1e-9
        top = RARITY_ORDER.index("rare")
        assert sum(boosted[top:]) > sum(base[top:])

    def test_chest_cannot_be_farmed_for_gold_at_max_luck(self) -> None:
        """即使满幸运（所有来源全满的上限），买箱出售的期望收益也低于箱子价格（无法刷金币）。"""
        max_luck = chest_luck_max()
        cheapest_band = min(CONFIG.chests["levelBands"], key=lambda b: float(b["priceMultiplier"]))
        for chest in CONFIG.chests["chests"]:
            unit = int(chest["price"] * float(cheapest_band["priceMultiplier"]))
            ev = _ev_sell_per_draw(
                chest["category"], chest["tier"], int(cheapest_band["level"]), max_luck
            )
            assert ev < unit, f"{chest['id']} 期望出售价 {ev:.1f} ≥ 箱子价 {unit}"


class _ScoredItem:
    """适配 item_score / compute_stats 的生成装备替身。"""

    def __init__(self, generated: dict[str, Any], slot: str, equipped: bool = True) -> None:
        self.id = id(self)
        self.base_id = generated["baseId"]
        self.category = generated["category"]
        self.slot = slot
        self.rarity = generated["rarity"]
        self.level_req = generated["levelReq"]
        self.base_attrs = generated["baseAttrs"]
        self.sub_attrs = generated["subAttrs"]
        self.terms = generated["terms"]
        self.equipped_slot = slot if equipped else None


class TestPowerScoring:
    """战力重算：低档装备不得虚高，且战力排序必须与真实收益同向。

    来源：需求「会出现高战力低等级装备，且穿上高战力装备属性不如低战力装备」。
    """

    WEAPON_TIERS = {tier: f"w_lance_{tier}" for tier in range(6)}

    def test_sub_attr_score_scales_with_tier(self) -> None:
        """同一底材族、同一品阶下，item_score 必须随档位单调递增。"""
        for rarity in ("common", "epic", "mythic"):
            prev: float | None = None
            for tier in range(6):
                item, _ = generate_item(
                    "weapon", 95, rarity=rarity, base_id=self.WEAPON_TIERS[tier], rng=random.Random(7)
                )
                score = attrs_score(item["baseAttrs"], item["subAttrs"])
                if prev is not None:
                    assert score > prev, f"{rarity} 档位 {tier} 战力 {score} 未高于上一档 {prev}"
                prev = score

    def test_low_tier_mythic_below_high_tier_common(self) -> None:
        """低档高品阶（Lv1 神话）战力必须低于高档低品阶（Lv95 普通）。"""
        for category, low_base, high_base in (
            ("weapon", "w_lance_0", "w_lance_5"),
            ("armor", "a_head_0", "a_head_5"),
            ("accessory", "c_ring_0", "c_ring_5"),
        ):
            low, _ = generate_item(category, 1, rarity="mythic", base_id=low_base, rng=random.Random(3))
            high, _ = generate_item(category, 95, rarity="common", base_id=high_base, rng=random.Random(3))
            low_score = attrs_score(low["baseAttrs"], low["subAttrs"])
            high_score = attrs_score(high["baseAttrs"], high["subAttrs"])
            assert low_score < high_score, f"{category}: Lv1 神话 {low_score} ≥ Lv95 普通 {high_score}"

    def test_equipping_higher_score_item_does_not_lower_hero_power(self) -> None:
        """换上战力更高的装备后，英雄总战力不得下降（装备战力与英雄战力同口径）。"""
        hero = FakeHero(level=95)
        low_gen, _ = generate_item("weapon", 1, rarity="mythic", base_id="w_lance_0", rng=random.Random(5))
        high_gen, _ = generate_item("weapon", 95, rarity="common", base_id="w_lance_5", rng=random.Random(5))
        low = _ScoredItem(low_gen, "mainHand")
        high = _ScoredItem(high_gen, "mainHand")
        assert item_score(low) < item_score(high)
        assert hero_power(compute_stats(hero, [high])) > hero_power(compute_stats(hero, [low]))

    def test_power_weights_shape(self) -> None:
        """三属性权重不得压过攻击力，且必须高于普通副属性（PRD 排行榜 2.2）。"""
        w = CONFIG.economy["power"]["weights"]
        for attr in ("crit", "dh", "det"):
            assert w[attr] <= w["attack"] * 1.5, attr
            for utility in ("sks", "sps", "lifesteal", "dodge", "acc", "tenacity"):
                assert w[utility] < w[attr], f"{utility} 权重应低于 {attr}"

    def test_higher_score_means_higher_combat_value(self) -> None:
        """同一底材/品阶下，战力更高的装备其真实输出不得更低（防权重脱钩）。

        候选装备的底材固定（基础属性相同），差异只在副属性，因此该断言直接检验
        「战力排序 = 真实收益排序」。旧权重下 sks 等虚高会使其失败。
        """
        level = 80
        slot_ids = [s["id"] for s in CONFIG.slots]
        rng = random.Random(23)

        # 固定门槛装（主手留空，用于替换候选）
        loadout: dict[str, _ScoredItem] = {}
        for slot in slot_ids:
            if slot == "mainHand":
                continue
            usable = [b for b in CONFIG.base_items if slot in possible_slots(b) and b.level_req <= level]
            base = max(usable, key=lambda b: (b.tier_index, b.level_req))
            generated, _ = generate_item(base.category, level, rarity="epic", base_id=base.id, rng=rng)
            loadout[slot] = _ScoredItem(generated, slot)

        base = CONFIG.base_item_by_id["w_lance_4"]
        candidates = [
            _ScoredItem(generate_item("weapon", level, rarity="epic", base_id=base.id, rng=rng)[0], "mainHand")
            for _ in range(30)
        ]

        def dps(item: _ScoredItem) -> float:
            stats = compute_stats(FakeHero(level=level, attr_bias="str"), [*loadout.values(), item])
            return theoretical_dps(stats, 0.0, None)

        ranked = sorted(candidates, key=item_score)
        third = len(ranked) // 3
        low_power = sum(dps(i) for i in ranked[:third]) / third
        high_power = sum(dps(i) for i in ranked[-third:]) / third
        assert high_power > low_power, f"高战力组 {high_power:.0f} 未高于低战力组 {low_power:.0f}"

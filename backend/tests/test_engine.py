"""核心数值引擎：属性、伤害、掉落保底、售价、合成。"""

from __future__ import annotations

import random

import pytest

from app.services.combat_model import (
    max_kills_in_seconds,
    theoretical_boss_seconds,
    theoretical_dps,
    theoretical_kill_seconds,
)
from app.services.economy import REQUIRED, build_craft_plan
from app.services.game_config import CONFIG, BaseItem
from app.services.item_factory import generate_item, roll_sub_attr_value
from app.services.loot import PityState, chest_by_id, draw_rarity, roll_rarity
from app.services.combat_model import theoretical_dps
from app.services.regions_util import level_penalty
from app.services.raid_util import all_raids, boss_stats_for_raid
from app.services.slots_util import possible_slots
from app.services.stats import compute_stats, convert_three_attrs
from app.services.valuation import attr_factor, hero_power, sell_price, sell_price_range

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
        full_gain = 100 * 8  # int 对 maxMp 的系数

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
    """重造 / 附魔的单次消耗：随品阶单调递增、附魔始终比重造贵、且都控制在 5 万以内。"""

    CAP = 50_000

    def test_costs_within_cap_and_monotonic(self) -> None:
        refine = [int(CONFIG.rarities[r]["refineCost"]) for r in CONFIG.rarity_order]
        enchant = [int(CONFIG.rarities[r]["enchantCost"]) for r in CONFIG.rarity_order]

        assert max(refine) <= self.CAP
        assert max(enchant) <= self.CAP
        assert refine == sorted(refine)
        assert enchant == sorted(enchant)
        assert all(e > r for r, e in zip(refine, enchant))


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


class TestRaidScaling:
    """副本 BOSS 需随玩家战力缩放，避免装备超模后碾压。"""

    def test_boss_grows_with_player_power(self) -> None:
        raid = CONFIG.raid_by_id["raid_1"]
        weak = compute_stats(FakeHero(level=20), [])
        strong = compute_stats(FakeHero(level=20, strength=400, agility=400, intellect=400), [])

        weak_boss = boss_stats_for_raid(raid, 20, weak)[0]
        strong_boss = boss_stats_for_raid(raid, 20, strong)[0]
        assert strong_boss["hp"] > weak_boss["hp"]
        assert strong_boss["attack"] > weak_boss["attack"]

    def test_scaling_never_weakens_boss(self) -> None:
        """低于本等级参考输出时应保持基准强度，不因战力低而变弱。"""
        raid = CONFIG.raid_by_id["raid_1"]
        naked = compute_stats(FakeHero(level=20), [])
        assert boss_stats_for_raid(raid, 20, naked)[0]["hp"] == boss_stats_for_raid(raid, 20, None)[0]["hp"]

    def test_boss_scales_with_level(self) -> None:
        """等级越高，锚定的 BOSS 越强。"""
        raid = CONFIG.raid_by_id["raid_1"]
        low = boss_stats_for_raid(raid, 20, None)[0]["hp"]
        high = boss_stats_for_raid(raid, 100, None)[0]["hp"]
        assert high > low


class TestRaidPressure:
    """副本必须能打死人。

    门槛装备（刚好够进本的那一套）的承伤必须高于它的被动回复（生命回复 + 吸血），
    否则英雄永远不会掉血，普通玩家可以靠无限拖时间通关。
    """

    RAID_SLOTS = [s["id"] for s in CONFIG.slots]
    GATE_MIX = {
        "normal": ["epic"] * 6 + ["rare"] * 5,
        "hard": ["mythic"] * 6 + ["legendary"] * 5,
    }

    class _Item:
        def __init__(self, generated: dict[str, Any], slot: str) -> None:
            self.base_id = generated["baseId"]
            self.category = generated["category"]
            self.slot = slot
            self.rarity = generated["rarity"]
            self.level_req = generated["levelReq"]
            self.base_attrs = generated["baseAttrs"]
            self.sub_attrs = generated["subAttrs"]
            self.terms = generated["terms"]
            self.equipped_slot = slot

    def _gate_items(self, level: int, difficulty: str) -> list[Any]:
        mix = self.GATE_MIX[difficulty]
        rng = random.Random(11)
        items = []
        for index, slot in enumerate(self.RAID_SLOTS):
            usable = [
                b for b in CONFIG.base_items if slot in possible_slots(b) and b.level_req <= level
            ]
            base = max(usable, key=lambda b: (b.tier_index, b.level_req))
            generated, _ = generate_item(
                base.category, level, rarity=mix[index], base_id=base.id, rng=rng
            )
            items.append(self._Item(generated, slot))
        return items

    def test_incoming_damage_beats_passive_healing(self) -> None:
        for raid in all_raids():
            level = int(raid["requiredLevel"])
            difficulty = str(raid["difficulty"])
            stats = compute_stats(FakeHero(level=level), self._gate_items(level, difficulty))
            bosses = boss_stats_for_raid(raid, level, stats)

            taken = 1 + stats.term_mods.get("damageTakenPct", 0.0) / 100.0
            tenacity = 1 - min(0.6, stats.tenacity_pct / 100.0)
            dodge = 1 - min(60.0, stats.dodge_pct) / 100.0

            incoming = 0.0
            dealt = 0.0
            for boss in bosses:
                raw = float(boss["attack"]) * taken * tenacity
                per_hit = max(raw * 0.1, raw - stats.phys_def)
                incoming += per_hit / float(boss["attackInterval"]) * dodge
                dealt += theoretical_dps(stats, float(boss["defense"]), None)
            healing = stats.hp_regen + (dealt / len(bosses)) * (stats.lifesteal_pct / 100.0)

            assert incoming > healing, (
                f"{raid['id']} 门槛装备承伤 {incoming:.0f}/s 未超过被动回复 {healing:.0f}/s，可以无限拖时间"
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
    """数值平衡：起始英雄能推进地区 1；等级匹配 + 装备到位时单怪约 2.5 秒、BOSS 约 20 秒。"""

    def test_starter_hero_can_clear_first_region(self) -> None:
        """起始武器必须让 Lv1 英雄在阵亡重置前打满地区 1 的击杀要求。"""
        stats = compute_stats(FakeHero(level=1), [_starter_weapon()])
        kill = theoretical_kill_seconds(stats, 1)
        assert 3.0 <= kill <= 9.0, f"起始英雄单怪耗时 {kill:.1f}s"

    @pytest.mark.parametrize("level,region", [(20, 5), (45, 10), (80, 23), (100, 40)])
    def test_kill_time_is_playable(self, level: int, region: int) -> None:
        stats = compute_stats(FakeHero(level=level), _expected_gear(level))
        kill = theoretical_kill_seconds(stats, region)
        assert 1.5 <= kill <= 6.0, f"Lv{level} r{region} 击杀耗时 {kill:.1f}s"

    @pytest.mark.parametrize("level,region", [(20, 5), (45, 10), (80, 23), (100, 40)])
    def test_boss_time_is_playable(self, level: int, region: int) -> None:
        stats = compute_stats(FakeHero(level=level), _expected_gear(level))
        boss = theoretical_boss_seconds(stats, region)
        assert 8.0 <= boss <= 35.0, f"Lv{level} r{region} BOSS 耗时 {boss:.1f}s"

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

    def test_penalty_is_capped(self) -> None:
        cfg = CONFIG.regions["levelPenalty"]
        penalty = level_penalty(1, 40)  # 落后 98 级
        assert penalty["hitRatePenaltyPct"] == cfg["maxHitRatePenaltyPct"]
        assert penalty["damageDealtPenaltyPct"] == cfg["maxDamageDealtPenaltyPct"]
        assert penalty["damageTakenBonusPct"] == cfg["maxDamageTakenBonusPct"]

    def test_underleveled_output_collapses(self) -> None:
        """落后 20 级时有效输出不足等级匹配的 10%，且单怪耗时远超可玩区间。"""
        region = 23  # 地区下限 70
        stats = compute_stats(FakeHero(level=50), _expected_gear(50))
        matched = theoretical_dps(stats, 0.0, level_penalty(70, region))
        under = theoretical_dps(stats, 0.0, level_penalty(50, region))
        assert under < matched * 0.10, f"落后 20 级仍有 {under / matched:.1%} 输出"
        kill = theoretical_kill_seconds(stats, region, penalty=level_penalty(50, region))
        assert kill > 40.0, f"落后 20 级单怪仅 {kill:.1f}s"

    def test_kill_allowance_shrinks_when_underleveled(self) -> None:
        """服务端击杀额度必须同步收紧，否则越级可上报等级匹配才有的击杀速率。"""
        stats = compute_stats(FakeHero(level=50), _expected_gear(50))
        matched = max_kills_in_seconds(stats, 23, 10.0, 1.0, 70)
        under = max_kills_in_seconds(stats, 23, 10.0, 1.0, 50)
        assert under < matched
        assert under <= 1.0, f"落后 20 级仍允许 {under:.1f} 杀/10s"

"""共享数据层一致性：JSON 与加载器、前后端契约。"""

from __future__ import annotations

from app.services.game_config import CONFIG


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
    assert len(CONFIG.base_items) == 180
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


def test_mp_pool_is_tight() -> None:
    """蓝池与回复刻意收紧：满蓝约等于一轮技能消耗，持续施放会见底。"""
    attrs = CONFIG.heroes["attributes"]
    growth = CONFIG.heroes["levelUpGain"]["maxMp"]
    assert float(attrs["maxMp"]["coef"]["int"]) <= 1.0
    assert float(attrs["mpRegen"]["coef"]["int"]) <= 0.01
    assert float(growth["coef"]["int"]) <= 0.1


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

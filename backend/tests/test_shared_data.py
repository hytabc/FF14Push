"""共享数据层一致性：JSON 与加载器、前后端契约。"""

from __future__ import annotations

from app.services.game_config import CONFIG


def test_rarity_probabilities_sum_to_one() -> None:
    for tier in ("normal", "advanced"):
        total = sum(CONFIG.rarities[r]["boxChance"][tier] for r in CONFIG.rarity_order)
        assert abs(total - 1.0) < 1e-6, f"{tier} 品阶概率合计应为 1，实际 {total}"


def test_rarity_order_and_tiers() -> None:
    tiers = [CONFIG.rarities[r]["tier"] for r in CONFIG.rarity_order]
    assert tiers == sorted(tiers) == list(range(6))
    multipliers = [CONFIG.rarities[r]["multiplier"] for r in CONFIG.rarity_order]
    assert multipliers == sorted(multipliers)


def test_all_jobs_have_five_skills() -> None:
    assert len(CONFIG.jobs["jobs"]) == 21
    for job in CONFIG.jobs["jobs"]:
        assert len(job["skills"]) == CONFIG.jobs["maxSkills"], job["id"]
        assert len({s["id"] for s in job["skills"]}) == 5


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

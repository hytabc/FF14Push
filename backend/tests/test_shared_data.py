"""共享数据层一致性：JSON 与加载器、前后端契约。"""

from __future__ import annotations

import pytest

from app.services.game_config import CONFIG


def test_draw_counts_unlock_costs() -> None:
    """连抽档位与一次性解锁价：单抽/十连免费，50 连 500 万、100 连 2000 万。"""
    costs = {int(d["count"]): int(d["unlockCost"]) for d in CONFIG.chests["drawCounts"]}
    assert costs == {1: 0, 10: 0, 50: 5_000_000, 100: 20_000_000}


def test_transfer_fee_and_bounds() -> None:
    """好友转账：手续费 10%，单笔上下限与每日上限有效（手续费销毁，不可刷金币）。"""
    transfer = CONFIG.economy["transfer"]
    assert float(transfer["feePct"]) == pytest.approx(0.10)
    assert 0 < int(transfer["minAmount"]) <= int(transfer["maxAmount"])
    assert int(transfer["dailyLimit"]) >= int(transfer["maxAmount"])


def test_anti_alt_bounds() -> None:
    """反多开：同设备账号上限与关联账号额度有效，且不与单笔下限 / 单价下限冲突。"""
    cfg = CONFIG.economy["antiAlt"]
    assert int(cfg["maxAccountsPerDevice"]) >= 1
    assert int(cfg["transferDailyLimit"]) >= int(CONFIG.economy["transfer"]["minAmount"])
    assert int(cfg["marketDailyLimit"]) >= int(CONFIG.economy["market"]["minPrice"])


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


def test_all_jobs_have_ten_skills() -> None:
    assert len(CONFIG.jobs["jobs"]) == 21
    assert CONFIG.jobs["maxSkills"] == 10
    for job in CONFIG.jobs["jobs"]:
        assert len(job["skills"]) == CONFIG.jobs["maxSkills"], job["id"]
        assert len({s["id"] for s in job["skills"]}) == 10


def test_all_jobs_have_rotation_kit() -> None:
    """每个职业都补齐「短 CD 轮转技 + DOT 持续伤害 + 职能特色技」，用于避免反复刷同一个技能。"""
    for job in CONFIG.jobs["jobs"]:
        skills = job["skills"]
        # 至少两个短 CD 普通技（优先级 3，CD ≤ 8），保证 GCD 空档期能轮转
        short_fillers = [
            s for s in skills if int(s["priority"]) == 3 and float(s["cd"]) <= 8 and int(s["potency"]) > 0
        ]
        assert len(short_fillers) >= 2, (job["id"], [s["id"] for s in short_fillers])
        # 至少一个 DOT 持续伤害技能
        assert any(
            any(e.get("type") == "dot" for e in s.get("effects") or []) for s in skills
        ), job["id"]
        # 极短 CD 技能不得成为「最贵」的技能（耗蓝 ÷ CD 不能突破基础回蓝上限）
        hardest = max(float(s["mpCost"]) / max(0.1, float(s["cd"])) for s in skills)
        assert hardest <= float(CONFIG.heroes["attributes"]["mpRegen"]["base"]), job["id"]


def test_job_skills_reflect_role_identity() -> None:
    """职能特色：坦克必须有减伤 / 护盾技能，治疗必须有治疗 / 护盾技能，DPS 必须有高威力伤害技能。"""
    for job in CONFIG.jobs["jobs"]:
        kinds = {e.get("type") for s in job["skills"] for e in s.get("effects") or []}
        potency_skills = [s for s in job["skills"] if int(s.get("potency", 0)) >= 300]
        if job["role"] == "tank":
            assert kinds & {"shield", "damageReduction", "immunity", "undying"}, job["id"]
        elif job["role"] == "healer":
            assert kinds & {"heal", "healOverTime", "shield"}, job["id"]
        else:
            assert potency_skills, job["id"]


def test_dps_jobs_have_survival_tool() -> None:
    """输出职业也要有保命手段：辅助增伤技带一段减伤（或护盾），且越脆的职业补偿越多。"""
    dps_roles = {"melee", "physicalRanged", "magicalRanged"}
    dps_jobs = [j for j in CONFIG.jobs["jobs"] if j["role"] in dps_roles]
    assert dps_jobs, "未找到输出职业"
    max_dr: dict[str, float] = {}
    for job in dps_jobs:
        types = {e.get("type") for s in job["skills"] for e in s.get("effects") or []}
        assert types & {"damageReduction", "shield"}, job["id"]
        drs = [
            float(e.get("value", 0) or 0)
            for s in job["skills"]
            for e in s.get("effects") or []
            if e.get("type") == "damageReduction"
        ]
        assert drs, job["id"]
        for value in drs:
            assert 0 < value <= 0.30, (job["id"], value)
        max_dr[job["role"]] = max(max_dr.get(job["role"], 0.0), max(drs))
    # 最脆的远程法系补偿最多、近战最少，保留「输出越高越脆」的定位差异
    assert max_dr["magicalRanged"] >= max_dr["physicalRanged"] >= max_dr["melee"]


def test_all_jobs_have_signature() -> None:
    """每个职业恰好一个绝技，字段齐全、充能参数合理、id 不与现有技能重复。"""
    for job in CONFIG.jobs["jobs"]:
        sig = job["signature"]
        assert sig["id"] and sig["name"] and sig["desc"], job["id"]
        assert sig["id"] not in {s["id"] for s in job["skills"]}, (job["id"], sig["id"])
        assert float(sig["chargeSeconds"]) > 0, job["id"]
        assert float(sig["chargePerKill"]) >= 0, job["id"]
        assert sig["damageType"] in ("physical", "magical"), job["id"]
        assert sig["target"] in ("single", "aoe", "self"), job["id"]
        assert isinstance(sig["effects"], list), job["id"]


def test_signature_damage_type_matches_main_attr() -> None:
    """力量/敏捷职业的伤害型绝技必须是物理伤害（否则按智力结算、DPS 差数倍）。"""
    for job in CONFIG.jobs["jobs"]:
        sig = job["signature"]
        if job["mainAttr"] == "int" or int(sig.get("potency", 0)) <= 0:
            continue
        assert sig["damageType"] != "magical", (job["id"], sig["id"])


def test_signature_charge_is_reasonable() -> None:
    """绝技充能时间落在合理区间（60~180s），避免过短失衡 / 过长形同虚设。"""
    for job in CONFIG.jobs["jobs"]:
        charge = float(job["signature"]["chargeSeconds"])
        assert 60 <= charge <= 180, (job["id"], charge)


def test_weapon_types_cover_jobs() -> None:
    weapon_types = {j["weaponType"] for j in CONFIG.jobs["jobs"]}
    base_weapon_types = {b.weapon_type for b in CONFIG.base_items if b.category == "weapon"}
    assert weapon_types == base_weapon_types


def test_healer_heal_skill_costs_are_raised() -> None:
    """治疗职业的治疗 / 护盾技能：耗蓝与 CD 已提高，且另按最大魔力比例计费（见 heroes.json:mp）。"""
    heal_types = {"heal", "healOverTime", "fullHeal", "healingBuff", "shield"}
    assert 0 < float(CONFIG.heroes["mp"]["healSkillCostMaxMpPct"]) < 1
    for job in CONFIG.jobs["jobs"]:
        if job["role"] != "healer":
            continue
        for skill in job["skills"]:
            if not any(e.get("type") in heal_types for e in skill.get("effects") or []):
                continue
            assert skill["mpCost"] >= 40, (job["id"], skill["id"], skill["mpCost"])
            assert skill["cd"] >= 30, (job["id"], skill["id"], skill["cd"])


def test_mp_regen_sources_are_bounded() -> None:
    """回蓝来源已收敛，避免「无限回蓝 → 无限回血 → 永不死亡」。"""
    proc = CONFIG.combat["proc"]["mpRegenBuff"]
    assert float(proc["maxMpPctPerSec"]) <= 0.015
    caps = {
        "spiritOnHit": 12,
        "resolveOnHit": 12,
        "desperateMp": 20,
        "hpToMp": 10,
        "killRestoreMp": 10,
    }
    ranges = {t["id"]: t["range"] for t in CONFIG.terms["terms"]}
    for tid, cap in caps.items():
        assert ranges[tid][1] <= cap, (tid, ranges[tid], cap)


def test_base_items_expanded() -> None:
    """底材 = 族 × 档位 × 变体(minTier ≤ 档位)，且 id 唯一；武器只展开「基础型 + 自身职能词缀」。"""
    raw = CONFIG.raw["baseItems"]
    tiers = raw["tiers"]
    variants = raw.get("variants", {})
    affixes = raw.get("jobAffixes", {})

    def per_family(specs) -> int:
        return sum(sum(1 for v in specs if v["minTier"] <= t["index"]) for t in tiers)

    weapon_expected = sum(
        per_family(
            [
                v
                for v in variants["weapon"]
                if not v.get("id") or v["id"] == affixes.get(fam["jobId"], "")
            ]
        )
        for fam in raw["weaponFamilies"]
    )
    expected = (
        weapon_expected
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


def test_job_affixes_cover_all_jobs() -> None:
    """jobAffixes 覆盖全部战斗职业，且取值都是武器侧登记的职能变体 id。"""
    raw = CONFIG.raw["baseItems"]
    affixes = raw["jobAffixes"]
    assert set(affixes) == {j["id"] for j in CONFIG.jobs["jobs"]}
    weapon_affix_ids = {v["id"] for v in raw["variants"]["weapon"] if v["id"]}
    assert set(affixes.values()) == weapon_affix_ids


def test_weapon_uses_only_its_own_affix() -> None:
    """每种武器每档只出现「基础型 + 自身职业职能」两个变体（不再有跨职能变体）。"""
    raw = CONFIG.raw["baseItems"]
    affixes = raw["jobAffixes"]
    for fam in raw["weaponFamilies"]:
        want = affixes[fam["jobId"]]
        variant_ids = {
            b.variant_id for b in CONFIG.base_items if b.weapon_type == fam["weaponType"]
        }
        assert variant_ids == {"", want}, (fam["weaponType"], variant_ids)


def test_role_affix_pools_are_role_locked() -> None:
    """职能词缀只 roll 本职可用主属性：力量系（御敌/强袭/制敌）不出敏捷·智力，
    敏捷系（游击/精准）不出力量·智力，智力系（咏咒/治愈）不出力量·敏捷；基础型不设限。"""
    str_affixes = {"tank", "str", "det", "vit"}
    dex_affixes = {"dex", "crit", "gold"}
    int_affixes = {"int", "bal"}
    for item in CONFIG.base_items:
        if not item.variant_id:
            continue
        pool = set(item.sub_attr_pool)
        if item.variant_id in str_affixes:
            assert "str" in pool and not (pool & {"dex", "int"}), (item.id, pool)
        elif item.variant_id in dex_affixes:
            assert "dex" in pool and not (pool & {"str", "int"}), (item.id, pool)
        elif item.variant_id in int_affixes:
            assert "int" in pool and not (pool & {"str", "dex"}), (item.id, pool)
        else:
            raise AssertionError(f"未登记的职能变体 {item.variant_id}（{item.id}）")


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


def test_exp_terms_excluded_at_max_level() -> None:
    """所有经验类词条都设置 maxItemLevel=99：100 级装备不再出现经验加成。"""
    for term_id in ("expGain", "expDrain"):
        assert int(CONFIG.term_by_id[term_id]["maxItemLevel"]) == 99, term_id
    for term_id in ("dohInspiration", "dolKeenSense"):
        term = next(t for t in CONFIG.dohdol_equipment["terms"] if t["id"] == term_id)
        assert int(term["maxItemLevel"]) == 99, term_id


def test_consumable_tiers_keep_durations() -> None:
    """高等级药食只放大效果，单个物品的持续时长仍由 kind 决定（秘药 600s / 料理 1800s）。"""
    kinds = CONFIG.consumables["kinds"]
    assert int(kinds["potion"]["durationSec"]) == 600
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


def test_terms_have_categories() -> None:
    """每个词条（战斗 + 生产/采集）都带合法 category，且名表覆盖全部引用。"""
    combat_cats = {c["id"] for c in CONFIG.terms["categories"]}
    assert combat_cats, "战斗词条类别名表为空"
    for term in CONFIG.terms["terms"]:
        assert term.get("category") in combat_cats, term["id"]
    # 生产/采集类别名表同样覆盖该池全部词条
    prod_cats = {c["id"] for c in CONFIG.dohdol_equipment["termCategories"]}
    assert prod_cats, "生产/采集词条类别名表为空"
    for term in CONFIG.dohdol_equipment["terms"]:
        assert term.get("category") in prod_cats, term["id"]


def test_risk_terms_declare_cost() -> None:
    """风险代价类词条必须声明 cost（stat 在 combat.json 中可消费），desc 含 {c} 占位符。"""
    for term in CONFIG.terms["terms"]:
        if term.get("category") != "risk":
            continue
        cost = term.get("cost")
        assert cost and cost.get("stat") and float(cost["ratio"]) != 0, term["id"]
        assert "{c}" in term["desc"], term["id"]


def test_power_weights_cover_new_term_stats() -> None:
    """影响评分/战力的新增词条 stat 均登记了 power.weights（未登记即 0 权重）。"""
    weights = CONFIG.economy["power"]["weights"]
    new_stats = {
        "magicAttackPct", "physDefPct", "magicDefPct", "maxMpPct", "healPowerPct",
        "guardPct", "blockProcPct", "shieldBoostPct", "doubleAttackPct", "bleedProcPct",
        "magicShieldProcPct", "lifestealShieldPct",
        "defBreakProcPct", "slowProcPct", "stunProcPct", "reflectProcPct", "vengeanceProcPct",
        "aegisProcPct", "resolveProcPct", "lowHpAttackPct", "openingDamagePct", "bossDamagePct",
        "lowMpRegenPct", "killStackAttackPct", "hitStackSpeedPct", "skillStackDamagePct",
        "hpToMpPct", "mpSurgeDamagePct", "killRestoreMpPct", "vitToAttackPct", "critToDetPct",
        "berserkPct", "glassCannonPct", "recklessPct", "reviveChancePct", "executePct",
        "cheatDeathPct", "chargeBlastPct", "chargeShieldPct", "chargeHealPct",
    }
    missing = sorted(new_stats - set(weights))
    assert not missing, f"缺少权重：{missing}"


def test_exclusive_items_expanded_and_isolated() -> None:
    """绝境龙神系列：39 件（21 武器 + 10 防具 + 8 饰品），固定 100 级、id 唯一，
    且不进 base_items（抽箱 / 合成 / 生产候选池天然排除）。"""
    items = CONFIG.exclusive_items
    assert len(items) == 39
    assert len({b.id for b in items}) == 39
    assert sum(b.category == "weapon" for b in items) == 21
    assert sum(b.category == "armor" for b in items) == 10
    assert sum(b.category == "accessory" for b in items) == 8
    for item in items:
        assert item.exclusive is True, item.id
        assert item.level_req == 100, item.id
        assert item.base_attrs and item.sub_attr_pool, item.id
        for entry in item.base_attrs:
            assert entry["base"] > 0, item.id
    # 与普通底材互不重合，且不在 base_items 池中
    normal_ids = {b.id for b in CONFIG.base_items}
    assert normal_ids.isdisjoint({b.id for b in items})
    assert all(b.exclusive is False for b in CONFIG.base_items)
    # base_item_by_id 合并了两者（供属性 / 序列化 / 图鉴使用）
    assert set(CONFIG.base_item_by_id) == normal_ids | {b.id for b in items}


def test_exclusive_items_stronger_than_same_level_gear() -> None:
    """绝境龙神的主属性与副属性缩放均高于同等级（终末档）普通底材。"""
    normal_100 = next(b for b in CONFIG.base_items if b.id == "w_sword_shield_8")
    exclusive = next(b for b in CONFIG.exclusive_items if b.id == "w_sword_shield_9")
    normal_main = float(normal_100.base_attrs[0]["base"])
    exclusive_main = float(exclusive.base_attrs[0]["base"])
    assert exclusive_main > normal_main
    assert exclusive.sub_attr_scale > normal_100.sub_attr_scale


def test_world_boss_config() -> None:
    """世界BOSS 数值：24 亿血量、攻击 20000、5h 讨伐周期、周期内短休整、≥20 技能、8 席、80 级门槛。"""
    wb = CONFIG.worldboss
    boss = wb["boss"]
    assert int(wb["periodSeconds"]) == 5 * 3600, "讨伐周期沿用 5h 锚点"
    assert int(boss["maxHp"]) == 2_400_000_000
    assert int(boss["attack"]) == 20000
    assert 0 < int(boss["respawnSeconds"]) <= 300, "周期内击杀后应是短暂休整，而非 5h CD"
    pool = boss["skillPool"]
    assert len(pool) >= 20
    assert len({s["id"] for s in pool}) == len(pool), "BOSS 技能 id 必须唯一"
    for skill in pool:
        assert skill["effect"] in ("nuke", "aoe", "dot", "debuff", "charge", "enrage", "shield"), skill["id"]
        assert skill["desc"]
    rules = wb["rules"]
    assert int(rules["heroSlots"]) == 8
    assert int(rules["levelRequirement"]) == 80
    assert int(rules["fullPowerLevel"]) == 100
    assert 0 < float(rules["weaknessFloor"]) < 1
    reward = wb["reward"]
    assert int(reward["minDamage"]) == 5_000_000
    tiers = reward["tiers"]
    assert [int(t["minDamage"]) for t in tiers] == sorted(int(t["minDamage"]) for t in tiers), "档位必须升序"
    assert int(tiers[0]["minDamage"]) == 5_000_000, "首档 = 保底门槛"
    assert [int(t["items"]) for t in tiers] == sorted(int(t["items"]) for t in tiers), "档位件数应随伤害递增"
    assert int(reward["rankBonus"]["1"]) == 10, "第 1 名名次加成"
    # 强者第 1 名打满顶档 = 顶档件数 + 名次加成 = 20（与原上限一致）
    assert int(tiers[-1]["items"]) + int(reward["rankBonus"]["1"]) == 20


def test_world_boss_phases_escalate() -> None:
    """P1→P2→P3 随血量下降：minHpRatio 递减、防御与技能威力单调递增，且覆盖到 0。"""
    table = CONFIG.worldboss["phases"]
    assert [p["id"] for p in table] == [1, 2, 3]
    ratios = [float(p["minHpRatio"]) for p in table]
    assert ratios == sorted(ratios, reverse=True)
    assert ratios[-1] == 0.0, "最低阶段必须覆盖到 0 血量"
    defense = [float(p["defenseMultiplier"]) for p in table]
    potency = [float(p["skillPotencyMultiplier"]) for p in table]
    assert defense == sorted(defense) and defense[0] == 1.0 and defense[-1] > defense[0]
    assert potency == sorted(potency) and potency[0] == 1.0 and potency[-1] > potency[0]


def test_battle_difficulty_config() -> None:
    """难度配置：最高 15；怪物按加法（1 + 单级加成×N）、玩家按乘法（0.85^N / 0.9^N）。"""
    cfg = CONFIG.combat["difficulty"]
    assert int(cfg["maxLevel"]) == 15
    # 1 级加成符合需求：HP / 防御 / 经验 +100%、攻击 +50%、金币 +50%
    assert 1 + float(cfg["monsterHpBonusPerLevel"]) == pytest.approx(2.0)
    assert 1 + float(cfg["monsterDefenseBonusPerLevel"]) == pytest.approx(2.0)
    assert 1 + float(cfg["monsterExpBonusPerLevel"]) == pytest.approx(2.0)
    assert 1 + float(cfg["monsterAttackBonusPerLevel"]) == pytest.approx(1.5)
    assert 1 + float(cfg["monsterGoldBonusPerLevel"]) == pytest.approx(1.5)
    # 玩家攻击 / 防御为逐级相乘的系数
    assert float(cfg["playerAttackMultiplierPerLevel"]) == pytest.approx(0.85)
    assert float(cfg["playerDefenseMultiplierPerLevel"]) == pytest.approx(0.9)


def test_materia_config() -> None:
    """魔晶石：6 种 × 5 级 = 30 件；第 1 孔 100% → 第 5 孔 5%；5 合 1；名称沿用 FF14 国服译名。"""
    cfg = CONFIG.materia
    assert int(cfg["socketsPerSlot"]) == 5
    assert [float(v) for v in cfg["successChance"]] == [1.0, 0.6, 0.35, 0.15, 0.05]
    assert float(cfg["successChance"][0]) == 1.0
    assert float(cfg["successChance"][-1]) == 0.05
    assert int(cfg["mergeFrom"]) == 5
    assert len(cfg["types"]) == 6
    assert len(CONFIG.materia_by_id) == 6 * 5
    for mtype in cfg["types"]:
        assert mtype["stat"] in CONFIG.economy["power"]["weights"], "魔晶石属性必须计入战力权重"
        values = [CONFIG.materia_by_id[f"m_{mtype['id']}_{lv}"]["value"] for lv in range(1, 6)]
        assert values == sorted(values) and values[0] < values[-1]
    assert CONFIG.materia_by_id["m_crit_1"]["name"] == "武略魔晶石壹型"
    assert CONFIG.materia_by_id["m_str_3"]["name"] == "刚力魔晶石叁型"
    assert CONFIG.materia_by_id["m_dh_5"]["name"] == "神眼魔晶石伍型"


def test_farm_config() -> None:
    """种田：初始 2 片、最多 12 片、扩张越往后越贵；5 阶段 × 10min；金币/经验种子产出。"""
    cfg = CONFIG.farm
    assert int(cfg["initialPlots"]) == 2
    assert int(cfg["maxPlots"]) == 12
    costs = [int(c) for c in cfg["expansionCosts"]]
    assert len(costs) == int(cfg["maxPlots"]) - int(cfg["initialPlots"])
    assert costs == sorted(costs) and costs[0] < costs[-1]
    assert int(cfg["stages"]) == 5
    assert int(cfg["stageSeconds"]) == 600
    seeds = {s["id"]: s for s in cfg["seeds"]}
    assert seeds["seed_gold"]["yield"] == {"type": "gold", "amount": 10_000_000}
    assert seeds["seed_exp"]["yield"] == {"type": "heroLevel", "levels": 1}
    # 种子不可出售，避免「种田 → 卖种子」套利
    assert all(int(s["sell"]) == 0 for s in cfg["seeds"])


def test_hero_roster_config() -> None:
    """远征队（英雄名册）容量：基准 8 席、上限 20 席；扩充价格线性递增（首价 2500W、每席 +2500W）。"""
    cfg = CONFIG.heroes["roster"]
    base, top = int(cfg["baseCapacity"]), int(cfg["maxCapacity"])
    assert base == 8 and top == 20
    first, step = int(cfg["firstExpandCost"]), int(cfg["expandCostStep"])
    assert first == 25_000_000 and step == 25_000_000
    costs = [first + i * step for i in range(top - base)]
    assert costs == sorted(costs) and costs[0] == 25_000_000 and costs[0] < costs[-1]


def test_treasure_config() -> None:
    """挖宝：100W 入场、5 层、门 50%、每层 = 难度(层-1) 的地区 40 BOSS、通关五层 +1000W。"""
    cfg = CONFIG.treasure
    assert int(cfg["entryCost"]) == 1_000_000
    assert int(cfg["floors"]) == 5
    assert int(cfg["doors"]) == 2
    assert float(cfg["correctChance"]) == pytest.approx(0.5)
    assert int(cfg["sourceRegionId"]) == 40
    assert int(cfg["finalBonusGold"]) == 10_000_000
    assert float(cfg["specialEventChance"]) == pytest.approx(0.05)
    assert int(cfg["maxGuesses"]) == 5
    # 秘药档位：1-2 层 I、3-4 层 II、5 层 III
    assert [int(t) for t in cfg["potionTierByFloor"]] == [1, 1, 2, 2, 3]
    # 魔晶石等级随层上涨
    ranges = cfg["materiaLevelByFloor"]
    assert len(ranges) == int(cfg["floors"])
    assert [int(r[0]) for r in ranges] == sorted(int(r[0]) for r in ranges)
    # 概率序：魔晶石 >> 金币 = 经验 > 秘药 > 种子
    weights = cfg["rewardWeights"]
    assert weights["materia"] > weights["gold"] == weights["exp"] > weights["potion"] > weights["seed"]


def test_treasure_is_not_a_gold_printer() -> None:
    """防刷：即使假设玩家每层必定击败 BOSS，单次挖宝的期望金币也必须低于入场成本。

    只有「击败 5 层地区 40 关底 BOSS + 连过 4 扇 50/50 的门」才可能接近收益上限，
    因此挖宝不构成任何形式的「不打怪只刷金币」路线。

    注意挖宝金币**不吃难度加成**（`combat.json:difficulty.monsterGoldBonusPerLevel` 只作用于
    地区战斗；挖宝只借难度放大怪物数值与经验），因此这里不乘难度金币系数——否则提高难度
    金币加成会直接把挖宝顶成印钞路线。
    """
    cfg = CONFIG.treasure
    region = CONFIG.region_by_id[int(cfg["sourceRegionId"])]
    gold_base = float(region["baseGold"]) * float(CONFIG.regions["goldMultipliers"]["boss"])
    weights = cfg["rewardWeights"]
    p_gold = float(weights["gold"]) / sum(float(w) for w in weights.values())

    expected = 0.0
    reach = 1.0
    for floor in range(1, int(cfg["floors"]) + 1):
        gold_unit = gold_base * float(cfg["goldMultiplier"])
        entries = int(cfg["rewardsPerFloor"]["base"]) + int(cfg["rewardsPerFloor"]["perFloor"]) * (floor - 1)
        expected += reach * entries * p_gold * gold_unit
        reach *= float(cfg["correctChance"])
    # 通关第 5 层（需连过 4 扇门）的额外金币
    expected += float(cfg["correctChance"]) ** (int(cfg["floors"]) - 1) * int(cfg["finalBonusGold"])

    assert expected < int(cfg["entryCost"]), f"期望金币 {expected:.0f} 已达入场成本"

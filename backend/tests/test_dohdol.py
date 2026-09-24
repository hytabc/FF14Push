"""生产 / 采集 DLC：共享数据一致性 + 接口集成测试。"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import ActiveConsumable, DohDolProgress, FishRecord, StackItem
from app.services import dohdol_util
from app.services.game_config import CONFIG
from app.services.item_factory import (
    craft_rarity_distribution,
    craft_rarity_luck,
    craft_xp_rarity_multiplier,
    generate_crafted_item,
)
from app.services.valuation import sell_price


def _luck(
    hero: int = 0,
    cleared: int = 0,
    prod: int = 0,
    gear: float = 0.0,
    consumable: float = 0.0,
    coop: float = 0.0,
    raid: float = 0.0,
) -> float:
    return craft_rarity_luck(
        {
            "heroLevel": hero,
            "clearedRegions": cleared,
            "prodLevel": prod,
            "gearPct": gear,
            "consumablePct": consumable,
            "coopClears": coop,
            "raidClears": raid,
        }
    )[0]


def _backdate(session, seconds: float) -> None:
    """把会话的 last_report_at 往回调，模拟「已经过了一段时间」。"""
    session.last_report_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)


def _special(region: dict, kind: str) -> dict:
    """取钓场里指定类别的特殊鱼（king / emperor / legend）。"""
    return next(s for s in region["specials"] if s["kind"] == kind)


class TestSharedData:
    def test_jobs(self):
        jobs = CONFIG.dohdol_jobs["jobs"]
        assert len(jobs) == 11
        doh = [j for j in jobs if j["kind"] == "doh"]
        dol = [j for j in jobs if j["kind"] == "dol"]
        assert len(doh) == 8
        assert len(dol) == 3
        assert {j["id"] for j in dol} == {"MIN", "BTN", "FSH"}

    def test_materials_and_gather_nodes(self):
        ids = [m["id"] for m in CONFIG.materials["materials"]]
        assert len(ids) == len(set(ids)), "材料 id 必须唯一"
        for node in CONFIG.gather_nodes["nodes"]:
            assert node["regionId"] in CONFIG.region_by_id
            assert CONFIG.dohdol_job_by_id[node["jobId"]]["kind"] == "dol"
            for y in node["yields"]:
                assert y["materialId"] in CONFIG.material_by_id
                assert y["min"] <= y["max"]

    def test_region_material_variety(self):
        """每个地区至少 2 件专属材料，且专属材料跨地区不重复；每地区可采 ≥3 种。"""
        uniques = [m for m in CONFIG.materials["materials"] if m.get("regionId")]
        names = [m["name"] for m in uniques]
        assert len(names) == len(set(names)), "地区专属材料名称不应重复"
        assert len(uniques) == len(CONFIG.region_by_id) * 2

        per_region: dict[int, set[str]] = {}
        for node in CONFIG.gather_nodes["nodes"]:
            bucket = per_region.setdefault(node["regionId"], set())
            for y in node["yields"]:
                bucket.add(y["materialId"])
        for region_id, bucket in per_region.items():
            assert len(bucket) >= 3, f"地区 {region_id} 可采材料不足 3 种"

    def test_recipe_outputs_have_names(self):
        """配方产物名必须解析为中文名，不能回落成 id（如 f_expGainPct）。"""
        for r in CONFIG.recipes["recipes"]:
            out = r["output"]
            key = out.get("itemId") or out.get("baseId")
            assert dohdol_util.material_name(key) != key, f"配方 {r['id']} 产物名未解析：{key}"

    def test_recipes_reference_valid(self):
        for r in CONFIG.recipes["recipes"]:
            assert CONFIG.dohdol_job_by_id[r["jobId"]]["kind"] == "doh"
            assert r["requiredLevel"] >= 1
            for inp in r["inputs"]:
                assert inp["itemId"] in CONFIG.material_by_id
            out = r["output"]
            if out["kind"] == "equipment":
                assert out["baseId"] in CONFIG.base_item_by_id or out["baseId"] in CONFIG.dohdol_item_by_id
            elif out["kind"] == "consumable":
                assert out["itemId"] in CONFIG.consumable_by_id
            else:
                assert out["itemId"] in CONFIG.material_by_id

    def test_all_region_materials_are_used(self):
        """每个地区的专属材料（oreN / floraN）都必须被至少一个配方消耗。"""
        region_mats = {m["id"] for m in CONFIG.materials["materials"] if m.get("regionId")}
        used = {i["itemId"] for r in CONFIG.recipes["recipes"] for i in r["inputs"]}
        missing = sorted(region_mats - used)
        assert not missing, f"未被任何配方使用的地区材料：{missing}"

    def test_background_window_is_not_truncated(self):
        """页面在后台较长时间后上报：窗口按真实时长结算，不再被旧的 30 秒上限截断。"""
        now = datetime.now(timezone.utc)
        assert dohdol_util.window_seconds(now - timedelta(seconds=120), now) == 120.0
        # 上限仍存在，避免超长时间间隔（或时钟跳变）一次性换取过多产出
        assert dohdol_util.window_seconds(now - timedelta(days=1), now) == dohdol_util.MAX_WINDOW_SECONDS
        assert dohdol_util.MAX_WINDOW_SECONDS >= 120

    def test_dohdol_equipment(self):
        ids = [i["id"] for i in CONFIG.dohdol_equipment["items"]]
        assert len(ids) == len(set(ids))
        for item in CONFIG.dohdol_equipment["items"]:
            assert item["bonus"], "专用装备必须有加成"
            assert item["category"] in {c["id"] for c in CONFIG.dohdol_equipment["categories"]}

    def test_fish(self):
        assert len(CONFIG.fish["regions"]) == 40
        king_names: list[str] = []
        emperor_names: list[str] = []
        for region in CONFIG.fish["regions"]:
            assert region["normal"], "钓场必须有普通鱼"
            for f in region["normal"]:
                assert f["rarity"] in ("white", "blue", "purple")
                assert int(f["sizeMin"]) <= int(f["sizeMax"])
            specials = region["specials"]
            assert specials, "钓场必须有特殊鱼"
            for s in specials:
                assert s["kind"] in ("king", "emperor", "legend")
                assert float(s["intuition"]["chance"]) > 0
                assert s["intuition"]["requires"], "特殊鱼必须声明计数型前置"
                for req in s["intuition"]["requires"]:
                    assert req["fishId"] in CONFIG.fish_by_id, req["fishId"]
                    assert int(req["count"]) >= 1
            king = _special(region, "king")
            emperor = _special(region, "emperor")
            # 旧称号只统计 legacy：每地区恰有一条 legacy 鱼王 / 鱼皇
            assert king["legacy"] is True and emperor["legacy"] is True
            assert emperor["intuition"]["chance"] < king["intuition"]["chance"], "鱼皇概率必须低于鱼王"
            assert int(region["levelReq"]) >= 1
            assert int(region["levelReq"]) == int(
                CONFIG.gather_node_by[(region["regionId"], "MIN")]["levelReq"]
            ), f"地区 {region['regionId']} 钓场门槛与采集点不一致"
            king_names.append(king["name"])
            emperor_names.append(emperor["name"])
        assert int(CONFIG.fish_region_by_id[1]["levelReq"]) == 1
        assert int(CONFIG.fish_region_by_id[40]["levelReq"]) == 100
        # 每地区各一条鱼王 / 鱼皇，名称互不重复
        assert len(set(king_names)) == 40
        assert len(set(emperor_names)) == 40
        # 鱼名参考 FF14，不应再是「地区名+鱼王」这种拼出来的名字
        for region in CONFIG.fish["regions"]:
            assert not _special(region, "king")["name"].startswith(region["name"])
            assert not _special(region, "emperor")["name"].startswith(region["name"])

    def test_fish_weather_gates_are_reachable(self):
        """每条鱼声明的天气门槛必须落在该钓场天气表内，否则永远钓不到。"""
        weather_keys = {int(r["regionId"]): set(r["weights"]) for r in CONFIG.weather["regions"]}
        windows = set(CONFIG.weather["timeOfDay"])
        for region in CONFIG.fish["regions"]:
            rid = int(region["regionId"])
            assert rid in weather_keys, f"地区 {rid} 缺少天气权重表"
            for fish in [*region["normal"], *region["specials"]]:
                for w in fish.get("weather", []) or []:
                    assert w in weather_keys[rid], f"{fish['id']} 的天气 {w} 不可达"
                for tod in fish.get("timeOfDay", []) or []:
                    assert tod in windows, f"{fish['id']} 的时段 {tod} 未定义"

    def test_fish_has_difficult_legends(self):
        """困难鱼（legend）存在，且包含七彩天主的多前置链。"""
        legends = [
            s for region in CONFIG.fish["regions"] for s in region["specials"] if s["kind"] == "legend"
        ]
        assert len(legends) >= 10, "应包含一批 FF14 闻名的困难鱼"
        names = {s["name"] for s in legends}
        assert {"镜中蝶", "七彩天主"} <= names
        hue_lord = next(s for s in legends if s["name"] == "七彩天主")
        assert sum(int(r["count"]) for r in hue_lord["intuition"]["requires"]) == 11
        assert hue_lord.get("weather"), "七彩天主需要特定天气窗口"

    def test_consumables_and_titles(self):
        kinds = {c["kind"] for c in CONFIG.consumables["items"]}
        assert kinds == {"potion", "food"}
        for c in CONFIG.consumables["items"]:
            assert c["effects"]
        titles = {t["id"]: t for t in CONFIG.titles["titles"]}
        # 旧称号原样保留（本次更新不影响已有称号）
        assert titles["fish_king_all"]["name"] == "鱼王猎手"
        assert titles["fish_king_all"]["condition"] == {"type": "all_king"}
        assert titles["fish_emperor_all"]["name"] == "海皇"
        assert titles["fish_emperor_all"]["condition"] == {"type": "all_emperor"}
        # 新增 FF14 钓鱼称号
        assert titles["fish_grand_all"]["name"] == "烟波钓徒"
        assert len(titles) > 2

    def test_craft_xp_rarity_multiplier(self):
        """制造经验系数：覆盖全部品阶，最低品阶为 1.0，且随品阶单调递增。"""
        table = CONFIG.recipes["equipment"]["xpRarityMultiplier"]
        assert set(table) == set(CONFIG.rarity_order)
        values = [float(table[r]) for r in CONFIG.rarity_order]
        assert values[0] == pytest.approx(1.0)
        assert values == sorted(values) and values[-1] > values[0]

    def test_level_curve_fits_pacing_budget(self):
        """1→100 的总经验控制在上限内，保证生产等级可在约 10 小时内练满。

        配合配方经验上调与「品阶经验系数」。若曲线回退到 1.07（总经验 ≈ 92.6 万）本断言会失败。
        """
        total = sum(dohdol_util.exp_to_next(l) for l in range(1, dohdol_util.level_cap()))
        assert total < 200_000, f"1→100 总经验 {total} 偏高，超出约 10h 的练满预算"

    def test_total_exp_tracks_raw_award(self):
        """累计经验按原始经验累加，与当前等级内经验相互独立。"""
        progress = SimpleNamespace(level=1, exp=0, total_exp=0)
        info = dohdol_util.apply_level_exp(progress, 50)
        assert info["levelsGained"] == 0
        assert progress.exp == 50
        assert progress.total_exp == 50

    def test_total_exp_accumulates_past_level_cap(self):
        """满级后不再升级、当前等级经验清零，但累计经验继续增长。"""
        progress = SimpleNamespace(level=dohdol_util.level_cap(), exp=0, total_exp=0)
        dohdol_util.apply_level_exp(progress, 500)
        assert progress.level == dohdol_util.level_cap()
        assert progress.exp == 0, "满级后当前等级经验清零"
        assert progress.total_exp == 500, "满级后累计经验仍继续累加"
        dohdol_util.apply_level_exp(progress, 300)
        assert progress.total_exp == 800


class TestCraftedItem:
    def test_high_quality_combat_equipment(self):
        rng = random.Random(1234)
        item = generate_crafted_item("w_bow_2", rng)
        assert item["highQuality"] is True
        ancients = [t for t in item["terms"] if t.get("quality") == "ancient"]
        assert ancients, "制造装备必带太古词条"

    def test_dohdol_equipment_bonus(self):
        rng = random.Random(99)
        item = generate_crafted_item("dh_dohTool_0", rng)
        assert item["highQuality"] is True
        assert item["category"] == "doh_tool"
        assert item["baseAttrs"]


class TestCraftRarityScaling:
    """制造品阶概率抽奖化：单调提升、神话硬上限 20%、全部来源满 = 20%。"""

    def _scaling(self):
        return CONFIG.recipes["equipment"]["rarityScaling"]

    def test_zero_progress_equals_base_weights(self):
        base = CONFIG.recipes["equipment"]["rarityWeights"]
        dist = craft_rarity_distribution(0.0)
        for rarity in CONFIG.rarity_order:
            assert abs(dist[rarity] - base[rarity]) < 1e-9, rarity

    def test_full_progress_reaches_mythic_cap(self):
        """所有来源全部取满（含新来源）才 t=1 → 神话 = 硬上限。"""
        refs = self._scaling()["sources"]
        values = {key: float(spec["ref"]) for key, spec in refs.items()}
        luck = craft_rarity_luck(values)[0]
        assert luck == pytest.approx(1.0)
        assert craft_rarity_distribution(luck)["mythic"] == pytest.approx(0.2)

    def test_single_source_cannot_reach_cap(self):
        """权重合计 = 1 且每项 < 1，故任一来源单独拉满都不足以到顶。"""
        refs = self._scaling()["sources"]
        assert sum(float(spec["weight"]) for spec in refs.values()) == pytest.approx(1.0)
        for key, spec in refs.items():
            luck = craft_rarity_luck({key: float(spec["ref"])})[0]
            assert luck < 1.0, key
            assert craft_rarity_distribution(luck)["mythic"] < 0.2, key

    def test_mythic_never_exceeds_cap(self):
        cap = float(self._scaling()["mythicCap"])
        assert cap == pytest.approx(0.2)
        for t in (0.0, 0.25, 0.5, 0.75, 1.0, 2.0):
            dist = craft_rarity_distribution(t)
            assert dist["mythic"] <= cap + 1e-9
            assert abs(sum(dist.values()) - 1.0) < 1e-9

    def test_each_source_increases_mythic_and_lowers_common(self):
        refs = self._scaling()["sources"]
        base = craft_rarity_distribution(_luck())
        for key, spec in refs.items():
            luck = craft_rarity_luck({key: float(spec["ref"])})[0]
            dist = craft_rarity_distribution(luck)
            assert dist["mythic"] > base["mythic"], key
            assert dist["common"] < base["common"], key

    def test_luck_factors_expose_normalized_inputs(self):
        refs = self._scaling()["sources"]
        _, factors = craft_rarity_luck(
            {
                "heroLevel": 50,
                "clearedRegions": 20,
                "prodLevel": 25,
                "gearPct": 30.0,
                "consumablePct": 10.0,
                "coopClears": 12.0,
                "raidClears": 4.0,
            }
        )
        assert {f["key"] for f in factors} == set(refs)
        for factor in factors:
            assert 0.0 <= factor["norm"] <= 1.0
            assert factor["weight"] > 0


class TestDedicatedTerms:
    """专用装备 Buff/Debuff 词条系统。"""

    def _dedicated_term_ids(self):
        return {t["id"] for t in CONFIG.dohdol_equipment["terms"]}

    def test_term_pool_is_valid(self):
        slots = {s["id"] for s in CONFIG.dohdol_equipment["slots"]}
        bonus_names = CONFIG.dohdol_equipment["bonusNames"]
        terms = CONFIG.dohdol_equipment["terms"]
        assert terms, "专用装备词条池不能为空"
        assert len({t["id"] for t in terms}) == len(terms)
        for term in terms:
            assert term["type"] in ("buff", "debuff")
            assert term["stat"] in bonus_names, term["stat"]
            assert term["slots"] and set(term["slots"]) <= slots, term["id"]
            low, high = term["range"]
            if term["type"] == "buff":
                assert low > 0 and high > 0, term["id"]
            else:
                assert low < 0 and high < 0, term["id"]

    def test_pool_does_not_overlap_combat_terms(self):
        combat = {t["id"] for t in CONFIG.terms["terms"]}
        assert combat.isdisjoint(self._dedicated_term_ids())

    def test_crafted_dedicated_item_gets_terms(self):
        item = generate_crafted_item("dh_dohTool_2", random.Random(5), 0.0, 0.5)
        assert item["terms"], "专用装备应带 Buff/Debuff 词条"
        assert any(t["type"] == "buff" and t["quality"] == "ancient" for t in item["terms"])
        for term in item["terms"]:
            assert term["id"] in self._dedicated_term_ids()

    def test_combat_equipment_never_gets_dedicated_terms(self):
        dedicated = self._dedicated_term_ids()
        for seed in range(20):
            item = generate_crafted_item("w_bow_2", random.Random(seed))
            for term in item["terms"]:
                assert term["id"] not in dedicated

    def test_equipped_bonus_includes_terms(self):
        class _FakeItem:
            def __init__(self):
                self.base_id = "dh_dohTool_0"
                self.equipped_slot = "dohTool"
                self.terms = [{"type": "buff", "stat": "craftRarityPct", "value": 7.5}]

        bonus = dohdol_util.equipped_bonus([_FakeItem()])
        # 固定加成 craftRarityPct 3.0 + 词条 7.5
        assert bonus["craftRarityPct"] == pytest.approx(10.5)
        assert bonus["craftQualityPct"] == pytest.approx(4.0)


class TestCraftEconomy:
    """制造装备出售不得成为比打怪更快的金币来源（防刷）。"""

    def test_craft_sell_never_outearns_endgame_combat(self):
        # 终局战斗金币下限：地区 40 普通怪 × 金币浮动下限 ÷ 保守击杀耗时（8s，实际更快）。
        region40 = CONFIG.region_by_id[40]
        gold_floor = (
            float(region40["baseGold"])
            * float(CONFIG.regions["goldMultipliers"]["normal"])
            * (1.0 - float(CONFIG.regions["goldFloat"]))
        )
        combat_gold_per_sec = gold_floor / 8.0

        rng = random.Random(2024)
        worst_rate = 0.0
        worst_id = ""
        samples = 120
        for recipe in CONFIG.recipes["recipes"]:
            output = recipe["output"]
            if output["kind"] != "equipment":
                continue
            if output["baseId"] not in CONFIG.base_item_by_id:
                continue  # 专用装备
            material_sell = sum(
                int((CONFIG.material_by_id.get(e["itemId"]) or {}).get("sell", 0)) * int(e["count"])
                for e in recipe["inputs"]
            )
            total = 0.0
            for _ in range(samples):
                gen = generate_crafted_item(output["baseId"], rng, 0.0, 1.0)
                item = SimpleNamespace(
                    rarity=gen["rarity"],
                    base_attrs=gen["baseAttrs"],
                    sub_attrs=gen["subAttrs"],
                    terms=gen["terms"],
                )
                total += sell_price(item)
            rate = (total / samples - material_sell) / float(recipe["craftSeconds"])
            if rate > worst_rate:
                worst_rate, worst_id = rate, output["baseId"]

        assert worst_rate < combat_gold_per_sec, (
            f"{worst_id} 制造出售 {worst_rate:.0f} 金币/秒，不应超过终局战斗下限 {combat_gold_per_sec:.0f} 金币/秒"
        )


class TestDohdolSellBalance:
    """采集素材 / 渔获 / 半成品出售价：越高档涨幅越大，但非战斗收入不得反超同档战斗。"""

    BANDS = (1, 9, 17, 23, 29, 35)
    # 第 1 档是教程区：起始武器约 11 秒/杀，战斗保守下限仅约 1.3 金币/秒，
    # 本就低于采集产出（改动前既有的例外），故不纳入断言。
    CHECKED_BANDS = BANDS[1:]

    def _combat_gold_floor_per_sec(self, region_id: int) -> float:
        """同档战斗金币下限：baseGold × 普通倍率 × (1 − goldFloat) ÷ 保守击杀耗时 8s。"""
        region = CONFIG.region_by_id[region_id]
        gold_floor = (
            float(region["baseGold"])
            * float(CONFIG.regions["goldMultipliers"]["normal"])
            * (1.0 - float(CONFIG.regions["goldFloat"]))
        )
        return gold_floor / 8.0

    def _gather_gold_per_sec(self, region_id: int) -> float:
        """该地区采集的金币/秒：按节点权重与数量区间求材料期望产出，再除以单次动作耗时。"""
        node = CONFIG.gather_node_by[(region_id, "MIN")]
        total_weight = sum(int(y["weight"]) for y in node["yields"])
        expected = 0.0
        for y in node["yields"]:
            sell = int((CONFIG.material_by_id.get(y["materialId"]) or {}).get("sell", 0))
            avg_count = (int(y["min"]) + int(y["max"])) / 2.0
            expected += (int(y["weight"]) / total_weight) * sell * avg_count
        return expected / float(CONFIG.gather_nodes["baseSecondsPerAction"])

    def _region_mat_sell(self, band: int) -> int:
        return next(
            int(m["sell"]) for m in CONFIG.materials["materials"] if m.get("regionId") == band
        )

    def test_sell_tables_are_progressive(self):
        """档位内单价一致、跨档严格递增，且自第 2 档起每档涨幅 ≥ 1.5×。"""
        for band in self.BANDS:
            node = CONFIG.gather_node_by[(band, "MIN")]
            sells = {
                int((CONFIG.material_by_id.get(y["materialId"]) or {}).get("sell", 0))
                for y in node["yields"]
                if (CONFIG.material_by_id.get(y["materialId"]) or {}).get("regionId") == band
            }
            assert len(sells) == 1, f"档位 {band} 的专属材料单价不一致：{sells}"

        for label, pick in (
            ("采集素材", self._region_mat_sell),
            ("普通渔获", lambda b: int(CONFIG.fish_region_by_id[b]["normal"][0]["sell"])),
            ("鱼王", lambda b: int(_special(CONFIG.fish_region_by_id[b], "king")["sell"])),
            ("鱼皇", lambda b: int(_special(CONFIG.fish_region_by_id[b], "emperor")["sell"])),
        ):
            for prev, cur in zip(self.BANDS, self.BANDS[1:]):
                assert pick(cur) > pick(prev), f"{label} 档位 {cur} 未高于 {prev}：{pick(prev)} → {pick(cur)}"
                assert pick(cur) >= pick(prev) * 1.5, (
                    f"{label} 档位 {cur} 涨幅不足：{pick(prev)} → {pick(cur)}"
                )

    def test_non_combat_income_stays_well_below_combat(self):
        """采集与钓鱼的金币/秒须低于同档战斗下限的 30%，避免出现「不打怪只采集」的刷钱路线。"""
        cast_seconds = float(CONFIG.fish["castSeconds"])
        for band in self.CHECKED_BANDS:
            cap = self._combat_gold_floor_per_sec(band) * 0.3
            gather = self._gather_gold_per_sec(band)
            fish = int(CONFIG.fish_region_by_id[band]["normal"][0]["sell"]) / cast_seconds
            assert gather < cap, f"档位 {band} 采集 {gather:.1f} 金币/秒，超过战斗下限的 30%（{cap:.1f}）"
            assert fish < cap, f"档位 {band} 渔获 {fish:.1f} 金币/秒，超过战斗下限的 30%（{cap:.1f}）"

    # 鱼王/鱼皇出现概率已整体 ×2（见 scripts/gen-fish-data.py:KING_EMPEROR_CHANCE_MULT），
    # 「鱼识常驻」最坏情形的期望收益上限随之放宽为战斗下限的 2 倍。
    RARE_FISH_WORST_CASE_MULT = 2.0

    def test_fishing_income_including_rare_fish_stays_below_combat(self):
        """把鱼王/鱼皇的期望收益也计入（鱼识常驻的最坏情形），避免调价后出现「只钓鱼卖鱼」的刷钱路线。

        该模型假设鱼识全程常驻、每次抛竿都按满概率判定鱼王/鱼皇，现实中不可达（需钓齐计数型前置，
        且 BUFF 不刷新、现已统一为 30s）；概率 ×2 后上限同步放宽为战斗下限的 2 倍。
        """
        cast_seconds = float(CONFIG.fish["castSeconds"])
        for band in self.CHECKED_BANDS:
            region = CONFIG.fish_region_by_id[band]
            king = _special(region, "king")
            emperor = _special(region, "emperor")
            king_p = float(king["intuition"]["chance"])
            emperor_p = (1.0 - king_p) * float(emperor["intuition"]["chance"])
            per_cast = (
                int(region["normal"][0]["sell"])
                + king_p * int(king["sell"])
                + emperor_p * int(emperor["sell"])
            )
            total = per_cast / cast_seconds
            cap = self._combat_gold_floor_per_sec(band) * self.RARE_FISH_WORST_CASE_MULT
            assert total < cap, (
                f"档位 {band} 钓鱼（含鱼王/鱼皇）{total:.1f} 金币/秒，不应超过战斗下限的 "
                f"{self.RARE_FISH_WORST_CASE_MULT:.0f} 倍（{cap:.1f}）"
            )

    def test_half_good_conversion_is_bounded(self):
        """半成品配方：产出卖价不得超过输入卖价的 6 倍，避免「采集 → 加工 → 出售」变成印钞机。"""
        for recipe in CONFIG.recipes["recipes"]:
            output = recipe["output"]
            if output["kind"] != "material":
                continue
            produced = int((CONFIG.material_by_id.get(output["itemId"]) or {}).get("sell", 0)) * int(
                output.get("count", 1)
            )
            consumed = sum(
                int((CONFIG.material_by_id.get(e["itemId"]) or {}).get("sell", 0)) * int(e["count"])
                for e in recipe["inputs"]
            )
            assert consumed > 0, f"{recipe['id']} 输入无出售价值"
            assert produced <= consumed * 6, f"{recipe['id']} 产出 {produced} 超过输入 {consumed} 的 6 倍"


class TestGatherApi:
    @pytest.mark.asyncio
    async def test_gather_flow(self, auth_client, session_factory):
        resp = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "MIN", "regionId": 1})
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 20)
            await db.commit()

        rep = await auth_client.post("/api/v1/gather/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        data = rep.json()
        assert data["actions"] > 0
        assert data["gained"], "应有采集产出"

    @pytest.mark.asyncio
    async def test_egg_passive_gathers_extra_item(self, auth_client, session_factory, monkeypatch):
        """彩蛋被动「黑奴」：命中时每次采集动作额外多获得一个（此处固定命中以便断言）。"""
        from app.services import gathering

        monkeypatch.setattr(gathering, "gather_extra_chance", lambda _egg_id: 1.0)

        resp = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "MIN", "regionId": 1})
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 20)
            await db.commit()

        rep = await auth_client.post("/api/v1/gather/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        body = rep.json()
        assert body["gained"], "应有采集产出"
        total = sum(entry["count"] for entry in body["gained"])
        assert body["actions"] > 0
        assert total >= 2 * body["actions"], "每次采集动作应额外多获得一个"

    @pytest.mark.asyncio
    async def test_activities_mutually_exclusive(self, auth_client, session_factory):
        resp = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "BTN", "regionId": 1})
        session_id = resp.json()["sessionId"]

        # 开始战斗应结束采集会话
        battle = await auth_client.post("/api/v1/battle/session/start", json={"regionId": 1})
        assert battle.status_code == 200, battle.text

        rep = await auth_client.post("/api/v1/gather/session/report", json={"sessionId": session_id})
        assert rep.status_code == 404

    @pytest.mark.asyncio
    async def test_gather_level_requirement(self, auth_client):
        # 高等级地区（需要较高采集等级）应被拒绝
        resp = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "MIN", "regionId": 40})
        assert resp.status_code == 400


class TestProduceApi:
    @pytest.mark.asyncio
    async def test_produce_material(self, auth_client, session_factory):
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="material", item_id="g_wood", count=9))
            await db.commit()

        resp = await auth_client.post(
            "/api/v1/produce/session/start", json={"jobId": "CRP", "recipeId": "r_h_plank"}
        )
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 20)
            await db.commit()

        rep = await auth_client.post("/api/v1/produce/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        assert rep.json()["crafts"] == 3

        async with session_factory() as db:
            plank = (
                await db.execute(select(StackItem).where(StackItem.item_id == "h_plank"))
            ).scalar_one()
            assert plank.count == 3

    @pytest.mark.asyncio
    async def test_egg_passive_produces_extra_item(self, auth_client, session_factory, monkeypatch):
        """彩蛋被动「生产专家」：命中时每次多产出一件（此处固定命中以便断言），经验不额外增加。"""
        from app.services import production

        monkeypatch.setattr(production, "craft_extra_chance", lambda _egg_id: 1.0)

        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="material", item_id="g_wood", count=9))
            await db.commit()

        start = await auth_client.post(
            "/api/v1/produce/session/start", json={"jobId": "CRP", "recipeId": "r_h_plank"}
        )
        assert start.status_code == 200, start.text
        assert start.json()["targetActions"] == 3
        session_id = start.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 20)
            await db.commit()

        rep = await auth_client.post("/api/v1/produce/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        body = rep.json()
        assert body["crafts"] == 3
        assert body["materials"][0]["itemId"] == "h_plank"
        assert body["materials"][0]["count"] == 6, "每次命中应多产出一件"
        assert body["xp"] == 3 * int(CONFIG.recipe_by_id["r_h_plank"]["xp"]), "额外产出不额外计经验"

    @pytest.mark.asyncio
    async def test_produce_equipment_high_quality(self, auth_client, session_factory):
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            recipe = CONFIG.recipe_by_id["r_dh_dohTool_0"]
            for entry in recipe["inputs"]:
                db.add(
                    StackItem(
                        user_id=user_id, kind="material", item_id=entry["itemId"], count=10
                    )
                )
            await db.commit()

        # 专用装备进入装备图鉴（生产分组，底材见 dohdol-equipment）
        before = (await auth_client.get("/api/v1/game/state")).json()["codex"]["equipment"]["unlocked"]

        resp = await auth_client.post(
            "/api/v1/produce/session/start", json={"jobId": "CRP", "recipeId": "r_dh_dohTool_0"}
        )
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 20)
            await db.commit()

        rep = await auth_client.post("/api/v1/produce/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        items = rep.json()["items"]
        assert items, "应产出专用装备"
        assert items[0]["highQuality"] is True
        base_id = items[0]["baseId"]

        after = (await auth_client.get("/api/v1/game/state")).json()["codex"]["equipment"]["unlocked"]
        assert after == before + 1

        codex = (await auth_client.get("/api/v1/codex?category=equipment")).json()
        entry = next(e for e in codex["entries"] if e["baseId"] == base_id)
        assert entry["unlocked"] is True
        assert entry["jobGroup"] == "doh"

    @pytest.mark.asyncio
    async def test_recipe_level_gate(self, auth_client):
        resp = await auth_client.post(
            "/api/v1/produce/session/start", json={"jobId": "CRP", "recipeId": "r_w_bow_2"}
        )
        assert resp.status_code == 400


class TestProduceCount:
    """「制作 X 个」/「制作全部」：目标件数由服务端结算并在达成后自动结束会话。"""

    async def _give(self, session_factory, item_id: str, count: int) -> None:
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="material", item_id=item_id, count=count))
            await db.commit()

    async def _backdate_session(self, session_factory, session_id: int, seconds: float) -> None:
        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, seconds)
            await db.commit()

    @pytest.mark.asyncio
    async def test_craft_exactly_count_then_finishes(self, auth_client, session_factory):
        await self._give(session_factory, "g_wood", 20)  # 最多可制造 6 次

        start = await auth_client.post(
            "/api/v1/produce/session/start",
            json={"jobId": "CRP", "recipeId": "r_h_plank", "count": 2},
        )
        assert start.status_code == 200, start.text
        assert start.json()["targetActions"] == 2
        session_id = start.json()["sessionId"]

        await self._backdate_session(session_factory, session_id, 20)  # by_time 充足
        rep = await auth_client.post("/api/v1/produce/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        body = rep.json()
        assert body["crafts"] == 2
        assert body["targetActions"] == 2
        assert body["producedTotal"] == 2
        assert body["finished"] is True

        # 达成目标后会话自动结束：再次上报 404
        again = await auth_client.post("/api/v1/produce/session/report", json={"sessionId": session_id})
        assert again.status_code == 404

    @pytest.mark.asyncio
    async def test_count_is_clamped_to_available_materials(self, auth_client, session_factory):
        await self._give(session_factory, "g_wood", 6)  # 最多 2 次

        start = await auth_client.post(
            "/api/v1/produce/session/start",
            json={"jobId": "CRP", "recipeId": "r_h_plank", "count": 99},
        )
        assert start.status_code == 200, start.text
        assert start.json()["targetActions"] == 2

    @pytest.mark.asyncio
    async def test_craft_all_uses_material_cap(self, auth_client, session_factory):
        await self._give(session_factory, "g_wood", 9)  # 最多 3 次

        start = await auth_client.post(
            "/api/v1/produce/session/start", json={"jobId": "CRP", "recipeId": "r_h_plank"}
        )
        assert start.status_code == 200, start.text
        assert start.json()["targetActions"] == 3
        session_id = start.json()["sessionId"]

        await self._backdate_session(session_factory, session_id, 20)
        rep = await auth_client.post("/api/v1/produce/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        body = rep.json()
        assert body["crafts"] == 3
        assert body["finished"] is True

    @pytest.mark.asyncio
    async def test_no_materials_rejected(self, auth_client):
        start = await auth_client.post(
            "/api/v1/produce/session/start",
            json={"jobId": "CRP", "recipeId": "r_h_plank", "count": 1},
        )
        assert start.status_code == 400


class TestCraftXp:
    """制造经验：材料按配方基础值；装备按实际抽到的品阶乘以经验系数。"""

    async def _give(self, session_factory, recipe_id: str, count: int) -> None:
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            for entry in CONFIG.recipe_by_id[recipe_id]["inputs"]:
                db.add(
                    StackItem(
                        user_id=user_id, kind="material", item_id=entry["itemId"], count=count
                    )
                )
            await db.commit()

    async def _run(self, auth_client, session_factory, recipe_id: str, backdate: float = 20.0) -> dict:
        start = await auth_client.post(
            "/api/v1/produce/session/start",
            json={"jobId": CONFIG.recipe_by_id[recipe_id]["jobId"], "recipeId": recipe_id},
        )
        assert start.status_code == 200, start.text
        session_id = start.json()["sessionId"]
        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, backdate)
            await db.commit()
        rep = await auth_client.post("/api/v1/produce/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        return rep.json()

    @pytest.mark.asyncio
    async def test_material_craft_uses_base_xp(self, auth_client, session_factory):
        recipe = CONFIG.recipe_by_id["r_h_plank"]
        await self._give(session_factory, "r_h_plank", 9)  # 3 件
        body = await self._run(auth_client, session_factory, "r_h_plank")
        assert body["crafts"] == 3
        assert body["xp"] == 3 * int(recipe["xp"])

    @pytest.mark.asyncio
    async def test_equipment_craft_scales_with_rarity(self, auth_client, session_factory):
        recipe = CONFIG.recipe_by_id["r_dh_dohTool_0"]
        await self._give(session_factory, "r_dh_dohTool_0", 10)  # 5 件
        body = await self._run(auth_client, session_factory, "r_dh_dohTool_0")
        items = body["items"]
        assert len(items) == body["crafts"]
        expected = round(
            sum(craft_xp_rarity_multiplier(it["rarity"]) for it in items) * int(recipe["xp"])
        )
        assert body["xp"] == expected
        # 有非最低品阶时，经验必须严格高于「件数 × 基础经验」。
        if any(it["rarity"] != CONFIG.rarity_order[0] for it in items):
            assert body["xp"] > body["crafts"] * int(recipe["xp"])


class TestEquippedBonusSources:
    """经验加成来源明细：与 equipped_bonus 同源，且能区分固定加成与词条。"""

    class _FakeItem:
        def __init__(self, base_id, slot, terms):
            self.base_id = base_id
            self.equipped_slot = slot
            self.terms = terms

    def test_lists_fixed_bonus_and_term_separately(self):
        items = [
            self._FakeItem(
                "dh_dohTool_xp_4",
                "dohTool",
                [{"name": "灵感", "stat": "craftXpPct", "value": 12.5}],
            )
        ]
        sources = dict(dohdol_util.equipped_bonus_sources(items, "craftXpPct"))
        assert sources["高级悟道巧匠主手工具"] == pytest.approx(4.0)
        assert sources["灵感"] == pytest.approx(12.5)
        assert sum(sources.values()) == pytest.approx(
            dohdol_util.equipped_bonus(items)["craftXpPct"]
        )

    def test_ignores_unequipped_items(self):
        items = [self._FakeItem("dh_dohTool_xp_4", None, [])]
        assert dohdol_util.equipped_bonus_sources(items, "craftXpPct") == []


class TestXpGearData:
    """经验专用装备数据守卫：悟道 / 博识变体必须真实携带经验属性。"""

    def test_xp_variants_carry_xp_stat(self):
        items = CONFIG.dohdol_equipment["items"]
        doh_xp = [i for i in items if i["variant"] == "xp" and i["kind"] == "doh"]
        dol_xp = [i for i in items if i["variant"] == "xp" and i["kind"] == "dol"]
        assert doh_xp and dol_xp, "应存在生产 / 采集经验变体"
        for item in doh_xp:
            value = float(item["bonus"].get("craftXpPct", 0.0))
            assert 0 < value <= 25, f"{item['id']} 制造经验加成异常：{value}"
        for item in dol_xp:
            value = float(item["bonus"].get("gatherXpPct", 0.0))
            assert 0 < value <= 25, f"{item['id']} 采集经验加成异常：{value}"


class TestActivityXpBreakdown:
    """经验结算明细：基础 / 品阶系数 / 加成来源，且与最终经验自洽。"""

    async def _gather_once(self, auth_client, session_factory, backdate: float = 20.0) -> dict:
        from app.models import ActivitySession

        start = await auth_client.post(
            "/api/v1/gather/session/start", json={"jobId": "MIN", "regionId": 1}
        )
        assert start.status_code == 200, start.text
        session_id = start.json()["sessionId"]
        async with session_factory() as db:
            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, backdate)
            await db.commit()
        rep = await auth_client.post("/api/v1/gather/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        return rep.json()

    async def _produce_once(
        self, auth_client, session_factory, recipe_id: str, gives: dict[str, int], backdate: float = 20.0
    ) -> dict:
        from app.models import ActivitySession

        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            for item_id, count in gives.items():
                db.add(StackItem(user_id=user_id, kind="material", item_id=item_id, count=count))
            await db.commit()
        start = await auth_client.post(
            "/api/v1/produce/session/start",
            json={"jobId": CONFIG.recipe_by_id[recipe_id]["jobId"], "recipeId": recipe_id},
        )
        assert start.status_code == 200, start.text
        session_id = start.json()["sessionId"]
        async with session_factory() as db:
            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, backdate)
            await db.commit()
        rep = await auth_client.post("/api/v1/produce/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        return rep.json()

    @pytest.mark.asyncio
    async def test_gather_breakdown_is_consistent(self, auth_client, session_factory):
        body = await self._gather_once(auth_client, session_factory)
        b = body["xpBreakdown"]
        assert b["base"] == body["actions"] * int(CONFIG.dohdol_levels["actionXp"]["gather"])
        assert b["rarityMultiplier"] == 1.0
        assert b["amount"] == body["xp"]
        assert b["sources"] == []
        assert round(b["base"] * (1 + b["bonusPct"] / 100)) == pytest.approx(b["amount"], abs=1)

    @pytest.mark.asyncio
    async def test_gather_consumable_exp_bonus_is_itemized(self, auth_client, session_factory):
        base = await self._gather_once(auth_client, session_factory)
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="potion", item_id="p_expGainPct", count=1))
            await db.commit()
        used = await auth_client.post("/api/v1/consumable/use", json={"itemId": "p_expGainPct"})
        assert used.status_code == 200, used.text

        boosted = await self._gather_once(auth_client, session_factory)
        assert boosted["actions"] == base["actions"], "同一窗口下动作数应一致，才能比较经验"
        assert boosted["xp"] > base["xp"], "经验药水应提升采集经验"
        assert boosted["xpBreakdown"]["bonusPct"] == pytest.approx(25.0)
        sources = {s["label"]: s["pct"] for s in boosted["xpBreakdown"]["sources"]}
        assert sources["经验获取秘药"] == pytest.approx(25.0)

    @pytest.mark.asyncio
    async def test_equipped_gather_xp_gear_is_itemized(self, auth_client, session_factory):
        from app.models import User
        from app.services.grants import insert_items

        me = (await auth_client.get("/api/v1/auth/me")).json()
        async with session_factory() as db:
            user = (await db.execute(select(User).where(User.id == me["id"]))).scalar_one()
            generated = generate_crafted_item("dh_dolTool_xp_4", random.Random(5))
            created = await insert_items(db, user, [generated], source="craft")
            await db.commit()
        equip = await auth_client.post(
            "/api/v1/dohdol/equip", json={"itemId": created[0]["id"], "slot": "dolTool"}
        )
        assert equip.status_code == 200, equip.text

        body = await self._gather_once(auth_client, session_factory)
        sources = {s["label"]: s["pct"] for s in body["xpBreakdown"]["sources"]}
        assert sources["高级博识大地主手工具"] == pytest.approx(4.0)
        assert body["xpBreakdown"]["bonusPct"] >= 4.0

    @pytest.mark.asyncio
    async def test_material_craft_breakdown_is_consistent(self, auth_client, session_factory):
        recipe = CONFIG.recipe_by_id["r_h_plank"]
        body = await self._produce_once(auth_client, session_factory, "r_h_plank", {"g_wood": 9})
        b = body["xpBreakdown"]
        assert b["rarityMultiplier"] == 1.0
        assert b["base"] == body["crafts"] * int(recipe["xp"])
        assert b["amount"] == body["xp"]

    @pytest.mark.asyncio
    async def test_equipment_craft_reports_rarity_multiplier(self, auth_client, session_factory):
        recipe = CONFIG.recipe_by_id["r_dh_dohTool_0"]
        gives = {e["itemId"]: int(e["count"]) * 3 for e in recipe["inputs"]}
        body = await self._produce_once(auth_client, session_factory, "r_dh_dohTool_0", gives)
        b = body["xpBreakdown"]
        # 装备按实际抽到的品阶加权：最低品阶系数为 1，故平均值 >= 1。
        assert b["rarityMultiplier"] >= 1.0
        assert b["amount"] == body["xp"]
        expected = round(b["base"] * b["rarityMultiplier"] * (1 + b["bonusPct"] / 100))
        assert expected == pytest.approx(b["amount"], abs=1)


class TestFishApi:
    @pytest.mark.asyncio
    async def test_fish_flow(self, auth_client, session_factory):
        resp = await auth_client.post("/api/v1/fish/session/start", json={"regionId": 1})
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 60)
            await db.commit()

        rep = await auth_client.post("/api/v1/fish/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        data = rep.json()
        assert data["casts"] > 0
        assert data["caught"], "应有鱼获"

        async with session_factory() as db:
            records = (await db.execute(select(FishRecord))).scalars().all()
            assert records

    @pytest.mark.asyncio
    async def test_fish_level_requirement(self, auth_client, session_factory):
        """钓场按采集等级门槛开放（与采集点一致，并叠加在地区解锁之上）。"""
        from app.models import RegionProgress

        me = (await auth_client.get("/api/v1/auth/me")).json()
        async with session_factory() as db:
            # 解锁地区 2 的钓场（需先通关地区 1），但采集等级仍为 1
            for region_id, *flags in ((1, "cleared"), (2, "unlocked")):
                row = (
                    await db.execute(
                        select(RegionProgress).where(
                            RegionProgress.user_id == me["id"], RegionProgress.region_id == region_id
                        )
                    )
                ).scalar_one()
                setattr(row, flags[0], True)
            await db.commit()

        # region 2 需要采集等级 3 → 默认 1 级被拒
        denied = await auth_client.post("/api/v1/fish/session/start", json={"regionId": 2})
        assert denied.status_code == 400, denied.text
        assert "采集等级" in denied.json()["detail"]

        # 提升采集等级后放行
        async with session_factory() as db:
            progress = (
                await db.execute(
                    select(DohDolProgress).where(
                        DohDolProgress.user_id == me["id"], DohDolProgress.kind == "dol"
                    )
                )
            ).scalar_one()
            progress.level = 3
            await db.commit()

        ok = await auth_client.post("/api/v1/fish/session/start", json={"regionId": 2})
        assert ok.status_code == 200, ok.text


class TestConsumableApi:
    @pytest.mark.asyncio
    async def test_use_consumable_stacks_same_item_only(self, auth_client, session_factory):
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="potion", item_id="p_expGainPct", count=2))
            db.add(StackItem(user_id=user_id, kind="potion", item_id="p_goldGainPct", count=1))
            await db.commit()

        duration = int(CONFIG.consumables["kinds"]["potion"]["durationSec"])

        resp = await auth_client.post("/api/v1/consumable/use", json={"itemId": "p_expGainPct"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["kind"] == "potion"
        first_remaining = resp.json()["active"][0]["remainingSec"]
        assert 0 < first_remaining <= duration

        # 同一件再次使用：不新增记录，而是把该槽位时长叠加
        resp2 = await auth_client.post("/api/v1/consumable/use", json={"itemId": "p_expGainPct"})
        assert resp2.status_code == 200
        async with session_factory() as db:
            rows = (await db.execute(select(ActiveConsumable))).scalars().all()
            assert len(rows) == 1
        assert resp2.json()["active"][0]["remainingSec"] > duration, "同一件连续使用应叠加时长"

        # 换成同槽位的另一种药水：重置为新的一份时长，不继承已累计的时长
        resp3 = await auth_client.post("/api/v1/consumable/use", json={"itemId": "p_goldGainPct"})
        assert resp3.status_code == 200
        assert resp3.json()["active"][0]["remainingSec"] <= duration, "换成另一种消耗品应重置时长"
        async with session_factory() as db:
            rows = (await db.execute(select(ActiveConsumable))).scalars().all()
            assert len(rows) == 1
            assert rows[0].item_id == "p_goldGainPct"


class TestSellApi:
    @pytest.mark.asyncio
    async def test_sell_material(self, auth_client, session_factory):
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="material", item_id="g_ore", count=5))
            await db.commit()

        before = (await auth_client.get("/api/v1/game/state")).json()["user"]["gold"]
        resp = await auth_client.post(
            "/api/v1/dohdol/sell", json={"kind": "material", "itemId": "g_ore", "count": 3}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["goldGained"] == body["unitPrice"] * 3
        assert body["gold"] == before + body["goldGained"]

        async with session_factory() as db:
            row = (await db.execute(select(StackItem).where(StackItem.item_id == "g_ore"))).scalar_one()
            assert row.count == 2

    @pytest.mark.asyncio
    async def test_sell_fish_and_guards(self, auth_client, session_factory):
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="material", item_id="f1_1", count=2))
            await db.commit()

        resp = await auth_client.post(
            "/api/v1/dohdol/sell", json={"kind": "material", "itemId": "f1_1", "count": 1}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["goldGained"] > 0

        # 类型不匹配 / 未知物品 / 数量不足
        bad_kind = await auth_client.post(
            "/api/v1/dohdol/sell", json={"kind": "potion", "itemId": "f1_1", "count": 1}
        )
        assert bad_kind.status_code == 400
        unknown = await auth_client.post(
            "/api/v1/dohdol/sell", json={"kind": "material", "itemId": "nope", "count": 1}
        )
        assert unknown.status_code == 404
        too_many = await auth_client.post(
            "/api/v1/dohdol/sell", json={"kind": "material", "itemId": "f1_1", "count": 99}
        )
        assert too_many.status_code == 400


class TestFishingRanking:
    async def _fish_once(self, auth_client, session_factory):
        start = await auth_client.post("/api/v1/fish/session/start", json={"regionId": 1})
        session_id = start.json()["sessionId"]
        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 60)
            await db.commit()
        await auth_client.post("/api/v1/fish/session/report", json={"sessionId": session_id})

    @pytest.mark.asyncio
    async def test_fishing_boards_are_live_without_refresh(self, auth_client, session_factory):
        """刚钓完就能看到（钓鱼榜实时聚合，不等 5 分钟缓存刷新）。"""
        await self._fish_once(auth_client, session_factory)

        species_board = await auth_client.get("/api/v1/ranking", params={"board": "fish_species"})
        assert species_board.status_code == 200, species_board.text
        entries = species_board.json()["entries"]
        assert entries, "钓鱼种类榜应有记录（且不依赖缓存刷新）"
        assert entries[0]["value"] >= 1

        count_board = await auth_client.get("/api/v1/ranking", params={"board": "fish_count"})
        assert count_board.status_code == 200, count_board.text
        assert count_board.json()["entries"][0]["value"] >= 1

    @pytest.mark.asyncio
    async def test_species_board_breaks_down_by_kind(self, auth_client, session_factory):
        """种类榜要包含普通鱼，并区分普通 / 鱼王 / 鱼皇。"""
        await self._fish_once(auth_client, session_factory)
        await auth_client.post("/api/v1/ranking/refresh", json={})

        board = await auth_client.get("/api/v1/ranking", params={"board": "fish_species"})
        payload = board.json()["entries"][0]["payload"]
        assert payload["fishNormal"] >= 1, "普通鱼种类必须计入种类榜"
        assert payload["fishSpecies"] == payload["fishNormal"] + payload["fishKing"] + payload["fishEmperor"]
        assert payload["fishKing"] >= 0 and payload["fishEmperor"] >= 0

        # 榜单是 5 个缓存榜（含游玩时间）+ 2 个钓鱼榜 + 4 个生产采集榜 + 1 个远征榜
        assert board.json()["boards"] == [
            "level", "stage", "power", "gold", "playtime", "fish_species", "fish_count",
            "doh_exp", "dol_exp", "doh_attr", "dol_attr", "coop",
        ]

    @pytest.mark.asyncio
    async def test_no_fish_no_fishing_entry(self, auth_client):
        """没钓鱼的玩家不应出现在钓鱼榜上。"""
        await auth_client.post("/api/v1/ranking/refresh", json={})
        board = await auth_client.get("/api/v1/ranking", params={"board": "fish_species"})
        assert board.status_code == 200
        assert board.json()["entries"] == []


class TestDohDolRanking:
    """生产/采集榜：实时聚合（不需缓存刷新），刚完成即可见。"""

    async def _gather_once(self, auth_client, session_factory) -> None:
        start = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "MIN", "regionId": 1})
        assert start.status_code == 200, start.text
        session_id = start.json()["sessionId"]
        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 20)
            await db.commit()
        rep = await auth_client.post("/api/v1/gather/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text

    @pytest.mark.asyncio
    async def test_exp_board_is_live_without_refresh(self, auth_client, session_factory):
        me = (await auth_client.get("/api/v1/auth/me")).json()
        await self._gather_once(auth_client, session_factory)

        board = await auth_client.get("/api/v1/ranking", params={"board": "dol_exp"})
        assert board.status_code == 200, board.text
        row = next((e for e in board.json()["entries"] if e["userId"] == me["id"]), None)
        assert row is not None, "采集后应立即出现在采集经验榜（不依赖缓存刷新）"
        assert row["value"] > 0
        assert row["payload"]["dolLevel"] >= 1

    @pytest.mark.asyncio
    async def test_attr_board_counts_equipped_dedicated_gear(self, auth_client, session_factory):
        from app.models import User
        from app.services.grants import insert_items

        me = (await auth_client.get("/api/v1/auth/me")).json()
        async with session_factory() as db:
            user = (await db.execute(select(User).where(User.id == me["id"]))).scalar_one()
            generated = generate_crafted_item("dh_dohTool_0", random.Random(5))
            created = await insert_items(db, user, [generated], source="craft")
            await db.commit()
        item_id = created[0]["id"]

        equip = await auth_client.post("/api/v1/dohdol/equip", json={"itemId": item_id, "slot": "dohTool"})
        assert equip.status_code == 200, equip.text

        board = await auth_client.get("/api/v1/ranking", params={"board": "doh_attr"})
        assert board.status_code == 200, board.text
        row = next((e for e in board.json()["entries"] if e["userId"] == me["id"]), None)
        assert row is not None and row["value"] > 0, "装备生产专用装备后应出现在生产属性榜"

    @pytest.mark.asyncio
    async def test_no_activity_no_dohdol_entry(self, auth_client):
        """没有生产/采集的玩家不应出现在这些榜上。"""
        board = await auth_client.get("/api/v1/ranking", params={"board": "doh_exp"})
        assert board.status_code == 200
        assert board.json()["entries"] == []


class TestActivityCycle:
    @pytest.mark.asyncio
    async def test_cycle_reported_for_progress_bars(self, auth_client, session_factory):
        # 采集：开始与上报都带 cycle（供前端画进度条）
        start = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "MIN", "regionId": 1})
        assert start.status_code == 200, start.text
        body = start.json()
        assert body["cycle"]["seconds"] > 0
        assert body["cycle"]["credit"] == 0
        assert body["cycle"]["at"] > 0, "cycle.at 用于前端半 RTT 校正"

        rep = await auth_client.post("/api/v1/gather/session/report", json={"sessionId": body["sessionId"]})
        assert rep.status_code == 200, rep.text
        assert rep.json()["cycle"]["seconds"] > 0

        await auth_client.post("/api/v1/gather/session/stop", json={"sessionId": body["sessionId"]})

        # 生产（需先备料）
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="material", item_id="g_wood", count=3))
            await db.commit()
        pstart = await auth_client.post(
            "/api/v1/produce/session/start", json={"jobId": "CRP", "recipeId": "r_h_plank"}
        )
        assert pstart.status_code == 200, pstart.text
        assert pstart.json()["cycle"]["seconds"] > 0

        # 钓鱼
        fstart = await auth_client.post("/api/v1/fish/session/start", json={"regionId": 1})
        assert fstart.status_code == 200, fstart.text
        assert fstart.json()["cycle"]["seconds"] > 0


class TestDedicatedItemGuards:
    @pytest.mark.asyncio
    async def test_dedicated_gear_cannot_be_refined_or_enchanted(self, auth_client, session_factory):
        from app.models import User
        from app.services.grants import insert_items

        async with session_factory() as db:
            user = (await db.execute(select(User))).scalars().first()
            generated = generate_crafted_item("dh_dohTool_0", random.Random(1))
            created = await insert_items(db, user, [generated], source="craft")
            await db.commit()
        item_id = created[0]["id"]

        refine = await auth_client.post(
            "/api/v1/economy/refine", json={"itemId": item_id, "mode": "random"}
        )
        assert refine.status_code == 400, refine.text
        enchant = await auth_client.post(
            "/api/v1/economy/enchant", json={"itemId": item_id, "mode": "random"}
        )
        assert enchant.status_code == 400, enchant.text

    @pytest.mark.asyncio
    async def test_dedicated_gear_unlocks_codex_terms(self, auth_client, session_factory):
        from app.models import User
        from app.services.grants import insert_items

        async with session_factory() as db:
            user = (await db.execute(select(User))).scalars().first()
            generated = generate_crafted_item("dh_dohTool_0", random.Random(3))
            await insert_items(db, user, [generated], source="craft")
            await db.commit()

        body = (await auth_client.get("/api/v1/codex?category=term")).json()
        production = [e for e in body["entries"] if e["source"] == "production"]
        assert production, "生产装备词条应进入词条图鉴"
        # 制造装备必带太古词条 → 至少一条生产词条被解锁进图鉴
        assert any(q["unlocked"] for e in production for q in e["qualities"].values())


class TestDohDolState:
    @pytest.mark.asyncio
    async def test_state_block(self, auth_client):
        resp = await auth_client.get("/api/v1/game/state")
        assert resp.status_code == 200, resp.text
        dohdol = resp.json()["dohdol"]
        assert dohdol["progress"]["doh"]["level"] == 1
        assert dohdol["progress"]["dol"]["level"] == 1
        assert dohdol["recipes"], "应下发配方"
        assert dohdol["fishStats"]["kingTotal"] == 40
        # 配方产物名已解析（不再显示 f_expGainPct 这类 id）
        for r in dohdol["recipes"]:
            key = r["output"]["itemId"] or r["output"]["baseId"]
            assert r["output"]["name"] != key, r["id"]

        # 制造品阶概率块：全部来源 + 归一分布 + 神话硬上限
        craft = dohdol["craft"]
        assert len(craft["sources"]) == 7
        assert {s["key"] for s in craft["sources"]} == {
            "heroLevel",
            "clearedRegions",
            "prodLevel",
            "gearPct",
            "consumablePct",
            "coopClears",
            "raidClears",
        }
        assert abs(sum(craft["odds"].values()) - 1.0) < 1e-6
        assert craft["odds"]["mythic"] <= craft["mythicCap"] + 1e-9
        assert craft["mythicCap"] == 0.2

        # 抽箱品阶幸运块：与生产同源的六项来源 + 上限
        chest = resp.json()["chestRarityLuck"]
        assert chest["luckMax"] > 0
        assert 0 <= chest["luck"] <= chest["luckMax"]
        assert {s["key"] for s in chest["sources"]} == {
            "clearedRegions",
            "gearPct",
            "consumablePct",
            "coopClears",
            "raidClears",
            "egg",
        }


class TestMaterialAndFishCodex:
    @pytest.mark.asyncio
    async def test_material_codex_unlocks_on_gather(self, auth_client, session_factory):
        before = (await auth_client.get("/api/v1/codex?category=material")).json()
        assert before["progress"]["material"]["unlocked"] == 0
        assert before["progress"]["material"]["total"] > 0

        start = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "MIN", "regionId": 1})
        assert start.status_code == 200, start.text
        session_id = start.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 20)
            await db.commit()

        rep = await auth_client.post("/api/v1/gather/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        gained_ids = {g["itemId"] for g in rep.json()["gained"]}
        assert gained_ids, "应有采集产出"

        body = (await auth_client.get("/api/v1/codex?category=material")).json()
        unlocked = {e["itemId"] for e in body["entries"] if e["unlocked"]}
        assert gained_ids <= unlocked, "采集到的材料应解锁材料图鉴"
        assert body["progress"]["material"]["unlocked"] == len(unlocked)

    @pytest.mark.asyncio
    async def test_fish_codex_unlocks_on_catch(self, auth_client, session_factory):
        start = await auth_client.post("/api/v1/fish/session/start", json={"regionId": 1})
        assert start.status_code == 200, start.text
        session_id = start.json()["sessionId"]

        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 60)
            await db.commit()

        rep = await auth_client.post("/api/v1/fish/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        caught_ids = {c["id"] for c in rep.json()["caught"]}
        assert caught_ids, "应有鱼获"

        body = (await auth_client.get("/api/v1/codex?category=fish")).json()
        unlocked = {e["fishId"] for e in body["entries"] if e["unlocked"]}
        assert caught_ids <= unlocked, "钓到的鱼应解锁鱼获图鉴"

        # 鱼获单独成册：不应进入材料图鉴
        material = (await auth_client.get("/api/v1/codex?category=material")).json()
        assert caught_ids.isdisjoint({e["itemId"] for e in material["entries"]})

    @pytest.mark.asyncio
    async def test_unknown_codex_category_rejected(self, auth_client):
        resp = await auth_client.get("/api/v1/codex?category=bogus")
        assert resp.status_code == 422


class TestActivityTiming:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kind,payload",
        [
            ("gather", {"jobId": "MIN", "regionId": 1}),
            ("produce", {"jobId": "CRP", "recipeId": "r_h_plank", "count": 10}),
            ("fish", {"regionId": 1}),
        ],
    )
    async def test_cycle_matches_settlement_after_speed_change(
        self, auth_client, session_factory, monkeypatch, kind, payload
    ):
        from datetime import datetime, timedelta, timezone
        from app.models import ActivitySession
        from app.services import dohdol_util, fishing, gathering, production

        # 使用小数秒起点，防止数据库默认时间截断造成首轮偏移。
        current = datetime(2026, 9, 22, 0, 0, 0, 765432, tzinfo=timezone.utc)

        class Clock:
            @classmethod
            def now(cls, tz=None):
                return current

        service = {"gather": gathering, "produce": production, "fish": fishing}[kind]
        monkeypatch.setattr(service, "datetime", Clock)
        bonus = {"gatherSpeedPct": 0.0, "craftSpeedPct": 0.0}
        monkeypatch.setattr(dohdol_util, "equipped_bonus", lambda items: bonus)
        async with session_factory() as db:
            user_id = (await db.execute(select(DohDolProgress))).scalars().first().user_id
            db.add(StackItem(user_id=user_id, kind="material", item_id="g_wood", count=100))
            await db.commit()

        start = await auth_client.post(f"/api/v1/{kind}/session/start", json=payload)
        assert start.status_code == 200, start.text
        body = start.json()
        initial_seconds = body["cycle"]["seconds"]
        assert body["cycle"]["at"] == int(current.timestamp() * 1000)
        async with session_factory() as db:
            session = await db.get(ActivitySession, body["sessionId"])
            assert session.last_report_at.replace(tzinfo=timezone.utc) == current

        # 运行中属性加速，服务端实际扣除的时间与下发的周期必须一致。
        bonus.update(gatherSpeedPct=100.0, craftSpeedPct=50.0)
        elapsed = round(initial_seconds * 0.75, 6)
        current += timedelta(seconds=elapsed)
        report = await auth_client.post(
            f"/api/v1/{kind}/session/report", json={"sessionId": body["sessionId"]}
        )
        assert report.status_code == 200, report.text
        result = report.json()
        seconds = result["cycle"]["seconds"]
        assert seconds == pytest.approx(initial_seconds / 2)
        count_key = {"gather": "actions", "produce": "crafts", "fish": "casts"}[kind]
        assert result[count_key] == int(elapsed // seconds)
        assert result["cycle"]["credit"] == pytest.approx(elapsed % seconds)

        # 卸下加速装备后，余额保留，但下一动作按变慢后的真实耗时结算。
        credit = result["cycle"]["credit"]
        bonus.update(gatherSpeedPct=0.0, craftSpeedPct=0.0)
        current += timedelta(seconds=initial_seconds - credit + 0.01)
        report = await auth_client.post(
            f"/api/v1/{kind}/session/report", json={"sessionId": body["sessionId"]}
        )
        assert report.status_code == 200, report.text
        result = report.json()
        assert result["cycle"]["seconds"] == pytest.approx(initial_seconds)
        assert result[count_key] == 1
        assert result["cycle"]["credit"] == pytest.approx(0.01, abs=1e-6)


class TestExtendedDedicatedTerms:
    """扩展的生产/采集词条（材料节省 / 额外产出 / 满载 / 双钩 …，见设计文档第 6 节）。"""

    EXPANDED = {
        "dohFrugal", "dohProlific", "dohMasterpiece",
        "dolExtraAction", "dolRareFind", "dolDoubleHaul", "dolDoubleCatch",
        "dohWasteful", "dohBarren", "dohFlawed", "dolIdle", "dolBarren", "dolBadCatch",
    }

    def test_expanded_terms_present_and_categorized(self) -> None:
        terms = CONFIG.dohdol_equipment["terms"]
        ids = {t["id"] for t in terms}
        assert self.EXPANDED <= ids, sorted(self.EXPANDED - ids)
        cats = {c["id"] for c in CONFIG.dohdol_equipment["termCategories"]}
        assert cats
        for term in terms:
            assert term["category"] in cats, term["id"]

    def test_new_bonus_stats_are_named(self) -> None:
        """新增生产加成键都要有中文名（避免原始 key 泄漏到界面）。"""
        names = CONFIG.dohdol_equipment["bonusNames"]
        for stat in (
            "craftMaterialSavePct", "craftExtraOutputPct", "craftQualityJumpPct",
            "gatherExtraActionPct", "gatherRareChancePct", "gatherDoublePct", "fishDoubleCatchPct",
        ):
            assert stat in names, stat

    def test_equipped_bonus_sums_expanded_stats(self) -> None:
        from tests.fakes import FakeItem

        item = FakeItem(
            category="doh_tool",
            base_id="dh_dohTool_0",
            slot="dohTool",
            equipped_slot="dohTool",
            terms=[
                {
                    "id": "dohFrugal", "name": "节俭", "type": "buff",
                    "stat": "craftMaterialSavePct", "trigger": "触发", "value": 12.0,
                    "quality": "common", "desc": "制造时 {v}% 概率不消耗材料", "category": "doh",
                }
            ],
        )
        bonus = dohdol_util.equipped_bonus([item])
        assert bonus.get("craftMaterialSavePct") == pytest.approx(12.0)


# ─────────────────────────────────────────── 钓鱼 2.0：天气 / 时间 / 直觉 / 称号

def _cond(weather_id: str = "clear", tod: str = "day") -> dict:
    return {
        "weather": weather_id, "weatherName": weather_id, "weatherHex": "#000000",
        "etHour": 10, "etClock": "10:00", "timeOfDay": tod, "timeOfDayName": tod,
    }


def _one_special_region(weather_ids=None, time_ids=None, requires=None) -> dict:
    return {
        "regionId": 999, "name": "测试钓场", "levelReq": 1,
        "normal": [
            {"id": "ft_1", "name": "测试鱼", "rarity": "white", "weight": 1,
             "sizeMin": 1, "sizeMax": 2, "exp": 1, "sell": 1},
        ],
        "specials": [
            {
                "id": "lt_1", "name": "测试大鱼", "kind": "legend",
                **({"weather": weather_ids} if weather_ids else {}),
                **({"timeOfDay": time_ids} if time_ids else {}),
                "intuition": {
                    "name": "测试之识",
                    "requires": requires or [{"fishId": "ft_1", "count": 3}],
                    "durationSec": [100, 100], "chance": 0.5,
                },
                "sizeMin": 10, "sizeMax": 20, "exp": 5, "sell": 5,
            },
        ],
    }


class TestWeather:
    """天气 / ET：服务端时间的纯函数，且与前端 weather.ts 同值。"""

    def test_hash_matches_frontend_snapshot(self):
        from app.services import weather

        # 与 frontend/src/game/weather.ts::hash01 的固定快照一致（改动算法会同时失败）。
        assert round(weather.hash01(12345, 1), 9) == 0.865077992
        assert round(weather.hash01(999999, 1), 9) == 0.400823007

    def test_weather_is_deterministic_and_varies(self):
        from app.services import weather

        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert weather.weather_for(1, t) == weather.weather_for(1, t)
        period = weather.weather_period_sec()
        seen = {weather.weather_for(1, t + timedelta(seconds=i * period)) for i in range(40)}
        assert len(seen) > 1, "同一地区应随时间出现不同天气"

    def test_weather_always_reachable_for_every_region(self):
        from app.services import weather

        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        period = weather.weather_period_sec()
        for region in CONFIG.weather["regions"]:
            rid = int(region["regionId"])
            seen = {weather.weather_for(rid, t + timedelta(seconds=i * period)) for i in range(120)}
            assert seen <= set(region["weights"]), f"地区 {rid} 出现未声明的天气 {seen}"

    def test_time_of_day_windows_wrap(self):
        from app.services import weather

        windows = CONFIG.weather["timeOfDay"]
        for hour in range(24):
            assert weather.time_of_day  # sanity
        # 深夜窗口跨零点：[20,4]
        assert windows["night"][0] > windows["night"][1]

    def test_gate_matches(self):
        from app.services import weather

        cond = _cond("clear", "day")
        assert weather.gate_matches(cond, None, None)
        assert weather.gate_matches(cond, ["clear"], ["day"])
        assert not weather.gate_matches(cond, ["rain"], None)
        assert not weather.gate_matches(cond, None, ["night"])


class TestFishIntuition:
    """捕鱼人之识：一鱼一 BUFF、计数型前置、不刷新、结束后才可再次触发。"""

    def _rng(self):
        return random.Random(20260924)

    def test_counted_prereq_triggers_only_when_complete(self):
        from app.services import fishing

        region = _one_special_region(requires=[{"fishId": "ft_1", "count": 3}])
        cond = _cond()
        now = datetime.now(timezone.utc)
        insights: dict = {}
        intuition: dict = {}
        rng = self._rng()
        for _ in range(2):
            fishing._advance_intuition(region, cond, "ft_1", 1, insights, intuition, 0.0, rng, now)
        assert "lt_1" not in insights, "前置未满不应开启"
        fishing._advance_intuition(region, cond, "ft_1", 1, insights, intuition, 0.0, rng, now)
        assert "lt_1" in insights, "前置齐备应开启"
        assert intuition["lt_1"] == {}, "触发即消耗前置"

    def test_never_refreshes_while_active(self):
        from app.services import fishing

        region = _one_special_region(requires=[{"fishId": "ft_1", "count": 1}])
        cond = _cond()
        now = datetime.now(timezone.utc)
        insights: dict = {}
        intuition: dict = {}
        rng = self._rng()
        fishing._advance_intuition(region, cond, "ft_1", 1, insights, intuition, 0.0, rng, now)
        first = insights["lt_1"]
        # 已激活：即便再钓齐前置、即便有洞察加成，也绝不延长
        fishing._advance_intuition(region, cond, "ft_1", 5, insights, intuition, 999.0, rng, now)
        assert insights["lt_1"] == first

    def test_retrigger_allowed_only_after_expiry(self):
        from app.services import fishing

        region = _one_special_region(requires=[{"fishId": "ft_1", "count": 1}])
        cond = _cond()
        now = datetime.now(timezone.utc)
        insights: dict = {}
        intuition: dict = {}
        rng = self._rng()
        fishing._advance_intuition(region, cond, "ft_1", 1, insights, intuition, 0.0, rng, now)
        assert insights["lt_1"] == now + timedelta(seconds=100)

        # 未到期：重新钓齐也无法再次触发
        mid = now + timedelta(seconds=50)
        fishing._advance_intuition(region, cond, "ft_1", 1, insights, intuition, 0.0, rng, mid)
        assert insights["lt_1"] == now + timedelta(seconds=100)

        # 到期后：重新钓齐前置即可再次触发
        later = now + timedelta(seconds=200)
        fishing._advance_intuition(region, cond, "ft_1", 1, insights, intuition, 0.0, rng, later)
        assert insights["lt_1"] >= later

    def test_weather_gate_blocks_prereq_and_trigger(self):
        from app.services import fishing

        region = _one_special_region(weather_ids=["clear"], requires=[{"fishId": "ft_1", "count": 1}])
        now = datetime.now(timezone.utc)
        insights: dict = {}
        intuition: dict = {}
        rng = self._rng()
        # 非窗口天气：不计前置、不触发
        fishing._advance_intuition(region, _cond("fog"), "ft_1", 3, insights, intuition, 0.0, rng, now)
        assert "lt_1" not in insights and not intuition.get("lt_1")
        # 窗口天气：正常触发
        fishing._advance_intuition(region, _cond("clear"), "ft_1", 1, insights, intuition, 0.0, rng, now)
        assert "lt_1" in insights

    def test_special_not_catchable_outside_window(self):
        from app.services import fishing

        region = _one_special_region(weather_ids=["clear"], time_ids=["night"])
        now = datetime.now(timezone.utc)
        insights = {"lt_1": now + timedelta(seconds=100)}
        assert fishing._special_candidates(region, _cond("clear", "day"), insights, now) == []
        assert fishing._special_candidates(region, _cond("clear", "night"), insights, now)
        assert fishing._special_candidates(region, _cond("fog", "night"), insights, now) == []

    def test_special_not_catchable_without_insight(self):
        from app.services import fishing

        region = _one_special_region()
        now = datetime.now(timezone.utc)
        assert fishing._special_candidates(region, _cond(), {}, now) == []

    def test_normal_pool_respects_weather_gate(self):
        from app.services import fishing

        region = {
            "regionId": 998, "name": "t", "levelReq": 1,
            "normal": [
                {"id": "fa", "name": "always", "rarity": "white", "weight": 100,
                 "sizeMin": 1, "sizeMax": 2, "exp": 1, "sell": 1},
                {"id": "fb", "name": "rainonly", "rarity": "blue", "weight": 100,
                 "weather": ["rain"], "sizeMin": 1, "sizeMax": 2, "exp": 1, "sell": 1},
            ],
            "specials": [],
        }
        rng = self._rng()
        picks = {fishing._pick_normal(region, _cond("clear"), rng)["id"] for _ in range(50)}
        assert picks == {"fa"}, "非窗口天气不应钓到受门槛限制的鱼"


class TestTitleConditions:
    """称号条件判定：legacy 范围不受新困难鱼影响。"""

    def _ctx(self, ids, **kw):
        kind: dict[str, int] = {}
        rarity: dict[str, int] = {}
        for fish_id in ids:
            info = CONFIG.fish_by_id.get(fish_id)
            if not info:
                continue
            kind[info["kind"]] = kind.get(info["kind"], 0) + 1
            if info.get("rarity"):
                rarity[info["rarity"]] = rarity.get(info["rarity"], 0) + 1
        return {
            "ids": set(ids), "kind": kind, "rarity": rarity,
            "species": len(ids), "count": kw.get("count", len(ids)),
        }

    def test_count_and_specific(self):
        from app.services import titles

        ctx = self._ctx(["k1"], count=5)
        assert titles.matches({"type": "count_kind", "kind": "king", "count": 1}, ctx)
        assert not titles.matches({"type": "count_kind", "kind": "king", "count": 2}, ctx)
        assert titles.matches({"type": "fish_count", "count": 5}, ctx)
        assert not titles.matches({"type": "fish_count", "count": 6}, ctx)
        assert titles.matches({"type": "specific_fish", "fishIds": ["k1"]}, ctx)
        assert not titles.matches({"type": "specific_fish", "fishIds": ["k2"]}, ctx)

    def test_all_king_is_scoped_to_legacy(self):
        from app.services import titles

        legacy_kings = {
            s["id"] for region in CONFIG.fish["regions"] for s in region["specials"]
            if s["kind"] == "king" and s.get("legacy")
        }
        assert titles.matches({"type": "all_king"}, self._ctx(legacy_kings))
        # 少了任何一条 legacy 鱼王都不成立
        assert not titles.matches({"type": "all_king"}, self._ctx(list(legacy_kings)[:-1]))
        # 新增困难鱼不计入旧称号
        assert not titles.matches({"type": "all_king"}, self._ctx(list(legacy_kings)[:-1] + ["l21_hue_lord"]))


class TestFishingMechanicsApi:
    @pytest.mark.asyncio
    async def test_fish_report_exposes_conditions_and_insights(self, auth_client, session_factory):
        start = await auth_client.post("/api/v1/fish/session/start", json={"regionId": 1})
        assert start.status_code == 200, start.text
        assert start.json()["conditions"]["weather"]
        session_id = start.json()["sessionId"]
        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 60)
            await db.commit()
        rep = await auth_client.post("/api/v1/fish/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        body = rep.json()
        assert "conditions" in body and "insights" in body
        assert isinstance(body["insights"], list)
        for catch in body["caught"]:
            assert catch["kind"] in ("normal", "king", "emperor", "legend")

    @pytest.mark.asyncio
    async def test_fish_stats_include_legend_totals(self, auth_client):
        state = (await auth_client.get("/api/v1/dohdol/state")).json()
        stats = state["fishStats"]
        assert stats["kingTotal"] == 40 and stats["emperorTotal"] == 40
        assert stats["legendTotal"] >= 10
        assert stats["legend"] == 0


class TestActiveTitleApi:
    @pytest.mark.asyncio
    async def test_set_reject_and_clear(self, auth_client, session_factory):
        from app.models import UserTitle

        me = (await auth_client.get("/api/v1/auth/me")).json()
        async with session_factory() as db:
            db.add(UserTitle(user_id=me["id"], title_id="fish_king_all"))
            await db.commit()

        ok = await auth_client.post("/api/v1/settings/active-title", json={"titleId": "fish_king_all"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["ok"] is True and ok.json()["activeTitleId"] == "fish_king_all"

        state = (await auth_client.get("/api/v1/game/state")).json()
        assert state["user"]["activeTitleId"] == "fish_king_all"

        # 未拥有 → 拒绝
        denied = await auth_client.post("/api/v1/settings/active-title", json={"titleId": "fish_grand_all"})
        assert denied.json()["ok"] is False
        assert denied.json()["activeTitleId"] == "fish_king_all"

        # 未知称号 → 拒绝
        unknown = await auth_client.post("/api/v1/settings/active-title", json={"titleId": "nope"})
        assert unknown.json()["ok"] is False

        # 清除
        cleared = await auth_client.post("/api/v1/settings/active-title", json={"titleId": None})
        assert cleared.json()["activeTitleId"] is None
        assert (await auth_client.get("/api/v1/game/state")).json()["user"]["activeTitleId"] is None

    @pytest.mark.asyncio
    async def test_specific_fish_title_unlocks_from_record(self, auth_client, session_factory):
        from app.models import FishRecord
        from app.services import titles as titles_service

        me = (await auth_client.get("/api/v1/auth/me")).json()
        async with session_factory() as db:
            db.add(FishRecord(user_id=me["id"], fish_id="l21_hue_lord", region_id=21,
                              kind="legend", count=1, max_size=1))
            await db.commit()
            new = await titles_service.evaluate_titles(db, me["id"])
            await db.commit()
        assert "fish_specific_hue" in new


class TestEggTitles:
    """彩蛋称号：挖宝下底 / 采集时的极低概率掉落（非确定性条件）。"""

    EVENTS = {"treasure_bottom": 5, "gather": 5}

    def test_egg_titles_defined(self):
        from app.services import titles as titles_service

        for event, count in self.EVENTS.items():
            eggs = titles_service.random_drop_titles(event)
            assert len(eggs) == count, f"{event} 应有 {count} 个彩蛋称号"
            for title in eggs:
                assert title.get("egg") is True
                assert title["condition"]["type"] == "random_drop"
                assert 0 < float(title["condition"]["chance"]) < 0.05, "彩蛋概率必须极低"

    def test_title_ids_unique(self):
        ids = [t["id"] for t in CONFIG.titles["titles"]]
        assert len(ids) == len(set(ids))

    def test_deterministic_engine_never_awards_eggs(self):
        """彩蛋称号不能由确定性条件引擎（按鱼获记录）发放。"""
        from app.services import titles as titles_service

        ctx = {"ids": set(), "kind": {}, "rarity": {}, "species": 0, "count": 0}
        for title in CONFIG.titles["titles"]:
            if title["condition"].get("type") == "random_drop":
                assert titles_service.matches(title["condition"], ctx) is False

    @pytest.mark.asyncio
    async def test_no_rolls_no_title(self, auth_client, session_factory):
        from app.services import titles as titles_service

        me = (await auth_client.get("/api/v1/auth/me")).json()
        async with session_factory() as db:
            assert await titles_service.roll_random_titles(db, me["id"], "gather", rolls=0) == []
            assert await titles_service.roll_random_titles(db, me["id"], "nope", rolls=10) == []

    @pytest.mark.asyncio
    async def test_many_rolls_unlock_then_stop_repeating(self, auth_client, session_factory):
        from app.models import UserTitle
        from app.services import titles as titles_service

        me = (await auth_client.get("/api/v1/auth/me")).json()
        async with session_factory() as db:
            new = await titles_service.roll_random_titles(db, me["id"], "gather", rolls=1_000_000)
            await db.commit()
            assert len(new) == len(titles_service.random_drop_titles("gather"))
            owned = set(
                (await db.execute(
                    select(UserTitle.title_id).where(UserTitle.user_id == me["id"])
                )).scalars().all()
            )
            assert set(new) <= owned
            # 已拥有 → 不再重复发放
            assert await titles_service.roll_random_titles(db, me["id"], "gather", rolls=1_000_000) == []
            # 另一事件的彩蛋不受影响
            assert await titles_service.roll_random_titles(db, me["id"], "treasure_bottom", rolls=0) == []

    @pytest.mark.asyncio
    async def test_gather_report_carries_new_titles(self, auth_client, session_factory):
        start = await auth_client.post("/api/v1/gather/session/start", json={"jobId": "MIN", "regionId": 1})
        assert start.status_code == 200, start.text
        session_id = start.json()["sessionId"]
        async with session_factory() as db:
            from app.models import ActivitySession

            row = (await db.execute(select(ActivitySession).where(ActivitySession.id == session_id))).scalar_one()
            _backdate(row, 20)
            await db.commit()
        rep = await auth_client.post("/api/v1/gather/session/report", json={"sessionId": session_id})
        assert rep.status_code == 200, rep.text
        assert isinstance(rep.json()["newTitles"], list)

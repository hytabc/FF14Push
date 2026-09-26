"""重建伊修加德：阶段推进 / 轮次 / 阶段锁定 / 称号 / 主手装备 / 紫色附魔。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import (
    ActivitySession,
    IshgardMember,
    IshgardState,
    IshgardTool,
    Item,
    StackItem,
    User,
    UserTitle,
)

PREFIX = "/api/v1/ishgard"


async def _user_id(session_factory) -> int:
    async with session_factory() as db:
        return int((await db.execute(select(User.id).where(User.username == "tester"))).scalar_one())


async def _add_stack(session_factory, user_id: int, item_id: str, count: int) -> None:
    async with session_factory() as db:
        row = (
            await db.execute(
                select(StackItem).where(
                    StackItem.user_id == user_id,
                    StackItem.kind == "ishgard",
                    StackItem.item_id == item_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(StackItem(user_id=user_id, kind="ishgard", item_id=item_id, count=count))
        else:
            row.count = int(row.count) + count
        await db.commit()


async def _stack_count(session_factory, user_id: int, item_id: str) -> int:
    async with session_factory() as db:
        row = (
            await db.execute(
                select(StackItem).where(
                    StackItem.user_id == user_id,
                    StackItem.kind == "ishgard",
                    StackItem.item_id == item_id,
                )
            )
        ).scalar_one_or_none()
        return int(row.count) if row else 0


async def _state(session_factory) -> IshgardState:
    async with session_factory() as db:
        return await db.get(IshgardState, 1)


async def _tune_state(session_factory, **values) -> None:
    from app.services import ishgard as ishgard_service

    async with session_factory() as db:
        state = await db.get(IshgardState, 1)
        if state is None:
            state = await ishgard_service.get_state(db)
        for key, value in values.items():
            setattr(state, key, value)
        await db.commit()


async def _set_points(session_factory, user_id: int, points: int) -> None:
    async with session_factory() as db:
        row = (
            await db.execute(select(IshgardMember).where(IshgardMember.user_id == user_id))
        ).scalar_one_or_none()
        if row is None:
            db.add(IshgardMember(user_id=user_id, points=points))
        else:
            row.points = points
        await db.commit()


async def _rewind_session(session_factory, session_id: int, seconds: float = 120.0) -> None:
    async with session_factory() as db:
        row = await db.get(ActivitySession, session_id)
        row.last_report_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        await db.commit()


# ------------------------------------------------------------------ 状态
async def test_state_shape_and_naming(auth_client):
    resp = await auth_client.get(f"{PREFIX}/state")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stage"] == 1 and body["round"] == 1 and body["stageCount"] == 5
    assert body["stageTarget"] == 1_000_000
    assert len(body["stageTargets"]) == 5
    # 物资显示名按阶段生成
    assert body["current"]["materials"][0]["name"].startswith("第1次重建用的")
    products = body["current"]["products"]
    assert {p["itemId"] for p in products} == {"s1_p_scaffold", "s1_p_coating"}
    assert all(p["points"] > 0 for p in products)
    # 两件主手 + 8 条紫色附魔
    assert body["tools"]["doh"]["level"] == 0 and body["tools"]["dol"]["level"] == 0
    assert len(body["pinkEnchants"]) == 8
    assert body["bag"] == []
    # 有效加成（专用装备 + 紫色附魔 + 食物 / 秘药）随状态下发，供页面展示
    assert isinstance(body["bonus"], dict)


# ------------------------------------------------------------------ 采集 / 生产 / 提交
async def test_gather_produce_submit_flow(auth_client, session_factory):
    user_id = await _user_id(session_factory)

    # 采集（采矿）：把窗口回拨 2 分钟即可结算若干次动作
    started = await auth_client.post(f"{PREFIX}/gather/session/start", json={"jobId": "MIN"})
    assert started.status_code == 200, started.text
    await _rewind_session(session_factory, started.json()["sessionId"])
    report = await auth_client.post(
        f"{PREFIX}/gather/session/report", json={"sessionId": started.json()["sessionId"]}
    )
    assert report.status_code == 200, report.text
    assert report.json()["actions"] > 0
    assert await _stack_count(session_factory, user_id, "s1_m_limestone") > 0

    # 生产：补充材料后制作 1 件产物
    await _add_stack(session_factory, user_id, "s1_m_spruce", 10)
    produce = await auth_client.post(
        f"{PREFIX}/produce/session/start",
        json={"jobId": "CRP", "recipeId": "s1_p_scaffold", "count": 1},
    )
    assert produce.status_code == 200, produce.text
    await _rewind_session(session_factory, produce.json()["sessionId"])
    crafted = await auth_client.post(
        f"{PREFIX}/produce/session/report", json={"sessionId": produce.json()["sessionId"]}
    )
    assert crafted.status_code == 200, crafted.text
    assert crafted.json()["crafts"] == 1
    assert await _stack_count(session_factory, user_id, "s1_p_scaffold") == 1

    # 提交：获得 20 分，个人与全服进度同步
    submitted = await auth_client.post(
        f"{PREFIX}/submit", json={"itemId": "s1_p_scaffold", "count": 1}
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["gained"] == 20
    assert (await _state(session_factory)).stage_points == 20
    assert (await auth_client.get(f"{PREFIX}/state")).json()["myPoints"] == 20


async def test_gather_rejects_fisher(auth_client):
    resp = await auth_client.post(f"{PREFIX}/gather/session/start", json={"jobId": "FSH"})
    assert resp.status_code == 400


async def _use(auth_client, session_factory, user_id: int, kind: str, item_id: str) -> None:
    async with session_factory() as db:
        db.add(StackItem(user_id=user_id, kind=kind, item_id=item_id, count=1))
        await db.commit()
    used = await auth_client.post("/api/v1/consumable/use", json={"itemId": item_id})
    assert used.status_code == 200, used.text


async def test_state_bonus_merges_gear_and_consumables(auth_client, session_factory):
    """有效加成 = 专用装备（含紫色附魔）+ 食物 / 秘药，随状态下发。"""
    user_id = await _user_id(session_factory)
    await _set_points(session_factory, user_id, 50_000)
    await _tune_state(session_factory, stage=2, stage_points=0, stage_target=3_000_000)
    claimed = await auth_client.post(f"{PREFIX}/tool/claim", json={"kind": "dol"})
    assert claimed.status_code == 200, claimed.text
    equipped = await auth_client.post(
        "/api/v1/dohdol/equip", json={"itemId": claimed.json()["itemId"], "slot": "dolTool"}
    )
    assert equipped.status_code == 200, equipped.text

    await _use(auth_client, session_factory, user_id, "potion", "p_gatherYieldPct")
    await _use(auth_client, session_factory, user_id, "food", "f_craftQualityPct")

    body = (await auth_client.get(f"{PREFIX}/state")).json()
    # 20 级采集主手固定加成 11.52% + 采集产量秘药 30% 合并计入（词条可能更高）
    assert body["bonus"]["gatherYieldPct"] >= 11.52 + 30.0 - 1e-6
    # 制造品质料理 4%（与采集加成同源，仅键不同）
    assert body["bonus"]["craftQualityPct"] >= 4.0


async def test_gather_applies_consumable_exp_bonus(auth_client, session_factory):
    user_id = await _user_id(session_factory)
    await _use(auth_client, session_factory, user_id, "potion", "p_expGainPct")

    started = await auth_client.post(f"{PREFIX}/gather/session/start", json={"jobId": "MIN"})
    assert started.status_code == 200, started.text
    await _rewind_session(session_factory, started.json()["sessionId"])
    report = await auth_client.post(
        f"{PREFIX}/gather/session/report", json={"sessionId": started.json()["sessionId"]}
    )
    assert report.status_code == 200, report.text
    sources = {s["label"]: s["pct"] for s in report.json()["xpBreakdown"]["sources"]}
    assert sources["经验获取秘药"] == pytest.approx(25.0)


async def test_produce_applies_consumable_exp_bonus(auth_client, session_factory):
    user_id = await _user_id(session_factory)
    await _use(auth_client, session_factory, user_id, "potion", "p_expGainPct")
    await _add_stack(session_factory, user_id, "s1_m_spruce", 10)

    started = await auth_client.post(
        f"{PREFIX}/produce/session/start",
        json={"jobId": "CRP", "recipeId": "s1_p_scaffold", "count": 1},
    )
    assert started.status_code == 200, started.text
    await _rewind_session(session_factory, started.json()["sessionId"])
    report = await auth_client.post(
        f"{PREFIX}/produce/session/report", json={"sessionId": started.json()["sessionId"]}
    )
    assert report.status_code == 200, report.text
    sources = {s["label"]: s["pct"] for s in report.json()["xpBreakdown"]["sources"]}
    assert sources["经验获取秘药"] == pytest.approx(25.0)


# ------------------------------------------------------------------ 阶段推进 / 轮次
async def test_stage_advance_and_carry_over(auth_client, session_factory):
    user_id = await _user_id(session_factory)
    await _add_stack(session_factory, user_id, "s1_p_scaffold", 60_000)
    # 每件 20 分 → 1,200,000 分：跨过第一阶段（100W），余 20W 结转
    resp = await auth_client.post(
        f"{PREFIX}/submit", json={"itemId": "s1_p_scaffold", "count": 60_000}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["completedStages"] == [1]
    assert body["stage"] == 2 and body["stagePoints"] == 200_000
    assert body["round"] == 1


async def test_round_rollover(auth_client, session_factory):
    user_id = await _user_id(session_factory)
    await _add_stack(session_factory, user_id, "s5_p_skyframe", 2000)
    # 直接放到第 5 阶段，只差一点点
    await _tune_state(session_factory, stage=5, stage_points=49_999_900, stage_target=50_000_000)
    resp = await auth_client.post(
        f"{PREFIX}/submit", json={"itemId": "s5_p_skyframe", "count": 2}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["completedStages"] == [5]
    assert body["round"] == 2 and body["stage"] == 1 and body["stagePoints"] == 0
    # 个人积分保留
    assert body["points"] == 160


# ------------------------------------------------------------------ 阶段锁定
async def test_stage_lock_blocks_cross_stage_submit(auth_client, session_factory):
    user_id = await _user_id(session_factory)
    await _add_stack(session_factory, user_id, "s2_p_steelbeam", 5)
    resp = await auth_client.post(f"{PREFIX}/submit", json={"itemId": "s2_p_steelbeam", "count": 1})
    assert resp.status_code == 400


async def test_stage_lock_blocks_cross_stage_produce(auth_client, session_factory):
    user_id = await _user_id(session_factory)
    await _add_stack(session_factory, user_id, "s2_m_ironore", 10)
    resp = await auth_client.post(
        f"{PREFIX}/produce/session/start",
        json={"jobId": "BSM", "recipeId": "s2_p_steelbeam", "count": 1},
    )
    assert resp.status_code == 400


async def test_submit_rejects_non_product(auth_client, session_factory):
    user_id = await _user_id(session_factory)
    await _add_stack(session_factory, user_id, "s1_m_limestone", 5)
    assert (await auth_client.post(
        f"{PREFIX}/submit", json={"itemId": "s1_m_limestone", "count": 1}
    )).status_code == 400
    assert (await auth_client.post(
        f"{PREFIX}/submit", json={"itemId": "g_ore", "count": 1}
    )).status_code == 400


async def _gold(session_factory, user_id: int) -> int:
    async with session_factory() as db:
        return int((await db.execute(select(User.gold).where(User.id == user_id))).scalar_one())


async def test_sell_expired_material(auth_client, session_factory):
    user_id = await _user_id(session_factory)
    await _add_stack(session_factory, user_id, "s1_m_limestone", 10)
    before = await _gold(session_factory, user_id)
    resp = await auth_client.post(f"{PREFIX}/sell", json={"itemId": "s1_m_limestone", "count": 4})
    assert resp.status_code == 200, resp.text
    assert resp.json()["gold"] == 40  # 单价 10 × 4
    assert await _stack_count(session_factory, user_id, "s1_m_limestone") == 6
    assert await _gold(session_factory, user_id) == before + 40


# ------------------------------------------------------------------ 称号
async def test_title_settlement_unique_and_sticky(auth_client, session_factory):
    user_id = await _user_id(session_factory)
    await _set_points(session_factory, user_id, 1000)
    # 造一个第二名账号（积分榜不要求英雄，只需非管理员 / 未封禁）
    from app.core.security import hash_password

    async with session_factory() as db:
        rival = User(
            username="rival", password_hash=hash_password("secret123"), nickname="对手", gold=0
        )
        db.add(rival)
        await db.flush()
        other_id = int(rival.id)
        db.add(IshgardMember(user_id=other_id, points=500))
        await db.commit()

    # 让窗口过期 → 结算
    await _tune_state(session_factory, title_period_ends_at=0.0)
    state = (await auth_client.get(f"{PREFIX}/state")).json()
    assert state["saint"]["nickname"] == "光之战士"
    assert state["apostle"]["nickname"] == "对手"

    async with session_factory() as db:
        rows = (await db.execute(select(UserTitle))).scalars().all()
        owned = {r.title_id: r.user_id for r in rows}
    assert owned["ishgard_saint"] == user_id
    assert owned["ishgard_apostle"] == other_id

    # 仍居第一（未被人严格超越）→ 保持不变
    await _tune_state(session_factory, title_period_ends_at=0.0)
    await _set_points(session_factory, user_id, 900)
    await auth_client.get(f"{PREFIX}/state")
    async with session_factory() as db:
        holder = (
            await db.execute(select(UserTitle.user_id).where(UserTitle.title_id == "ishgard_saint"))
        ).scalar_one()
    assert holder == user_id

    # 严格被超越 → 圣人转移给对手；对手不得同时持有圣徒（改判给原持有人）
    await _tune_state(session_factory, title_period_ends_at=0.0)
    await _set_points(session_factory, user_id, 400)
    async with session_factory() as db:
        rival = (
            await db.execute(select(IshgardMember).where(IshgardMember.user_id == other_id))
        ).scalar_one()
        rival.points = 9999
        await db.commit()
    await auth_client.get(f"{PREFIX}/state")
    async with session_factory() as db:
        owned = {
            r.title_id: r.user_id for r in (await db.execute(select(UserTitle))).scalars().all()
        }
    assert owned["ishgard_saint"] == other_id
    assert owned["ishgard_apostle"] == user_id


# ------------------------------------------------------------------ 主手装备 + 紫色附魔
async def test_tool_claim_requires_points_and_stage(auth_client, session_factory):
    # 积分不足
    assert (await auth_client.post(f"{PREFIX}/tool/claim", json={"kind": "doh"})).status_code == 400

    user_id = await _user_id(session_factory)
    await _set_points(session_factory, user_id, 50_000)
    # 积分达标但阶段未完成（仍在第 1 阶段）
    assert (await auth_client.post(f"{PREFIX}/tool/claim", json={"kind": "doh"})).status_code == 400

    await _tune_state(session_factory, stage=2, stage_points=0, stage_target=3_000_000)
    resp = await auth_client.post(f"{PREFIX}/tool/claim", json={"kind": "doh"})
    assert resp.status_code == 200, resp.text
    tool = resp.json()
    assert tool["level"] == 20 and tool["slot"] == "dohTool"
    assert tool["bonus"] == {"craftQualityPct": 7.68, "craftRarityPct": 5.76}
    assert tool["pink"]["kind"] == "doh" and tool["pink"]["values"]
    assert len(tool["pink"]["values"]) >= 1

    # 幂等：再次领取返回同一结果
    again = await auth_client.post(f"{PREFIX}/tool/claim", json={"kind": "doh"})
    assert again.json()["level"] == 20

    # 升级：积分不足时拒绝
    assert (await auth_client.post(f"{PREFIX}/tool/upgrade", json={"kind": "doh"})).status_code == 400
    await _tune_state(session_factory, stage=3, stage_points=0, stage_target=8_000_000)
    await _set_points(session_factory, user_id, 250_000)
    up = await auth_client.post(f"{PREFIX}/tool/upgrade", json={"kind": "doh"})
    assert up.status_code == 200, up.text
    assert up.json()["level"] == 40
    assert up.json()["bonus"] == {"craftQualityPct": 12.0, "craftRarityPct": 9.0}


async def test_pink_reroll_consumes_card(auth_client, session_factory):
    user_id = await _user_id(session_factory)
    await _set_points(session_factory, user_id, 50_000)
    await _tune_state(session_factory, stage=2, stage_points=0, stage_target=3_000_000)
    claimed = await auth_client.post(f"{PREFIX}/tool/claim", json={"kind": "dol"})
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["pink"]["kind"] == "dol"

    # 没有重新打造卡 → 拒绝
    assert (await auth_client.post(f"{PREFIX}/tool/enchant", json={"kind": "dol"})).status_code == 400

    async with session_factory() as db:
        db.add(StackItem(user_id=user_id, kind="card", item_id="recraft_card", count=3))
        await db.commit()
    resp = await auth_client.post(f"{PREFIX}/tool/enchant", json={"kind": "dol"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["pink"]["kind"] == "dol"
    async with session_factory() as db:
        left = (
            await db.execute(
                select(StackItem.count).where(
                    StackItem.user_id == user_id,
                    StackItem.kind == "card",
                    StackItem.item_id == "recraft_card",
                )
            )
        ).scalar_one()
    assert int(left) == 2


async def test_purple_effects_require_equipped_tool(auth_client, session_factory):
    from app.services import ishgard as ishgard_service

    user_id = await _user_id(session_factory)
    await _set_points(session_factory, user_id, 50_000)
    await _tune_state(session_factory, stage=2, stage_points=0, stage_target=3_000_000)
    await auth_client.post(f"{PREFIX}/tool/claim", json={"kind": "doh"})

    async with session_factory() as db:
        assert await ishgard_service.purple_effects(db, user_id) == {}
        tool = (
            await db.execute(select(IshgardTool).where(IshgardTool.user_id == user_id))
        ).scalar_one()
        tool.pink_values = {"craftQualityPct": 25.0}
        await db.commit()

    async with session_factory() as db:
        # 未装备 → 不生效
        assert await ishgard_service.purple_effects(db, user_id) == {}
        item = await db.get(Item, int(
            (await db.execute(select(IshgardTool.item_id).where(IshgardTool.user_id == user_id))).scalar_one()
        ))
        item.equipped_slot = "dohTool"
        await db.commit()

    async with session_factory() as db:
        # 已装备 → 生效
        assert await ishgard_service.purple_effects(db, user_id) == {"craftQualityPct": 25.0}

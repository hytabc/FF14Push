from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Hero, User
from app.services.game_config import CONFIG
from app.services.progression import apply_exp, catch_up_exp, combat_exp, exp_to_next


def old_exp(level):
    curve = CONFIG.heroes['expCurve']
    return round(curve['base'] * curve['growth'] ** (level - 1))


def test_late_level_curve_reduction_and_monotonicity():
    for level in range(1, 60):
        assert exp_to_next(level) == old_exp(level)
    for level in range(60, 100):
        assert .69 < exp_to_next(level) / old_exp(level) < .91
    assert exp_to_next(60) == pytest.approx(old_exp(60) * .9, abs=1)
    assert exp_to_next(99) == pytest.approx(old_exp(99) * .7, abs=1)
    assert all(exp_to_next(level + 1) > exp_to_next(level) for level in range(1, 100))


@pytest.mark.parametrize('level,highest,expected', [(10, 60, 200), (60, 60, 100), (61, 60, 100), (100, 100, 100)])
def test_catch_up_only_for_lower_level(level, highest, expected):
    assert catch_up_exp(SimpleNamespace(level=level, exp=0), 100, highest) == expected


@pytest.mark.parametrize('gap', [1, 2, 99, 100])
def test_large_reward_stops_bonus_at_highest_level(gap):
    hero = SimpleNamespace(level=59, exp=exp_to_next(59) - gap)
    amount = catch_up_exp(hero, 1000, 60)
    assert amount == 1000 + gap // 2
    apply_exp(hero, amount)
    assert hero.level == 60
    assert catch_up_exp(hero, 100, 60) == 100


def test_catch_up_across_multiple_levels_and_level_cap():
    hero = SimpleNamespace(level=98, exp=0)
    gap = exp_to_next(98) + exp_to_next(99)
    amount = catch_up_exp(hero, gap, 100)
    assert amount == gap + gap // 2
    apply_exp(hero, amount)
    assert hero.level == 100 and hero.exp == 0


def test_existing_exp_preserved_when_new_curve_levels_up():
    hero = SimpleNamespace(level=70, exp=old_exp(70) - 1)
    before = hero.exp
    apply_exp(hero, 1)
    assert hero.level == 71
    assert hero.exp == before + 1 - exp_to_next(70)


async def test_account_scoped_bonus_and_state(auth_client, session_factory):
    async with session_factory() as db:
        hero = (await db.scalars(select(Hero))).first()
        hero.level = 10
        user_id = hero.user_id
        assert await combat_exp(db, hero, 100) == 100
        other = User(username='other', password_hash='unused', nickname='other')
        db.add(other)
        await db.flush()
        db.add(Hero(user_id=other.id, name='其他账号', level=100, talent='common', attr_bias='balanced'))
        await db.flush()
        assert await combat_exp(db, hero, 100) == 100
        senior = Hero(user_id=user_id, name='高等级英雄', level=60, talent='common', attr_bias='balanced')
        db.add(senior)
        await db.flush()
        assert await combat_exp(db, hero, 100) == 200
        assert await combat_exp(db, senior, 100) == 100
        await db.commit()
    state = (await auth_client.get('/api/v1/game/state')).json()
    assert state['catchUpExpBonusPct'] == 100
    async with session_factory() as db:
        hero = await db.get(Hero, state['hero']['id'])
        hero.level = 60
        await db.commit()
    state = (await auth_client.get('/api/v1/game/state')).json()
    assert state['catchUpExpBonusPct'] == 0
    assert state['expToNext'] == exp_to_next(60)

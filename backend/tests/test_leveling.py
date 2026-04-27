"""Тесты XP/leveling pure functions."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from wotk.game.leveling import (
    MAX_LEVEL,
    STAT_POINTS_PER_LEVEL,
    apply_xp,
    compute_level,
    xp_for_level,
)


@dataclass
class FakeHero:
    xp: int
    level: int
    unspent_points: dict


def test_xp_for_level_1_is_zero() -> None:
    assert xp_for_level(1) == 0


def test_xp_for_level_monotonically_increasing() -> None:
    last = -1
    for lvl in range(1, MAX_LEVEL + 1):
        x = xp_for_level(lvl)
        assert x > last
        last = x


def test_compute_level_at_zero_xp() -> None:
    assert compute_level(0) == 1


def test_compute_level_at_threshold() -> None:
    # XP ровно для лвл 2 → лвл 2
    assert compute_level(xp_for_level(2)) == 2


def test_compute_level_just_below_threshold() -> None:
    assert compute_level(xp_for_level(2) - 1) == 1


def test_compute_level_invariant_holds_for_random_xp() -> None:
    """xp_for_level(L) <= xp < xp_for_level(L+1) для всех L."""
    for sample_xp in [0, 100, 500, 1000, 5000, 50_000, 500_000, 1_000_000]:
        lvl = compute_level(sample_xp)
        assert xp_for_level(lvl) <= sample_xp
        if lvl < MAX_LEVEL:
            assert sample_xp < xp_for_level(lvl + 1)


def test_compute_level_caps_at_max() -> None:
    huge = xp_for_level(MAX_LEVEL) * 100
    assert compute_level(huge) == MAX_LEVEL


def test_compute_level_negative_raises() -> None:
    with pytest.raises(ValueError):
        compute_level(-1)


def test_apply_xp_no_level_up() -> None:
    hero = FakeHero(xp=10, level=1, unspent_points={"stat": 0, "skill": 0})
    result = apply_xp(hero, 50)
    assert result.levels_gained == 0
    assert result.stat_points_awarded == 0
    assert hero.xp == 60
    assert hero.level == 1
    assert hero.unspent_points["stat"] == 0


def test_apply_xp_single_level_up() -> None:
    hero = FakeHero(xp=0, level=1, unspent_points={"stat": 0, "skill": 0})
    target_xp = xp_for_level(2)
    result = apply_xp(hero, target_xp)
    assert result.levels_gained == 1
    assert result.stat_points_awarded == STAT_POINTS_PER_LEVEL
    assert hero.level == 2
    assert hero.unspent_points["stat"] == STAT_POINTS_PER_LEVEL


def test_apply_xp_multi_level_up() -> None:
    """Зашёл на lvl 1, сразу заработал XP до lvl 5 → +4 уровня = +12 stat points."""
    hero = FakeHero(xp=0, level=1, unspent_points={"stat": 0, "skill": 0})
    huge = xp_for_level(5)
    result = apply_xp(hero, huge)
    assert hero.level == 5
    assert result.levels_gained == 4
    assert result.stat_points_awarded == 4 * STAT_POINTS_PER_LEVEL
    assert hero.unspent_points["stat"] == 4 * STAT_POINTS_PER_LEVEL


def test_apply_xp_invariant_level_equals_compute() -> None:
    """После apply_xp всегда: hero.level == compute_level(hero.xp)."""
    hero = FakeHero(xp=100, level=1, unspent_points={"stat": 0, "skill": 0})
    apply_xp(hero, 1_000_000)
    assert hero.level == compute_level(hero.xp)


def test_apply_xp_negative_raises() -> None:
    hero = FakeHero(xp=100, level=1, unspent_points={"stat": 0, "skill": 0})
    with pytest.raises(ValueError):
        apply_xp(hero, -1)


def test_apply_xp_preserves_skill_points() -> None:
    hero = FakeHero(xp=0, level=1, unspent_points={"stat": 5, "skill": 2})
    apply_xp(hero, xp_for_level(3))
    assert hero.unspent_points["skill"] == 2  # не трогаем skill points
    assert hero.unspent_points["stat"] == 5 + 2 * STAT_POINTS_PER_LEVEL

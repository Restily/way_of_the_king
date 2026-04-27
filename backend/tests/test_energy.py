"""Тесты energy regen pure function."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from wotk.game.energy import ENERGY_TICK_SECONDS, compute_regenerated


def test_no_regen_when_at_cap() -> None:
    base = datetime(2026, 4, 27, tzinfo=UTC)
    state = compute_regenerated(
        energy=100,
        energy_cap=100,
        energy_updated_at=base,
        now=base + timedelta(hours=24),
    )
    assert state.energy == 100
    assert state.energy_updated_at == base


def test_no_regen_when_no_full_tick_passed() -> None:
    base = datetime(2026, 4, 27, tzinfo=UTC)
    state = compute_regenerated(
        energy=50,
        energy_cap=100,
        energy_updated_at=base,
        now=base + timedelta(seconds=ENERGY_TICK_SECONDS - 1),
    )
    assert state.energy == 50
    assert state.energy_updated_at == base


def test_single_tick_regen() -> None:
    base = datetime(2026, 4, 27, tzinfo=UTC)
    state = compute_regenerated(
        energy=50,
        energy_cap=100,
        energy_updated_at=base,
        now=base + timedelta(seconds=ENERGY_TICK_SECONDS),
    )
    assert state.energy == 51
    assert state.energy_updated_at == base + timedelta(seconds=ENERGY_TICK_SECONDS)


def test_multiple_ticks_regen() -> None:
    base = datetime(2026, 4, 27, tzinfo=UTC)
    state = compute_regenerated(
        energy=50,
        energy_cap=100,
        energy_updated_at=base,
        now=base + timedelta(seconds=ENERGY_TICK_SECONDS * 5 + 30),
    )
    assert state.energy == 55
    # carry-over: дробное время не теряется
    assert state.energy_updated_at == base + timedelta(
        seconds=ENERGY_TICK_SECONDS * 5
    )


def test_regen_capped() -> None:
    base = datetime(2026, 4, 27, tzinfo=UTC)
    state = compute_regenerated(
        energy=98,
        energy_cap=100,
        energy_updated_at=base,
        now=base + timedelta(hours=24),  # много тиков
    )
    assert state.energy == 100  # capped


def test_pure_function_does_not_mutate_input() -> None:
    """Проверка чистоты — компилятор бы вычислил, но явный тест не помешает."""
    base = datetime(2026, 4, 27, tzinfo=UTC)
    state = compute_regenerated(
        energy=50,
        energy_cap=100,
        energy_updated_at=base,
        now=base + timedelta(hours=2),
    )
    # base должен быть нетронут
    assert base == datetime(2026, 4, 27, tzinfo=UTC)
    assert state.energy != 50  # был регент

"""Тесты loot-генерации.

Проверяем:

* Распределение affix_count по rarity (статистика на 10k роллов).
* Mod_group exclusion: один и тот же mod_group не появляется дважды.
* ilvl gating: low-tier аффиксы не появляются на high-ilvl только если
  фильтр работает.
* Determinism: один seed → идентичный результат.
* Tag-based weight override (leftmost wins).
* Side limits: MAGIC ≤ 1+1, RARE ≤ 3+3.
* Pure function: одинаковый input даёт одинаковый output.
"""

from __future__ import annotations

import random
from collections import Counter

import pytest

from wotk.game.loot import (
    AFFIX_COUNT_DISTRIBUTION,
    SIDE_LIMITS,
    AffixDefinition,
    AffixType,
    Rarity,
    RolledAffix,
    effective_weight,
    generate_affixes,
    generate_item,
    roll_quality_pct,
    sample_affix_count,
)


# ============================================================================
# Fixtures: mini affix pool covering 6 mod_groups across all slots
# ============================================================================


#: Стабильные id-константы для in-pool аффиксов (используются в assertions).
LIFE_FLAT_T1 = 1
LIFE_FLAT_T2 = 2
STR_FLAT_T1 = 3
ATK_PCT_T1 = 4
CRIT_PCT_T1 = 5
RESIST_FIRE_T1 = 6


def _affix_pool() -> tuple[AffixDefinition, ...]:
    """Маленький pool: 6 аффиксов по 5 mod_groups (4 префикса, 2 суффикса)."""
    return (
        AffixDefinition(
            id=LIFE_FLAT_T1,
            affix_type=AffixType.PREFIX,
            mod_group="life_flat",
            mod_type="flat_hp",
            tier=1,
            applicable_slots=(0, 1, 2, 3, 4, 5),
            min_ilvl=1,
            weight=100,
            value_min=10,
            value_max=20,
        ),
        AffixDefinition(
            id=LIFE_FLAT_T2,
            affix_type=AffixType.PREFIX,
            mod_group="life_flat",
            mod_type="flat_hp",
            tier=2,
            applicable_slots=(0, 1, 2, 3, 4, 5),
            min_ilvl=20,
            weight=50,
            value_min=21,
            value_max=40,
        ),
        AffixDefinition(
            id=STR_FLAT_T1,
            affix_type=AffixType.PREFIX,
            mod_group="str_flat",
            mod_type="flat_str",
            tier=1,
            applicable_slots=(0, 1, 2, 3, 4, 5),
            min_ilvl=1,
            weight=80,
            value_min=2,
            value_max=5,
        ),
        AffixDefinition(
            id=ATK_PCT_T1,
            affix_type=AffixType.PREFIX,
            mod_group="atk_pct",
            mod_type="pct_atk",
            tier=1,
            applicable_slots=(2,),  # weapon-only
            min_ilvl=1,
            weight=120,
            value_min=10,
            value_max=25,
        ),
        AffixDefinition(
            id=CRIT_PCT_T1,
            affix_type=AffixType.SUFFIX,
            mod_group="crit_pct",
            mod_type="pct_crit",
            tier=1,
            applicable_slots=(0, 1, 2, 3, 4, 5),
            min_ilvl=1,
            weight=60,
            value_min=3,
            value_max=8,
        ),
        AffixDefinition(
            id=RESIST_FIRE_T1,
            affix_type=AffixType.SUFFIX,
            mod_group="resist_fire",
            mod_type="pct_resist_fire",
            tier=1,
            applicable_slots=(0, 1, 3, 4, 5),  # без weapon
            min_ilvl=1,
            weight=80,
            value_min=10,
            value_max=20,
        ),
    )


def _seeded_rng(seed: int = 42) -> random.Random:
    return random.Random(seed)


# ============================================================================
# sample_affix_count
# ============================================================================


def test_sample_affix_count_common_always_zero() -> None:
    rng = _seeded_rng()
    for _ in range(100):
        assert sample_affix_count(rng, Rarity.COMMON) == 0


@pytest.mark.parametrize("rarity", [r for r in Rarity if r != Rarity.COMMON])
def test_sample_affix_count_within_distribution(rarity: Rarity) -> None:
    rng = _seeded_rng()
    valid_counts = {c for c, _w in AFFIX_COUNT_DISTRIBUTION[rarity]}
    for _ in range(500):
        n = sample_affix_count(rng, rarity)
        assert n in valid_counts


def test_sample_affix_count_distribution_statistical() -> None:
    """RARE: 70% (3 affixes) / 30% (4 affixes), tolerance ±5%."""
    rng = _seeded_rng()
    counter = Counter(sample_affix_count(rng, Rarity.RARE) for _ in range(10_000))
    p3 = counter[3] / 10_000
    p4 = counter[4] / 10_000
    assert 0.65 < p3 < 0.75, f"P(3)={p3}"
    assert 0.25 < p4 < 0.35, f"P(4)={p4}"


# ============================================================================
# effective_weight
# ============================================================================


def _make_affix(**overrides: object) -> AffixDefinition:
    """Удобный конструктор для weight-тестов."""
    defaults: dict[str, object] = {
        "id": 999,
        "affix_type": AffixType.PREFIX,
        "mod_group": "g",
        "applicable_slots": (0,),
        "min_ilvl": 1,
        "weight": 100,
        "value_min": 1,
        "value_max": 10,
        "mod_type": "test_mod",
    }
    defaults.update(overrides)
    return AffixDefinition(**defaults)  # type: ignore[arg-type]


def test_effective_weight_no_overrides_returns_base() -> None:
    a = _make_affix()
    assert effective_weight(a, ["sword", "weapon"]) == 100


def test_effective_weight_uses_leftmost_tag_match() -> None:
    a = _make_affix(spawn_weights={"sword": 500, "weapon": 1})
    # leftmost = "sword" → 500 (а не 1 от weapon)
    assert effective_weight(a, ["sword", "weapon"]) == 500


def test_effective_weight_zero_means_excluded() -> None:
    a = _make_affix(spawn_weights={"bow": 0})
    assert effective_weight(a, ["bow", "weapon"]) == 0


def test_effective_weight_falls_back_when_no_tag_matches() -> None:
    a = _make_affix(spawn_weights={"unrelated_tag": 999})
    assert effective_weight(a, ["sword", "weapon"]) == 100


# ============================================================================
# generate_affixes
# ============================================================================


def test_common_returns_no_affixes() -> None:
    affixes = generate_affixes(
        _seeded_rng(),
        rarity=Rarity.COMMON,
        slot=2,
        ilvl=1,
        base_tags=["sword"],
        affix_pool=_affix_pool(),
    )
    assert affixes == ()


def test_magic_within_side_limits() -> None:
    pool = _affix_pool()
    for seed in range(50):
        affixes = generate_affixes(
            random.Random(seed),
            rarity=Rarity.MAGIC,
            slot=2,
            ilvl=30,
            base_tags=["sword"],
            affix_pool=pool,
        )
        prefix_n = sum(
            1 for a in affixes if _resolve(pool, a.affix_id).affix_type == AffixType.PREFIX
        )
        suffix_n = len(affixes) - prefix_n
        max_p, max_s = SIDE_LIMITS[Rarity.MAGIC]
        assert prefix_n <= max_p
        assert suffix_n <= max_s


def test_rare_within_side_limits() -> None:
    pool = _affix_pool()
    for seed in range(50):
        affixes = generate_affixes(
            random.Random(seed),
            rarity=Rarity.RARE,
            slot=2,
            ilvl=30,
            base_tags=["sword"],
            affix_pool=pool,
        )
        prefix_n = sum(
            1 for a in affixes if _resolve(pool, a.affix_id).affix_type == AffixType.PREFIX
        )
        suffix_n = len(affixes) - prefix_n
        max_p, max_s = SIDE_LIMITS[Rarity.RARE]
        assert prefix_n <= max_p
        assert suffix_n <= max_s


def test_mod_group_exclusion_no_duplicates() -> None:
    """Один mod_group не должен встречаться дважды на одном предмете."""
    pool = _affix_pool()
    for seed in range(100):
        affixes = generate_affixes(
            random.Random(seed),
            rarity=Rarity.LEGENDARY,
            slot=2,
            ilvl=30,
            base_tags=["sword"],
            affix_pool=pool,
        )
        groups = [_resolve(pool, a.affix_id).mod_group for a in affixes]
        assert len(groups) == len(set(groups)), f"Дубликат mod_group: {groups}"


def test_ilvl_filtering_excludes_high_tier_below_threshold() -> None:
    """На ilvl=10 LIFE_FLAT_T2 (min_ilvl=20) не должен появиться."""
    pool = _affix_pool()
    appeared = set()
    for seed in range(200):
        affixes = generate_affixes(
            random.Random(seed),
            rarity=Rarity.LEGENDARY,
            slot=2,
            ilvl=10,
            base_tags=["sword"],
            affix_pool=pool,
        )
        for a in affixes:
            appeared.add(a.affix_id)
    assert LIFE_FLAT_T2 not in appeared


def test_slot_filtering_weapon_only_affix_excluded_from_helmet() -> None:
    """ATK_PCT_T1 (weapon-only, slot=2) не должен попасть на helmet (slot=0)."""
    pool = _affix_pool()
    appeared = set()
    for seed in range(200):
        affixes = generate_affixes(
            random.Random(seed),
            rarity=Rarity.LEGENDARY,
            slot=0,  # helmet
            ilvl=30,
            base_tags=["plate", "armor"],
            affix_pool=pool,
        )
        for a in affixes:
            appeared.add(a.affix_id)
    assert ATK_PCT_T1 not in appeared


def test_value_within_range() -> None:
    pool = _affix_pool()
    by_id = {a.id: a for a in pool}
    for seed in range(100):
        affixes = generate_affixes(
            random.Random(seed),
            rarity=Rarity.LEGENDARY,
            slot=2,
            ilvl=30,
            base_tags=["sword"],
            affix_pool=pool,
        )
        for rolled in affixes:
            defn = by_id[rolled.affix_id]
            assert defn.value_min <= rolled.value <= defn.value_max


def test_determinism_same_seed_same_result() -> None:
    pool = _affix_pool()
    args = dict(
        rarity=Rarity.RARE,
        slot=2,
        ilvl=30,
        base_tags=["sword"],
        affix_pool=pool,
    )
    a = generate_affixes(random.Random(123), **args)
    b = generate_affixes(random.Random(123), **args)
    assert a == b


def test_different_seeds_different_results() -> None:
    pool = _affix_pool()
    args = dict(
        rarity=Rarity.LEGENDARY,
        slot=2,
        ilvl=30,
        base_tags=["sword"],
        affix_pool=pool,
    )
    results = {
        generate_affixes(random.Random(seed), **args) for seed in range(20)
    }
    # Минимум 5 разных результатов из 20 разных seed'ов
    assert len(results) > 5


def test_empty_pool_returns_empty() -> None:
    affixes = generate_affixes(
        _seeded_rng(),
        rarity=Rarity.RARE,
        slot=2,
        ilvl=30,
        base_tags=["sword"],
        affix_pool=(),
    )
    assert affixes == ()


def test_spawn_weight_override_zeroes_pool() -> None:
    """Если spawn_weights = 0 для тегов base'а — аффикс никогда не появится."""
    forbidden_id = 9001
    pool = (
        AffixDefinition(
            id=forbidden_id,
            affix_type=AffixType.PREFIX,
            mod_group="x",
            applicable_slots=(2,),
            min_ilvl=1,
            weight=99999,
            value_min=1,
            value_max=10,
            mod_type="forbidden",
            spawn_weights={"sword": 0},
        ),
    )
    appeared = set()
    for seed in range(50):
        affixes = generate_affixes(
            random.Random(seed),
            rarity=Rarity.LEGENDARY,
            slot=2,
            ilvl=30,
            base_tags=["sword", "weapon"],
            affix_pool=pool,
        )
        for a in affixes:
            appeared.add(a.affix_id)
    assert forbidden_id not in appeared


# ============================================================================
# generate_item (high-level wrapper)
# ============================================================================


def test_generate_item_full_object() -> None:
    pool = _affix_pool()
    item = generate_item(
        random.Random(7),
        base_id=42,
        slot=2,
        ilvl=30,
        rarity=Rarity.RARE,
        base_tags=["sword", "two_handed", "weapon"],
        affix_pool=pool,
    )
    assert item.base_id == 42
    assert item.slot == 2
    assert item.ilvl == 30
    assert item.rarity == Rarity.RARE
    assert all(isinstance(a, RolledAffix) for a in item.affixes)


# ============================================================================
# roll_quality_pct
# ============================================================================


def test_quality_min_value_is_zero_pct() -> None:
    assert roll_quality_pct(10, 10, 100) == 0


def test_quality_max_value_is_100_pct() -> None:
    assert roll_quality_pct(100, 10, 100) == 100


def test_quality_mid_value_is_about_50_pct() -> None:
    assert roll_quality_pct(55, 10, 100) == 50


def test_quality_degenerate_range() -> None:
    """value_min == value_max → всегда 100% (нет диапазона для tier)."""
    assert roll_quality_pct(5, 5, 5) == 100


def test_quality_clamped() -> None:
    # value за пределами диапазона (theoretical, не должно happen в норме)
    assert roll_quality_pct(200, 10, 100) == 100
    assert roll_quality_pct(0, 10, 100) == 0


# ============================================================================
# Helpers
# ============================================================================


def _resolve(
    pool: tuple[AffixDefinition, ...], affix_id: int
) -> AffixDefinition:
    return next(a for a in pool if a.id == affix_id)

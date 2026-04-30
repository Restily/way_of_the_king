"""Тесты combat.py / cooldowns.py / skills.py / drops.py — pure functions без БД."""

from __future__ import annotations

import random

import pytest

from wotk.game.combat import (
    MIN_DAMAGE,
    RESIST_CAP,
    AttackerStats,
    DamageType,
    DefenderStats,
    apply_resistance,
    compute_damage,
)
from wotk.game.cooldowns import CooldownTracker
from wotk.game.drops import on_mob_killed
from wotk.game.loot import AffixDefinition, AffixType, Rarity
from wotk.game.mobs import MOBS
from wotk.game.skills import KNIGHT_SKILLS


# ---------------------------------------------------------------------------
# apply_resistance
# ---------------------------------------------------------------------------


def test_apply_resistance_zero_no_change() -> None:
    assert apply_resistance(100, 0) == 100


def test_apply_resistance_50pct_halves() -> None:
    assert apply_resistance(100, 50) == 50


def test_apply_resistance_75pct_quarters() -> None:
    assert apply_resistance(100, 75) == 25


def test_apply_resistance_above_cap_clamps() -> None:
    """Resist > RESIST_CAP всё равно даёт RESIST_CAP%."""
    assert apply_resistance(100, 90) == apply_resistance(100, RESIST_CAP)


def test_apply_resistance_negative_amplifies() -> None:
    """Vulnerability (-25%) — урон больше."""
    assert apply_resistance(100, -25) == 125


# ---------------------------------------------------------------------------
# compute_damage — happy path
# ---------------------------------------------------------------------------


def _atk(**kw: object) -> AttackerStats:
    defaults: dict = {"atk": 50}
    defaults.update(kw)
    return AttackerStats(**defaults)  # type: ignore[arg-type]


def _def(**kw: object) -> DefenderStats:
    defaults: dict = {"hp": 100}
    defaults.update(kw)
    return DefenderStats(**defaults)  # type: ignore[arg-type]


def test_basic_damage_no_def_no_resist_no_crit() -> None:
    """skill_mult=1.0, def=0, resist=0, crit=0 → raw = atk * 1.0."""
    rng = random.Random(0)
    res = compute_damage(
        attacker=_atk(atk=100, crit_chance_pct=0),
        defender=_def(def_=0),
        skill_multiplier=1.0,
        damage_type=DamageType.PHYSICAL,
        rng=rng,
    )
    assert res.mitigated == 100
    assert not res.was_crit
    assert not res.was_dodged


def test_skill_multiplier_scales_damage() -> None:
    rng = random.Random(0)
    res = compute_damage(
        attacker=_atk(atk=100),
        defender=_def(def_=0),
        skill_multiplier=2.0,
        damage_type=DamageType.PHYSICAL,
        rng=rng,
    )
    assert res.mitigated == 200


def test_def_mitigates_damage() -> None:
    rng = random.Random(0)
    res = compute_damage(
        attacker=_atk(atk=100),
        defender=_def(def_=30),
        skill_multiplier=1.0,
        damage_type=DamageType.PHYSICAL,
        rng=rng,
    )
    assert res.mitigated == 70


def test_def_floors_at_min_damage() -> None:
    """Высокий def не может полностью обнулить урон."""
    rng = random.Random(0)
    res = compute_damage(
        attacker=_atk(atk=10),
        defender=_def(def_=999),
        skill_multiplier=1.0,
        damage_type=DamageType.PHYSICAL,
        rng=rng,
    )
    assert res.mitigated == MIN_DAMAGE


def test_resistance_after_def() -> None:
    rng = random.Random(0)
    res = compute_damage(
        attacker=_atk(atk=100),
        defender=_def(def_=0, resists={DamageType.FIRE: 50}),
        skill_multiplier=1.0,
        damage_type=DamageType.FIRE,
        rng=rng,
    )
    assert res.mitigated == 50


def test_resistance_only_for_matching_type() -> None:
    """50% fire resist не должен влиять на physical uron."""
    rng = random.Random(0)
    res = compute_damage(
        attacker=_atk(atk=100),
        defender=_def(def_=0, resists={DamageType.FIRE: 75}),
        skill_multiplier=1.0,
        damage_type=DamageType.PHYSICAL,
        rng=rng,
    )
    assert res.mitigated == 100


def test_crit_amplifies_when_rng_below_chance() -> None:
    """100% crit chance → всегда crit, damage = base * crit_dmg/100."""
    rng = random.Random(0)
    res = compute_damage(
        attacker=_atk(
            atk=100, crit_chance_pct=100.0, crit_damage_pct=200.0
        ),
        defender=_def(def_=0),
        skill_multiplier=1.0,
        damage_type=DamageType.PHYSICAL,
        rng=rng,
    )
    assert res.was_crit is True
    assert res.mitigated == 200  # 100 * 2.0


def test_crit_against_high_resist_floors_at_min_damage() -> None:
    """Regression: при максимальной resist + def crit не должен уходить в 0.

    Раньше код делал ``max(MIN_DAMAGE if not was_crit else final, final)`` —
    тавтология, не флорящая crit'ы. Теперь общий floor для всех путей.
    """
    rng = random.Random(0)
    res = compute_damage(
        attacker=_atk(atk=10, crit_chance_pct=100.0, crit_damage_pct=200.0),
        defender=_def(def_=999, resists={DamageType.PHYSICAL: 75}),
        skill_multiplier=1.0,
        damage_type=DamageType.PHYSICAL,
        rng=rng,
    )
    assert res.was_crit is True
    assert res.mitigated >= MIN_DAMAGE


def test_dodge_zero_damage() -> None:
    """100% dodge → 0 damage, was_dodged=True."""
    rng = random.Random(0)
    res = compute_damage(
        attacker=_atk(atk=100),
        defender=_def(dodge_chance_pct=100.0),
        skill_multiplier=1.0,
        damage_type=DamageType.PHYSICAL,
        rng=rng,
    )
    assert res.was_dodged is True
    assert res.mitigated == 0


def test_weapon_dmg_adds_to_atk() -> None:
    """weapon_min/max добавляется к raw_attack uniform-роллом."""
    rng = random.Random(123)
    res = compute_damage(
        attacker=_atk(
            atk=50, weapon_min_dmg=10, weapon_max_dmg=10
        ),  # фиксированный 10
        defender=_def(def_=0),
        skill_multiplier=1.0,
        damage_type=DamageType.PHYSICAL,
        rng=rng,
    )
    assert res.mitigated == 60  # 50 + 10


def test_determinism_same_seed_same_result() -> None:
    """Для replay: одинаковый seed → одинаковый result."""
    atk = _atk(atk=100, crit_chance_pct=30.0)
    df = _def(def_=10, dodge_chance_pct=10.0)
    r1 = compute_damage(
        attacker=atk,
        defender=df,
        skill_multiplier=1.0,
        damage_type=DamageType.PHYSICAL,
        rng=random.Random(42),
    )
    r2 = compute_damage(
        attacker=atk,
        defender=df,
        skill_multiplier=1.0,
        damage_type=DamageType.PHYSICAL,
        rng=random.Random(42),
    )
    assert r1 == r2


# ---------------------------------------------------------------------------
# CooldownTracker
# ---------------------------------------------------------------------------


def test_cooldown_first_cast_succeeds() -> None:
    t = CooldownTracker()
    assert t.try_cast("cleave", current_time_ms=1000, cooldown_ms=800) is True


def test_cooldown_second_cast_during_cd_fails() -> None:
    t = CooldownTracker()
    t.try_cast("cleave", current_time_ms=1000, cooldown_ms=800)
    assert t.try_cast("cleave", current_time_ms=1500, cooldown_ms=800) is False


def test_cooldown_after_expiry_succeeds() -> None:
    t = CooldownTracker()
    t.try_cast("cleave", current_time_ms=1000, cooldown_ms=800)
    assert t.try_cast("cleave", current_time_ms=1801, cooldown_ms=800) is True


def test_cooldown_remaining_ms() -> None:
    t = CooldownTracker()
    t.try_cast("cleave", current_time_ms=1000, cooldown_ms=800)
    assert t.remaining_ms("cleave", current_time_ms=1300, cooldown_ms=800) == 500
    assert t.remaining_ms("cleave", current_time_ms=2000, cooldown_ms=800) == 0


def test_cooldown_independent_per_skill() -> None:
    t = CooldownTracker()
    t.try_cast("cleave", current_time_ms=1000, cooldown_ms=800)
    # Другой skill должен быть готов
    assert t.try_cast("shield_bash", current_time_ms=1000, cooldown_ms=6000) is True


def test_cooldown_reset_specific() -> None:
    t = CooldownTracker()
    t.try_cast("cleave", current_time_ms=1000, cooldown_ms=800)
    t.reset("cleave")
    assert t.try_cast("cleave", current_time_ms=1100, cooldown_ms=800) is True


def test_cooldown_reset_all() -> None:
    t = CooldownTracker()
    t.try_cast("cleave", current_time_ms=1000, cooldown_ms=800)
    t.try_cast("charge", current_time_ms=1000, cooldown_ms=8000)
    t.reset()
    assert t.try_cast("cleave", current_time_ms=1100, cooldown_ms=800) is True
    assert t.try_cast("charge", current_time_ms=1100, cooldown_ms=8000) is True


# ---------------------------------------------------------------------------
# Knight skills sanity
# ---------------------------------------------------------------------------


def test_knight_default_skills_all_defined() -> None:
    """Все 4 default skills из heroes.py есть в KNIGHT_SKILLS."""
    expected = {"cleave", "shield_bash", "whirlwind", "charge"}
    assert set(KNIGHT_SKILLS.keys()) == expected


def test_knight_skills_have_consistent_damage_type() -> None:
    """В MVP все Knight skills — PHYSICAL."""
    for sk in KNIGHT_SKILLS.values():
        assert sk.damage_type == DamageType.PHYSICAL


def test_knight_skills_cooldowns_reasonable() -> None:
    """CD'и не нулевые и не астрономические — basic sanity."""
    for sk in KNIGHT_SKILLS.values():
        assert 100 <= sk.cooldown_ms <= 60000


# ---------------------------------------------------------------------------
# Property-based: damage всегда >= 0 (или MIN_DAMAGE при contact)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# W6-013: Boss drop — guaranteed rare+ + gold multiplier
# ---------------------------------------------------------------------------

#: Минимальный affix pool для on_mob_killed (нужен для generate_item).
_MINI_AFFIX_POOL: tuple[AffixDefinition, ...] = tuple(
    AffixDefinition(
        id=i,
        affix_type=AffixType.PREFIX if i < 3 else AffixType.SUFFIX,
        mod_group=f"grp_{i}",
        tier=1,
        weight=100,
        applicable_slots=[1],
        mod_type=f"mod_{i}",
        value_min=1,
        value_max=10,
        spawn_weights={},
        min_ilvl=1,
    )
    for i in range(6)
)


def test_boss_drop_guaranteed_rare_plus() -> None:
    """Босс всегда дропает item (drop_chance=1.0) и rarity ≥ RARE."""
    lich = MOBS["crypt_lich"]
    # Прогоняем 50 раз — все дропы должны быть rare+
    for seed in range(50):
        rng = random.Random(seed)
        rewards = on_mob_killed(
            rng,
            mob_def=lich,
            killer_hero_level=10,
            affix_pool=_MINI_AFFIX_POOL,
            base_id=1,
            base_slot=1,
            boss_multiplier=2.0,
        )
        assert len(rewards.items) == 1, f"seed={seed}: expected 1 item, got {len(rewards.items)}"
        assert rewards.items[0].rarity >= Rarity.RARE, (
            f"seed={seed}: expected rarity >= RARE, got {rewards.items[0].rarity}"
        )


def test_boss_drop_gold_multiplier() -> None:
    """gold_gained и xp_gained множатся на boss_multiplier=2.0."""
    lich = MOBS["crypt_lich"]
    rng = random.Random(42)
    rewards = on_mob_killed(
        rng,
        mob_def=lich,
        killer_hero_level=10,
        affix_pool=_MINI_AFFIX_POOL,
        base_id=1,
        base_slot=1,
        boss_multiplier=2.0,
    )
    # Gold должен быть в пределах [min*2, max*2]
    assert rewards.gold_gained >= lich.gold_drop_min * 2
    assert rewards.gold_gained <= lich.gold_drop_max * 2
    # XP тоже умножен
    assert rewards.xp_gained == lich.xp_drop * 2


def test_boss_drop_no_multiplier_1x() -> None:
    """boss_multiplier=1.0 (default) — обычный drop, не boss."""
    warrior = MOBS["skeleton_warrior"]
    rng = random.Random(7)
    rewards = on_mob_killed(
        rng,
        mob_def=warrior,
        killer_hero_level=5,
        affix_pool=_MINI_AFFIX_POOL,
        base_id=1,
        base_slot=1,
    )
    # XP не умножен
    assert rewards.xp_gained == warrior.xp_drop
    # Gold в пределах обычного диапазона
    assert warrior.gold_drop_min <= rewards.gold_gained <= warrior.gold_drop_max


@pytest.mark.parametrize("seed", list(range(20)))
def test_damage_always_nonnegative_random_inputs(seed: int) -> None:
    """Любая комбинация stats не должна выдавать negative damage."""
    rng = random.Random(seed)
    atk = AttackerStats(
        atk=rng.randint(1, 500),
        crit_chance_pct=rng.uniform(0, 100),
        crit_damage_pct=rng.uniform(100, 400),
        weapon_min_dmg=rng.randint(0, 50),
        weapon_max_dmg=rng.randint(50, 100),
    )
    df = DefenderStats(
        hp=rng.randint(1, 1000),
        def_=rng.randint(0, 200),
        dodge_chance_pct=rng.uniform(0, 50),
        resists={DamageType.PHYSICAL: rng.randint(-50, 90)},
    )
    res = compute_damage(
        attacker=atk,
        defender=df,
        skill_multiplier=rng.uniform(0.1, 3.0),
        damage_type=DamageType.PHYSICAL,
        rng=rng,
    )
    assert res.mitigated >= 0

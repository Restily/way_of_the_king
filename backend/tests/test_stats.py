"""Тесты compute_derived_stats."""

from __future__ import annotations

from wotk.game.stats import BASE_HP, BASE_MANA, BaseStats, compute_derived_stats


KNIGHT_DEFAULT: BaseStats = {"str": 10, "dex": 5, "int": 3}


def test_default_knight_lvl_1_no_gear() -> None:
    derived = compute_derived_stats(KNIGHT_DEFAULT, level=1)
    # HP = 50 + 10*5 + 1*10 = 110
    assert derived.hp == 110
    # Mana = 20 + 3*3 = 29
    assert derived.mana == 29
    # без оружия → atk = 0
    assert derived.atk == 0
    # DEF = 0 + 10*0.5 = 5
    assert derived.def_ == 5
    # Crit Chance = 5 + 5*0.2 = 6.0
    assert derived.crit_chance_pct == 6.0
    # Crit Damage = 150 + 5*0.5 = 152.5
    assert derived.crit_damage_pct == 152.5
    # Attack speed = 1.0 * (1 + 5*0.005) = 1.025
    assert derived.attack_speed_mult == 1.025
    # Movement speed аналогично
    assert derived.movement_speed_mult == 1.025
    # Resistances = 0 без снаряжения
    assert derived.resist_fire_pct == 0


def test_default_knight_lvl_60() -> None:
    derived = compute_derived_stats(KNIGHT_DEFAULT, level=60)
    # HP = 50 + 50 + 600 = 700
    assert derived.hp == 700


def test_with_weapon() -> None:
    derived = compute_derived_stats(
        KNIGHT_DEFAULT,
        level=1,
        weapon_min_dmg=10,
        weapon_max_dmg=20,
    )
    # avg = 15, atk = round(15 * (1 + 10*0.02)) = round(15 * 1.2) = 18
    assert derived.atk == 18


def test_with_armor() -> None:
    derived = compute_derived_stats(
        KNIGHT_DEFAULT, level=1, armor_value=100
    )
    # def = round(100 + 10*0.5) = 105
    assert derived.def_ == 105


def test_with_full_kit_bonuses() -> None:
    derived = compute_derived_stats(
        KNIGHT_DEFAULT,
        level=10,
        weapon_min_dmg=20,
        weapon_max_dmg=40,
        armor_value=50,
        bonus_hp=100,
        bonus_atk=10,
        bonus_def=20,
        bonus_crit_chance=5.0,
        resist_fire=25,
    )
    # HP = 50 + 50 + 100 + 100 = 300
    assert derived.hp == 300
    # atk = round(30 * 1.2) + 10 = 36 + 10 = 46
    assert derived.atk == 46
    # def = round(50 + 5) + 20 = 75
    assert derived.def_ == 75
    # crit = 5 + 1.0 + 5.0 = 11.0
    assert derived.crit_chance_pct == 11.0
    assert derived.resist_fire_pct == 25


def test_zero_stats_baseline() -> None:
    derived = compute_derived_stats({"str": 0, "dex": 0, "int": 0}, level=1)
    assert derived.hp == BASE_HP + 10  # 50 + 1*10
    assert derived.mana == BASE_MANA
    assert derived.atk == 0
    assert derived.def_ == 0
    assert derived.crit_chance_pct == 5.0
    assert derived.attack_speed_mult == 1.0

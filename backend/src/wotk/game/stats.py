"""Pure-function расчёт производных статов hero.

Формулы — `docs/SPEC.md` §2.2.

Сейчас рассчитываются только базовые статы из base_stats + level.
В Phase 5 добавляются бонусы от equipment + passives.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class BaseStats(TypedDict):
    """Распределённые очки str/dex/int."""

    str: int
    dex: int
    int: int


@dataclass(frozen=True, slots=True)
class DerivedStats:
    hp: int
    mana: int
    atk: int  # без оружия — base attack
    def_: int  # 'def' — reserved Python keyword
    crit_chance_pct: float
    crit_damage_pct: float
    attack_speed_mult: float
    movement_speed_mult: float
    resist_fire_pct: int
    resist_cold_pct: int
    resist_lightning_pct: int


# Базовые значения без статов и снаряжения
BASE_HP = 50
BASE_MANA = 20
BASE_ATTACK_SPEED = 1.0
BASE_MOVEMENT_SPEED = 1.0


def compute_derived_stats(
    base_stats: BaseStats,
    *,
    level: int,
    weapon_min_dmg: int = 0,
    weapon_max_dmg: int = 0,
    armor_value: int = 0,
    bonus_hp: int = 0,
    bonus_mana: int = 0,
    bonus_atk: int = 0,
    bonus_def: int = 0,
    bonus_crit_chance: float = 0.0,
    bonus_crit_damage: float = 0.0,
    bonus_attack_speed: float = 0.0,
    bonus_movement_speed: float = 0.0,
    resist_fire: int = 0,
    resist_cold: int = 0,
    resist_lightning: int = 0,
) -> DerivedStats:
    """Рассчитывает производные статы из базовых.

    Per SPEC.md §2.2:
        HP = 50 + STR × 5 + level × 10 + bonuses
        Mana = 20 + INT × 3 + bonuses
        ATK = weapon_dmg × (1 + STR × 0.02) + bonuses
        DEF = armor + STR × 0.5 + bonuses
        Crit Chance % = 5 + DEX × 0.2 + bonuses
        Crit Damage % = 150 + DEX × 0.5 + bonuses
        Attack Speed = base × (1 + DEX × 0.005) + bonuses
        Movement Speed = base × (1 + 0.005 × DEX) + bonuses
        Resistances — только от снаряжения
    """
    str_ = base_stats["str"]
    dex = base_stats["dex"]
    int_ = base_stats["int"]

    hp = BASE_HP + str_ * 5 + level * 10 + bonus_hp
    mana = BASE_MANA + int_ * 3 + bonus_mana

    avg_weapon_dmg = (weapon_min_dmg + weapon_max_dmg) / 2.0
    atk = round(avg_weapon_dmg * (1 + str_ * 0.02)) + bonus_atk

    def_ = round(armor_value + str_ * 0.5) + bonus_def

    crit_chance = 5.0 + dex * 0.2 + bonus_crit_chance
    crit_damage = 150.0 + dex * 0.5 + bonus_crit_damage

    attack_speed = BASE_ATTACK_SPEED * (1 + dex * 0.005) + bonus_attack_speed
    movement_speed = (
        BASE_MOVEMENT_SPEED * (1 + dex * 0.005) + bonus_movement_speed
    )

    return DerivedStats(
        hp=hp,
        mana=mana,
        atk=atk,
        def_=def_,
        crit_chance_pct=round(crit_chance, 2),
        crit_damage_pct=round(crit_damage, 2),
        attack_speed_mult=round(attack_speed, 4),
        movement_speed_mult=round(movement_speed, 4),
        resist_fire_pct=resist_fire,
        resist_cold_pct=resist_cold,
        resist_lightning_pct=resist_lightning,
    )

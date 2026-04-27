"""Pure-function расчёт производных статов hero.

Формулы — `docs/SPEC.md` §2.2.

В MVP рассчитываются базовые статы из base_stats + level. В Phase 5
добавятся бонусы от equipment + passives — добавляем поля в `StatBonuses`,
сигнатура `compute_derived_stats` не меняется.
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
class WeaponDmg:
    """Урон оружия (min, max). По умолчанию — без оружия."""

    min_dmg: int = 0
    max_dmg: int = 0

    @property
    def avg_dmg(self) -> float:
        return (self.min_dmg + self.max_dmg) / 2.0


@dataclass(frozen=True, slots=True)
class StatBonuses:
    """Бонусы со снаряжения / пассивок. Все по умолчанию 0."""

    hp: int = 0
    mana: int = 0
    atk: int = 0
    def_: int = 0
    crit_chance: float = 0.0
    crit_damage: float = 0.0
    attack_speed: float = 0.0
    movement_speed: float = 0.0
    resist_fire: int = 0
    resist_cold: int = 0
    resist_lightning: int = 0


@dataclass(frozen=True, slots=True)
class DerivedStats:
    hp: int
    mana: int
    atk: int
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

_NO_WEAPON = WeaponDmg()
_NO_BONUSES = StatBonuses()


def compute_derived_stats(
    base_stats: BaseStats,
    *,
    level: int,
    weapon: WeaponDmg = _NO_WEAPON,
    armor_value: int = 0,
    bonuses: StatBonuses = _NO_BONUSES,
) -> DerivedStats:
    """Рассчитывает производные статы из базовых.

    Per SPEC.md §2.2:
        HP = 50 + STR × 5 + level × 10 + bonuses.hp
        Mana = 20 + INT × 3 + bonuses.mana
        ATK = avg_weapon_dmg × (1 + STR × 0.02) + bonuses.atk
        DEF = armor_value + STR × 0.5 + bonuses.def
        Crit Chance % = 5 + DEX × 0.2 + bonuses.crit_chance
        Crit Damage % = 150 + DEX × 0.5 + bonuses.crit_damage
        Attack Speed = base × (1 + DEX × 0.005) + bonuses.attack_speed
        Movement Speed = base × (1 + DEX × 0.005) + bonuses.movement_speed
        Resistances — только от снаряжения (bonuses.resist_*)
    """
    str_ = base_stats["str"]
    dex = base_stats["dex"]
    int_ = base_stats["int"]

    hp = BASE_HP + str_ * 5 + level * 10 + bonuses.hp
    mana = BASE_MANA + int_ * 3 + bonuses.mana

    atk = round(weapon.avg_dmg * (1 + str_ * 0.02)) + bonuses.atk
    def_ = round(armor_value + str_ * 0.5) + bonuses.def_

    crit_chance = 5.0 + dex * 0.2 + bonuses.crit_chance
    crit_damage = 150.0 + dex * 0.5 + bonuses.crit_damage

    attack_speed = BASE_ATTACK_SPEED * (1 + dex * 0.005) + bonuses.attack_speed
    movement_speed = (
        BASE_MOVEMENT_SPEED * (1 + dex * 0.005) + bonuses.movement_speed
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
        resist_fire_pct=bonuses.resist_fire,
        resist_cold_pct=bonuses.resist_cold,
        resist_lightning_pct=bonuses.resist_lightning,
    )

"""Pure-функции боевых формул: damage calc, crit, resistances.

Все функции детерминированы при фиксированном :class:`random.Random` seed —
позволяет replay/anti-cheat: одно и то же combat-resolution на сервере и
при аудит-восстановлении выдаст идентичный результат.

Формулы — упрощённые ARPG-baseline (Diablo/PoE-style):

1. ``raw = atk * skill.dmg_multiplier + weapon_dmg.uniform()``
2. ``after_def = max(1, raw - defender.def)`` (минимум 1, не divide-by-zero)
3. ``after_resist = after_def * (1 - clamp(resist_pct, 0, RESIST_CAP) / 100)``
4. Crit roll: ``rng.random() < crit_chance / 100`` → ``after_crit *= crit_damage / 100``
5. Dodge roll: ``rng.random() < dodge_chance / 100`` → урон 0

См. :mod:`wotk.game.skills` для skill definitions, :mod:`wotk.game.stats`
для derivation атрибутов.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import IntEnum


class DamageType(IntEnum):
    """Тип урона. Определяет какую resistance проверять.

    PHYSICAL — базовая физика (мечи, стрелы).
    Стихийные — для skill'ов с элементальными эффектами.
    """

    PHYSICAL = 0
    FIRE = 1
    COLD = 2
    LIGHTNING = 3
    POISON = 4


#: Глобальный кап resist% — выше не проходит, даже если stats > 75.
#: Стандарт ARPG (PoE: 75% по умолчанию, можно поднять uniques до 90%).
RESIST_CAP = 75

#: Минимальный возможный урон удара. Защита не может полностью обнулить
#: атаку (иначе высокий defense → invincibility).
MIN_DAMAGE = 1


@dataclass(frozen=True, slots=True)
class AttackerStats:
    """Срез attacker'а необходимый для damage calc. Подмножество DerivedStats.

    Передаётся в :func:`compute_damage` без полной :class:`DerivedStats`,
    чтобы combat работал и для мобов (упрощённая структура).
    """

    atk: int
    crit_chance_pct: float = 0.0
    crit_damage_pct: float = 150.0
    weapon_min_dmg: int = 0
    weapon_max_dmg: int = 0


@dataclass(frozen=True, slots=True)
class DefenderStats:
    """Срез defender'а необходимый для damage calc.

    ``resists`` — dict ``{DamageType: int_pct}``. Отсутствующий ключ = 0%.
    """

    hp: int
    def_: int = 0
    dodge_chance_pct: float = 0.0
    resists: dict[DamageType, int] | None = None


@dataclass(frozen=True, slots=True)
class DamageResult:
    """Итог одного damage calc.

    :ivar raw: Сырой урон до смягчений.
    :ivar mitigated: Финальный урон, нанесённый defender'у.
    :ivar was_crit: Был ли crit roll успешным.
    :ivar was_dodged: Был ли dodge roll успешным (если да, mitigated=0).
    """

    raw: int
    mitigated: int
    was_crit: bool
    was_dodged: bool


def apply_resistance(damage: int, resist_pct: int) -> int:
    """Применить resistance к урону. Капится :data:`RESIST_CAP`.

    Negative resists (дебафф уязвимости) поддерживаются — урон умножается на
    ``1 + abs(resist)/100``. Cap применяется только к положительным resist.

    :param damage: Урон ПОСЛЕ defense mitigation.
    :param resist_pct: Resistance в процентах (-100..+100; > RESIST_CAP → cap).
    :returns: Урон после resistance.
    """
    if resist_pct > 0:
        capped = min(resist_pct, RESIST_CAP)
        return int(damage * (1.0 - capped / 100.0))
    if resist_pct < 0:
        return int(damage * (1.0 - resist_pct / 100.0))
    return damage


def compute_damage(
    *,
    attacker: AttackerStats,
    defender: DefenderStats,
    skill_multiplier: float,
    damage_type: DamageType,
    rng: random.Random,
) -> DamageResult:
    """Расчёт одного удара ``attacker → defender`` через skill.

    Порядок:

    1. Dodge roll: если успех — return result(0, was_dodged=True) сразу.
    2. raw = ``(atk * skill_mult) + weapon_dmg.uniform()`` (atk-component усиливается множителем skill'а).
    3. Crit roll: если успех → ``raw *= crit_damage / 100``.
    4. after_def = ``max(MIN_DAMAGE, raw - def)``.
    5. final = :func:`apply_resistance`.

    :param attacker: Атакующий с весами для damage calc.
    :param defender: Обороняющийся с def + resists.
    :param skill_multiplier: ``skill.dmg_multiplier`` (1.0 = baseline).
    :param damage_type: Тип урона — определяет какой resist проверяется.
    :param rng: :class:`random.Random` для crit/dodge rolls. Caller отвечает
        за seed (для replay).
    :returns: :class:`DamageResult` со всеми intermediate-значениями.
    """
    if defender.dodge_chance_pct > 0 and (
        rng.random() < defender.dodge_chance_pct / 100.0
    ):
        return DamageResult(raw=0, mitigated=0, was_crit=False, was_dodged=True)

    weapon_roll = (
        rng.randint(attacker.weapon_min_dmg, attacker.weapon_max_dmg)
        if attacker.weapon_max_dmg >= attacker.weapon_min_dmg > 0
        else 0
    )
    raw_attack = int(attacker.atk * skill_multiplier) + weapon_roll

    was_crit = (
        attacker.crit_chance_pct > 0
        and rng.random() < attacker.crit_chance_pct / 100.0
    )
    if was_crit:
        raw_attack = int(raw_attack * (attacker.crit_damage_pct / 100.0))

    after_def = max(MIN_DAMAGE, raw_attack - defender.def_)

    resist_pct = 0
    if defender.resists is not None:
        resist_pct = defender.resists.get(damage_type, 0)
    final = max(MIN_DAMAGE, apply_resistance(after_def, resist_pct))

    return DamageResult(
        raw=raw_attack,
        mitigated=final,
        was_crit=was_crit,
        was_dodged=False,
    )


__all__ = [
    "MIN_DAMAGE",
    "RESIST_CAP",
    "AttackerStats",
    "DamageResult",
    "DamageType",
    "DefenderStats",
    "apply_resistance",
    "compute_damage",
]

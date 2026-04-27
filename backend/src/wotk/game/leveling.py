"""XP-кривая и level up для hero. Pure functions, без I/O.

Source of truth для ``hero.level`` — :func:`compute_level`. Колонка
``level`` в ``hero`` — денормализация для индексов / лидерборда.
При изменении xp обязательно пересчитывается level в той же транзакции
(см. :func:`apply_xp`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# Per docs/SPEC.md §2.2:
#   xp(n) = round(100 * n^1.7)
# где n — НАЧАЛЬНЫЙ XP для перехода с уровня (n-1) на уровень n.
# Иначе говоря: xp_for_level(2) = round(100 * 2^1.7) = 322 — это XP
# который нужен чтобы достичь lvl 2.
#
# Соответственно:
# - lvl 1 = 0..xp_for_level(2)-1
# - lvl 2 = xp_for_level(2)..xp_for_level(3)-1
# и т.д.

#: Максимальный достижимый уровень в MVP.
MAX_LEVEL = 100

#: Сколько stat points начисляется за каждый level up.
STAT_POINTS_PER_LEVEL = 3


def xp_for_level(level: int) -> int:
    """XP-граница для достижения уровня ``level``.

    ``xp_for_level(1) = 0`` (стартовый уровень).
    ``xp_for_level(2)`` = первый уровень-ап.

    :param level: Уровень от 1 до :data:`MAX_LEVEL`.
    :returns: Минимальный XP для этого уровня.
    """
    if level <= 1:
        return 0
    return round(100 * (level**1.7))


def compute_level(xp: int) -> int:
    """Текущий уровень исходя из накопленного XP.

    Источник истины для ``hero.level``. Использует binary search.

    :param xp: Накопленный XP (≥ 0).
    :returns: Уровень от 1 до :data:`MAX_LEVEL`.
    :raises ValueError: Если ``xp < 0``.
    """
    if xp < 0:
        raise ValueError(f"xp must be non-negative, got {xp}")
    if xp < xp_for_level(2):
        return 1
    if xp >= xp_for_level(MAX_LEVEL):
        return MAX_LEVEL
    lo, hi = 2, MAX_LEVEL
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if xp >= xp_for_level(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


@dataclass(frozen=True, slots=True)
class LevelUpResult:
    """Результат :func:`apply_xp`.

    :ivar old_level: Уровень до изменения.
    :ivar new_level: Уровень после.
    :ivar levels_gained: Дельта уровней (0 если не было level up).
    :ivar stat_points_awarded: Сколько stat points начислено
        (``levels_gained * STAT_POINTS_PER_LEVEL`` при росте уровня).
    """

    old_level: int
    new_level: int
    levels_gained: int
    stat_points_awarded: int


class _HeroLike(Protocol):
    """Protocol для типизации без жёсткой связи с моделью SQLAlchemy.

    Достаточно объекта с тремя атрибутами ниже — позволяет тестам
    использовать ``FakeHero`` dataclass.
    """

    xp: int
    level: int
    unspent_points: dict


def apply_xp(hero: _HeroLike, gained_xp: int) -> LevelUpResult:
    """Применяет ``gained_xp`` к hero, обновляя ``xp`` + ``level`` + ``unspent_points``.

    Мутирует объект in-place. Должно вызываться внутри той же DB-транзакции,
    что и сохранение hero — иначе можно потерять level up при failure.

    Корректно обрабатывает multi-level (например, lvl 5 + 1M xp = lvl 100,
    +95×3 stat points за один вызов).

    :param hero: Объект с полями ``xp``, ``level``, ``unspent_points``.
    :param gained_xp: Положительный XP к начислению.
    :returns: :class:`LevelUpResult` с информацией об изменении.
    :raises ValueError: Если ``gained_xp < 0``.
    """
    if gained_xp < 0:
        raise ValueError(f"gained_xp must be non-negative, got {gained_xp}")

    old_level = hero.level
    hero.xp += gained_xp
    new_level = compute_level(hero.xp)
    hero.level = new_level

    levels_gained = new_level - old_level
    points_awarded = max(0, levels_gained) * STAT_POINTS_PER_LEVEL
    if points_awarded > 0:
        # Обновление JSONB через прямую мутацию + явное переприсваивание,
        # чтобы SQLAlchemy зафиксировал изменение dict-объекта.
        current = dict(hero.unspent_points)
        current["stat"] = int(current.get("stat", 0)) + points_awarded
        hero.unspent_points = current

    return LevelUpResult(
        old_level=old_level,
        new_level=new_level,
        levels_gained=levels_gained,
        stat_points_awarded=points_awarded,
    )

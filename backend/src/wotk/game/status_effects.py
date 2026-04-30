"""Status effects: stun, slow, poison, burn — base система.

Pure-functions. Caller хранит ``list[StatusEffect]`` на entity.

Примеры применения:
* shield_bash → STUN 1000ms
* zombie bite → SLOW 50% 2000ms
* fire-skill → BURN 5dmg/sec for 3000ms
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class StatusType(IntEnum):
    STUN = 0
    SLOW = 1
    POISON = 2
    BURN = 3


@dataclass(frozen=True, slots=True)
class StatusEffect:
    """Однократно применённый эффект.

    :ivar status_type: Тип.
    :ivar applied_at_ms: Когда наложен.
    :ivar duration_ms: Длительность.
    :ivar magnitude: Интерпретируется по типу:
        STUN → ignored. SLOW → % замедления. POISON/BURN → dmg/sec.
    """

    status_type: StatusType
    applied_at_ms: int
    duration_ms: int
    magnitude: float = 0.0


def is_active(effect: StatusEffect, *, now_ms: int) -> bool:
    """True если эффект ещё в силе."""
    return now_ms - effect.applied_at_ms < effect.duration_ms


def filter_active(
    effects: list[StatusEffect], *, now_ms: int
) -> list[StatusEffect]:
    """Вернуть только активные (для periodic cleanup на entity tick)."""
    return [e for e in effects if is_active(e, now_ms=now_ms)]


def is_stunned(effects: list[StatusEffect], *, now_ms: int) -> bool:
    """True если хотя бы один STUN активен."""
    return any(
        e.status_type == StatusType.STUN and is_active(e, now_ms=now_ms)
        for e in effects
    )


def slow_multiplier(effects: list[StatusEffect], *, now_ms: int) -> float:
    """Множитель скорости (1.0 = нормал, 0.5 = -50%).

    Несколько SLOW не складываются — берётся максимальный magnitude.
    """
    max_slow = 0.0
    for e in effects:
        if e.status_type == StatusType.SLOW and is_active(e, now_ms=now_ms):
            max_slow = max(max_slow, e.magnitude)
    return max(0.1, 1.0 - max_slow / 100.0)


def dot_damage_per_sec(
    effects: list[StatusEffect], *, now_ms: int
) -> float:
    """Сумма damage-over-time (POISON + BURN) per second."""
    total = 0.0
    for e in effects:
        if (
            e.status_type in (StatusType.POISON, StatusType.BURN)
            and is_active(e, now_ms=now_ms)
        ):
            total += e.magnitude
    return total


__all__ = [
    "StatusEffect",
    "StatusType",
    "dot_damage_per_sec",
    "filter_active",
    "is_active",
    "is_stunned",
    "slow_multiplier",
]

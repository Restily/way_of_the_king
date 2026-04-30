"""Append-only combat event log для anti-cheat audit + replay.

Caller (combat orchestrator) накапливает events за encounter, при finalize
сериализует в ``run_encounters.combat_summary`` JSONB как
``{"v": 1, "events": [...], "damage_dealt": ..., "damage_taken": ..., "duration_s": ..., "deaths": ...}``.

Версия v=1; при breaking format change → v=2 + поддержка обоих в reader.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class CombatEventType(IntEnum):
    PLAYER_ATTACK = 0
    MOB_ATTACK = 1
    PLAYER_KILL_MOB = 2
    MOB_KILL_PLAYER = 3
    SKILL_CAST = 4
    STATUS_APPLIED = 5


@dataclass(frozen=True, slots=True)
class CombatEvent:
    """Одно событие. Минимальный shape для JSONB serialization.

    :ivar tick: Server tick когда произошло (для ordering при replay).
    :ivar event_type: Тип события.
    :ivar actor_id: Кто действовал (player_id или mob.instance_id).
    :ivar target_id: Целевая entity (None для self-cast / status apply на актора).
    :ivar damage: Урон (если применимо). 0 для не-damage events.
    :ivar was_crit: True если crit (только для attack events).
    :ivar extra: Произвольные ключи (skill_id, status_type, и т.п.).
    """

    tick: int
    event_type: CombatEventType
    actor_id: int
    target_id: int | None = None
    damage: int = 0
    was_crit: bool = False
    extra: dict[str, Any] | None = None


class CombatLog:
    """Накопитель events. Serialize → dict в combat_summary."""

    def __init__(self) -> None:
        self._events: list[CombatEvent] = []
        self._damage_dealt: int = 0
        self._damage_taken: int = 0
        self._deaths: int = 0
        self._start_tick: int | None = None
        self._end_tick: int = 0

    def record(self, event: CombatEvent) -> None:
        """Добавить event + обновить агрегаты для combat_summary."""
        self._events.append(event)
        if self._start_tick is None:
            self._start_tick = event.tick
        self._end_tick = max(self._end_tick, event.tick)

        if event.event_type == CombatEventType.PLAYER_ATTACK:
            self._damage_dealt += event.damage
        elif event.event_type == CombatEventType.MOB_ATTACK:
            self._damage_taken += event.damage
        elif event.event_type == CombatEventType.MOB_KILL_PLAYER:
            self._deaths += 1

    def to_summary(self, *, tick_rate_hz: int = 20) -> dict[str, Any]:
        """Сериализовать в format совместимый с ``run_encounters.combat_summary``.

        :param tick_rate_hz: Server tick rate для расчёта duration_s.
        :returns: Dict готовый для JSONB INSERT с обязательным ``v=1`` ключом.
        """
        ticks = (self._end_tick - (self._start_tick or 0)) if self._start_tick else 0
        return {
            "v": 1,
            "damage_dealt": self._damage_dealt,
            "damage_taken": self._damage_taken,
            "duration_s": int(ticks / tick_rate_hz),
            "deaths": self._deaths,
            "events": [
                {
                    "t": e.tick,
                    "k": int(e.event_type),
                    "a": e.actor_id,
                    "tg": e.target_id,
                    "dmg": e.damage,
                    "c": 1 if e.was_crit else 0,
                    **({"x": e.extra} if e.extra else {}),
                }
                for e in self._events
            ],
        }

    @property
    def event_count(self) -> int:
        return len(self._events)


__all__ = ["CombatEvent", "CombatEventType", "CombatLog"]

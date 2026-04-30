"""Tracker для skill cooldowns. Pure data — caller передаёт current_time_ms.

Используется как entity-level state у hero/mob. Не привязан к real clock —
для server-side simulation всегда передаём ``world_now_ms`` (детерминирует
replay при том же tick rate).

Пример::

    tracker = CooldownTracker()
    if tracker.try_cast("cleave", current_time_ms=1000, cooldown_ms=800):
        # cast goes through, CD started
        ...
    # Через 500мс
    tracker.try_cast("cleave", current_time_ms=1500, cooldown_ms=800)  # → False
    # Через 800мс с last cast
    tracker.try_cast("cleave", current_time_ms=1800, cooldown_ms=800)  # → True
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CooldownTracker:
    """Хранит ``last_cast_at_ms`` для каждого skill_id.

    :ivar last_cast_ms: ``{skill_id: timestamp_ms}``. Отсутствующий ключ =
        skill ни разу не кастился, готов всегда.
    """

    last_cast_ms: dict[str, int] = field(default_factory=dict)

    def try_cast(
        self, skill_id: str, *, current_time_ms: int, cooldown_ms: int
    ) -> bool:
        """Попытаться скастить skill. Если CD готов — пометить и return True.

        Атомарность: если возвращает True, CD немедленно ставится. Caller
        не должен вызывать try_cast повторно для одного и того же намерения.

        :param skill_id: ID скилла (``"cleave"``, ``"shield_bash"``, …).
        :param current_time_ms: Текущий tick время в мс (server clock).
        :param cooldown_ms: CD скилла из :data:`SkillDef.cooldown_ms`.
        :returns: True если cast разрешён (CD стартовал); False если ещё на CD.
        """
        last = self.last_cast_ms.get(skill_id)
        if last is None or current_time_ms - last >= cooldown_ms:
            self.last_cast_ms[skill_id] = current_time_ms
            return True
        return False

    def remaining_ms(
        self, skill_id: str, *, current_time_ms: int, cooldown_ms: int
    ) -> int:
        """Сколько мс до готовности skill (для UI индикатора).

        :param skill_id: ID скилла.
        :param current_time_ms: Текущий tick время в мс.
        :param cooldown_ms: CD скилла.
        :returns: ``0`` если готов, иначе оставшееся время в мс.
        """
        last = self.last_cast_ms.get(skill_id)
        if last is None:
            return 0
        elapsed = current_time_ms - last
        return max(0, cooldown_ms - elapsed)

    def reset(self, skill_id: str | None = None) -> None:
        """Сбросить CD конкретного skill или всех (None).

        Используется для item-эффектов «reset cooldowns» или после respawn.

        :param skill_id: Конкретный ID, или None для полного сброса.
        """
        if skill_id is None:
            self.last_cast_ms.clear()
        else:
            self.last_cast_ms.pop(skill_id, None)


__all__ = ["CooldownTracker"]

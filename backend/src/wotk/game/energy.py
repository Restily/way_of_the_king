"""Lazy energy регенерация — pure function без I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

ENERGY_TICK_SECONDS = 6 * 60  # 1 ед / 6 минут


@dataclass(frozen=True, slots=True)
class EnergyState:
    energy: int
    energy_updated_at: datetime


def compute_regenerated(
    *,
    energy: int,
    energy_cap: int,
    energy_updated_at: datetime,
    now: datetime | None = None,
) -> EnergyState:
    """Возвращает регенерированное состояние без мутации.

    Использование:
    - На read-эндпоинтах (`/me`) — для отображения, **без записи в БД**.
    - На spend-эндпоинтах (списание энергии) — внутри одной транзакции:
      compute → проверить достаточно ли → atomic UPDATE с новым значением.

    Carry-over дробного времени сохраняется в `energy_updated_at` чтобы
    последующие compute_regenerated не теряли регенерацию.
    """
    if energy >= energy_cap:
        return EnergyState(energy=energy, energy_updated_at=energy_updated_at)

    effective_now = now if now is not None else datetime.now(energy_updated_at.tzinfo)
    elapsed_seconds = (effective_now - energy_updated_at).total_seconds()
    full_ticks = int(elapsed_seconds // ENERGY_TICK_SECONDS)
    if full_ticks <= 0:
        return EnergyState(energy=energy, energy_updated_at=energy_updated_at)

    new_energy = min(energy_cap, energy + full_ticks)
    new_updated_at = energy_updated_at + timedelta(
        seconds=ENERGY_TICK_SECONDS * full_ticks
    )
    return EnergyState(energy=new_energy, energy_updated_at=new_updated_at)

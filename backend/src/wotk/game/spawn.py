"""Encounter spawn — генерация набора мобов для floor encounter.

Pure-функция: для (rng_seed, floor, encounter_idx) всегда выдаёт идентичный
набор. Это позволяет replay'ить run для anti-cheat audit.

В W4 — placeholder spawn (равномерный pick из MOBS). В W5+ tied к dungeon
config'у с loot tables и difficulty-scaled stats.
"""

from __future__ import annotations

import random

from wotk.game.ai import MobInstance, Vec2
from wotk.game.mobs import MOBS


#: Кандидаты для spawn в MVP (все 3 типа моба).
DEFAULT_MOB_POOL: tuple[str, ...] = (
    "skeleton_warrior",
    "skeleton_archer",
    "zombie",
)


def spawn_encounter(
    rng: random.Random,
    *,
    floor: int,
    encounter_idx: int,
    spawn_positions: list[Vec2],
    mob_pool: tuple[str, ...] = DEFAULT_MOB_POOL,
) -> list[MobInstance]:
    """Spawn list of mobs для конкретного encounter.

    Каждая позиция получает рандомного моба из ``mob_pool``. Mob HP
    масштабируется ``floor`` (placeholder — +20% per floor сверх baseline).

    :param rng: :class:`random.Random` (caller владеет seed'ом).
    :param floor: Номер этажа (0-based).
    :param encounter_idx: Индекс encounter'а внутри этажа.
    :param spawn_positions: Стартовые координаты для каждого моба.
    :param mob_pool: Tuple возможных mob_def IDs.
    :returns: Список :class:`MobInstance` готовых для AI/combat.
    """
    floor_hp_mult = 1.0 + 0.2 * floor
    mobs: list[MobInstance] = []
    for i, pos in enumerate(spawn_positions):
        mob_id = rng.choice(mob_pool)
        md = MOBS[mob_id]
        mobs.append(
            MobInstance(
                instance_id=floor * 1000 + encounter_idx * 10 + i,
                mob_def=md,
                position=pos,
                spawn_position=pos,
                hp=int(md.base_hp * floor_hp_mult),
            )
        )
    return mobs


__all__ = ["DEFAULT_MOB_POOL", "spawn_encounter"]

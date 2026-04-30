"""Mob registry — статичные определения мобов для MVP (3 типа + BOSS).

Подгружается в spawn_encounter (см. :mod:`wotk.game.spawn`) и AI FSM
(:mod:`wotk.game.ai`). Балансные значения placeholder — будут тюниться
в W5+ при появлении реального playtesting.

W6-010: добавлены boss-специфичные поля ``is_boss``, ``telegraph_ms``,
``enrage_hp_threshold_pct``, ``summon_period_ms`` и моб ``crypt_lich``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MobDef:
    """Статичное определение моба.

    :ivar id: Stable string ID (``"skeleton_warrior"``).
    :ivar name_key: i18n якорь.
    :ivar base_hp: Стартовый HP (масштабируется по difficulty в spawn).
    :ivar base_atk: Базовая атака для compute_damage.
    :ivar base_def: Базовая защита.
    :ivar move_speed_px_s: Скорость в пикселях/сек.
    :ivar detect_radius_px: Дистанция обнаружения player'а (idle → detect).
    :ivar attack_range_px: Дистанция с которой моб атакует.
    :ivar attack_cooldown_ms: CD атаки.
    :ivar xp_drop: XP за убийство.
    :ivar gold_drop_min/max: Диапазон gold drop'а (uniform random).
    :ivar is_boss: True для боссов (активирует boss-specific AI ветки).
    :ivar telegraph_ms: Время телеграфа (charge → strike) для боссов, мс.
        Игнорируется если ``is_boss=False``.
    :ivar enrage_hp_threshold_pct: HP% порог для enrage (0.30 = 30%).
        0.0 означает no enrage.
    :ivar summon_period_ms: Период призыва добавок, мс. 0 = нет призыва.
    """

    id: str
    name_key: str
    base_hp: int
    base_atk: int
    base_def: int
    move_speed_px_s: int
    detect_radius_px: int
    attack_range_px: int
    attack_cooldown_ms: int
    xp_drop: int
    gold_drop_min: int
    gold_drop_max: int
    # Boss-specific fields (W6-010)
    is_boss: bool = False
    telegraph_ms: int = 0
    enrage_hp_threshold_pct: float = 0.0
    summon_period_ms: int = 0


MOBS: dict[str, MobDef] = {
    "skeleton_warrior": MobDef(
        id="skeleton_warrior",
        name_key="mob.skeleton_warrior.name",
        base_hp=50,
        base_atk=8,
        base_def=2,
        move_speed_px_s=80,
        detect_radius_px=200,
        attack_range_px=30,  # melee
        attack_cooldown_ms=1500,
        xp_drop=10,
        gold_drop_min=20,
        gold_drop_max=60,
    ),
    "skeleton_archer": MobDef(
        id="skeleton_archer",
        name_key="mob.skeleton_archer.name",
        base_hp=35,
        base_atk=12,
        base_def=1,
        move_speed_px_s=60,
        detect_radius_px=300,
        attack_range_px=200,  # ranged
        attack_cooldown_ms=2000,
        xp_drop=12,
        gold_drop_min=25,
        gold_drop_max=70,
    ),
    "zombie": MobDef(
        id="zombie",
        name_key="mob.zombie.name",
        base_hp=90,
        base_atk=6,
        base_def=4,
        move_speed_px_s=50,  # slow tank
        detect_radius_px=150,
        attack_range_px=30,
        attack_cooldown_ms=2000,
        xp_drop=15,
        gold_drop_min=30,
        gold_drop_max=80,
    ),
    # W6-010: Boss mob — Crypt Lich
    "crypt_lich": MobDef(
        id="crypt_lich",
        name_key="mob.crypt_lich.name",
        base_hp=600,
        base_atk=40,
        base_def=30,
        move_speed_px_s=80,
        detect_radius_px=1000,  # always agro on boss floor
        attack_range_px=90,
        attack_cooldown_ms=1500,
        xp_drop=500,
        gold_drop_min=100,
        gold_drop_max=200,
        is_boss=True,
        telegraph_ms=1000,
        enrage_hp_threshold_pct=0.30,
        summon_period_ms=20000,
    ),
}


__all__ = ["MOBS", "MobDef"]

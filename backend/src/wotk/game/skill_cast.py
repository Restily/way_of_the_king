"""Skill cast resolution — кто попал в AoE/single-target.

Pure-функция: принимает caster pos + skill def + target pos + список targets
с координатами, возвращает list[entity_id] кто попал в hit-shape.

Не считает damage — это отдельный слой (combat.compute_damage). Не проверяет
mana cost / cooldown — caller через CooldownTracker делает это до cast.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from wotk.game.ai import Vec2
from wotk.game.skills import SkillDef


@dataclass(frozen=True, slots=True)
class TargetCandidate:
    """Возможная цель с координатами для hit-shape проверки."""

    entity_id: int
    position: Vec2


@dataclass(frozen=True, slots=True)
class CastResult:
    """Итог cast'а.

    :ivar success: True если cast прошёл (хотя бы одна цель в hit-shape ИЛИ
        skill self-cast). False = ``reason`` объясняет почему.
    :ivar reason: Один из ``"out_of_range"`` / ``"no_targets"`` (информативно).
    :ivar hit_entities: IDs целей попавших в shape.
    """

    success: bool
    reason: Literal["ok", "out_of_range", "no_targets"]
    hit_entities: tuple[int, ...]


def _distance(a: Vec2, b: Vec2) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _angle_between(origin: Vec2, target: Vec2) -> float:
    """Угол от origin до target в градусах [-180, 180]. East = 0, North = -90."""
    return math.degrees(math.atan2(target.y - origin.y, target.x - origin.x))


def _angular_distance(a: float, b: float) -> float:
    """Минимальная угловая дистанция между двумя углами в градусах [0, 180]."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


def resolve_cast(
    *,
    caster_position: Vec2,
    skill: SkillDef,
    target_position: Vec2,
    candidates: list[TargetCandidate],
) -> CastResult:
    """Разрешить cast: проверить range + hit-shape.

    Логика:

    * Если ``skill.range_px > 0`` и distance(caster, target) > range — out_of_range.
    * AoE single (aoe_radius=0): берём ближайший candidate в range от target_position.
    * AoE circle (aoe_cone_deg=360 или 0 при aoe_radius>0): все candidates
      в radius от target_position.
    * AoE cone (0 < aoe_cone_deg < 360): candidates в radius И в cone от
      caster по направлению к target.

    :param caster_position: Позиция caster'а (для cone direction).
    :param skill: Определение skill'а.
    :param target_position: Точка прицеливания (player tap).
    :param candidates: Возможные цели (уже отфильтрованы alive).
    :returns: :class:`CastResult`.
    """
    # Range check (для AoE — точка прицеливания, для single — target_position)
    if skill.range_px > 0:
        if _distance(caster_position, target_position) > skill.range_px:
            return CastResult(success=False, reason="out_of_range", hit_entities=())

    hits: list[int] = []

    if skill.aoe_radius_px == 0:
        # Single-target — ближайший candidate к target_position
        nearest: TargetCandidate | None = None
        nearest_d = float("inf")
        for c in candidates:
            d = _distance(target_position, c.position)
            if d < nearest_d:
                nearest_d = d
                nearest = c
        # Hit threshold: 30px (tap-tolerance)
        if nearest is not None and nearest_d <= 30:
            hits.append(nearest.entity_id)
    elif skill.aoe_cone_deg in (0, 360):
        # Circle AoE
        for c in candidates:
            if _distance(target_position, c.position) <= skill.aoe_radius_px:
                hits.append(c.entity_id)
    else:
        # Cone AoE — direction = caster → target
        direction = _angle_between(caster_position, target_position)
        half_cone = skill.aoe_cone_deg / 2
        for c in candidates:
            if _distance(caster_position, c.position) > skill.aoe_radius_px:
                continue
            angle_to_c = _angle_between(caster_position, c.position)
            if _angular_distance(direction, angle_to_c) <= half_cone:
                hits.append(c.entity_id)

    if not hits:
        return CastResult(success=False, reason="no_targets", hit_entities=())
    return CastResult(success=True, reason="ok", hit_entities=tuple(hits))


__all__ = ["CastResult", "TargetCandidate", "resolve_cast"]

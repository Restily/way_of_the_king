"""Skill definitions: Knight 4 active skills (MVP).

Подгружается в :func:`wotk.game.skill_cast.resolve_cast` для исполнения
когда player отправляет ``input.cast`` в combat session.

Иконки/анимации skill'ов привязываются по ``id`` ключу из
``KNIGHT_SKILLS`` — frontend знает skill через тот же id.

Дизайн (все 4 знакомы Knight'у с создания героя, см. KNIGHT_DEFAULT_SKILLS
в :mod:`wotk.api.v1.heroes`):

* ``cleave`` — basic AoE melee, дефолтный «atk button»
* ``shield_bash`` — single-target stun, для прерывания опасных мобов
* ``whirlwind`` — burst AoE с mana cost, ко-toolan для groups
* ``charge`` — gap closer + nuke, для ranged мобов

Damage type — все PHYSICAL в MVP. Elemental skills придут в Phase 6 с
ARCHER (fire arrow) / NECROMANCER (cold/poison).
"""

from __future__ import annotations

from dataclasses import dataclass

from wotk.game.combat import DamageType


@dataclass(frozen=True, slots=True)
class SkillDef:
    """Статичное определение skill'а.

    :ivar id: Stable string ID (``"cleave"``).
    :ivar name_key: i18n якорь (``"skill.cleave.name"``).
    :ivar mana_cost: Стоимость в mana (0 = free).
    :ivar cooldown_ms: CD после каста.
    :ivar dmg_multiplier: Множитель к ``attacker.atk`` (1.0 = baseline).
    :ivar range_px: Maximum cast range. Для AoE — расстояние от caster до
        центра AoE (для AoE-on-self = 0).
    :ivar aoe_radius_px: Радиус AoE (0 = single-target).
    :ivar aoe_cone_deg: Угол конуса для cone-AoE (0 = circle, 360 = circle).
    :ivar animation_ms: Длительность анимации (для UI sync; cast происходит
        в начале анимации).
    :ivar damage_type: :class:`DamageType` — определяет какую resistance defender'а
        применять.
    """

    id: str
    name_key: str
    mana_cost: int
    cooldown_ms: int
    dmg_multiplier: float
    range_px: int
    aoe_radius_px: int
    aoe_cone_deg: int
    animation_ms: int
    damage_type: DamageType


KNIGHT_SKILLS: dict[str, SkillDef] = {
    "cleave": SkillDef(
        id="cleave",
        name_key="skill.cleave.name",
        mana_cost=0,
        cooldown_ms=800,
        dmg_multiplier=1.2,
        range_px=100,
        aoe_radius_px=100,
        aoe_cone_deg=60,
        animation_ms=400,
        damage_type=DamageType.PHYSICAL,
    ),
    "shield_bash": SkillDef(
        id="shield_bash",
        name_key="skill.shield_bash.name",
        mana_cost=0,
        cooldown_ms=6000,
        dmg_multiplier=1.5,
        range_px=80,
        aoe_radius_px=0,
        aoe_cone_deg=0,
        animation_ms=600,
        damage_type=DamageType.PHYSICAL,
    ),
    "whirlwind": SkillDef(
        id="whirlwind",
        name_key="skill.whirlwind.name",
        mana_cost=30,
        cooldown_ms=12000,
        dmg_multiplier=0.8,  # многократный (3 ticks) — итого ~2.4×
        range_px=0,
        aoe_radius_px=120,
        aoe_cone_deg=360,
        animation_ms=1500,
        damage_type=DamageType.PHYSICAL,
    ),
    "charge": SkillDef(
        id="charge",
        name_key="skill.charge.name",
        mana_cost=20,
        cooldown_ms=8000,
        dmg_multiplier=2.0,
        range_px=200,  # dash distance + attack
        aoe_radius_px=0,
        aoe_cone_deg=0,
        animation_ms=500,
        damage_type=DamageType.PHYSICAL,
    ),
}


__all__ = ["KNIGHT_SKILLS", "SkillDef"]

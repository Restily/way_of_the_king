"""Тесты skill_cast / status_effects / drops / combat_log — pure functions."""

from __future__ import annotations

import random

import pytest

from wotk.game.ai import Vec2
from wotk.game.combat_log import CombatEvent, CombatEventType, CombatLog
from wotk.game.drops import DEFAULT_RARITY_WEIGHTS, on_mob_killed
from wotk.game.loot import AffixDefinition as LootAffixDefinition
from wotk.game.loot import AffixType, Rarity
from wotk.game.mobs import MOBS
from wotk.game.skill_cast import TargetCandidate, resolve_cast
from wotk.game.skills import KNIGHT_SKILLS
from wotk.game.status_effects import (
    StatusEffect,
    StatusType,
    dot_damage_per_sec,
    filter_active,
    is_active,
    is_stunned,
    slow_multiplier,
)


# ---------------------------------------------------------------------------
# skill_cast.resolve_cast
# ---------------------------------------------------------------------------


def test_cast_out_of_range() -> None:
    """Single-target skill за пределами range → out_of_range."""
    skill = KNIGHT_SKILLS["shield_bash"]  # range=80
    res = resolve_cast(
        caster_position=Vec2(0, 0),
        skill=skill,
        target_position=Vec2(500, 0),  # >> 80
        candidates=[TargetCandidate(entity_id=1, position=Vec2(500, 0))],
    )
    assert res.success is False
    assert res.reason == "out_of_range"


def test_cast_single_target_hits_nearest() -> None:
    """shield_bash hits closest mob to target_position."""
    skill = KNIGHT_SKILLS["shield_bash"]
    res = resolve_cast(
        caster_position=Vec2(0, 0),
        skill=skill,
        target_position=Vec2(50, 0),
        candidates=[
            TargetCandidate(entity_id=1, position=Vec2(50, 0)),
            TargetCandidate(entity_id=2, position=Vec2(60, 30)),
        ],
    )
    assert res.success is True
    assert res.hit_entities == (1,)


def test_cast_aoe_circle_hits_multiple() -> None:
    """whirlwind 360° hits all candidates в radius."""
    skill = KNIGHT_SKILLS["whirlwind"]  # aoe_radius=120, cone=360
    res = resolve_cast(
        caster_position=Vec2(0, 0),
        skill=skill,
        target_position=Vec2(0, 0),  # self-cast — AoE around caster
        candidates=[
            TargetCandidate(entity_id=1, position=Vec2(50, 0)),
            TargetCandidate(entity_id=2, position=Vec2(0, 100)),
            TargetCandidate(entity_id=3, position=Vec2(-80, -50)),
            TargetCandidate(entity_id=4, position=Vec2(200, 0)),  # outside radius
        ],
    )
    assert res.success is True
    assert set(res.hit_entities) == {1, 2, 3}


def test_cast_aoe_cone_hits_only_in_arc() -> None:
    """cleave 60° cone к East: hits только тех кто справа от caster."""
    skill = KNIGHT_SKILLS["cleave"]  # range=100, aoe_radius=100, cone=60
    res = resolve_cast(
        caster_position=Vec2(0, 0),
        skill=skill,
        target_position=Vec2(80, 0),  # East
        candidates=[
            TargetCandidate(entity_id=1, position=Vec2(80, 0)),  # right in cone
            TargetCandidate(entity_id=2, position=Vec2(50, 30)),  # right edge
            TargetCandidate(entity_id=3, position=Vec2(0, 80)),  # north — not in cone
            TargetCandidate(entity_id=4, position=Vec2(-80, 0)),  # west — opposite
        ],
    )
    assert res.success is True
    assert 1 in res.hit_entities
    assert 4 not in res.hit_entities


def test_cast_aoe_no_targets() -> None:
    skill = KNIGHT_SKILLS["whirlwind"]
    res = resolve_cast(
        caster_position=Vec2(0, 0),
        skill=skill,
        target_position=Vec2(0, 0),
        candidates=[TargetCandidate(entity_id=1, position=Vec2(500, 500))],
    )
    assert res.success is False
    assert res.reason == "no_targets"


# ---------------------------------------------------------------------------
# status_effects
# ---------------------------------------------------------------------------


def test_status_active_flag() -> None:
    e = StatusEffect(
        status_type=StatusType.STUN, applied_at_ms=1000, duration_ms=500
    )
    assert is_active(e, now_ms=1200) is True
    assert is_active(e, now_ms=1500) is False


def test_status_filter_active() -> None:
    effects = [
        StatusEffect(
            status_type=StatusType.STUN, applied_at_ms=0, duration_ms=100
        ),
        StatusEffect(
            status_type=StatusType.SLOW, applied_at_ms=0, duration_ms=1000
        ),
    ]
    active = filter_active(effects, now_ms=200)
    assert len(active) == 1
    assert active[0].status_type == StatusType.SLOW


def test_status_stunned_flag() -> None:
    effects = [
        StatusEffect(
            status_type=StatusType.STUN, applied_at_ms=0, duration_ms=1000
        )
    ]
    assert is_stunned(effects, now_ms=500) is True
    assert is_stunned(effects, now_ms=2000) is False


def test_status_slow_multiplier_takes_max() -> None:
    """Несколько SLOW не складываются — берётся максимальный."""
    effects = [
        StatusEffect(
            status_type=StatusType.SLOW,
            applied_at_ms=0,
            duration_ms=2000,
            magnitude=30,
        ),
        StatusEffect(
            status_type=StatusType.SLOW,
            applied_at_ms=0,
            duration_ms=2000,
            magnitude=50,
        ),
    ]
    # 50% slow → multiplier 0.5
    assert slow_multiplier(effects, now_ms=500) == 0.5


def test_status_slow_floor() -> None:
    """Slow не может уронить speed ниже 0.1× (10% от нормы)."""
    effects = [
        StatusEffect(
            status_type=StatusType.SLOW,
            applied_at_ms=0,
            duration_ms=2000,
            magnitude=99,
        )
    ]
    assert slow_multiplier(effects, now_ms=100) >= 0.1


def test_status_dot_damage_sums() -> None:
    effects = [
        StatusEffect(
            status_type=StatusType.POISON,
            applied_at_ms=0,
            duration_ms=2000,
            magnitude=5,
        ),
        StatusEffect(
            status_type=StatusType.BURN,
            applied_at_ms=0,
            duration_ms=2000,
            magnitude=3,
        ),
    ]
    assert dot_damage_per_sec(effects, now_ms=100) == 8


# ---------------------------------------------------------------------------
# drops.on_mob_killed
# ---------------------------------------------------------------------------


def _empty_pool() -> tuple[LootAffixDefinition, ...]:
    """Минимальный affix pool для случаев когда rarity rolls > COMMON."""
    return (
        LootAffixDefinition(
            id=1,
            affix_type=AffixType.PREFIX,
            mod_group="g",
            applicable_slots=(0, 1, 2, 3, 4, 5),
            min_ilvl=1,
            weight=100,
            value_min=1,
            value_max=10,
            mod_type="m",
        ),
    )


def test_drops_xp_always_given() -> None:
    res = on_mob_killed(
        random.Random(1),
        mob_def=MOBS["zombie"],
        killer_hero_level=5,
        affix_pool=_empty_pool(),
        base_id=1,
        base_slot=0,
        drop_chance=0.0,  # отключаем item-drop
    )
    assert res.xp_gained == MOBS["zombie"].xp_drop
    assert res.items == ()


def test_drops_gold_in_range() -> None:
    md = MOBS["skeleton_warrior"]
    for seed in range(20):
        res = on_mob_killed(
            random.Random(seed),
            mob_def=md,
            killer_hero_level=1,
            affix_pool=_empty_pool(),
            base_id=1,
            base_slot=0,
            drop_chance=0.0,
        )
        assert md.gold_drop_min <= res.gold_gained <= md.gold_drop_max


def test_drops_item_when_chance_100() -> None:
    res = on_mob_killed(
        random.Random(0),
        mob_def=MOBS["zombie"],
        killer_hero_level=10,
        affix_pool=_empty_pool(),
        base_id=42,
        base_slot=0,
        drop_chance=1.0,
    )
    assert len(res.items) == 1
    assert res.items[0].base_id == 42


def test_rarity_weights_default() -> None:
    """Default — COMMON наиболее частый."""
    common_w = DEFAULT_RARITY_WEIGHTS[Rarity.COMMON]
    legendary_w = DEFAULT_RARITY_WEIGHTS[Rarity.LEGENDARY]
    assert common_w > legendary_w


# ---------------------------------------------------------------------------
# combat_log.CombatLog
# ---------------------------------------------------------------------------


def test_combat_log_aggregates_damage() -> None:
    log = CombatLog()
    log.record(
        CombatEvent(tick=0, event_type=CombatEventType.PLAYER_ATTACK, actor_id=1, target_id=2, damage=50)
    )
    log.record(
        CombatEvent(tick=10, event_type=CombatEventType.PLAYER_ATTACK, actor_id=1, target_id=2, damage=30)
    )
    log.record(
        CombatEvent(tick=15, event_type=CombatEventType.MOB_ATTACK, actor_id=2, target_id=1, damage=10)
    )

    summary = log.to_summary(tick_rate_hz=20)
    assert summary["v"] == 1
    assert summary["damage_dealt"] == 80
    assert summary["damage_taken"] == 10
    assert summary["deaths"] == 0
    assert len(summary["events"]) == 3


def test_combat_log_death_count() -> None:
    log = CombatLog()
    log.record(
        CombatEvent(
            tick=100, event_type=CombatEventType.MOB_KILL_PLAYER, actor_id=2, target_id=1
        )
    )
    summary = log.to_summary()
    assert summary["deaths"] == 1


def test_combat_log_event_serialization_compact_keys() -> None:
    log = CombatLog()
    log.record(
        CombatEvent(
            tick=5,
            event_type=CombatEventType.SKILL_CAST,
            actor_id=1,
            damage=0,
            extra={"skill_id": "cleave"},
        )
    )
    summary = log.to_summary()
    e = summary["events"][0]
    # Compact keys (t/k/a/dmg/x) — не разворачиваем full names в JSONB
    assert e["t"] == 5
    assert e["k"] == int(CombatEventType.SKILL_CAST)
    assert e["a"] == 1
    assert e["x"] == {"skill_id": "cleave"}


def test_combat_log_v_field_required_for_db_check() -> None:
    """run_encounters CHECK требует combat_summary.v как number."""
    summary = CombatLog().to_summary()
    assert "v" in summary
    assert isinstance(summary["v"], int)


# Suppress unused
_ = pytest

"""Тесты mobs / ai FSM / pathfinding / spawn — pure functions без БД."""

from __future__ import annotations

import random

import pytest

from wotk.game.ai import (
    AIState,
    MobInstance,
    PlayerObservation,
    Vec2,
    step_ai,
)
from wotk.game.mobs import MOBS, MobDef
from wotk.game.pathfind import Rect, find_path
from wotk.game.spawn import DEFAULT_MOB_POOL, spawn_encounter


# ---------------------------------------------------------------------------
# MOBS registry
# ---------------------------------------------------------------------------


def test_mobs_registry_has_4_types() -> None:
    # W6-010: crypt_lich boss added
    expected = {"skeleton_warrior", "skeleton_archer", "zombie", "crypt_lich"}
    assert set(MOBS.keys()) == expected


def test_mob_archer_is_ranged() -> None:
    """Archer attack_range > Warrior attack_range."""
    assert MOBS["skeleton_archer"].attack_range_px > MOBS["skeleton_warrior"].attack_range_px


def test_mob_zombie_is_tanky() -> None:
    """Zombie HP > Warrior HP, but slower."""
    assert MOBS["zombie"].base_hp > MOBS["skeleton_warrior"].base_hp
    assert MOBS["zombie"].move_speed_px_s < MOBS["skeleton_warrior"].move_speed_px_s


# ---------------------------------------------------------------------------
# AI FSM helpers
# ---------------------------------------------------------------------------


def _new_mob(
    *,
    mob_def: MobDef,
    pos: Vec2 = Vec2(0, 0),
    state: AIState = AIState.IDLE,
    hp_override: int | None = None,
) -> MobInstance:
    return MobInstance(
        instance_id=1,
        mob_def=mob_def,
        position=pos,
        spawn_position=pos,
        hp=hp_override if hp_override is not None else mob_def.base_hp,
        state=state,
    )


def _player(*, x: float = 0, y: float = 0, alive: bool = True) -> PlayerObservation:
    return PlayerObservation(
        player_id=42, position=Vec2(x, y), is_alive=alive
    )


# ---------------------------------------------------------------------------
# AI FSM transitions
# ---------------------------------------------------------------------------


def test_ai_idle_no_player_stays_idle() -> None:
    mob = _new_mob(mob_def=MOBS["skeleton_warrior"])
    action = step_ai(mob, nearest_player=None, now_ms=0)
    assert action.next_state == AIState.IDLE
    assert action.kind == "idle"


def test_ai_idle_player_in_radius_chases() -> None:
    mob = _new_mob(mob_def=MOBS["skeleton_warrior"])
    action = step_ai(mob, nearest_player=_player(x=100, y=0), now_ms=0)
    assert action.next_state == AIState.CHASE
    assert action.kind == "move"
    assert action.move_to == Vec2(100, 0)


def test_ai_idle_player_outside_radius_stays_idle() -> None:
    md = MOBS["skeleton_warrior"]
    mob = _new_mob(mob_def=md)
    far_player = _player(x=md.detect_radius_px + 50, y=0)
    action = step_ai(mob, nearest_player=far_player, now_ms=0)
    assert action.next_state == AIState.IDLE


def test_ai_chase_player_in_attack_range_attacks() -> None:
    md = MOBS["skeleton_warrior"]
    mob = _new_mob(mob_def=md, state=AIState.CHASE)
    near = _player(x=md.attack_range_px - 5, y=0)
    action = step_ai(mob, nearest_player=near, now_ms=10_000)
    assert action.kind == "attack"
    assert action.next_state == AIState.ATTACK
    assert action.target_player_id == 42


def test_ai_attack_cooldown_blocks_until_ready() -> None:
    md = MOBS["skeleton_warrior"]
    mob = _new_mob(mob_def=md, state=AIState.ATTACK)
    mob.last_attack_at_ms = 5000
    near = _player(x=md.attack_range_px - 5, y=0)

    # CD не готов
    action = step_ai(mob, nearest_player=near, now_ms=5000 + md.attack_cooldown_ms - 100)
    assert action.kind == "idle"
    assert action.next_state == AIState.ATTACK

    # CD готов
    action2 = step_ai(mob, nearest_player=near, now_ms=5000 + md.attack_cooldown_ms + 1)
    assert action2.kind == "attack"


def test_ai_chase_player_too_far_returns() -> None:
    """Если player ушёл за 2× detect_radius — RETURN."""
    md = MOBS["skeleton_warrior"]
    mob = _new_mob(mob_def=md, pos=Vec2(50, 50), state=AIState.CHASE)
    far = _player(x=2 * md.detect_radius_px + 100, y=0)
    action = step_ai(mob, nearest_player=far, now_ms=0)
    assert action.next_state == AIState.RETURN
    assert action.move_to == mob.spawn_position


def test_ai_dead_returns_no_action() -> None:
    mob = _new_mob(mob_def=MOBS["zombie"], hp_override=0)
    action = step_ai(mob, nearest_player=_player(x=10), now_ms=0)
    assert action.next_state == AIState.DEAD
    assert action.kind == "idle"


def test_ai_returning_reaches_spawn_then_idles() -> None:
    md = MOBS["skeleton_warrior"]
    mob = MobInstance(
        instance_id=1,
        mob_def=md,
        position=Vec2(100, 100),  # уже на spawn
        spawn_position=Vec2(100, 100),
        hp=50,
        state=AIState.RETURN,
    )
    action = step_ai(mob, nearest_player=None, now_ms=0)
    assert action.next_state == AIState.IDLE
    assert action.kind == "idle"


# ---------------------------------------------------------------------------
# Pathfinding
# ---------------------------------------------------------------------------


def test_path_direct_no_walls() -> None:
    """A* возвращает waypoint'ы по центрам cells (не raw input coords)."""
    path = find_path(start=(50, 50), goal=(200, 50), walls=[], grid_size=32)
    assert len(path) >= 2
    # Центр первой cell (col=1,row=1) = (48,48); последней (col=6,row=1) = (208,48)
    assert path[0] == (48.0, 48.0)
    assert path[-1] == (208.0, 48.0)


def test_path_around_wall() -> None:
    """Wall посередине — path должен обойти."""
    walls = [Rect(x=64, y=0, w=32, h=128)]
    path = find_path(start=(20, 50), goal=(150, 50), walls=walls, grid_size=32)
    assert len(path) > 0
    # Без обхода был бы ~5 cells (manhattan); вокруг — > 5
    assert len(path) > 5


def test_path_unreachable_returns_empty() -> None:
    """Goal заблокирован стеной → []."""
    walls = [Rect(x=100, y=100, w=64, h=64)]
    path = find_path(
        start=(20, 50),
        goal=(120, 120),  # внутри wall
        walls=walls,
        grid_size=32,
    )
    assert path == []


def test_path_same_start_and_goal() -> None:
    """Degenerate edge case — возвращает [start, goal]."""
    path = find_path(start=(50, 50), goal=(50, 50), walls=[], grid_size=32)
    assert path == [(50, 50), (50, 50)]


# ---------------------------------------------------------------------------
# Spawn
# ---------------------------------------------------------------------------


def test_spawn_deterministic_for_same_seed() -> None:
    positions = [Vec2(100, 100), Vec2(200, 100), Vec2(300, 100)]
    m1 = spawn_encounter(
        random.Random(42), floor=0, encounter_idx=0, spawn_positions=positions
    )
    m2 = spawn_encounter(
        random.Random(42), floor=0, encounter_idx=0, spawn_positions=positions
    )
    assert [m.mob_def.id for m in m1] == [m.mob_def.id for m in m2]


def test_spawn_count_matches_positions() -> None:
    positions = [Vec2(0, 0), Vec2(50, 0), Vec2(100, 0), Vec2(150, 0)]
    mobs = spawn_encounter(
        random.Random(1), floor=0, encounter_idx=0, spawn_positions=positions
    )
    assert len(mobs) == 4


def test_spawn_floor_scales_hp() -> None:
    positions = [Vec2(0, 0)]
    mobs_floor0 = spawn_encounter(
        random.Random(0), floor=0, encounter_idx=0, spawn_positions=positions
    )
    mobs_floor3 = spawn_encounter(
        random.Random(0), floor=3, encounter_idx=0, spawn_positions=positions
    )
    # floor 3: +60% HP
    assert mobs_floor3[0].hp > mobs_floor0[0].hp


def test_spawn_uses_only_pool() -> None:
    positions = [Vec2(0, 0) for _ in range(20)]
    mobs = spawn_encounter(
        random.Random(0),
        floor=0,
        encounter_idx=0,
        spawn_positions=positions,
        mob_pool=("zombie",),
    )
    assert all(m.mob_def.id == "zombie" for m in mobs)


# ---------------------------------------------------------------------------
# Integration: AI runs full encounter cycle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ticks", [50, 100])
def test_ai_player_approach_triggers_chase_attack(ticks: int) -> None:
    """Полная симуляция: player идёт к зомби, тот должен заметить и атаковать."""
    md = MOBS["zombie"]
    mob = _new_mob(mob_def=md, pos=Vec2(500, 500))
    player_pos = Vec2(800, 500)

    saw_chase = False
    saw_attack = False
    last_attack_at = 0
    for tick in range(ticks):
        now_ms = tick * 50  # 20Hz
        # Player двигается к мобу со скоростью 100px/sec
        player_pos = Vec2(player_pos.x - 5, player_pos.y)
        action = step_ai(
            mob,
            nearest_player=PlayerObservation(
                player_id=1, position=player_pos, is_alive=True
            ),
            now_ms=now_ms,
        )
        if action.next_state == AIState.CHASE:
            saw_chase = True
        if action.kind == "attack":
            saw_attack = True
            last_attack_at = now_ms
            mob.last_attack_at_ms = now_ms
        # Применяем move (placeholder — caller это делает)
        if action.kind == "move" and action.move_to is not None:
            dx = action.move_to.x - mob.position.x
            dy = action.move_to.y - mob.position.y
            d = (dx * dx + dy * dy) ** 0.5
            if d > 0:
                step = md.move_speed_px_s * 0.05
                mob.position = Vec2(
                    mob.position.x + dx / d * step,
                    mob.position.y + dy / d * step,
                )
        mob.state = action.next_state

    assert saw_chase is True
    assert saw_attack is True
    assert last_attack_at > 0


def test_default_mob_pool_matches_registry() -> None:
    # Boss mobs are NOT in the DEFAULT_MOB_POOL (they're spawned explicitly)
    assert set(DEFAULT_MOB_POOL) == {"skeleton_warrior", "skeleton_archer", "zombie"}


# ---------------------------------------------------------------------------
# W6-010..011: Boss AI — telegraph, enrage, summon
# ---------------------------------------------------------------------------


def _new_boss(
    *,
    pos: Vec2 = Vec2(640, 480),
    state: AIState = AIState.IDLE,
    hp_override: int | None = None,
    enraged: bool = False,
    charge_until_ms: int = 0,
    last_summon_at_ms: int = 0,
    last_attack_at_ms: int = 0,
) -> MobInstance:
    """Создать экземпляр boss моба crypt_lich для тестов."""
    md = MOBS["crypt_lich"]
    mi = MobInstance(
        instance_id=4999,
        mob_def=md,
        position=pos,
        spawn_position=pos,
        hp=hp_override if hp_override is not None else md.base_hp,
        state=state,
    )
    mi.enraged = enraged
    mi.charge_until_ms = charge_until_ms
    mi.last_summon_at_ms = last_summon_at_ms
    mi.last_attack_at_ms = last_attack_at_ms
    return mi


def test_boss_exists_in_registry() -> None:
    """crypt_lich зарегистрирован и является боссом."""
    lich = MOBS["crypt_lich"]
    assert lich.is_boss is True
    assert lich.base_hp == 600
    assert lich.telegraph_ms == 1000
    assert lich.enrage_hp_threshold_pct == 0.30
    assert lich.summon_period_ms == 20000


def test_boss_telegraph_then_strikes() -> None:
    """Когда босс в attack range и CD готов → charge; после charge_until_ms → attack."""
    from wotk.game.ai import AIState

    md = MOBS["crypt_lich"]
    boss = _new_boss(pos=Vec2(640, 480), state=AIState.CHASE)

    # Помещаем player в attack range (90px)
    player_pos = Vec2(640 + md.attack_range_px - 10, 480)
    player = PlayerObservation(player_id=1, position=player_pos, is_alive=True)

    # CD готов (last_attack_at_ms = 0, now_ms = 2000 > cooldown_ms)
    action1 = step_ai(boss, player, now_ms=2000)
    assert action1.kind == "charge", f"expected charge, got {action1.kind}"
    assert action1.next_state == AIState.BOSS_CHARGING

    # Применяем charge state — симулируем caller'а
    boss.state = AIState.BOSS_CHARGING
    boss.charge_until_ms = 2000 + md.telegraph_ms  # 3000ms
    boss.target_player_id = 1

    # До charge_until_ms → ещё заряжаемся
    action2 = step_ai(boss, player, now_ms=2500)
    assert action2.kind == "idle"
    assert action2.next_state == AIState.BOSS_CHARGING

    # После charge_until_ms → strike
    action3 = step_ai(boss, player, now_ms=3001)
    assert action3.kind == "attack"
    assert action3.next_state == AIState.ATTACK


def test_boss_enrage_reduces_cooldown() -> None:
    """При enrage=True эффективный cooldown = base * 0.67."""
    from wotk.game.ai import _effective_cooldown_ms

    md = MOBS["crypt_lich"]
    boss_normal = _new_boss()
    boss_normal.enraged = False
    assert _effective_cooldown_ms(boss_normal) == md.attack_cooldown_ms

    boss_enraged = _new_boss()
    boss_enraged.enraged = True
    expected = int(md.attack_cooldown_ms * 0.67)
    assert _effective_cooldown_ms(boss_enraged) == expected


def test_boss_enrage_triggers_below_30pct() -> None:
    """При HP < 30% → CD форсируется ниже base (через enraged flag).

    Примечание: step_ai сам не выставляет enraged — это делает caller (DungeonRoom).
    Этот тест проверяет что step_ai ИСПОЛЬЗУЕТ enraged flag для ускоренного CD.
    """
    from wotk.game.ai import _effective_cooldown_ms

    md = MOBS["crypt_lich"]
    hp_30pct = int(md.base_hp * 0.30)  # 180 HP

    boss = _new_boss(hp_override=hp_30pct - 1)  # below threshold
    boss.enraged = True  # caller выставил после проверки
    boss.state = AIState.CHASE

    # Enraged cooldown должен быть короче base
    cd_enraged = _effective_cooldown_ms(boss)
    assert cd_enraged < md.attack_cooldown_ms
    assert cd_enraged == int(md.attack_cooldown_ms * 0.67)


def test_boss_summons_every_20s() -> None:
    """Каждые 20s step_ai возвращает summon_pack с минионами.

    Первый вызов (last_summon_at_ms=0) не должен суммонить.
    После 20s — должен.
    """
    md = MOBS["crypt_lich"]
    boss = _new_boss(state=AIState.CHASE)

    player_far = PlayerObservation(
        player_id=1,
        position=Vec2(640, 240),  # В detect_radius, но вне attack_range
        is_alive=True,
    )

    # Первый тик — last_summon_at_ms=0, суммона быть не должно
    action_first = step_ai(boss, player_far, now_ms=1000)
    assert action_first.summon_pack == ()

    # Симулируем что первый суммон уже был (last_summon=1000ms)
    boss.last_summon_at_ms = 1000

    # До 20s — суммона нет
    action_before = step_ai(boss, player_far, now_ms=1000 + md.summon_period_ms - 1)
    assert action_before.summon_pack == ()

    # После 20s — суммон!
    action_after = step_ai(boss, player_far, now_ms=1000 + md.summon_period_ms + 1)
    assert len(action_after.summon_pack) == 2
    assert "skeleton_warrior" in action_after.summon_pack
    assert "zombie" in action_after.summon_pack

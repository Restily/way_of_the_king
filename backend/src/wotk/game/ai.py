"""Mob AI — финитный автомат состояний (FSM).

Дизайн как в Diablo 2 / D3: idle → patrol → detect → chase → attack → return.

step_ai — pure function: принимает текущее состояние моба + observation
(player position), возвращает next state + action. Caller сам мутирует
mob state на основе action — это упрощает testability и replay determinism.

Pathfinding (см. :mod:`wotk.game.pathfind`) вызывается отдельно когда
chase'у нужен path вокруг препятствий. В прямой видимости (line-of-sight)
pathfinding не нужен — мob идёт напрямую.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Literal

from wotk.game.mobs import MobDef


class AIState(IntEnum):
    """Состояния mob FSM. Целочисленные — для быстрой serialization.

    W6-010: добавлен ``BOSS_CHARGING`` для telegraph-атаки босса.
    """

    IDLE = 0
    PATROL = 1
    DETECT = 2  # short-lived; → CHASE на следующем tick
    CHASE = 3
    ATTACK = 4
    RETURN = 5
    DEAD = 6
    BOSS_CHARGING = 7  # W6-010: boss telegraph phase (charge → strike)


@dataclass(frozen=True, slots=True)
class Vec2:
    x: float
    y: float


@dataclass
class MobInstance:
    """Mutable runtime-состояние моба в encounter'е.

    Caller (combat orchestrator) обновляет position / hp / state на основе
    AIAction, возвращённой :func:`step_ai`. Этот dataclass — просто bag of
    fields для удобства; equality / hashing не нужны.

    W6-011: boss-specific runtime fields:

    :ivar enraged: True когда HP упал ниже enrage порога (применяется 1 раз).
    :ivar charge_until_ms: Timestamp (мс) до которого босс в BOSS_CHARGING.
        0 означает не заряжается.
    :ivar last_summon_at_ms: Timestamp последнего призыва добавок.
    """

    instance_id: int
    mob_def: MobDef
    position: Vec2
    spawn_position: Vec2
    hp: int
    state: AIState = AIState.IDLE
    target_player_id: int | None = None
    last_attack_at_ms: int = 0
    # Boss-specific runtime fields (W6-011)
    enraged: bool = False
    charge_until_ms: int = 0
    last_summon_at_ms: int = 0


@dataclass(frozen=True, slots=True)
class PlayerObservation:
    """Срез информации о player'е что видит mob.

    Не передаём весь Player — изоляция AI от полной combat-state модели.
    """

    player_id: int
    position: Vec2
    is_alive: bool


@dataclass(frozen=True, slots=True)
class AIAction:
    """Action который caller должен применить к мобу после step_ai.

    :ivar kind: ``"move"`` — двигаться к target. ``"attack"`` — атаковать
        target_player_id. ``"idle"`` — ничего не делать.
        ``"charge"`` — начать telegraph фазу (boss only).
    :ivar move_to: Целевая позиция для move (если kind=move).
    :ivar target_player_id: ID цели атаки (если kind=attack).
    :ivar next_state: Новое состояние моба после применения action.
    :ivar summon_pack: Список mob ID для призыва (boss summon event).
        Caller обрабатывает spawn; пустой tuple = нет призыва.
    """

    kind: Literal["move", "attack", "idle", "charge"]
    next_state: AIState
    move_to: Vec2 | None = None
    target_player_id: int | None = None
    summon_pack: tuple[str, ...] = ()


def _distance(a: Vec2, b: Vec2) -> float:
    """Евклидово расстояние между двумя точками."""
    return math.hypot(a.x - b.x, a.y - b.y)


def _effective_cooldown_ms(mob: MobInstance) -> int:
    """Вернуть эффективный attack cooldown с учётом enrage.

    W6-011: при enrage attack_cooldown_ms × 0.67.

    :param mob: Runtime-состояние моба.
    :returns: Cooldown в мс.
    """
    base = mob.mob_def.attack_cooldown_ms
    if mob.enraged:
        return int(base * 0.67)
    return base


def step_ai(
    mob: MobInstance,
    nearest_player: PlayerObservation | None,
    *,
    now_ms: int,
) -> AIAction:
    """Решить что mob делает на этом tick. Pure function (не мутирует mob).

    Логика FSM (обычные мобы):

    * IDLE → если player в detect_radius → CHASE (immediate, без отдельного DETECT state — упрощение)
    * CHASE → если player вышел за 2× detect_radius → RETURN; если в attack_range → ATTACK; иначе move к player
    * ATTACK → если cooldown готов → emit attack; иначе CHASE (поджаться)
    * RETURN → idle если дошёл до spawn, иначе move к spawn
    * DEAD → no action

    Boss-extensions (W6-011):

    * BOSS_CHARGING → когда charge_until_ms достигнут → emit attack (strike фаза)
    * При HP < enrage_hp_threshold_pct → возвращает action с флагом (caller применяет)
    * Каждые summon_period_ms → summon_pack в AIAction (caller вызывает spawnEncounter)

    :param mob: Текущее состояние моба.
    :param nearest_player: Player в зоне видимости (None если никого нет).
    :param now_ms: Текущий tick время в мс.
    :returns: :class:`AIAction` для применения caller'ом.
    """
    if mob.state == AIState.DEAD or mob.hp <= 0:
        return AIAction(kind="idle", next_state=AIState.DEAD)

    md = mob.mob_def

    # W6-011: Boss BOSS_CHARGING state — ждём пока истечёт telegraph_ms
    if mob.state == AIState.BOSS_CHARGING:
        if now_ms >= mob.charge_until_ms:
            # Telegraph готов — emit attack (strike фаза)
            return AIAction(
                kind="attack",
                next_state=AIState.ATTACK,
                target_player_id=mob.target_player_id,
            )
        # Ещё заряжаемся
        return AIAction(
            kind="idle",
            next_state=AIState.BOSS_CHARGING,
            target_player_id=mob.target_player_id,
        )

    # Если player невидим — RETURN или IDLE.
    if nearest_player is None or not nearest_player.is_alive:
        if _distance(mob.position, mob.spawn_position) > md.move_speed_px_s * 0.05:
            return AIAction(
                kind="move",
                next_state=AIState.RETURN,
                move_to=mob.spawn_position,
            )
        return AIAction(kind="idle", next_state=AIState.IDLE)

    dist_to_player = _distance(mob.position, nearest_player.position)

    # CHASE leash: если player ушёл за 2× detect_radius → RETURN
    # Боссы не leash'атся (detect_radius=1000 эффективно infinite на арене)
    if mob.state in (AIState.CHASE, AIState.ATTACK) and dist_to_player > 2 * md.detect_radius_px:
        return AIAction(
            kind="move",
            next_state=AIState.RETURN,
            move_to=mob.spawn_position,
        )

    # IDLE → детект player'а
    if mob.state in (AIState.IDLE, AIState.PATROL, AIState.RETURN):
        if dist_to_player <= md.detect_radius_px:
            return AIAction(
                kind="move",
                next_state=AIState.CHASE,
                move_to=nearest_player.position,
                target_player_id=nearest_player.player_id,
            )
        # RETURN продолжается
        if mob.state == AIState.RETURN:
            if _distance(mob.position, mob.spawn_position) > md.move_speed_px_s * 0.05:
                return AIAction(
                    kind="move",
                    next_state=AIState.RETURN,
                    move_to=mob.spawn_position,
                )
            return AIAction(kind="idle", next_state=AIState.IDLE)
        return AIAction(kind="idle", next_state=mob.state)

    # W6-011: Boss summon check (every summon_period_ms)
    summon_pack: tuple[str, ...] = ()
    if md.is_boss and md.summon_period_ms > 0:
        elapsed_since_summon = now_ms - mob.last_summon_at_ms
        if mob.last_summon_at_ms == 0:
            # Первый тик боссовой арены — не суммонить сразу
            elapsed_since_summon = 0
        if elapsed_since_summon >= md.summon_period_ms and mob.last_summon_at_ms > 0:
            summon_pack = ("skeleton_warrior", "zombie")

    # CHASE / ATTACK
    if dist_to_player <= md.attack_range_px:
        cooldown = _effective_cooldown_ms(mob)
        # В attack range — попытаться атаковать если CD готов
        if now_ms - mob.last_attack_at_ms >= cooldown:
            if md.is_boss and md.telegraph_ms > 0:
                # Boss начинает telegraph (charge phase)
                return AIAction(
                    kind="charge",
                    next_state=AIState.BOSS_CHARGING,
                    target_player_id=nearest_player.player_id,
                    summon_pack=summon_pack,
                )
            return AIAction(
                kind="attack",
                next_state=AIState.ATTACK,
                target_player_id=nearest_player.player_id,
                summon_pack=summon_pack,
            )
        # CD не готов — стоим в ATTACK pose
        return AIAction(
            kind="idle",
            next_state=AIState.ATTACK,
            target_player_id=nearest_player.player_id,
            summon_pack=summon_pack,
        )

    # Слишком далеко — chase к player'у
    return AIAction(
        kind="move",
        next_state=AIState.CHASE,
        move_to=nearest_player.position,
        target_player_id=nearest_player.player_id,
        summon_pack=summon_pack,
    )


__all__ = [
    "AIAction",
    "AIState",
    "MobInstance",
    "PlayerObservation",
    "Vec2",
    "step_ai",
]


# Suppress unused
_ = field

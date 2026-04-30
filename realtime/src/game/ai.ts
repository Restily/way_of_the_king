/**
 * Mirror of `backend/src/wotk/game/ai.py` — keep numbers in sync; pure logic only.
 *
 * W6-010: added BOSS_CHARGING state (value 7) for boss telegraph phase.
 * W6-011: boss enrage + summon logic in stepAi.
 */

import type { MobInstance, Vec2 } from './spawn.js';

export enum AIState {
  IDLE = 0,
  PATROL = 1,
  DETECT = 2,
  CHASE = 3,
  ATTACK = 4,
  RETURN = 5,
  DEAD = 6,
  /** W6-010: Boss telegraph phase — charging before strike. */
  BOSS_CHARGING = 7,
}

export type { Vec2 };

export interface PlayerObservation {
  playerId: number;
  position: Vec2;
  isAlive: boolean;
}

export interface AIAction {
  kind: 'move' | 'attack' | 'idle' | 'charge';
  nextState: AIState;
  moveTo?: Vec2;
  targetPlayerId?: number;
  /** W6-011: mob IDs to summon (boss only). Empty = no summon this tick. */
  summonPack?: string[];
}

function _distance(a: Vec2, b: Vec2): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/**
 * Return effective attack cooldown accounting for boss enrage.
 *
 * W6-011: enraged boss uses attack_cooldown_ms × 0.67.
 *
 * @param mob - Current mob runtime state.
 * @returns Cooldown in ms.
 */
function _effectiveCooldownMs(mob: MobInstance): number {
  const base = mob.mobDef.attack_cooldown_ms;
  if (mob.enraged) {
    return Math.floor(base * 0.67);
  }
  return base;
}

/**
 * Decide what a mob does this tick. Pure function — does not mutate mob.
 *
 * FSM logic mirrors Python step_ai exactly:
 *  - DEAD or hp <= 0 → idle, DEAD
 *  - BOSS_CHARGING: if chargeUntilMs reached → attack (strike); else idle BOSS_CHARGING
 *  - No player (or dead) → RETURN toward spawn or IDLE if close
 *  - CHASE/ATTACK and player > 2× detectRadius → RETURN
 *  - IDLE/PATROL/RETURN: detect player in radius → CHASE; or continue RETURN/IDLE
 *  - CHASE/ATTACK: in attack range + CD ready → boss: charge; normal: attack
 *    In range + CD not ready → idle ATTACK; else → move CHASE
 *
 * W6-011: Boss summon check is included in non-trivial CHASE/ATTACK branches.
 *
 * @param mob - Current mob runtime state.
 * @param nearestPlayer - Nearest alive player observation, or null.
 * @param nowMs - Current time in milliseconds.
 * @returns AIAction for caller to apply.
 */
export function stepAi(
  mob: MobInstance,
  nearestPlayer: PlayerObservation | null,
  nowMs: number,
): AIAction {
  if (mob.state === AIState.DEAD || mob.hp <= 0) {
    return { kind: 'idle', nextState: AIState.DEAD };
  }

  const md = mob.mobDef;

  // W6-011: Boss BOSS_CHARGING state — wait for telegraph_ms to elapse
  if (mob.state === AIState.BOSS_CHARGING) {
    if (nowMs >= (mob.chargeUntilMs ?? 0)) {
      // Telegraph done — emit strike
      return {
        kind: 'attack',
        nextState: AIState.ATTACK,
        targetPlayerId: mob.targetPlayerId,
      };
    }
    // Still charging
    return {
      kind: 'idle',
      nextState: AIState.BOSS_CHARGING,
      targetPlayerId: mob.targetPlayerId,
    };
  }

  // No visible player — RETURN or IDLE.
  if (nearestPlayer === null || !nearestPlayer.isAlive) {
    if (_distance(mob.position, mob.spawnPosition) > md.move_speed_px_s * 0.05) {
      return { kind: 'move', nextState: AIState.RETURN, moveTo: mob.spawnPosition };
    }
    return { kind: 'idle', nextState: AIState.IDLE };
  }

  const distToPlayer = _distance(mob.position, nearestPlayer.position);

  // CHASE leash: player ran too far away → RETURN
  // Bosses have detect_radius_px = 1000, so this effectively never fires on arena.
  if (
    (mob.state === AIState.CHASE || mob.state === AIState.ATTACK) &&
    distToPlayer > 2 * md.detect_radius_px
  ) {
    return { kind: 'move', nextState: AIState.RETURN, moveTo: mob.spawnPosition };
  }

  // IDLE / PATROL / RETURN — check for player detection
  if (
    mob.state === AIState.IDLE ||
    mob.state === AIState.PATROL ||
    mob.state === AIState.RETURN
  ) {
    if (distToPlayer <= md.detect_radius_px) {
      return {
        kind: 'move',
        nextState: AIState.CHASE,
        moveTo: nearestPlayer.position,
        targetPlayerId: nearestPlayer.playerId,
      };
    }
    // Continue returning if needed
    if (mob.state === AIState.RETURN) {
      if (_distance(mob.position, mob.spawnPosition) > md.move_speed_px_s * 0.05) {
        return { kind: 'move', nextState: AIState.RETURN, moveTo: mob.spawnPosition };
      }
      return { kind: 'idle', nextState: AIState.IDLE };
    }
    return { kind: 'idle', nextState: mob.state as AIState };
  }

  // W6-011: Boss summon check (every summon_period_ms)
  let summonPack: string[] | undefined;
  if (md.is_boss && md.summon_period_ms > 0) {
    const lastSummon = mob.lastSummonAtMs ?? 0;
    const elapsed = nowMs - lastSummon;
    if (lastSummon > 0 && elapsed >= md.summon_period_ms) {
      summonPack = ['skeleton_warrior', 'zombie'];
    }
  }

  // CHASE / ATTACK
  // TODO W5-pathfind-hookup: use findPath when LoS blocked.
  if (distToPlayer <= md.attack_range_px) {
    const cooldown = _effectiveCooldownMs(mob);
    if (nowMs - (mob.lastAttackAtMs ?? 0) >= cooldown) {
      if (md.is_boss && md.telegraph_ms > 0) {
        // Boss begins telegraph (charge phase)
        return {
          kind: 'charge',
          nextState: AIState.BOSS_CHARGING,
          targetPlayerId: nearestPlayer.playerId,
          summonPack,
        };
      }
      return {
        kind: 'attack',
        nextState: AIState.ATTACK,
        targetPlayerId: nearestPlayer.playerId,
        summonPack,
      };
    }
    // Cooldown not ready — stay in ATTACK pose
    return {
      kind: 'idle',
      nextState: AIState.ATTACK,
      targetPlayerId: nearestPlayer.playerId,
      summonPack,
    };
  }

  // Too far — chase toward player
  return {
    kind: 'move',
    nextState: AIState.CHASE,
    moveTo: nearestPlayer.position,
    targetPlayerId: nearestPlayer.playerId,
    summonPack,
  };
}

export { MobInstance };

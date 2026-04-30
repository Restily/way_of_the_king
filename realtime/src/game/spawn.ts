/** Mirror of `backend/src/wotk/game/spawn.py` — keep numbers in sync; pure logic only. */

import { MOBS, type MobDef } from './mobs.js';
import type { StatusEffect } from './statusEffects.js';

export interface Vec2 {
  x: number;
  y: number;
}

export interface MobInstance {
  instanceId: number;
  mobDef: MobDef;
  position: Vec2;
  spawnPosition: Vec2;
  hp: number;
  /** AIState enum value — 0=IDLE. */
  state: number;
  /** ID of the player currently targeted by this mob (opaque internal number). */
  targetPlayerId?: number;
  /** Timestamp (ms) of the last attack emitted by this mob. */
  lastAttackAtMs?: number;
  /** Active status effects on this mob (stun, slow, poison, burn). */
  statuses: StatusEffect[];
  // Boss-specific runtime fields (W6-011)
  /** True once enrage threshold has been crossed (applied once permanently). */
  enraged?: boolean;
  /** Timestamp (ms) until which the boss is in BOSS_CHARGING state. */
  chargeUntilMs?: number;
  /** Timestamp (ms) of last minion summon. 0 or undefined = not yet summoned. */
  lastSummonAtMs?: number;
}

export const DEFAULT_MOB_POOL: readonly string[] = [
  'skeleton_warrior',
  'skeleton_archer',
  'zombie',
];

export interface SpawnEncounterArgs {
  floor: number;
  encounterIdx: number;
  spawnPositions: Vec2[];
  mobPool?: readonly string[];
}

/**
 * Spawn a list of mobs for a specific encounter.
 *
 * HP scaling: +20% per floor above 0. Instance IDs are deterministic:
 * `floor * 1000 + encounterIdx * 10 + i`.
 *
 * @param rng - Caller-supplied RNG returning [0, 1). Must be seeded by caller
 *   for determinism (same seed → same output across two calls).
 * @param args - Floor index, encounter index, spawn positions, optional pool.
 * @returns Array of MobInstance ready for AI/combat, length equals spawnPositions.length.
 */
export function spawnEncounter(rng: () => number, args: SpawnEncounterArgs): MobInstance[] {
  const { floor, encounterIdx, spawnPositions, mobPool = DEFAULT_MOB_POOL } = args;
  const floorHpMult = 1.0 + 0.2 * floor;
  const mobs: MobInstance[] = [];

  for (let i = 0; i < spawnPositions.length; i++) {
    const pos = spawnPositions[i];
    const mobId = mobPool[Math.floor(rng() * mobPool.length)];
    const md = MOBS[mobId];
    if (!md) {
      throw new Error(`Unknown mob id in pool: ${mobId}`);
    }
    mobs.push({
      instanceId: floor * 1000 + encounterIdx * 10 + i,
      mobDef: md,
      position: { x: pos.x, y: pos.y },
      spawnPosition: { x: pos.x, y: pos.y },
      hp: Math.floor(md.base_hp * floorHpMult),
      state: 0, // AIState.IDLE
      statuses: [],
    });
  }

  return mobs;
}

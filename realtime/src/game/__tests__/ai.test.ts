import { describe, expect, it } from 'vitest';

import { AIState, stepAi, type AIAction, type PlayerObservation } from '../ai.js';
import { MOBS } from '../mobs.js';
import type { MobInstance } from '../spawn.js';

// ── Helpers ─────────────────────────────────────────────────────────────────

function makeMob(overrides: Partial<MobInstance> = {}): MobInstance {
  return {
    instanceId: 1,
    mobDef: MOBS.zombie,
    position: { x: 500, y: 500 },
    spawnPosition: { x: 500, y: 500 },
    hp: 90,
    state: AIState.IDLE,
    lastAttackAtMs: 0,
    targetPlayerId: undefined,
    statuses: [],
    ...overrides,
  };
}

function makePlayer(x: number, y: number, isAlive = true): PlayerObservation {
  return { playerId: 1, position: { x, y }, isAlive };
}

// Zombie stats for reference:
//   detect_radius_px = 150
//   attack_range_px  = 30
//   attack_cooldown_ms = 2000
//   move_speed_px_s  = 50

describe('stepAi — table-driven cases', () => {
  it('DEAD mob + alive player → idle, DEAD', () => {
    const mob = makeMob({ state: AIState.DEAD, hp: 0 });
    const action = stepAi(mob, makePlayer(500, 500), 0);
    expect(action.kind).toBe('idle');
    expect(action.nextState).toBe(AIState.DEAD);
  });

  it('hp <= 0 regardless of state → idle, DEAD', () => {
    const mob = makeMob({ state: AIState.CHASE, hp: 0 });
    const action = stepAi(mob, makePlayer(510, 500), 0);
    expect(action.kind).toBe('idle');
    expect(action.nextState).toBe(AIState.DEAD);
  });

  it('IDLE + no player → idle, IDLE (at spawn)', () => {
    const mob = makeMob({ state: AIState.IDLE });
    const action = stepAi(mob, null, 0);
    expect(action.kind).toBe('idle');
    expect(action.nextState).toBe(AIState.IDLE);
  });

  it('IDLE + dead player → return toward spawn or idle', () => {
    const mob = makeMob({ state: AIState.IDLE });
    const action = stepAi(mob, makePlayer(510, 500, false), 0);
    // mob is at spawn → idle IDLE
    expect(action.kind).toBe('idle');
    expect(action.nextState).toBe(AIState.IDLE);
  });

  it('IDLE + player within detectRadius → CHASE/move', () => {
    const mob = makeMob({ state: AIState.IDLE });
    // zombie detectRadius = 150; place player 100px away
    const action = stepAi(mob, makePlayer(600, 500), 0);
    expect(action.kind).toBe('move');
    expect(action.nextState).toBe(AIState.CHASE);
    expect(action.moveTo).toEqual({ x: 600, y: 500 });
    expect(action.targetPlayerId).toBe(1);
  });

  it('IDLE + player far (>detectRadius) → idle, IDLE', () => {
    const mob = makeMob({ state: AIState.IDLE });
    // place player 300px away (> 150 detect radius)
    const action = stepAi(mob, makePlayer(800, 500), 0);
    expect(action.kind).toBe('idle');
    expect(action.nextState).toBe(AIState.IDLE);
  });

  it('CHASE + player in attackRange + cooldown ready → ATTACK/attack', () => {
    const mob = makeMob({ state: AIState.CHASE, lastAttackAtMs: 0 });
    // place player 20px away (< 30 attack range)
    const action = stepAi(mob, makePlayer(520, 500), 3000);
    expect(action.kind).toBe('attack');
    expect(action.nextState).toBe(AIState.ATTACK);
    expect(action.targetPlayerId).toBe(1);
  });

  it('CHASE + player in attackRange + cooldown NOT ready → idle, ATTACK', () => {
    const mob = makeMob({ state: AIState.CHASE, lastAttackAtMs: 2900 });
    // cooldown is 2000ms; 3000 - 2900 = 100 < 2000
    const action = stepAi(mob, makePlayer(520, 500), 3000);
    expect(action.kind).toBe('idle');
    expect(action.nextState).toBe(AIState.ATTACK);
  });

  it('CHASE + player > 2×detectRadius → RETURN/move to spawn', () => {
    const mob = makeMob({ state: AIState.CHASE });
    // 2 × 150 = 300; place player 400px away
    const action = stepAi(mob, makePlayer(900, 500), 0);
    expect(action.kind).toBe('move');
    expect(action.nextState).toBe(AIState.RETURN);
    expect(action.moveTo).toEqual({ x: 500, y: 500 });
  });

  it('ATTACK + player > 2×detectRadius → RETURN/move to spawn', () => {
    const mob = makeMob({ state: AIState.ATTACK });
    const action = stepAi(mob, makePlayer(900, 500), 0);
    expect(action.kind).toBe('move');
    expect(action.nextState).toBe(AIState.RETURN);
  });

  it('RETURN + at spawn → idle, IDLE', () => {
    // at spawn exactly, so distance = 0 < move_speed * 0.05 = 2.5
    const mob = makeMob({ state: AIState.RETURN });
    // place player far so no detection
    const action = stepAi(mob, makePlayer(900, 500), 0);
    expect(action.kind).toBe('idle');
    expect(action.nextState).toBe(AIState.IDLE);
  });

  it('RETURN + away from spawn → continue move RETURN', () => {
    const mob = makeMob({
      state: AIState.RETURN,
      position: { x: 600, y: 500 }, // 100px from spawn
    });
    // player is far — no detection
    const action = stepAi(mob, makePlayer(900, 500), 0);
    expect(action.kind).toBe('move');
    expect(action.nextState).toBe(AIState.RETURN);
    expect(action.moveTo).toEqual({ x: 500, y: 500 });
  });

  it('IDLE + no player and mob not at spawn → move RETURN', () => {
    // Mob displaced from spawn; no player
    const mob = makeMob({
      state: AIState.IDLE,
      position: { x: 600, y: 500 }, // 100px from spawn at (500,500)
    });
    const action = stepAi(mob, null, 0);
    expect(action.kind).toBe('move');
    expect(action.nextState).toBe(AIState.RETURN);
    expect(action.moveTo).toEqual({ x: 500, y: 500 });
  });

  it('PATROL + player in detectRadius → CHASE', () => {
    const mob = makeMob({ state: AIState.PATROL });
    const action = stepAi(mob, makePlayer(600, 500), 0);
    expect(action.kind).toBe('move');
    expect(action.nextState).toBe(AIState.CHASE);
  });

  it('PATROL + no player → idle, PATROL', () => {
    const mob = makeMob({ state: AIState.PATROL });
    // at spawn, no player
    const action = stepAi(mob, null, 0);
    // at spawn → idle IDLE (global no-player branch)
    expect(action.kind).toBe('idle');
    expect(action.nextState).toBe(AIState.IDLE);
  });
});

// ── W6-010..011: Boss AI tests ──────────────────────────────────────────────

describe('stepAi — boss (crypt_lich) behavior', () => {
  function makeBoss(overrides: Partial<MobInstance> = {}): MobInstance {
    return {
      instanceId: 4999,
      mobDef: MOBS.crypt_lich,
      position: { x: 640, y: 480 },
      spawnPosition: { x: 640, y: 480 },
      hp: 600,
      state: AIState.CHASE,
      lastAttackAtMs: 0,
      targetPlayerId: undefined,
      statuses: [],
      enraged: false,
      chargeUntilMs: 0,
      lastSummonAtMs: 0,
      ...overrides,
    };
  }

  // crypt_lich: attack_range_px = 90, telegraph_ms = 1000, attack_cooldown_ms = 1500

  it('boss in attack range + CD ready → charge (BOSS_CHARGING)', () => {
    const boss = makeBoss({ lastAttackAtMs: 0 });
    // Player within 90px attack range
    const player = makePlayer(640 + 80, 480);
    const action = stepAi(boss, player, 5000);
    expect(action.kind).toBe('charge');
    expect(action.nextState).toBe(AIState.BOSS_CHARGING);
  });

  it('BOSS_CHARGING before chargeUntilMs → idle, BOSS_CHARGING', () => {
    const boss = makeBoss({
      state: AIState.BOSS_CHARGING,
      chargeUntilMs: 6000,
      targetPlayerId: 1,
    });
    const action = stepAi(boss, makePlayer(640 + 80, 480), 5500);
    expect(action.kind).toBe('idle');
    expect(action.nextState).toBe(AIState.BOSS_CHARGING);
  });

  it('BOSS_CHARGING after chargeUntilMs → attack (strike)', () => {
    const boss = makeBoss({
      state: AIState.BOSS_CHARGING,
      chargeUntilMs: 6000,
      targetPlayerId: 1,
    });
    const action = stepAi(boss, makePlayer(640 + 80, 480), 6001);
    expect(action.kind).toBe('attack');
    expect(action.nextState).toBe(AIState.ATTACK);
  });

  it('enraged boss effective cooldown = base * 0.67', () => {
    // With enrage: boss should enter charge sooner (after 0.67× cooldown).
    const cd = MOBS.crypt_lich.attack_cooldown_ms; // 1500
    const enragedCd = Math.floor(cd * 0.67); // 1005
    const boss = makeBoss({ enraged: true, lastAttackAtMs: 5000 });
    const player = makePlayer(640 + 80, 480);

    // Before enraged CD — should NOT charge
    const actionBefore = stepAi(boss, player, 5000 + enragedCd - 10);
    expect(actionBefore.kind).toBe('idle');

    // After enraged CD — should charge
    const actionAfter = stepAi(boss, player, 5000 + enragedCd + 10);
    expect(actionAfter.kind).toBe('charge');
  });

  it('boss summons every summon_period_ms when lastSummonAtMs > 0', () => {
    const period = MOBS.crypt_lich.summon_period_ms; // 20000
    // Player far but within detect radius (1000px)
    const player = makePlayer(640, 480 - 500);
    const boss = makeBoss({ lastSummonAtMs: 1000 });

    // Just before period — no summon
    const actionBefore = stepAi(boss, player, 1000 + period - 1);
    expect(actionBefore.summonPack).toBeFalsy(); // undefined or empty

    // Just after period — summon!
    const actionAfter = stepAi(boss, player, 1000 + period + 1);
    expect(actionAfter.summonPack).toBeDefined();
    expect(actionAfter.summonPack!.length).toBe(2);
    expect(actionAfter.summonPack).toContain('skeleton_warrior');
    expect(actionAfter.summonPack).toContain('zombie');
  });

  it('boss does NOT summon on first tick (lastSummonAtMs=0)', () => {
    const player = makePlayer(640, 480 - 500);
    const boss = makeBoss({ lastSummonAtMs: 0 });
    // Even after 20s+ since epoch, should not summon on first tick
    const action = stepAi(boss, player, 25000);
    expect(action.summonPack).toBeFalsy();
  });
});

// ── Simulation test: player slowly approaches zombie ────────────────────────

describe('stepAi — simulation: player approaches zombie', () => {
  it('IDLE→CHASE→ATTACK transitions at expected times', () => {
    // Zombie at (500, 500); player starts at (500, 800) and moves north 5px/tick.
    // detect_radius = 150; attack_range = 30; attack_cooldown_ms = 2000.
    const TICK_MS = 50;
    const PLAYER_STEP = 5;

    const mob = makeMob({ state: AIState.IDLE });
    let playerY = 800;
    let nowMs = 0;
    let detectedTick = -1;
    let attackTick = -1;

    const transitions: Array<{ tick: number; action: AIAction }> = [];

    for (let tick = 0; tick < 100; tick++) {
      playerY -= PLAYER_STEP;
      nowMs += TICK_MS;
      const player = makePlayer(500, playerY);
      const action = stepAi(mob, player, nowMs);

      // Apply action to mob state (simulate caller mutation)
      mob.state = action.nextState;
      if (action.targetPlayerId !== undefined) {
        mob.targetPlayerId = action.targetPlayerId;
      }
      if (action.kind === 'attack') {
        mob.lastAttackAtMs = nowMs;
      }

      if (detectedTick === -1 && action.nextState === AIState.CHASE) {
        detectedTick = tick;
        transitions.push({ tick, action });
      }
      if (attackTick === -1 && action.kind === 'attack') {
        attackTick = tick;
        transitions.push({ tick, action });
      }
    }

    // Player starts 300px away, moves 5px/tick north.
    // Detect at 150px → (800 - 500) / 5 = 60 ticks to 500 → detect at tick when dist ≤ 150
    // dist = 800 - playerY - 500... player at y=800-5*tick; dist = (800-5*tick) - 500 = 300 - 5*tick
    // detect when 300 - 5*tick ≤ 150 → tick ≥ 30. First tick after movement = tick 30 (1-indexed, playerY = 800-155=645, dist=145? Let's check)
    // Actually tick=30: playerY = 800 - 5*30 = 650, dist = 650 - 500 = 150 → exactly on boundary
    // tick=31: playerY = 645, dist = 145 ≤ 150 → CHASE
    expect(detectedTick).toBeGreaterThanOrEqual(29);
    expect(detectedTick).toBeLessThanOrEqual(32);

    // Attack range = 30; player must reach y ≤ 530; tick ≈ (800-530)/5 = 54 ticks
    expect(attackTick).toBeGreaterThan(detectedTick);
    expect(attackTick).toBeGreaterThanOrEqual(53);
    expect(attackTick).toBeLessThanOrEqual(57);

    // Verify transitions are IDLE→CHASE→ATTACK order
    expect(transitions[0].action.nextState).toBe(AIState.CHASE);
    expect(transitions[1].action.kind).toBe('attack');
  });
});

import { describe, expect, it } from 'vitest';

import { DEFAULT_MOB_POOL, spawnEncounter } from '../spawn.js';

/** Build a simple LCG RNG with a fixed seed — same as DungeonRoom. */
function makeLcg(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

const POSITIONS = [
  { x: 640, y: 480 },
  { x: 800, y: 400 },
  { x: 500, y: 600 },
  { x: 900, y: 700 },
  { x: 700, y: 300 },
];

describe('spawnEncounter', () => {
  it('count matches spawnPositions.length', () => {
    const mobs = spawnEncounter(makeLcg(1), {
      floor: 0,
      encounterIdx: 0,
      spawnPositions: POSITIONS,
    });
    expect(mobs).toHaveLength(POSITIONS.length);
  });

  it('determinism: same seed → same mob types and HP across two calls', () => {
    const argsA = { floor: 0, encounterIdx: 0, spawnPositions: POSITIONS };
    const argsB = { floor: 0, encounterIdx: 0, spawnPositions: POSITIONS };

    const mobsA = spawnEncounter(makeLcg(42), argsA);
    const mobsB = spawnEncounter(makeLcg(42), argsB);

    for (let i = 0; i < mobsA.length; i++) {
      expect(mobsA[i].mobDef.id).toBe(mobsB[i].mobDef.id);
      expect(mobsA[i].hp).toBe(mobsB[i].hp);
    }
  });

  it('HP floor scaling: floor=3 has 60% more HP than floor=0 for same mob', () => {
    // Force a single-mob pool so both calls produce the same mob type.
    const pool = ['zombie'] as const;
    const pos = [{ x: 0, y: 0 }];

    const [floor0] = spawnEncounter(makeLcg(7), {
      floor: 0,
      encounterIdx: 0,
      spawnPositions: pos,
      mobPool: pool,
    });
    const [floor3] = spawnEncounter(makeLcg(7), {
      floor: 3,
      encounterIdx: 0,
      spawnPositions: pos,
      mobPool: pool,
    });

    // floor=0: mult=1.0 → base_hp; floor=3: mult=1.6 → base_hp * 1.6
    expect(floor3.hp).toBe(Math.floor(floor0.hp * 1.6));
  });

  it('mob_pool filter: single-entry pool → all spawned are that mob', () => {
    const mobs = spawnEncounter(makeLcg(99), {
      floor: 0,
      encounterIdx: 0,
      spawnPositions: POSITIONS,
      mobPool: ['zombie'],
    });
    for (const mob of mobs) {
      expect(mob.mobDef.id).toBe('zombie');
    }
  });

  it('instance_id formula: floor * 1000 + encounterIdx * 10 + i', () => {
    const floor = 2;
    const encounterIdx = 3;
    const mobs = spawnEncounter(makeLcg(1), {
      floor,
      encounterIdx,
      spawnPositions: POSITIONS,
    });
    for (let i = 0; i < mobs.length; i++) {
      expect(mobs[i].instanceId).toBe(floor * 1000 + encounterIdx * 10 + i);
    }
  });

  it('default mob pool covers all three mob types', () => {
    expect(DEFAULT_MOB_POOL).toContain('skeleton_warrior');
    expect(DEFAULT_MOB_POOL).toContain('skeleton_archer');
    expect(DEFAULT_MOB_POOL).toContain('zombie');
  });

  it('state defaults to 0 (IDLE) for all spawned mobs', () => {
    const mobs = spawnEncounter(makeLcg(5), {
      floor: 0,
      encounterIdx: 0,
      spawnPositions: POSITIONS,
    });
    for (const mob of mobs) {
      expect(mob.state).toBe(0);
    }
  });
});

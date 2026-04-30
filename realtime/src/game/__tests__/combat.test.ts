import { describe, expect, it } from 'vitest';

import {
  DamageType,
  MIN_DAMAGE,
  RESIST_CAP,
  applyResistance,
  computeDamage,
  type AttackerStats,
  type DefenderStats,
} from '../combat.js';
import { makeMulberry32 } from '../rng.js';

// ── Helpers ──────────────────────────────────────────────────────────────────

/** RNG that always returns 0 — dodge/crit never triggers (prob < 0). */
const alwaysMiss = (): number => 0;
/** RNG that always returns just below 1 — dodge/crit always triggers (prob > 0). */
const alwaysHit = (): number => 0.9999;
/** Seeded RNG for determinism tests. */
const seeded = (seed: number) => makeMulberry32(seed);

function makeAttacker(overrides: Partial<AttackerStats> = {}): AttackerStats {
  return {
    atk: 20,
    critChancePct: 0,
    critDamagePct: 150,
    weaponMinDmg: 0,
    weaponMaxDmg: 0,
    ...overrides,
  };
}

function makeDefender(overrides: Partial<DefenderStats> = {}): DefenderStats {
  return {
    hp: 100,
    def_: 0,
    dodgeChancePct: 0,
    ...overrides,
  };
}

// ── applyResistance unit tests ────────────────────────────────────────────────

describe('applyResistance', () => {
  it('zero resist → no change', () => {
    expect(applyResistance(100, 0)).toBe(100);
  });

  it('50% resist → halves damage', () => {
    expect(applyResistance(100, 50)).toBe(50);
  });

  it('resist capped at RESIST_CAP=75', () => {
    // 75% → floor(100 * 0.25) = 25
    expect(applyResistance(100, 80)).toBe(applyResistance(100, RESIST_CAP));
    expect(applyResistance(100, RESIST_CAP)).toBe(25);
  });

  it('negative resist (vulnerability) amplifies damage', () => {
    // -50% → 100 * (1 - (-50)/100) = 100 * 1.5 = 150
    expect(applyResistance(100, -50)).toBe(150);
  });
});

// ── computeDamage parity tests ────────────────────────────────────────────────

describe('computeDamage', () => {
  it('basic no-def no-resist: damage = floor(atk * mult)', () => {
    const result = computeDamage({
      attacker: makeAttacker({ atk: 20 }),
      defender: makeDefender(),
      skillMultiplier: 1.0,
      damageType: DamageType.PHYSICAL,
      rng: alwaysMiss,
    });
    expect(result.wasDodged).toBe(false);
    expect(result.wasCrit).toBe(false);
    expect(result.raw).toBe(20); // floor(20 * 1.0)
    expect(result.mitigated).toBe(20);
  });

  it('skill multiplier scales raw damage', () => {
    const result = computeDamage({
      attacker: makeAttacker({ atk: 20 }),
      defender: makeDefender(),
      skillMultiplier: 1.5,
      damageType: DamageType.PHYSICAL,
      rng: alwaysMiss,
    });
    expect(result.raw).toBe(30); // floor(20 * 1.5)
    expect(result.mitigated).toBe(30);
  });

  it('def mitigates: damage = max(1, raw - def)', () => {
    const result = computeDamage({
      attacker: makeAttacker({ atk: 20 }),
      defender: makeDefender({ def_: 5 }),
      skillMultiplier: 1.0,
      damageType: DamageType.PHYSICAL,
      rng: alwaysMiss,
    });
    expect(result.mitigated).toBe(15); // 20 - 5
  });

  it('def floors at MIN_DAMAGE=1 even when def > raw', () => {
    const result = computeDamage({
      attacker: makeAttacker({ atk: 5 }),
      defender: makeDefender({ def_: 100 }),
      skillMultiplier: 1.0,
      damageType: DamageType.PHYSICAL,
      rng: alwaysMiss,
    });
    expect(result.mitigated).toBe(MIN_DAMAGE);
  });

  it('resistance reduces post-def damage', () => {
    const result = computeDamage({
      attacker: makeAttacker({ atk: 20 }),
      defender: makeDefender({
        resists: { [DamageType.PHYSICAL]: 50 },
      }),
      skillMultiplier: 1.0,
      damageType: DamageType.PHYSICAL,
      rng: alwaysMiss,
    });
    // raw=20, afterDef=20, applyResistance(20, 50) = floor(20*0.5)=10
    expect(result.mitigated).toBe(10);
  });

  it('resistance only applies to matching damage type', () => {
    const resultPhysical = computeDamage({
      attacker: makeAttacker({ atk: 20 }),
      defender: makeDefender({
        resists: { [DamageType.FIRE]: 50 }, // fire resist, not physical
      }),
      skillMultiplier: 1.0,
      damageType: DamageType.PHYSICAL,
      rng: alwaysMiss,
    });
    // PHYSICAL does not consume FIRE resist → full 20
    expect(resultPhysical.mitigated).toBe(20);
  });

  it('100% crit chance amplifies with critDamagePct', () => {
    // rng sequence: first call for dodge (0 → no dodge), second for crit (0 → 0 < 1.0 → crit)
    let callCount = 0;
    const rng = () => {
      callCount++;
      return 0; // always "hits" crit (0 < critChancePct/100)
    };
    const result = computeDamage({
      attacker: makeAttacker({ atk: 20, critChancePct: 100, critDamagePct: 200 }),
      defender: makeDefender(),
      skillMultiplier: 1.0,
      damageType: DamageType.PHYSICAL,
      rng,
    });
    expect(result.wasCrit).toBe(true);
    // raw before crit=20; after crit=floor(20*2.0)=40
    expect(result.raw).toBe(40);
    expect(result.mitigated).toBe(40);
  });

  it('100% dodge chance → zero damage, wasDodged=true', () => {
    const result = computeDamage({
      attacker: makeAttacker({ atk: 20 }),
      defender: makeDefender({ dodgeChancePct: 100 }),
      skillMultiplier: 1.0,
      damageType: DamageType.PHYSICAL,
      rng: alwaysMiss, // 0 < 100/100=1.0 → dodge
    });
    expect(result.wasDodged).toBe(true);
    expect(result.mitigated).toBe(0);
    expect(result.raw).toBe(0);
  });

  it('weapon roll adds to raw damage', () => {
    // weaponMinDmg=weaponMaxDmg=10 → always +10 (no variance in rng path)
    // rng returns 0 → floor(0 * (10-10+1)) + 10 = 10
    const result = computeDamage({
      attacker: makeAttacker({ atk: 20, weaponMinDmg: 10, weaponMaxDmg: 10 }),
      defender: makeDefender(),
      skillMultiplier: 1.0,
      damageType: DamageType.PHYSICAL,
      rng: alwaysMiss, // no dodge, no crit; weapon roll = floor(0*(1))+10=10
    });
    expect(result.raw).toBe(30); // 20 atk + 10 weapon
    expect(result.mitigated).toBe(30);
  });

  it('determinism: same seed → identical results across two calls', () => {
    const args = {
      attacker: makeAttacker({ atk: 20, critChancePct: 30, critDamagePct: 150, weaponMinDmg: 5, weaponMaxDmg: 15 }),
      defender: makeDefender({ def_: 5, dodgeChancePct: 10, resists: { [DamageType.PHYSICAL]: 20 } }),
      skillMultiplier: 1.2,
      damageType: DamageType.PHYSICAL,
    };
    const r1 = computeDamage({ ...args, rng: seeded(42) });
    const r2 = computeDamage({ ...args, rng: seeded(42) });
    expect(r1).toEqual(r2);
  });

  it('mitigated is always at least MIN_DAMAGE when not dodged', () => {
    // Extremely high resist + high def
    const result = computeDamage({
      attacker: makeAttacker({ atk: 1 }),
      defender: makeDefender({ def_: 1000, resists: { [DamageType.PHYSICAL]: 75 } }),
      skillMultiplier: 0.01,
      damageType: DamageType.PHYSICAL,
      rng: alwaysMiss,
    });
    expect(result.wasDodged).toBe(false);
    expect(result.mitigated).toBeGreaterThanOrEqual(MIN_DAMAGE);
  });
});

import { describe, expect, it } from 'vitest';

import {
  StatusType,
  dotDamagePerSec,
  filterActive,
  isActive,
  isStunned,
  slowMultiplier,
  type StatusEffect,
} from '../statusEffects.js';

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeEffect(
  statusType: StatusType,
  appliedAtMs: number,
  durationMs: number,
  magnitude = 0,
): StatusEffect {
  return { statusType, appliedAtMs, durationMs, magnitude };
}

const NOW = 5000;

// ── isActive ─────────────────────────────────────────────────────────────────

describe('isActive', () => {
  it('effect still within duration → active', () => {
    const e = makeEffect(StatusType.STUN, 4000, 2000); // expires at 6000
    expect(isActive(e, NOW)).toBe(true);
  });

  it('effect exactly at duration boundary → expired (nowMs - applied >= duration)', () => {
    // expires when now - applied >= duration → 5000 - 4000 = 1000 >= 1000 → expired
    const e = makeEffect(StatusType.STUN, 4000, 1000);
    expect(isActive(e, NOW)).toBe(false);
  });

  it('effect expired before now → not active', () => {
    const e = makeEffect(StatusType.STUN, 1000, 500); // expired at 1500
    expect(isActive(e, NOW)).toBe(false);
  });

  it('just-applied effect at same tick → active', () => {
    const e = makeEffect(StatusType.STUN, NOW, 1000);
    expect(isActive(e, NOW)).toBe(true);
  });
});

// ── filterActive ─────────────────────────────────────────────────────────────

describe('filterActive', () => {
  it('returns only active effects', () => {
    const effects: StatusEffect[] = [
      makeEffect(StatusType.STUN, 4000, 2000), // active
      makeEffect(StatusType.SLOW, 1000, 500),  // expired
      makeEffect(StatusType.BURN, 4500, 1000), // active (4500+1000=5500 > 5000)
    ];
    const active = filterActive(effects, NOW);
    expect(active).toHaveLength(2);
    expect(active.some((e) => e.statusType === StatusType.STUN)).toBe(true);
    expect(active.some((e) => e.statusType === StatusType.BURN)).toBe(true);
  });

  it('empty list → empty result', () => {
    expect(filterActive([], NOW)).toHaveLength(0);
  });

  it('all expired → empty result', () => {
    const effects: StatusEffect[] = [
      makeEffect(StatusType.STUN, 0, 100),
      makeEffect(StatusType.SLOW, 0, 200),
    ];
    expect(filterActive(effects, NOW)).toHaveLength(0);
  });
});

// ── isStunned ─────────────────────────────────────────────────────────────────

describe('isStunned', () => {
  it('active STUN → stunned', () => {
    const effects = [makeEffect(StatusType.STUN, 4000, 2000)];
    expect(isStunned(effects, NOW)).toBe(true);
  });

  it('expired STUN → not stunned', () => {
    const effects = [makeEffect(StatusType.STUN, 0, 100)];
    expect(isStunned(effects, NOW)).toBe(false);
  });

  it('active SLOW but no STUN → not stunned', () => {
    const effects = [makeEffect(StatusType.SLOW, 4000, 2000, 50)];
    expect(isStunned(effects, NOW)).toBe(false);
  });

  it('mixed effects with one active STUN → stunned', () => {
    const effects = [
      makeEffect(StatusType.SLOW, 4000, 2000, 50),
      makeEffect(StatusType.STUN, 4500, 1000), // active (expires at 5500)
    ];
    expect(isStunned(effects, NOW)).toBe(true);
  });

  it('empty effects → not stunned', () => {
    expect(isStunned([], NOW)).toBe(false);
  });
});

// ── slowMultiplier ────────────────────────────────────────────────────────────

describe('slowMultiplier', () => {
  it('no SLOW effects → multiplier 1.0', () => {
    expect(slowMultiplier([], NOW)).toBe(1.0);
  });

  it('single 50% SLOW → multiplier 0.5', () => {
    const effects = [makeEffect(StatusType.SLOW, 4000, 2000, 50)];
    expect(slowMultiplier(effects, NOW)).toBe(0.5);
  });

  it('two SLOWs: takes maximum, not sum', () => {
    const effects = [
      makeEffect(StatusType.SLOW, 4000, 2000, 30),
      makeEffect(StatusType.SLOW, 4000, 2000, 70),
    ];
    // max=70 → 1.0 - 70/100 = 0.3
    expect(slowMultiplier(effects, NOW)).toBeCloseTo(0.3);
  });

  it('100% SLOW clamped to 0.1 minimum (not full stop)', () => {
    const effects = [makeEffect(StatusType.SLOW, 4000, 2000, 100)];
    expect(slowMultiplier(effects, NOW)).toBe(0.1);
  });

  it('expired SLOW → multiplier 1.0', () => {
    const effects = [makeEffect(StatusType.SLOW, 0, 100, 80)];
    expect(slowMultiplier(effects, NOW)).toBe(1.0);
  });
});

// ── dotDamagePerSec ───────────────────────────────────────────────────────────

describe('dotDamagePerSec', () => {
  it('no DoT effects → 0', () => {
    expect(dotDamagePerSec([], NOW)).toBe(0);
  });

  it('single POISON active → returns its magnitude', () => {
    const effects = [makeEffect(StatusType.POISON, 4000, 2000, 10)];
    expect(dotDamagePerSec(effects, NOW)).toBe(10);
  });

  it('POISON + BURN stack additively', () => {
    const effects = [
      makeEffect(StatusType.POISON, 4000, 2000, 10),
      makeEffect(StatusType.BURN, 4000, 2000, 5),
    ];
    expect(dotDamagePerSec(effects, NOW)).toBe(15);
  });

  it('expired DoT → 0', () => {
    const effects = [makeEffect(StatusType.POISON, 0, 100, 20)];
    expect(dotDamagePerSec(effects, NOW)).toBe(0);
  });

  it('STUN does not contribute to DoT', () => {
    const effects = [makeEffect(StatusType.STUN, 4000, 2000, 999)];
    expect(dotDamagePerSec(effects, NOW)).toBe(0);
  });

  it('SLOW does not contribute to DoT', () => {
    const effects = [makeEffect(StatusType.SLOW, 4000, 2000, 50)];
    expect(dotDamagePerSec(effects, NOW)).toBe(0);
  });
});

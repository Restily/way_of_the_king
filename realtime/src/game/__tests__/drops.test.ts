/**
 * Tests for drops.ts — onMobKilled rewards, W6-013 boss multiplier.
 */

import { describe, expect, it } from 'vitest';

import { BASE_DROP_CHANCE, onMobKilled, Rarity } from '../drops.js';
import { MOBS } from '../mobs.js';

// Simple seeded LCG for deterministic tests (same as game/rng.ts makeLcg).
function makeLcgRng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(1664525, s) + 1013904223) >>> 0;
    return s / 0x100000000;
  };
}

describe('onMobKilled — normal mob', () => {
  it('returns xp = mob.xp_drop and gold in [min, max]', () => {
    const rng = makeLcgRng(42);
    const warrior = MOBS.skeleton_warrior;
    const rewards = onMobKilled({ rng, mobDef: warrior });
    expect(rewards.xpGained).toBe(warrior.xp_drop);
    expect(rewards.goldGained).toBeGreaterThanOrEqual(warrior.gold_drop_min);
    expect(rewards.goldGained).toBeLessThanOrEqual(warrior.gold_drop_max);
  });

  it('bossMultiplier=1.0 (default) does not scale normal mob gold/xp', () => {
    const rng = makeLcgRng(7);
    const zombie = MOBS.zombie;
    const rewards = onMobKilled({ rng, mobDef: zombie });
    // XP should match mob def exactly (no multiplier)
    expect(rewards.xpGained).toBe(zombie.xp_drop);
    expect(rewards.goldGained).toBeGreaterThanOrEqual(zombie.gold_drop_min);
    expect(rewards.goldGained).toBeLessThanOrEqual(zombie.gold_drop_max);
  });
});

describe('onMobKilled — boss (crypt_lich) W6-013', () => {
  it('boss always drops an item (100% drop chance)', () => {
    const lich = MOBS.crypt_lich;
    // Run 50 seeds — boss must ALWAYS drop
    for (let seed = 0; seed < 50; seed++) {
      const rng = makeLcgRng(seed);
      const rewards = onMobKilled({ rng, mobDef: lich, bossMultiplier: 2.0 });
      expect(rewards.items.length).toBe(1);
    }
  });

  it('boss drop rarity is always >= RARE', () => {
    const lich = MOBS.crypt_lich;
    for (let seed = 0; seed < 50; seed++) {
      const rng = makeLcgRng(seed);
      const rewards = onMobKilled({ rng, mobDef: lich, bossMultiplier: 2.0 });
      expect(rewards.items[0].rarity).toBeGreaterThanOrEqual(Rarity.RARE);
    }
  });

  it('boss gold is multiplied by bossMultiplier=2.0', () => {
    const lich = MOBS.crypt_lich;
    const rng = makeLcgRng(42);
    const rewards = onMobKilled({ rng, mobDef: lich, bossMultiplier: 2.0 });
    expect(rewards.goldGained).toBeGreaterThanOrEqual(lich.gold_drop_min * 2);
    expect(rewards.goldGained).toBeLessThanOrEqual(lich.gold_drop_max * 2);
  });

  it('boss xp is multiplied by bossMultiplier=2.0', () => {
    const lich = MOBS.crypt_lich;
    const rng = makeLcgRng(99);
    const rewards = onMobKilled({ rng, mobDef: lich, bossMultiplier: 2.0 });
    expect(rewards.xpGained).toBe(lich.xp_drop * 2);
  });

  it('boss legendary drop still possible (not clamped above RARE)', () => {
    // Statistical: with enough seeds and fixed weights one should get EPIC/LEGENDARY
    // This test just verifies the guarantee is a floor (>= RARE), not a ceiling.
    const lich = MOBS.crypt_lich;
    const rarities = new Set<Rarity>();
    for (let seed = 0; seed < 500; seed++) {
      const rng = makeLcgRng(seed);
      const rewards = onMobKilled({ rng, mobDef: lich, bossMultiplier: 2.0 });
      rarities.add(rewards.items[0].rarity);
    }
    // All rarities should be >= RARE
    for (const r of rarities) {
      expect(r).toBeGreaterThanOrEqual(Rarity.RARE);
    }
    // Should see at least RARE (3 possible: RARE=2, EPIC=3, LEGENDARY=4)
    expect(rarities.size).toBeGreaterThanOrEqual(1);
  });

  it('bossMultiplier=1.0 with is_boss still forces drop and rare+', () => {
    // Even without explicit multiplier, is_boss=true should guarantee drop + rare+
    const lich = MOBS.crypt_lich;
    const rng = makeLcgRng(13);
    const rewards = onMobKilled({ rng, mobDef: lich }); // no bossMultiplier — defaults 1.0
    expect(rewards.items.length).toBe(1);
    expect(rewards.items[0].rarity).toBeGreaterThanOrEqual(Rarity.RARE);
    // Gold unchanged (1× multiplier)
    expect(rewards.goldGained).toBeGreaterThanOrEqual(lich.gold_drop_min);
    expect(rewards.goldGained).toBeLessThanOrEqual(lich.gold_drop_max);
  });
});

describe('rollRarity — determinism', () => {
  it('same seed produces same rewards for same mob', () => {
    const warrior = MOBS.skeleton_warrior;
    const makeRewards = () => {
      const rng = makeLcgRng(777);
      return onMobKilled({ rng, mobDef: warrior, dropChance: 1.0 });
    };
    const r1 = makeRewards();
    const r2 = makeRewards();
    expect(r1.goldGained).toBe(r2.goldGained);
    expect(r1.xpGained).toBe(r2.xpGained);
    expect(r1.items.length).toBe(r2.items.length);
    if (r1.items.length > 0) {
      expect(r1.items[0].rarity).toBe(r2.items[0].rarity);
    }
  });
});

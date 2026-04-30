/**
 * Mob death reward calculation — Colyseus side.
 *
 * Mirror of `backend/src/wotk/game/drops.py` with a critical deviation:
 * Colyseus has no access to the `affix_definition` table, so items are
 * represented as lightweight {@link ItemDropIntent} objects (rarity only).
 * FastAPI's `/internal/runs/{id}/finalize` picks the base_id and rolls
 * affixes from the DB pool.
 *
 * Rarity weights and drop chance mirror the Python defaults exactly.
 */

import type { MobDef } from './mobs.js';

/** Rarity values — mirrors `backend/src/wotk/game/loot.py` Rarity enum. */
export enum Rarity {
  COMMON = 0,
  MAGIC = 1,
  RARE = 2,
  EPIC = 3,
  LEGENDARY = 4,
}

/**
 * Lightweight drop intent sent to FastAPI for materialization.
 *
 * Colyseus sends only the rarity. FastAPI picks base_id from the dungeon's
 * loot_table and rolls affixes via the affix_definition pool.
 */
export interface ItemDropIntent {
  /** Rarity enum value (0=COMMON..4=LEGENDARY). */
  rarity: Rarity;
}

/**
 * Accumulated rewards for one mob kill.
 *
 * XP and gold are always granted. Items is empty if the drop roll failed.
 */
export interface KillRewards {
  /** XP to credit (always = mobDef.xp_drop). */
  xpGained: number;
  /** Gold to credit (uniform [goldDropMin, goldDropMax]). */
  goldGained: number;
  /** Drop intents — FastAPI materializes these into real items. */
  items: ItemDropIntent[];
}

/**
 * Default rarity weights — mirrors Python DEFAULT_RARITY_WEIGHTS (60/25/12/2/1).
 *
 * SOURCE OF TRUTH: backend/src/wotk/game/drops.py DEFAULT_RARITY_WEIGHTS.
 * Keep in sync — server-side roll должен совпадать с client-side preview hint.
 */
export const DEFAULT_RARITY_WEIGHTS: Record<Rarity, number> = {
  [Rarity.COMMON]: 60,
  [Rarity.MAGIC]: 25,
  [Rarity.RARE]: 12,
  [Rarity.EPIC]: 2,
  [Rarity.LEGENDARY]: 1,
};

/** Pre-computed total of {@link DEFAULT_RARITY_WEIGHTS} (= 100). */
const DEFAULT_RARITY_TOTAL = Object.values(DEFAULT_RARITY_WEIGHTS).reduce(
  (a, b) => a + b,
  0,
);

/** Base drop chance — mirrors Python BASE_DROP_CHANCE = 0.35. */
export const BASE_DROP_CHANCE = 0.35;

/**
 * Weighted random pick of a Rarity from weights table.
 *
 * @param rng - RNG returning [0, 1).
 * @param weights - Rarity → weight mapping.
 * @returns Chosen rarity.
 */
export function rollRarity(rng: () => number, weights: Record<Rarity, number>): Rarity {
  const total =
    weights === DEFAULT_RARITY_WEIGHTS
      ? DEFAULT_RARITY_TOTAL
      : Object.values(weights).reduce((a, b) => a + b, 0);
  const pick = rng() * total;
  let cum = 0;
  for (const [key, w] of Object.entries(weights) as [string, number][]) {
    cum += w;
    if (pick < cum) {
      return Number(key) as Rarity;
    }
  }
  return Rarity.COMMON;
}

/**
 * Compute kill rewards for a single mob death.
 *
 * XP = mobDef.xp_drop always. Gold = uniform [goldDropMin, goldDropMax].
 * Item drop: if rng() < dropChance, roll a rarity and push one ItemDropIntent.
 *
 * W6-013: When mobDef.is_boss is true:
 *  - dropChance forced to 1.0 (guaranteed drop).
 *  - Rarity forced to max(rolled, RARE) — guaranteed rare+.
 *  - goldGained and xpGained multiplied by bossMultiplier (default 2.0 for bosses).
 *
 * @param args.rng - Seeded RNG [0, 1).
 * @param args.mobDef - Definition of the killed mob.
 * @param args.dropChance - Override drop probability (default BASE_DROP_CHANCE).
 * @param args.rarityWeights - Override rarity weights (default DEFAULT_RARITY_WEIGHTS).
 * @param args.bossMultiplier - Gold/XP multiplier for boss kills (default 1.0; pass 2.0 for bosses).
 * @returns KillRewards accumulator (caller merges into room pendingRewards).
 */
export function onMobKilled(args: {
  rng: () => number;
  mobDef: MobDef;
  dropChance?: number;
  rarityWeights?: Record<Rarity, number>;
  bossMultiplier?: number;
}): KillRewards {
  const {
    rng,
    mobDef,
    dropChance = BASE_DROP_CHANCE,
    rarityWeights = DEFAULT_RARITY_WEIGHTS,
    bossMultiplier = 1.0,
  } = args;

  const isBoss = mobDef.is_boss;

  // W6-013: boss always drops, guaranteed rare+
  const effectiveDropChance = isBoss ? 1.0 : dropChance;

  // Gold: uniform integer in [gold_drop_min, gold_drop_max] inclusive.
  const goldRange = mobDef.gold_drop_max - mobDef.gold_drop_min;
  let goldGained = mobDef.gold_drop_min + Math.floor(rng() * (goldRange + 1));
  let xpGained = mobDef.xp_drop;

  const items: ItemDropIntent[] = [];
  if (rng() < effectiveDropChance) {
    let rarity = rollRarity(rng, rarityWeights);
    if (isBoss && rarity < Rarity.RARE) {
      rarity = Rarity.RARE;
    }
    items.push({ rarity });
  }

  // W6-013: apply boss_multiplier to gold and xp
  if (bossMultiplier !== 1.0) {
    goldGained = Math.floor(goldGained * bossMultiplier);
    xpGained = Math.floor(xpGained * bossMultiplier);
  }

  return {
    xpGained,
    goldGained,
    items,
  };
}

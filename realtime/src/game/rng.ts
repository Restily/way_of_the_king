/**
 * Shared seedable RNG factory for realtime game logic.
 *
 * Extracted from DungeonRoom so tests and game modules can share the same
 * deterministic LCG without duplicating the inline definition.
 *
 * LCG parameters match those used in DungeonRoom Day 1:
 *   state = (state * 1664525 + 1013904223) >>> 0
 * Returns values in [0, 1).
 */

/**
 * Create a deterministic Linear Congruential Generator (LCG) RNG.
 *
 * @param seed - Initial seed. Same seed → identical output sequence.
 * @returns Zero-argument function returning numbers in [0, 1).
 */
export function makeLcg(seed: number): () => number {
  let state = seed >>> 0; // ensure uint32
  return (): number => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

/**
 * Mulberry32 — alternative high-quality seedable PRNG.
 *
 * Better statistical properties than LCG; used in tests that need
 * controlled randomness without the LCG bias pattern.
 *
 * @param seed - Initial seed (uint32).
 * @returns Zero-argument function returning numbers in [0, 1).
 */
export function makeMulberry32(seed: number): () => number {
  let s = seed >>> 0;
  return (): number => {
    s += 0x6d2b79f5;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 0x100000000;
  };
}

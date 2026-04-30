/** Mirror of `backend/src/wotk/game/status_effects.py` — keep numbers in sync; pure logic only.
 *
 * camelCase mapping vs Python snake_case:
 *   status_type    → statusType
 *   applied_at_ms  → appliedAtMs
 *   duration_ms    → durationMs
 *   is_active      → isActive (function)
 *   filter_active  → filterActive
 *   is_stunned     → isStunned
 *   slow_multiplier → slowMultiplier
 *   dot_damage_per_sec → dotDamagePerSec
 */

export enum StatusType {
  STUN = 0,
  SLOW = 1,
  POISON = 2,
  BURN = 3,
}

export interface StatusEffect {
  statusType: StatusType;
  /** Server timestamp (ms) when effect was applied. */
  appliedAtMs: number;
  /** How long the effect lasts in ms. */
  durationMs: number;
  /**
   * Effect magnitude. Interpretation by type:
   *   STUN   → ignored (presence = stunned).
   *   SLOW   → % speed reduction (e.g. 50 = half speed).
   *   POISON → damage per second.
   *   BURN   → damage per second.
   */
  magnitude: number;
}

/**
 * True if the effect is still within its duration window.
 *
 * @param effect - StatusEffect to check.
 * @param nowMs - Current server time in ms.
 */
export function isActive(effect: StatusEffect, nowMs: number): boolean {
  return nowMs - effect.appliedAtMs < effect.durationMs;
}

/**
 * Filter to only active (non-expired) effects.
 *
 * @param effects - Full list of effects on an entity.
 * @param nowMs - Current server time in ms.
 * @returns New array containing only active effects.
 */
export function filterActive(effects: StatusEffect[], nowMs: number): StatusEffect[] {
  return effects.filter((e) => isActive(e, nowMs));
}

/**
 * True if any STUN effect is currently active.
 *
 * @param effects - Entity's status effect list.
 * @param nowMs - Current server time in ms.
 */
export function isStunned(effects: StatusEffect[], nowMs: number): boolean {
  return effects.some((e) => e.statusType === StatusType.STUN && isActive(e, nowMs));
}

/**
 * Speed multiplier from SLOW effects (1.0 = full speed, 0.5 = half speed).
 *
 * Multiple SLOWs do not stack — only the highest magnitude applies.
 * Floor at 0.1 to prevent full immobilisation via SLOW alone.
 *
 * @param effects - Entity's status effect list.
 * @param nowMs - Current server time in ms.
 * @returns Speed multiplier in [0.1, 1.0].
 */
export function slowMultiplier(effects: StatusEffect[], nowMs: number): number {
  let maxSlow = 0;
  for (const e of effects) {
    if (e.statusType === StatusType.SLOW && isActive(e, nowMs)) {
      maxSlow = Math.max(maxSlow, e.magnitude);
    }
  }
  return Math.max(0.1, 1.0 - maxSlow / 100.0);
}

/**
 * Total damage-over-time per second from all active POISON + BURN effects.
 *
 * Effects stack additively (mirrors Python dot_damage_per_sec).
 *
 * @param effects - Entity's status effect list.
 * @param nowMs - Current server time in ms.
 * @returns Total DoT damage per second.
 */
export function dotDamagePerSec(effects: StatusEffect[], nowMs: number): number {
  let total = 0;
  for (const e of effects) {
    if (
      (e.statusType === StatusType.POISON || e.statusType === StatusType.BURN) &&
      isActive(e, nowMs)
    ) {
      total += e.magnitude;
    }
  }
  return total;
}

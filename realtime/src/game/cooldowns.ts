/** Mirror of `backend/src/wotk/game/cooldowns.py` — keep numbers in sync; pure logic only.
 *
 * camelCase mapping vs Python snake_case:
 *   last_cast_ms    → lastCastMs
 *   try_cast        → tryCast
 *   remaining_ms    → remainingMs
 *   skill_id        → skillId
 *   current_time_ms → currentTimeMs
 *   cooldown_ms     → cooldownMs
 */

/**
 * Tracks per-skill last-cast timestamps. Pure data — caller passes currentTimeMs.
 *
 * Mirrors Python CooldownTracker exactly: missing key = never cast = always ready.
 * Atomic: tryCast returning true immediately records the timestamp.
 */
export class CooldownTracker {
  /** Maps skill_id → last cast timestamp in ms. */
  readonly lastCastMs: Map<string, number> = new Map();

  /**
   * Attempt to cast a skill. Records timestamp and returns true if CD is ready.
   *
   * @param skillId - Skill identifier (e.g. "cleave").
   * @param args.currentTimeMs - Current server tick time in ms.
   * @param args.cooldownMs - Skill cooldown from SkillDef.cooldownMs.
   * @returns true if cast allowed (CD started); false if still on cooldown.
   */
  tryCast(skillId: string, args: { currentTimeMs: number; cooldownMs: number }): boolean {
    const { currentTimeMs, cooldownMs } = args;
    const last = this.lastCastMs.get(skillId);
    if (last === undefined || currentTimeMs - last >= cooldownMs) {
      this.lastCastMs.set(skillId, currentTimeMs);
      return true;
    }
    return false;
  }

  /**
   * Remaining ms until skill is ready (0 = ready now).
   *
   * @param skillId - Skill identifier.
   * @param args.currentTimeMs - Current server tick time in ms.
   * @param args.cooldownMs - Skill cooldown duration in ms.
   * @returns 0 if ready, otherwise remaining milliseconds.
   */
  remainingMs(skillId: string, args: { currentTimeMs: number; cooldownMs: number }): number {
    const { currentTimeMs, cooldownMs } = args;
    const last = this.lastCastMs.get(skillId);
    if (last === undefined) return 0;
    const elapsed = currentTimeMs - last;
    return Math.max(0, cooldownMs - elapsed);
  }

  /**
   * Reset cooldown for a specific skill or all skills.
   *
   * @param skillId - Specific skill to reset, or undefined to reset all.
   */
  reset(skillId?: string): void {
    if (skillId === undefined) {
      this.lastCastMs.clear();
    } else {
      this.lastCastMs.delete(skillId);
    }
  }
}

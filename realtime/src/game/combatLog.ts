/**
 * Append-only combat event log for anti-cheat audit and replay.
 *
 * Mirror of `backend/src/wotk/game/combat_log.py`. Serializes to the same
 * `{"v": 1, "events": [...], ...}` shape that FastAPI writes to
 * `run_encounters.combat_summary` JSONB.
 *
 * Format v=1; on breaking change increment to v=2 and support both in reader.
 */

/** Event types — mirrors Python CombatEventType enum values. */
export enum CombatEventType {
  PLAYER_ATTACK = 0,
  MOB_ATTACK = 1,
  PLAYER_KILL_MOB = 2,
  MOB_KILL_PLAYER = 3,
  SKILL_CAST = 4,
  STATUS_APPLIED = 5,
}

/** One combat event. Minimal shape for JSONB serialization. */
export interface CombatEvent {
  /** Server tick when the event occurred (for ordering in replay). */
  tick: number;
  /** Event type. */
  eventType: CombatEventType;
  /** Who acted (player session-id hash or mob instance_id). */
  actorId: number;
  /** Target entity (undefined for self-cast or no-target events). */
  targetId?: number;
  /** Damage dealt (0 for non-damage events). */
  damage?: number;
  /** True if the hit was a critical strike. */
  wasCrit?: boolean;
  /** Arbitrary extra payload (skill_id, status_type, etc.). */
  extra?: Record<string, unknown>;
}

/**
 * Serialized combat summary shape written to run_encounters.combat_summary.
 *
 * The `v` field is required by the DB CHECK constraint.
 */
export interface CombatSummary {
  v: 1;
  damage_dealt: number;
  damage_taken: number;
  duration_s: number;
  deaths: number;
  events: Array<{
    t: number;
    k: number;
    a: number;
    tg?: number;
    dmg?: number;
    c?: number;
    x?: Record<string, unknown>;
  }>;
}

/**
 * Append-only combat log. Accumulates events for one encounter; serializes to
 * {@link CombatSummary} on `toSummary()`.
 *
 * Usage:
 * ```ts
 * const log = new CombatLog();
 * log.record({ tick: 10, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 25 });
 * const summary = log.toSummary();
 * ```
 */
export class CombatLog {
  private readonly _events: CombatEvent[] = [];
  private _damageDealt = 0;
  private _damageTaken = 0;
  private _deaths = 0;
  private _startTick: number | null = null;
  private _endTick = 0;

  /**
   * Record one event and update running aggregates.
   *
   * @param event - The combat event to append.
   */
  record(event: CombatEvent): void {
    this._events.push(event);

    if (this._startTick === null) {
      this._startTick = event.tick;
    }
    this._endTick = Math.max(this._endTick, event.tick);

    switch (event.eventType) {
      case CombatEventType.PLAYER_ATTACK:
        this._damageDealt += event.damage ?? 0;
        break;
      case CombatEventType.MOB_ATTACK:
        this._damageTaken += event.damage ?? 0;
        break;
      case CombatEventType.MOB_KILL_PLAYER:
        this._deaths += 1;
        break;
      default:
        break;
    }
  }

  /**
   * Serialize to the v=1 format compatible with run_encounters.combat_summary.
   *
   * @param tickRateHz - Server tick rate for duration_s calculation (default 20).
   * @returns {@link CombatSummary} ready for JSON serialization.
   */
  toSummary(tickRateHz = 20): CombatSummary {
    const ticks = this._startTick !== null ? this._endTick - this._startTick : 0;
    return {
      v: 1,
      damage_dealt: this._damageDealt,
      damage_taken: this._damageTaken,
      duration_s: Math.floor(ticks / tickRateHz),
      deaths: this._deaths,
      events: this._events.map((e) => ({
        t: e.tick,
        k: e.eventType,
        a: e.actorId,
        ...(e.targetId !== undefined && { tg: e.targetId }),
        ...(e.damage !== undefined && e.damage !== 0 && { dmg: e.damage }),
        ...(e.wasCrit && { c: 1 }),
        ...(e.extra && { x: e.extra }),
      })),
    };
  }

  /**
   * Flush the current floor's combat data and reset internal state.
   *
   * Returns the summary for the floor that just ended, then clears all
   * accumulated events and counters so the next floor starts fresh.
   * The existing `toSummary()` stays unchanged for the final flush in
   * onDispose (or for single-floor encounters).
   *
   * @param tickRateHz - Server tick rate for duration_s calculation (default 20).
   * @returns {@link CombatSummary} for the completed floor.
   */
  flushFloor(tickRateHz = 20): CombatSummary {
    const summary = this.toSummary(tickRateHz);

    // Reset all state for next floor
    this._events.length = 0;
    this._damageDealt = 0;
    this._damageTaken = 0;
    this._deaths = 0;
    this._startTick = null;
    this._endTick = 0;

    return summary;
  }

  /** Number of events recorded. */
  get eventCount(): number {
    return this._events.length;
  }
}

/**
 * TS interfaces for dungeon floor configuration.
 *
 * Mirror of `backend/src/wotk/game/dungeon_config.py` — keep in sync.
 *
 * These types describe the shape of `dungeon.config.floors[]` embedded in the
 * ws_token JWT at /enter time.  The Colyseus room reads them from
 * `auth.floors` to drive per-floor spawning and collision geometry.
 *
 * Schema version: v=1.  Bump when the shape changes incompatibly.
 */

/** 2-D integer coordinate. */
export interface Vec2 {
  x: number;
  y: number;
}

/** Axis-aligned wall rectangle in pixel space. */
export interface WallRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Configuration for a single floor inside a dungeon.
 *
 * `floor` must equal the index of this object inside `DungeonConfig.floors`.
 */
export interface FloorConfig {
  /** 0-based floor index. */
  floor: number;
  /** Perimeter and obstacle rectangles for server-side collision detection. */
  walls: WallRect[];
  /** Candidate anchor positions for mob spawning. */
  spawn_points: Vec2[];
  /**
   * Ordered list of mob_def IDs to spawn on this floor.
   * Ignored on boss floors (`is_boss_floor = true`).
   */
  mob_pack: string[];
  /** True for the last floor (boss floor). */
  is_boss_floor: boolean;
  /**
   * W6-012: ID of the boss mob_def to spawn on boss floors.
   * Only present when `is_boss_floor = true`.
   */
  boss_id?: string;
}

/** Top-level dungeon configuration embedded in the ws_token JWT payload. */
export interface DungeonConfig {
  /** Schema version (= 1). */
  v: number;
  /** Ordered list of per-floor configs; index must equal FloorConfig.floor. */
  floors: FloorConfig[];
}

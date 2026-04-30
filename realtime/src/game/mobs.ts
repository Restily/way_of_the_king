/**
 * Mirror of `backend/src/wotk/game/mobs.py` — keep numbers in sync; pure logic only.
 *
 * W6-010: added boss-specific fields and `crypt_lich` boss mob def.
 */

export interface MobDef {
  id: string;
  name_key: string;
  base_hp: number;
  base_atk: number;
  base_def: number;
  move_speed_px_s: number;
  detect_radius_px: number;
  attack_range_px: number;
  attack_cooldown_ms: number;
  xp_drop: number;
  gold_drop_min: number;
  gold_drop_max: number;
  /** W6-010: True for boss mobs (activates boss-specific AI branches). */
  is_boss: boolean;
  /** W6-010: Telegraph window in ms (charge → strike). 0 = no telegraph. */
  telegraph_ms: number;
  /** W6-010: HP% threshold for enrage (0.30 = 30%). 0.0 = no enrage. */
  enrage_hp_threshold_pct: number;
  /** W6-010: Summon period in ms. 0 = no summons. */
  summon_period_ms: number;
}

export const MOBS: Record<string, MobDef> = {
  skeleton_warrior: {
    id: 'skeleton_warrior',
    name_key: 'mob.skeleton_warrior.name',
    base_hp: 50,
    base_atk: 8,
    base_def: 2,
    move_speed_px_s: 80,
    detect_radius_px: 200,
    attack_range_px: 30,
    attack_cooldown_ms: 1500,
    xp_drop: 10,
    gold_drop_min: 20,
    gold_drop_max: 60,
    is_boss: false,
    telegraph_ms: 0,
    enrage_hp_threshold_pct: 0,
    summon_period_ms: 0,
  },
  skeleton_archer: {
    id: 'skeleton_archer',
    name_key: 'mob.skeleton_archer.name',
    base_hp: 35,
    base_atk: 12,
    base_def: 1,
    move_speed_px_s: 60,
    detect_radius_px: 300,
    attack_range_px: 200,
    attack_cooldown_ms: 2000,
    xp_drop: 12,
    gold_drop_min: 25,
    gold_drop_max: 70,
    is_boss: false,
    telegraph_ms: 0,
    enrage_hp_threshold_pct: 0,
    summon_period_ms: 0,
  },
  zombie: {
    id: 'zombie',
    name_key: 'mob.zombie.name',
    base_hp: 90,
    base_atk: 6,
    base_def: 4,
    move_speed_px_s: 50,
    detect_radius_px: 150,
    attack_range_px: 30,
    attack_cooldown_ms: 2000,
    xp_drop: 15,
    gold_drop_min: 30,
    gold_drop_max: 80,
    is_boss: false,
    telegraph_ms: 0,
    enrage_hp_threshold_pct: 0,
    summon_period_ms: 0,
  },
  // W6-010: Boss mob — Crypt Lich
  crypt_lich: {
    id: 'crypt_lich',
    name_key: 'mob.crypt_lich.name',
    base_hp: 600,
    base_atk: 40,
    base_def: 30,
    move_speed_px_s: 80,
    detect_radius_px: 1000,
    attack_range_px: 90,
    attack_cooldown_ms: 1500,
    xp_drop: 500,
    gold_drop_min: 100,
    gold_drop_max: 200,
    is_boss: true,
    telegraph_ms: 1000,
    enrage_hp_threshold_pct: 0.30,
    summon_period_ms: 20000,
  },
};

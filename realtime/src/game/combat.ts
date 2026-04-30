/** Mirror of `backend/src/wotk/game/combat.py` — keep numbers in sync; pure logic only.
 *
 * camelCase mapping vs Python snake_case:
 *   crit_chance_pct    → critChancePct
 *   crit_damage_pct    → critDamagePct
 *   weapon_min_dmg     → weaponMinDmg
 *   weapon_max_dmg     → weaponMaxDmg
 *   dodge_chance_pct   → dodgeChancePct
 *   was_crit           → wasCrit
 *   was_dodged         → wasDodged
 *
 * Python `rng: random.Random` is replaced with `rng: () => number`
 * (equivalent of rng.random()). For weapon roll (rng.randint) we compute
 * `Math.floor(rng() * (max - min + 1)) + min`.
 */

/** Тип урона. Определяет какую resistance проверять. */
export enum DamageType {
  PHYSICAL = 0,
  FIRE = 1,
  COLD = 2,
  LIGHTNING = 3,
  POISON = 4,
}

/** Global resistance cap — mirrors RESIST_CAP = 75 in combat.py. */
export const RESIST_CAP = 75;

/** Minimum damage per hit — mirrors MIN_DAMAGE = 1 in combat.py. */
export const MIN_DAMAGE = 1;

export interface AttackerStats {
  atk: number;
  critChancePct?: number;
  critDamagePct?: number;
  weaponMinDmg?: number;
  weaponMaxDmg?: number;
}

export interface DefenderStats {
  hp: number;
  def_?: number;
  dodgeChancePct?: number;
  resists?: Partial<Record<DamageType, number>>;
}

export interface DamageResult {
  raw: number;
  mitigated: number;
  wasCrit: boolean;
  wasDodged: boolean;
}

/**
 * Apply resistance to post-defense damage. Caps positive resist at RESIST_CAP.
 * Negative resist (vulnerability) amplifies damage.
 *
 * @param damage - Damage after defense mitigation.
 * @param resistPct - Resistance percentage. Negative = vulnerability.
 * @returns Damage after resistance.
 */
export function applyResistance(damage: number, resistPct: number): number {
  if (resistPct > 0) {
    const capped = Math.min(resistPct, RESIST_CAP);
    return Math.floor(damage * (1.0 - capped / 100.0));
  }
  if (resistPct < 0) {
    return Math.floor(damage * (1.0 - resistPct / 100.0));
  }
  return damage;
}

/**
 * Compute one hit: attacker → defender through a skill.
 *
 * Algorithm (mirrors combat.py exactly):
 *  1. Dodge roll: if dodge succeeds → return {raw:0, mitigated:0, wasDodged:true}.
 *  2. weapon roll: if weaponMaxDmg >= weaponMinDmg > 0 → randint(min, max).
 *  3. raw = floor(atk * skillMultiplier) + weaponRoll.
 *  4. Crit roll: if success → raw = floor(raw * critDamagePct / 100).
 *  5. afterDef = max(MIN_DAMAGE, raw - def_).
 *  6. resist lookup for damageType.
 *  7. final = max(MIN_DAMAGE, applyResistance(afterDef, resistPct)).
 *
 * @param args.attacker - Attacker stats.
 * @param args.defender - Defender stats.
 * @param args.skillMultiplier - Skill dmg_multiplier (1.0 = baseline).
 * @param args.damageType - Determines which resist to check.
 * @param args.rng - Seeded RNG returning [0, 1). Caller owns seed for replay.
 * @returns DamageResult with all intermediate values.
 */
export function computeDamage(args: {
  attacker: AttackerStats;
  defender: DefenderStats;
  skillMultiplier: number;
  damageType: DamageType;
  rng: () => number;
}): DamageResult {
  const { attacker, defender, skillMultiplier, damageType, rng } = args;

  const dodgeChance = defender.dodgeChancePct ?? 0;
  if (dodgeChance > 0 && rng() < dodgeChance / 100.0) {
    return { raw: 0, mitigated: 0, wasCrit: false, wasDodged: true };
  }

  const wMin = attacker.weaponMinDmg ?? 0;
  const wMax = attacker.weaponMaxDmg ?? 0;
  let weaponRoll = 0;
  if (wMax >= wMin && wMin > 0) {
    // Mirrors Python rng.randint(min, max) — inclusive on both ends
    weaponRoll = Math.floor(rng() * (wMax - wMin + 1)) + wMin;
  }

  let rawAttack = Math.floor(attacker.atk * skillMultiplier) + weaponRoll;

  const critChance = attacker.critChancePct ?? 0;
  const critDmg = attacker.critDamagePct ?? 150;
  const wasCrit = critChance > 0 && rng() < critChance / 100.0;
  if (wasCrit) {
    rawAttack = Math.floor(rawAttack * (critDmg / 100.0));
  }

  const def = defender.def_ ?? 0;
  const afterDef = Math.max(MIN_DAMAGE, rawAttack - def);

  const resistPct = defender.resists?.[damageType] ?? 0;
  const final = Math.max(MIN_DAMAGE, applyResistance(afterDef, resistPct));

  return { raw: rawAttack, mitigated: final, wasCrit, wasDodged: false };
}

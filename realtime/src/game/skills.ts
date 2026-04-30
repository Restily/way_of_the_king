/** Mirror of `backend/src/wotk/game/skills.py` — keep numbers in sync; pure logic only.
 *
 * camelCase mapping vs Python snake_case:
 *   name_key       → nameKey
 *   mana_cost      → manaCost
 *   cooldown_ms    → cooldownMs
 *   dmg_multiplier → dmgMultiplier
 *   range_px       → rangePx
 *   aoe_radius_px  → aoeRadiusPx
 *   aoe_cone_deg   → aoeConeDeg
 *   animation_ms   → animationMs
 *   damage_type    → damageType
 *
 * All 4 Knight skills (cleave, shield_bash, whirlwind, charge) have identical
 * numeric values to the Python definitions.
 */

import { DamageType } from './combat.js';

export interface SkillDef {
  id: string;
  nameKey: string;
  manaCost: number;
  cooldownMs: number;
  dmgMultiplier: number;
  rangePx: number;
  aoeRadiusPx: number;
  aoeConeDeg: number;
  animationMs: number;
  damageType: DamageType;
}

/**
 * Knight active skills — 4 entries matching Python KNIGHT_SKILLS exactly.
 *
 * All damage types are PHYSICAL in MVP. Elemental skills arrive in Phase 6.
 */
export const KNIGHT_SKILLS: Record<string, SkillDef> = {
  cleave: {
    id: 'cleave',
    nameKey: 'skill.cleave.name',
    manaCost: 0,
    cooldownMs: 800,
    dmgMultiplier: 1.2,
    rangePx: 100,
    aoeRadiusPx: 100,
    aoeConeDeg: 60,
    animationMs: 400,
    damageType: DamageType.PHYSICAL,
  },
  shield_bash: {
    id: 'shield_bash',
    nameKey: 'skill.shield_bash.name',
    manaCost: 0,
    cooldownMs: 6000,
    dmgMultiplier: 1.5,
    rangePx: 80,
    aoeRadiusPx: 0,
    aoeConeDeg: 0,
    animationMs: 600,
    damageType: DamageType.PHYSICAL,
  },
  whirlwind: {
    id: 'whirlwind',
    nameKey: 'skill.whirlwind.name',
    manaCost: 30,
    cooldownMs: 12000,
    dmgMultiplier: 0.8,
    rangePx: 0,
    aoeRadiusPx: 120,
    aoeConeDeg: 360,
    animationMs: 1500,
    damageType: DamageType.PHYSICAL,
  },
  charge: {
    id: 'charge',
    nameKey: 'skill.charge.name',
    manaCost: 20,
    cooldownMs: 8000,
    dmgMultiplier: 2.0,
    rangePx: 200,
    aoeRadiusPx: 0,
    aoeConeDeg: 0,
    animationMs: 500,
    damageType: DamageType.PHYSICAL,
  },
};

/** Mirror of `backend/src/wotk/game/skill_cast.py` — keep numbers in sync; pure logic only.
 *
 * camelCase mapping vs Python snake_case:
 *   entity_id         → entityId
 *   caster_position   → casterPosition
 *   target_position   → targetPosition
 *   hit_entities      → hitEntities
 *   aoe_radius_px     → aoeRadiusPx (via SkillDef)
 *   aoe_cone_deg      → aoeConeDeg  (via SkillDef)
 *   range_px          → rangePx     (via SkillDef)
 *
 * Pure function: no mana/CD checks (caller handles those before calling).
 */

import type { SkillDef } from './skills.js';

export interface Vec2 {
  x: number;
  y: number;
}

export interface TargetCandidate {
  /** Canonical mob instance_id (number). */
  entityId: number;
  position: Vec2;
}

export interface CastResult {
  success: boolean;
  reason: 'ok' | 'out_of_range' | 'no_targets';
  hitEntities: number[];
}

function _distance(a: Vec2, b: Vec2): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function _angleBetween(origin: Vec2, target: Vec2): number {
  return (Math.atan2(target.y - origin.y, target.x - origin.x) * 180) / Math.PI;
}

function _angularDistance(a: number, b: number): number {
  const d = Math.abs(a - b) % 360;
  return Math.min(d, 360 - d);
}

/**
 * Resolve which candidates are hit by a skill cast.
 *
 * Mirrors Python resolve_cast exactly:
 *  - range_px > 0: target_position must be within range of caster.
 *  - aoeRadiusPx == 0 (single-target): nearest candidate within 30px of target_position.
 *  - aoeConeDeg in {0, 360} and aoeRadiusPx > 0: circle AoE around target_position.
 *  - else: cone AoE from caster in direction of target_position.
 *
 * @param args.casterPosition - Caster world position.
 * @param args.skill - Skill definition (SkillDef).
 * @param args.targetPosition - Tap/aim world position.
 * @param args.candidates - Alive mobs to check (caller filters dead ones out).
 * @returns CastResult with hitEntities array (not tuple, for easy mutation in caller).
 */
export function resolveCast(args: {
  casterPosition: Vec2;
  skill: SkillDef;
  targetPosition: Vec2;
  candidates: TargetCandidate[];
}): CastResult {
  const { casterPosition, skill, targetPosition, candidates } = args;

  // Range check
  if (skill.rangePx > 0) {
    if (_distance(casterPosition, targetPosition) > skill.rangePx) {
      return { success: false, reason: 'out_of_range', hitEntities: [] };
    }
  }

  const hits: number[] = [];

  if (skill.aoeRadiusPx === 0) {
    // Single-target: nearest candidate within 30px tap-tolerance
    let nearest: TargetCandidate | null = null;
    let nearestD = Infinity;
    for (const c of candidates) {
      const d = _distance(targetPosition, c.position);
      if (d < nearestD) {
        nearestD = d;
        nearest = c;
      }
    }
    if (nearest !== null && nearestD <= 30) {
      hits.push(nearest.entityId);
    }
  } else if (skill.aoeConeDeg === 0 || skill.aoeConeDeg === 360) {
    // Circle AoE
    for (const c of candidates) {
      if (_distance(targetPosition, c.position) <= skill.aoeRadiusPx) {
        hits.push(c.entityId);
      }
    }
  } else {
    // Cone AoE — direction = caster → target
    const direction = _angleBetween(casterPosition, targetPosition);
    const halfCone = skill.aoeConeDeg / 2;
    for (const c of candidates) {
      if (_distance(casterPosition, c.position) > skill.aoeRadiusPx) continue;
      const angleToC = _angleBetween(casterPosition, c.position);
      if (_angularDistance(direction, angleToC) <= halfCone) {
        hits.push(c.entityId);
      }
    }
  }

  if (hits.length === 0) {
    return { success: false, reason: 'no_targets', hitEntities: [] };
  }
  return { success: true, reason: 'ok', hitEntities: hits };
}

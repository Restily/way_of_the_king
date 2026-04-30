import { describe, expect, it } from 'vitest';

import { resolveCast, type TargetCandidate, type Vec2 } from '../skillCast.js';
import { KNIGHT_SKILLS, type SkillDef } from '../skills.js';
import { DamageType } from '../combat.js';

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeSkill(overrides: Partial<SkillDef>): SkillDef {
  return {
    id: 'test',
    nameKey: 'skill.test.name',
    manaCost: 0,
    cooldownMs: 1000,
    dmgMultiplier: 1.0,
    rangePx: 0,
    aoeRadiusPx: 0,
    aoeConeDeg: 0,
    animationMs: 300,
    damageType: DamageType.PHYSICAL,
    ...overrides,
  };
}

function makeCandidate(entityId: number, x: number, y: number): TargetCandidate {
  return { entityId, position: { x, y } };
}

const ORIGIN: Vec2 = { x: 0, y: 0 };

// ── Out-of-range ─────────────────────────────────────────────────────────────

describe('resolveCast — out of range', () => {
  it('target beyond rangePx → out_of_range', () => {
    const skill = makeSkill({ rangePx: 100, aoeRadiusPx: 0 });
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: { x: 150, y: 0 },
      candidates: [makeCandidate(1, 150, 0)],
    });
    expect(result.success).toBe(false);
    expect(result.reason).toBe('out_of_range');
    expect(result.hitEntities).toHaveLength(0);
  });

  it('target exactly at rangePx → allowed (boundary inclusive)', () => {
    const skill = makeSkill({ rangePx: 100, aoeRadiusPx: 0 });
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: { x: 100, y: 0 },
      candidates: [makeCandidate(1, 100, 0)],
    });
    // Target at exactly 100px: distance=100, rangePx=100 → 100 > 100 is false → allowed
    expect(result.reason).not.toBe('out_of_range');
  });

  it('rangePx=0 means no range limit', () => {
    const skill = makeSkill({ rangePx: 0, aoeRadiusPx: 120, aoeConeDeg: 360 });
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: { x: 10000, y: 10000 },
      candidates: [makeCandidate(1, 10000, 10000)],
    });
    // aoeRadiusPx=120 circle around target → candidate at target → 0 distance ≤ 120
    expect(result.reason).not.toBe('out_of_range');
  });
});

// ── Single-target nearest ─────────────────────────────────────────────────────

describe('resolveCast — single-target', () => {
  it('no candidates → no_targets', () => {
    const skill = makeSkill({ aoeRadiusPx: 0 });
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: { x: 50, y: 0 },
      candidates: [],
    });
    expect(result.success).toBe(false);
    expect(result.reason).toBe('no_targets');
  });

  it('nearest within 30px threshold → hits', () => {
    const skill = makeSkill({ aoeRadiusPx: 0 });
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: { x: 50, y: 0 },
      candidates: [makeCandidate(1, 60, 0)], // 10px from target
    });
    expect(result.success).toBe(true);
    expect(result.hitEntities).toContain(1);
  });

  it('selects nearest among multiple candidates', () => {
    const skill = makeSkill({ aoeRadiusPx: 0 });
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: { x: 50, y: 0 },
      candidates: [
        makeCandidate(1, 65, 0), // 15px from target
        makeCandidate(2, 55, 0), // 5px from target — nearer
        makeCandidate(3, 70, 0), // 20px from target
      ],
    });
    expect(result.success).toBe(true);
    expect(result.hitEntities).toEqual([2]);
  });

  it('candidate beyond 30px threshold → no_targets', () => {
    const skill = makeSkill({ aoeRadiusPx: 0 });
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: { x: 50, y: 0 },
      candidates: [makeCandidate(1, 90, 0)], // 40px from target
    });
    expect(result.success).toBe(false);
    expect(result.reason).toBe('no_targets');
  });
});

// ── AoE circle ───────────────────────────────────────────────────────────────

describe('resolveCast — AoE circle', () => {
  it('all candidates within radius → all hit', () => {
    const skill = makeSkill({ aoeRadiusPx: 100, aoeConeDeg: 360 });
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: ORIGIN,
      candidates: [
        makeCandidate(1, 50, 0),
        makeCandidate(2, 0, 80),
        makeCandidate(3, -60, 60),
      ],
    });
    expect(result.success).toBe(true);
    expect(result.hitEntities).toHaveLength(3);
    expect(result.hitEntities).toContain(1);
    expect(result.hitEntities).toContain(2);
    expect(result.hitEntities).toContain(3);
  });

  it('candidate outside radius → not hit', () => {
    const skill = makeSkill({ aoeRadiusPx: 100, aoeConeDeg: 360 });
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: ORIGIN,
      candidates: [
        makeCandidate(1, 50, 0),  // inside
        makeCandidate(2, 200, 0), // outside
      ],
    });
    expect(result.hitEntities).toContain(1);
    expect(result.hitEntities).not.toContain(2);
  });

  it('aoeConeDeg=0 with aoeRadiusPx>0 → circle (mirrors Python elif branch)', () => {
    // Python: elif skill.aoe_cone_deg in (0, 360) → circle
    const skill = makeSkill({ aoeRadiusPx: 100, aoeConeDeg: 0 });
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: ORIGIN,
      candidates: [makeCandidate(1, 50, 0)],
    });
    expect(result.success).toBe(true);
    expect(result.hitEntities).toContain(1);
  });
});

// ── AoE cone ─────────────────────────────────────────────────────────────────

describe('resolveCast — AoE cone (cleave)', () => {
  // cleave: rangePx=100, aoeRadiusPx=100, aoeConeDeg=60 (halfCone=30°)
  // Caster at (0,0), target at (100,0) → direction = 0° (east)
  // Half-cone = 30°; candidates within 100px of caster AND within ±30° of east

  it('candidate in cone → hit', () => {
    const skill = KNIGHT_SKILLS.cleave;
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: { x: 100, y: 0 },
      candidates: [makeCandidate(1, 80, 0)], // directly east, 80px
    });
    expect(result.success).toBe(true);
    expect(result.hitEntities).toContain(1);
  });

  it('candidate outside cone angle → not hit', () => {
    const skill = KNIGHT_SKILLS.cleave;
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: { x: 100, y: 0 }, // pointing east
      candidates: [
        makeCandidate(1, 0, -80), // north (270°/−90°) — 90° from east > 30° half-cone
      ],
    });
    expect(result.hitEntities).not.toContain(1);
  });

  it('candidate in cone angle but beyond radius → not hit', () => {
    const skill = KNIGHT_SKILLS.cleave;
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: { x: 100, y: 0 },
      candidates: [makeCandidate(1, 200, 0)], // east but 200px > 100px radius
    });
    expect(result.hitEntities).not.toContain(1);
  });

  it('multiple candidates: some in cone, some not', () => {
    const skill = KNIGHT_SKILLS.cleave;
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: { x: 100, y: 0 }, // pointing east
      candidates: [
        makeCandidate(1, 80, 20),  // east-ish, ~14° → inside 30° half-cone
        makeCandidate(2, 0, -80),  // north → 90° from east → outside
        makeCandidate(3, 70, -35), // ~−27° from east → inside (< 30°)
      ],
    });
    expect(result.hitEntities).toContain(1);
    expect(result.hitEntities).not.toContain(2);
    expect(result.hitEntities).toContain(3);
  });
});

// ── No targets ────────────────────────────────────────────────────────────────

describe('resolveCast — no targets', () => {
  it('empty candidates list → no_targets for circle AoE', () => {
    const skill = makeSkill({ aoeRadiusPx: 500, aoeConeDeg: 360 });
    const result = resolveCast({
      casterPosition: ORIGIN,
      skill,
      targetPosition: ORIGIN,
      candidates: [],
    });
    expect(result.success).toBe(false);
    expect(result.reason).toBe('no_targets');
  });
});

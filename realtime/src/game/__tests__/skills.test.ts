import { describe, expect, it } from 'vitest';

import { DamageType } from '../combat.js';
import { KNIGHT_SKILLS } from '../skills.js';

// ── Knight skills registry tests ─────────────────────────────────────────────

describe('KNIGHT_SKILLS', () => {
  it('all 4 Knight skills are present with their correct id keys', () => {
    expect(KNIGHT_SKILLS).toHaveProperty('cleave');
    expect(KNIGHT_SKILLS).toHaveProperty('shield_bash');
    expect(KNIGHT_SKILLS).toHaveProperty('whirlwind');
    expect(KNIGHT_SKILLS).toHaveProperty('charge');
  });

  it('id field matches the record key for each skill', () => {
    for (const [key, skill] of Object.entries(KNIGHT_SKILLS)) {
      expect(skill.id).toBe(key);
    }
  });

  it('all damage types are PHYSICAL in MVP', () => {
    for (const skill of Object.values(KNIGHT_SKILLS)) {
      expect(skill.damageType).toBe(DamageType.PHYSICAL);
    }
  });

  it('all cooldowns are within reasonable range (100ms–60000ms)', () => {
    for (const skill of Object.values(KNIGHT_SKILLS)) {
      expect(skill.cooldownMs).toBeGreaterThanOrEqual(100);
      expect(skill.cooldownMs).toBeLessThanOrEqual(60000);
    }
  });

  it('cleave: cone AoE with matching dmgMultiplier', () => {
    const cleave = KNIGHT_SKILLS.cleave;
    expect(cleave.aoeRadiusPx).toBeGreaterThan(0);
    expect(cleave.aoeConeDeg).toBe(60);
    expect(cleave.dmgMultiplier).toBeCloseTo(1.2);
    expect(cleave.manaCost).toBe(0);
    expect(cleave.cooldownMs).toBe(800);
  });

  it('shield_bash: single-target, applies stun (aoeRadius=0)', () => {
    const sb = KNIGHT_SKILLS.shield_bash;
    expect(sb.aoeRadiusPx).toBe(0);
    expect(sb.aoeConeDeg).toBe(0);
    expect(sb.dmgMultiplier).toBeCloseTo(1.5);
    expect(sb.cooldownMs).toBe(6000);
    expect(sb.manaCost).toBe(0);
  });

  it('whirlwind: circle AoE with mana cost and long CD', () => {
    const ww = KNIGHT_SKILLS.whirlwind;
    expect(ww.aoeRadiusPx).toBeGreaterThan(0);
    expect(ww.aoeConeDeg).toBe(360);
    expect(ww.manaCost).toBeGreaterThan(0);
    expect(ww.cooldownMs).toBeGreaterThan(1000);
    expect(ww.rangePx).toBe(0); // self-cast
  });

  it('charge: single-target with highest range and dmgMultiplier', () => {
    const charge = KNIGHT_SKILLS.charge;
    expect(charge.aoeRadiusPx).toBe(0);
    expect(charge.rangePx).toBeGreaterThan(100);
    expect(charge.dmgMultiplier).toBeCloseTo(2.0);
    expect(charge.manaCost).toBeGreaterThan(0);
  });

  it('all skills have nameKey in i18n format (skill.<id>.name)', () => {
    for (const skill of Object.values(KNIGHT_SKILLS)) {
      expect(skill.nameKey).toBe(`skill.${skill.id}.name`);
    }
  });

  it('all skills have positive animationMs', () => {
    for (const skill of Object.values(KNIGHT_SKILLS)) {
      expect(skill.animationMs).toBeGreaterThan(0);
    }
  });
});

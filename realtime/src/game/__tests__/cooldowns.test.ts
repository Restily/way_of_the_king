import { describe, expect, it } from 'vitest';

import { CooldownTracker } from '../cooldowns.js';

// ── CooldownTracker tests ─────────────────────────────────────────────────────

describe('CooldownTracker', () => {
  it('first cast always succeeds (no prior record)', () => {
    const tracker = new CooldownTracker();
    const ok = tracker.tryCast('cleave', { currentTimeMs: 1000, cooldownMs: 800 });
    expect(ok).toBe(true);
  });

  it('second cast immediately after first → on CD, returns false', () => {
    const tracker = new CooldownTracker();
    tracker.tryCast('cleave', { currentTimeMs: 1000, cooldownMs: 800 });
    const ok = tracker.tryCast('cleave', { currentTimeMs: 1001, cooldownMs: 800 });
    expect(ok).toBe(false);
  });

  it('cast exactly at CD boundary (elapsed === cooldownMs) → allowed', () => {
    const tracker = new CooldownTracker();
    tracker.tryCast('cleave', { currentTimeMs: 1000, cooldownMs: 800 });
    // At 1800ms: elapsed = 1800 - 1000 = 800 >= 800 → allowed
    const ok = tracker.tryCast('cleave', { currentTimeMs: 1800, cooldownMs: 800 });
    expect(ok).toBe(true);
  });

  it('cast just before CD expiry → rejected', () => {
    const tracker = new CooldownTracker();
    tracker.tryCast('cleave', { currentTimeMs: 1000, cooldownMs: 800 });
    // At 1799ms: elapsed = 799 < 800 → rejected
    const ok = tracker.tryCast('cleave', { currentTimeMs: 1799, cooldownMs: 800 });
    expect(ok).toBe(false);
  });

  it('after CD expires the next cast succeeds', () => {
    const tracker = new CooldownTracker();
    tracker.tryCast('cleave', { currentTimeMs: 0, cooldownMs: 800 });
    expect(tracker.tryCast('cleave', { currentTimeMs: 400, cooldownMs: 800 })).toBe(false);
    expect(tracker.tryCast('cleave', { currentTimeMs: 900, cooldownMs: 800 })).toBe(true);
  });

  it('per-skill independence: one skill on CD does not affect another', () => {
    const tracker = new CooldownTracker();
    tracker.tryCast('cleave', { currentTimeMs: 0, cooldownMs: 800 });
    // shield_bash not yet cast → always ready
    const ok = tracker.tryCast('shield_bash', { currentTimeMs: 100, cooldownMs: 6000 });
    expect(ok).toBe(true);
    // cleave still on CD
    expect(tracker.tryCast('cleave', { currentTimeMs: 100, cooldownMs: 800 })).toBe(false);
  });

  it('remainingMs returns 0 for uncasted skill', () => {
    const tracker = new CooldownTracker();
    expect(tracker.remainingMs('cleave', { currentTimeMs: 5000, cooldownMs: 800 })).toBe(0);
  });

  it('remainingMs returns correct ms when on CD', () => {
    const tracker = new CooldownTracker();
    tracker.tryCast('cleave', { currentTimeMs: 1000, cooldownMs: 800 });
    // At 1300ms: remaining = 800 - (1300-1000) = 500
    expect(tracker.remainingMs('cleave', { currentTimeMs: 1300, cooldownMs: 800 })).toBe(500);
  });

  it('remainingMs returns 0 when CD has expired', () => {
    const tracker = new CooldownTracker();
    tracker.tryCast('cleave', { currentTimeMs: 0, cooldownMs: 800 });
    expect(tracker.remainingMs('cleave', { currentTimeMs: 900, cooldownMs: 800 })).toBe(0);
  });

  it('reset(skillId) clears specific skill CD', () => {
    const tracker = new CooldownTracker();
    tracker.tryCast('cleave', { currentTimeMs: 0, cooldownMs: 800 });
    tracker.tryCast('shield_bash', { currentTimeMs: 0, cooldownMs: 6000 });
    tracker.reset('cleave');
    // cleave is cleared → can cast immediately
    expect(tracker.tryCast('cleave', { currentTimeMs: 100, cooldownMs: 800 })).toBe(true);
    // shield_bash still on CD
    expect(tracker.tryCast('shield_bash', { currentTimeMs: 100, cooldownMs: 6000 })).toBe(false);
  });

  it('reset() with no args clears all skill CDs', () => {
    const tracker = new CooldownTracker();
    tracker.tryCast('cleave', { currentTimeMs: 0, cooldownMs: 800 });
    tracker.tryCast('shield_bash', { currentTimeMs: 0, cooldownMs: 6000 });
    tracker.reset();
    expect(tracker.tryCast('cleave', { currentTimeMs: 100, cooldownMs: 800 })).toBe(true);
    expect(tracker.tryCast('shield_bash', { currentTimeMs: 100, cooldownMs: 6000 })).toBe(true);
  });

  it('tryCast records correct timestamp — next window starts from new cast', () => {
    const tracker = new CooldownTracker();
    tracker.tryCast('cleave', { currentTimeMs: 0, cooldownMs: 800 });
    tracker.tryCast('cleave', { currentTimeMs: 900, cooldownMs: 800 }); // second cast at t=900
    // Next ready at 900 + 800 = 1700
    expect(tracker.tryCast('cleave', { currentTimeMs: 1699, cooldownMs: 800 })).toBe(false);
    expect(tracker.tryCast('cleave', { currentTimeMs: 1700, cooldownMs: 800 })).toBe(true);
  });
});

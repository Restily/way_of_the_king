/**
 * Unit tests for CombatLog — mirrors Python test_combat_log.py structure.
 *
 * Verifies: event recording, toSummary v=1 shape, aggregate calculations
 * (damage_dealt, damage_taken, deaths), and duration_s tick→second conversion.
 */

import { describe, expect, it } from 'vitest';
import { CombatLog, CombatEventType } from '../combatLog.js';

describe('CombatLog', () => {
  it('toSummary returns v=1 with empty events when no events recorded', () => {
    const cl = new CombatLog();
    const summary = cl.toSummary();
    expect(summary.v).toBe(1);
    expect(summary.damage_dealt).toBe(0);
    expect(summary.damage_taken).toBe(0);
    expect(summary.deaths).toBe(0);
    expect(summary.duration_s).toBe(0);
    expect(summary.events).toHaveLength(0);
  });

  it('aggregates damage_dealt from PLAYER_ATTACK events', () => {
    const cl = new CombatLog();
    cl.record({ tick: 1, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 25 });
    cl.record({ tick: 2, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 40 });
    const summary = cl.toSummary();
    expect(summary.damage_dealt).toBe(65);
    expect(summary.damage_taken).toBe(0);
  });

  it('aggregates damage_taken from MOB_ATTACK events', () => {
    const cl = new CombatLog();
    cl.record({ tick: 1, eventType: CombatEventType.MOB_ATTACK, actorId: 99, targetId: 1, damage: 15 });
    cl.record({ tick: 2, eventType: CombatEventType.MOB_ATTACK, actorId: 99, targetId: 1, damage: 10 });
    const summary = cl.toSummary();
    expect(summary.damage_taken).toBe(25);
    expect(summary.damage_dealt).toBe(0);
  });

  it('counts deaths from MOB_KILL_PLAYER events', () => {
    const cl = new CombatLog();
    cl.record({ tick: 5, eventType: CombatEventType.MOB_KILL_PLAYER, actorId: 99, targetId: 1 });
    cl.record({ tick: 6, eventType: CombatEventType.MOB_KILL_PLAYER, actorId: 99, targetId: 2 });
    const summary = cl.toSummary();
    expect(summary.deaths).toBe(2);
  });

  it('calculates duration_s from first to last tick at default 20Hz', () => {
    const cl = new CombatLog();
    cl.record({ tick: 10, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 5 });
    cl.record({ tick: 110, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 5 });
    // 100 ticks / 20 Hz = 5s
    const summary = cl.toSummary(20);
    expect(summary.duration_s).toBe(5);
  });

  it('calculates duration_s with custom tick rate', () => {
    const cl = new CombatLog();
    cl.record({ tick: 0, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 10 });
    cl.record({ tick: 60, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 10 });
    // 60 ticks / 10 Hz = 6s
    const summary = cl.toSummary(10);
    expect(summary.duration_s).toBe(6);
  });

  it('serializes events with correct field mapping', () => {
    const cl = new CombatLog();
    cl.record({
      tick: 5,
      eventType: CombatEventType.PLAYER_ATTACK,
      actorId: 1,
      targetId: 42,
      damage: 30,
      wasCrit: true,
      extra: { skill_id: 'slash' },
    });
    const summary = cl.toSummary();
    expect(summary.events).toHaveLength(1);
    const ev = summary.events[0];
    expect(ev).toBeDefined();
    if (ev) {
      expect(ev.t).toBe(5);
      expect(ev.k).toBe(CombatEventType.PLAYER_ATTACK);
      expect(ev.a).toBe(1);
      expect(ev.tg).toBe(42);
      expect(ev.dmg).toBe(30);
      expect(ev.c).toBe(1);
      expect(ev.x).toEqual({ skill_id: 'slash' });
    }
  });

  it('omits undefined optional fields from serialized events', () => {
    const cl = new CombatLog();
    cl.record({ tick: 1, eventType: CombatEventType.PLAYER_KILL_MOB, actorId: 1, targetId: 5 });
    const summary = cl.toSummary();
    const ev = summary.events[0];
    expect(ev).toBeDefined();
    if (ev) {
      expect(ev.tg).toBe(5);
      expect(ev.dmg).toBeUndefined();
      expect(ev.c).toBeUndefined();
      expect(ev.x).toBeUndefined();
    }
  });

  it('does not include dmg key for zero-damage events', () => {
    const cl = new CombatLog();
    cl.record({ tick: 1, eventType: CombatEventType.SKILL_CAST, actorId: 1, damage: 0 });
    const summary = cl.toSummary();
    const ev = summary.events[0];
    expect(ev).toBeDefined();
    if (ev) {
      expect(ev.dmg).toBeUndefined();
    }
  });

  it('eventCount reflects number of recorded events', () => {
    const cl = new CombatLog();
    expect(cl.eventCount).toBe(0);
    cl.record({ tick: 1, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 5 });
    cl.record({ tick: 2, eventType: CombatEventType.MOB_ATTACK, actorId: 99, damage: 3 });
    expect(cl.eventCount).toBe(2);
  });

  it('mixed event types aggregate correctly', () => {
    const cl = new CombatLog();
    cl.record({ tick: 1, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 50 });
    cl.record({ tick: 2, eventType: CombatEventType.MOB_ATTACK, actorId: 99, damage: 20 });
    cl.record({ tick: 3, eventType: CombatEventType.PLAYER_KILL_MOB, actorId: 1, targetId: 99 });
    cl.record({ tick: 4, eventType: CombatEventType.MOB_KILL_PLAYER, actorId: 99, targetId: 1 });
    cl.record({ tick: 5, eventType: CombatEventType.SKILL_CAST, actorId: 1, extra: { skill_id: 'slash' } });
    const summary = cl.toSummary();
    expect(summary.damage_dealt).toBe(50);
    expect(summary.damage_taken).toBe(20);
    expect(summary.deaths).toBe(1);
    expect(summary.events).toHaveLength(5);
  });

  // ── flushFloor tests ───────────────────────────────────────────────────────

  it('flushFloor returns current summary then resets state', () => {
    const cl = new CombatLog();
    cl.record({ tick: 1, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 30 });
    cl.record({ tick: 2, eventType: CombatEventType.MOB_ATTACK, actorId: 99, damage: 10 });
    cl.record({ tick: 3, eventType: CombatEventType.MOB_KILL_PLAYER, actorId: 99, targetId: 1 });

    const floorSummary = cl.flushFloor();
    expect(floorSummary.v).toBe(1);
    expect(floorSummary.damage_dealt).toBe(30);
    expect(floorSummary.damage_taken).toBe(10);
    expect(floorSummary.deaths).toBe(1);
    expect(floorSummary.events).toHaveLength(3);

    // After flush: all counters reset
    expect(cl.eventCount).toBe(0);
    const nextSummary = cl.toSummary();
    expect(nextSummary.damage_dealt).toBe(0);
    expect(nextSummary.damage_taken).toBe(0);
    expect(nextSummary.deaths).toBe(0);
    expect(nextSummary.events).toHaveLength(0);
  });

  it('flushFloor on empty log returns zero summary and stays empty', () => {
    const cl = new CombatLog();
    const summary = cl.flushFloor();
    expect(summary.v).toBe(1);
    expect(summary.damage_dealt).toBe(0);
    expect(summary.events).toHaveLength(0);
    expect(cl.eventCount).toBe(0);
  });

  it('flushFloor followed by recording next floor events works independently', () => {
    const cl = new CombatLog();

    // Floor 0 events
    cl.record({ tick: 1, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 100 });
    const floor0 = cl.flushFloor();
    expect(floor0.damage_dealt).toBe(100);
    expect(floor0.events).toHaveLength(1);

    // Floor 1 events (different tick range)
    cl.record({ tick: 200, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 55 });
    cl.record({ tick: 210, eventType: CombatEventType.MOB_ATTACK, actorId: 99, damage: 25 });
    const floor1 = cl.flushFloor();
    expect(floor1.damage_dealt).toBe(55);
    expect(floor1.damage_taken).toBe(25);
    expect(floor1.events).toHaveLength(2);

    // After second flush, state is clean again
    expect(cl.eventCount).toBe(0);
    const empty = cl.toSummary();
    expect(empty.damage_dealt).toBe(0);
  });

  it('flushFloor does not affect the original toSummary after a subsequent record', () => {
    const cl = new CombatLog();
    cl.record({ tick: 5, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 40 });
    cl.flushFloor(); // clears floor 0

    // New event for floor 1
    cl.record({ tick: 100, eventType: CombatEventType.PLAYER_ATTACK, actorId: 1, damage: 20 });
    const finalSummary = cl.toSummary();
    // Only the floor-1 event should appear
    expect(finalSummary.damage_dealt).toBe(20);
    expect(finalSummary.events).toHaveLength(1);
  });
});

import { describe, expect, it } from 'vitest';

import { findPath, type Rect } from '../pathfind.js';

// ── Helpers ─────────────────────────────────────────────────────────────────

/** No walls — open field. */
const NO_WALLS: readonly Rect[] = Object.freeze([]);

/** Perimeter walls for a 20×15 tile (32px) arena. */
const TILE = 32;
const COLS = 20;
const ROWS = 15;
const ARENA_WALLS: readonly Rect[] = Object.freeze([
  { x: 0, y: 0, w: COLS * TILE, h: TILE },
  { x: 0, y: (ROWS - 1) * TILE, w: COLS * TILE, h: TILE },
  { x: 0, y: 0, w: TILE, h: ROWS * TILE },
  { x: (COLS - 1) * TILE, y: 0, w: TILE, h: ROWS * TILE },
]);

describe('findPath — basic cases', () => {
  it('direct path with no walls returns ≥2 waypoints', () => {
    const path = findPath({
      start: { x: 64, y: 64 },
      goal: { x: 320, y: 64 },
      walls: NO_WALLS,
    });
    expect(path.length).toBeGreaterThanOrEqual(2);
  });

  it('first waypoint is close to start cell centre', () => {
    const GRID = 32;
    const path = findPath({
      start: { x: 64, y: 64 },
      goal: { x: 320, y: 64 },
      walls: NO_WALLS,
    });
    // Start cell (64→col=2, row=2), centre = 2*32+16 = 80
    expect(path[0].x).toBeCloseTo(80, 0);
    expect(path[0].y).toBeCloseTo(80, 0);
  });

  it('last waypoint is close to goal cell centre', () => {
    const path = findPath({
      start: { x: 64, y: 64 },
      goal: { x: 320, y: 64 },
      walls: NO_WALLS,
    });
    // Goal cell (320→col=10, row=2), centre = 10*32+16 = 336
    const last = path[path.length - 1];
    expect(last.x).toBeCloseTo(336, 0);
    expect(last.y).toBeCloseTo(64 + 16, 0); // row 2 → 80
  });

  it('same start and goal → returns [start, goal] degenerate', () => {
    const start = { x: 64, y: 64 };
    const goal = { x: 64, y: 64 };
    const path = findPath({ start, goal, walls: NO_WALLS });
    expect(path).toHaveLength(2);
    expect(path[0]).toEqual(start);
    expect(path[1]).toEqual(goal);
  });

  it('goal blocked by wall → returns empty array', () => {
    // Place a wall that covers the entire right half of the space
    const blockingWall: Rect = { x: 256, y: 0, w: 1000, h: 1000 };
    const path = findPath({
      start: { x: 64, y: 64 },
      goal: { x: 400, y: 64 },
      walls: [blockingWall],
    });
    expect(path).toHaveLength(0);
  });

  it('path around a wall is longer than Manhattan distance', () => {
    // A vertical wall between start (x=64) and goal (x=320) at x=160
    const verticalWall: Rect = { x: 160, y: 0, w: 32, h: 200 };
    const withWall = findPath({
      start: { x: 64, y: 64 },
      goal: { x: 320, y: 64 },
      walls: [verticalWall],
    });
    const direct = findPath({
      start: { x: 64, y: 64 },
      goal: { x: 320, y: 64 },
      walls: NO_WALLS,
    });
    // Path around wall must be longer than direct path
    expect(withWall.length).toBeGreaterThan(direct.length);
  });

  it('inside arena — can navigate from one corner to another', () => {
    const path = findPath({
      start: { x: 64, y: 64 },
      goal: { x: 540, y: 400 },
      walls: ARENA_WALLS,
    });
    expect(path.length).toBeGreaterThan(0);
  });
});

describe('findPath — cache correctness', () => {
  it('second call with same walls reference returns same result', () => {
    const walls: readonly Rect[] = Object.freeze([{ x: 160, y: 0, w: 32, h: 200 }]);

    const path1 = findPath({ start: { x: 64, y: 64 }, goal: { x: 320, y: 64 }, walls });
    const path2 = findPath({ start: { x: 64, y: 64 }, goal: { x: 320, y: 64 }, walls });

    expect(path1).toHaveLength(path2.length);
    for (let i = 0; i < path1.length; i++) {
      expect(path1[i].x).toBeCloseTo(path2[i].x, 5);
      expect(path1[i].y).toBeCloseTo(path2[i].y, 5);
    }
  });

  it('different walls reference with same content produces same path length', () => {
    const walls1: readonly Rect[] = [{ x: 160, y: 0, w: 32, h: 200 }];
    const walls2: readonly Rect[] = [{ x: 160, y: 0, w: 32, h: 200 }];

    const p1 = findPath({ start: { x: 64, y: 64 }, goal: { x: 320, y: 64 }, walls: walls1 });
    const p2 = findPath({ start: { x: 64, y: 64 }, goal: { x: 320, y: 64 }, walls: walls2 });
    expect(p1.length).toBe(p2.length);
  });

  it('no walls → unreachable goal returns []', () => {
    // Max explore exceeded: large distance
    const path = findPath({
      start: { x: 0, y: 0 },
      goal: { x: 99999, y: 99999 },
      walls: NO_WALLS,
      maxExplore: 10, // very low cap → path not found
    });
    expect(path).toHaveLength(0);
  });
});

describe('findPath — grid size customisation', () => {
  it('larger gridSize = 64 works and returns fewer cells than gridSize=32', () => {
    const path32 = findPath({
      start: { x: 64, y: 64 },
      goal: { x: 512, y: 64 },
      walls: NO_WALLS,
      gridSize: 32,
    });
    const path64 = findPath({
      start: { x: 64, y: 64 },
      goal: { x: 512, y: 64 },
      walls: NO_WALLS,
      gridSize: 64,
    });
    // coarser grid → fewer waypoints
    expect(path64.length).toBeLessThanOrEqual(path32.length);
  });
});

/** Mirror of `backend/src/wotk/game/pathfind.py` — keep numbers in sync; pure logic only. */

import type { Vec2 } from './spawn.js';

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface GridPoint {
  col: number;
  row: number;
}

function gridKey(p: GridPoint): string {
  return `${p.col},${p.row}`;
}

function worldToGrid(x: number, y: number, gridSize: number): GridPoint {
  return { col: Math.floor(x / gridSize), row: Math.floor(y / gridSize) };
}

function gridToWorld(p: GridPoint, gridSize: number): Vec2 {
  return { x: p.col * gridSize + gridSize / 2, y: p.row * gridSize + gridSize / 2 };
}

function buildBlocked(walls: readonly Rect[], gridSize: number): Set<string> {
  const blocked = new Set<string>();
  for (const w of walls) {
    const colMin = Math.floor(w.x / gridSize);
    const colMax = Math.floor((w.x + w.w) / gridSize);
    const rowMin = Math.floor(w.y / gridSize);
    const rowMax = Math.floor((w.y + w.h) / gridSize);
    for (let c = colMin; c <= colMax; c++) {
      for (let r = rowMin; r <= rowMax; r++) {
        blocked.add(`${c},${r}`);
      }
    }
  }
  return blocked;
}

function manhattan(a: GridPoint, b: GridPoint): number {
  return Math.abs(a.col - b.col) + Math.abs(a.row - b.row);
}

const NEIGHBOURS: readonly GridPoint[] = [
  { col: 1, row: 0 },
  { col: -1, row: 0 },
  { col: 0, row: 1 },
  { col: 0, row: -1 },
];

// ── Tiny binary min-heap ────────────────────────────────────────────────────

interface HeapEntry {
  f: number;
  counter: number;
  cell: GridPoint;
}

class MinHeap {
  private readonly _data: HeapEntry[] = [];

  get size(): number {
    return this._data.length;
  }

  push(entry: HeapEntry): void {
    this._data.push(entry);
    this._bubbleUp(this._data.length - 1);
  }

  pop(): HeapEntry {
    const top = this._data[0];
    const last = this._data.pop()!;
    if (this._data.length > 0) {
      this._data[0] = last;
      this._siftDown(0);
    }
    return top;
  }

  private _bubbleUp(i: number): void {
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (this._cmp(i, parent) < 0) {
        [this._data[i], this._data[parent]] = [this._data[parent], this._data[i]];
        i = parent;
      } else {
        break;
      }
    }
  }

  private _siftDown(i: number): void {
    const n = this._data.length;
    while (true) {
      let smallest = i;
      const left = 2 * i + 1;
      const right = 2 * i + 2;
      if (left < n && this._cmp(left, smallest) < 0) smallest = left;
      if (right < n && this._cmp(right, smallest) < 0) smallest = right;
      if (smallest === i) break;
      [this._data[i], this._data[smallest]] = [this._data[smallest], this._data[i]];
      i = smallest;
    }
  }

  private _cmp(a: number, b: number): number {
    const ea = this._data[a];
    const eb = this._data[b];
    if (ea.f !== eb.f) return ea.f - eb.f;
    return ea.counter - eb.counter;
  }
}

// ── Blocked-set cache (WeakMap keyed by walls array reference) ──────────────

const _blockedCache = new WeakMap<readonly Rect[], Map<number, Set<string>>>();

/**
 * Return (or build and cache) the blocked-cell set for this walls array.
 *
 * Uses WeakMap so the cache is automatically GC'd when the walls const is
 * dropped. Safe for frozen room-level wall constants (same object reference
 * every call within one room).
 *
 * @param walls - Immutable array of wall rectangles.
 * @param gridSize - Cell size in pixels.
 * @returns Set of "col,row" string keys for all blocked cells.
 */
function getBlockedSet(walls: readonly Rect[], gridSize: number): Set<string> {
  let sizeMap = _blockedCache.get(walls);
  if (!sizeMap) {
    sizeMap = new Map<number, Set<string>>();
    _blockedCache.set(walls, sizeMap);
  }
  let set = sizeMap.get(gridSize);
  if (!set) {
    set = buildBlocked(walls, gridSize);
    sizeMap.set(gridSize, set);
  }
  return set;
}

export interface FindPathArgs {
  start: Vec2;
  goal: Vec2;
  walls: readonly Rect[];
  gridSize?: number;
  maxExplore?: number;
}

/**
 * A* pathfinding returning world-coord waypoints (cell centres).
 *
 * Mirrors Python find_path exactly:
 * - Manhattan heuristic
 * - 4-directional grid movement
 * - Cells blocked if the wall AABB covers that cell (grid-aligned scan)
 * - Blocked-set cached per walls-array reference and gridSize
 *
 * @param args - Start, goal, walls, optional gridSize (default 32) and
 *   maxExplore (default 5000).
 * @returns Array of Vec2 waypoints from start-cell to goal-cell centres.
 *   Empty array if no path found or goal cell is blocked.
 */
export function findPath(args: FindPathArgs): Vec2[] {
  const { start, goal, walls, gridSize = 32, maxExplore = 5000 } = args;

  const startP = worldToGrid(start.x, start.y, gridSize);
  const goalP = worldToGrid(goal.x, goal.y, gridSize);

  if (startP.col === goalP.col && startP.row === goalP.row) {
    return [start, goal];
  }

  const blocked = getBlockedSet(walls, gridSize);

  if (blocked.has(gridKey(goalP))) {
    return [];
  }

  const heap = new MinHeap();
  let counter = 0;
  heap.push({ f: 0, counter: counter++, cell: startP });

  const cameFrom = new Map<string, GridPoint>();
  const gScore = new Map<string, number>();
  gScore.set(gridKey(startP), 0);

  let explored = 0;

  while (heap.size > 0 && explored < maxExplore) {
    explored++;
    const { cell: current } = heap.pop();
    const currentKey = gridKey(current);

    if (current.col === goalP.col && current.row === goalP.row) {
      // Reconstruct path
      const pathCells: GridPoint[] = [current];
      let c: GridPoint = current;
      while (cameFrom.has(gridKey(c))) {
        c = cameFrom.get(gridKey(c))!;
        pathCells.push(c);
      }
      pathCells.reverse();
      return pathCells.map((p) => gridToWorld(p, gridSize));
    }

    const currentG = gScore.get(currentKey) ?? Infinity;

    for (const d of NEIGHBOURS) {
      const neighbour: GridPoint = { col: current.col + d.col, row: current.row + d.row };
      const nKey = gridKey(neighbour);
      if (blocked.has(nKey)) continue;
      const tentativeG = currentG + 1;
      if (tentativeG < (gScore.get(nKey) ?? (1 << 30))) {
        cameFrom.set(nKey, current);
        gScore.set(nKey, tentativeG);
        const f = tentativeG + manhattan(neighbour, goalP);
        heap.push({ f, counter: counter++, cell: neighbour });
      }
    }
  }

  return [];
}

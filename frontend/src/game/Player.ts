/**
 * Player — placeholder Knight через PIXI.Graphics circle.
 *
 * Заменится на AnimatedSprite в W3 когда появится LPC sprite pack.
 * До тех пор: цветной круг с outline + facing-indicator (chevron).
 */

import { Container, Graphics } from 'pixi.js';

import { rectsIntersect, type Rect, type Vec2 } from './types';

const RADIUS = 12;
/** Hitbox чуть меньше визуала — pixel-perfect feel при пролезании в дверные проёмы. */
const HITBOX_HALF = 11;
const SPEED_PX_PER_SEC = 140;

type Facing = 'south' | 'north' | 'east' | 'west';

const CHEVRON_TIP = RADIUS + 4;
const CHEVRON_BASE = RADIUS - 2;
const CHEVRON_HALFWIDTH = 4;

/** Pre-computed chevron triangles per facing — иначе 12 Vec2 аллокаций при каждом повороте. */
const CHEVRON_OFFSETS: Record<Facing, [Vec2, Vec2, Vec2]> = {
  south: [
    { x: 0, y: CHEVRON_TIP },
    { x: -CHEVRON_HALFWIDTH, y: CHEVRON_BASE },
    { x: CHEVRON_HALFWIDTH, y: CHEVRON_BASE },
  ],
  north: [
    { x: 0, y: -CHEVRON_TIP },
    { x: -CHEVRON_HALFWIDTH, y: -CHEVRON_BASE },
    { x: CHEVRON_HALFWIDTH, y: -CHEVRON_BASE },
  ],
  east: [
    { x: CHEVRON_TIP, y: 0 },
    { x: CHEVRON_BASE, y: -CHEVRON_HALFWIDTH },
    { x: CHEVRON_BASE, y: CHEVRON_HALFWIDTH },
  ],
  west: [
    { x: -CHEVRON_TIP, y: 0 },
    { x: -CHEVRON_BASE, y: -CHEVRON_HALFWIDTH },
    { x: -CHEVRON_BASE, y: CHEVRON_HALFWIDTH },
  ],
};

export class Player {
  readonly view: Container;
  position: Vec2;
  private facing: Facing = 'south';
  private readonly facingChevron: Graphics;
  /** Reused per-frame hitbox — иначе ~180 Rect-аллокаций/сек на 60 FPS. */
  private readonly probe: Rect = { x: 0, y: 0, w: HITBOX_HALF * 2, h: HITBOX_HALF * 2 };

  constructor(spawn: Vec2) {
    this.position = { ...spawn };

    const body = new Graphics();
    body.circle(0, 0, RADIUS).fill(0x4a90e2).stroke({ width: 2, color: 0x1a3a5e });

    this.facingChevron = new Graphics();
    this.redrawChevron();

    this.view = new Container();
    this.view.addChild(body, this.facingChevron);
    this.view.position.set(spawn.x, spawn.y);
  }

  /**
   * Обновить позицию по input vector с проверкой коллизий.
   * Реализует slide-along-wall: при коллизии пробует двигаться отдельно по осям.
   */
  update(input: Vec2, dtSec: number, walls: readonly Rect[]): void {
    const len = Math.hypot(input.x, input.y);
    if (len < 0.01) return;

    const nx = input.x / len;
    const ny = input.y / len;
    const distance = SPEED_PX_PER_SEC * dtSec * Math.min(len, 1);

    const dx = nx * distance;
    const dy = ny * distance;

    if (!this.collidesAt(this.position.x + dx, this.position.y + dy, walls)) {
      this.position.x += dx;
      this.position.y += dy;
    } else {
      if (!this.collidesAt(this.position.x + dx, this.position.y, walls)) {
        this.position.x += dx;
      }
      if (!this.collidesAt(this.position.x, this.position.y + dy, walls)) {
        this.position.y += dy;
      }
    }

    const newFacing = this.computeFacing(nx, ny);
    if (newFacing !== this.facing) {
      this.facing = newFacing;
      this.redrawChevron();
    }

    this.view.position.set(this.position.x, this.position.y);
  }

  private collidesAt(cx: number, cy: number, walls: readonly Rect[]): boolean {
    this.probe.x = cx - HITBOX_HALF;
    this.probe.y = cy - HITBOX_HALF;
    for (const w of walls) {
      if (rectsIntersect(this.probe, w)) return true;
    }
    return false;
  }

  private computeFacing(nx: number, ny: number): Facing {
    if (Math.abs(nx) > Math.abs(ny)) return nx > 0 ? 'east' : 'west';
    return ny > 0 ? 'south' : 'north';
  }

  private redrawChevron(): void {
    const [tip, a, b] = CHEVRON_OFFSETS[this.facing];
    this.facingChevron
      .clear()
      .poly([tip.x, tip.y, a.x, a.y, b.x, b.y])
      .fill(0xffd34a);
  }
}

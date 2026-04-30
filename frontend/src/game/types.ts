/**
 * Shared 2D primitives для placeholder-сцены.
 *
 * Без assets и Tiled — сцена строится процедурно из этих структур.
 */

export interface Vec2 {
  x: number;
  y: number;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * AABB-проверка пересечения двух прямоугольников.
 * Используется в коллизиях player-vs-walls.
 */
export function rectsIntersect(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

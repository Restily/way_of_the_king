/**
 * Процедурные тестовые комнаты — placeholder вместо Tiled .tmx файлов.
 *
 * Возвращает геометрию (стены + размеры) для рендера и коллизий.
 * Когда LPC/Tiled assets появятся — этот модуль заменится загрузкой JSON,
 * но :type:`Room` интерфейс останется тем же.
 */

import type { Rect } from './types';

export interface Room {
  /** Ширина комнаты в пикселях. */
  width: number;
  /** Высота комнаты в пикселях. */
  height: number;
  /** Размер тайла в пикселях. */
  tileSize: number;
  /** Стены — для рендера и коллизий. AABB-прямоугольники в координатах комнаты. */
  walls: Rect[];
  /** Стартовая позиция игрока. */
  spawn: { x: number; y: number };
}

const TILE = 32;
const WALL = TILE;

/**
 * Стены по периметру комнаты заданного размера в тайлах.
 * Reused builder для всех layouts.
 */
function perimeter(cols: number, rows: number): Rect[] {
  const w = cols * TILE;
  const h = rows * TILE;
  return [
    { x: 0, y: 0, w, h: WALL },
    { x: 0, y: h - WALL, w, h: WALL },
    { x: 0, y: 0, w: WALL, h },
    { x: w - WALL, y: 0, w: WALL, h },
  ];
}

function smallRoom(): Room {
  const cols = 12;
  const rows = 9;
  return {
    width: cols * TILE,
    height: rows * TILE,
    tileSize: TILE,
    walls: perimeter(cols, rows),
    spawn: { x: (cols * TILE) / 2, y: (rows * TILE) / 2 },
  };
}

function defaultRoom(): Room {
  const cols = 20;
  const rows = 15;
  return {
    width: cols * TILE,
    height: rows * TILE,
    tileSize: TILE,
    walls: [
      ...perimeter(cols, rows),
      // Колонна в центре
      { x: 7 * TILE, y: 6 * TILE, w: 2 * TILE, h: 2 * TILE },
      // L-образный коридор
      { x: 12 * TILE, y: 9 * TILE, w: 4 * TILE, h: WALL },
      { x: 12 * TILE, y: 9 * TILE, w: WALL, h: 3 * TILE },
    ],
    spawn: { x: 10 * TILE, y: 7 * TILE },
  };
}

function corridorsRoom(): Room {
  const cols = 24;
  const rows = 12;
  // Узкие коридоры — сетка с тонкими стенками-преградами.
  return {
    width: cols * TILE,
    height: rows * TILE,
    tileSize: TILE,
    walls: [
      ...perimeter(cols, rows),
      { x: 6 * TILE, y: 0, w: WALL, h: 8 * TILE },
      { x: 12 * TILE, y: 4 * TILE, w: WALL, h: 8 * TILE },
      { x: 18 * TILE, y: 0, w: WALL, h: 8 * TILE },
    ],
    spawn: { x: 3 * TILE, y: 10 * TILE },
  };
}

function pillarsRoom(): Room {
  const cols = 20;
  const rows = 15;
  const walls = perimeter(cols, rows);
  // 4 симметричные колонны 1×1 тайл
  for (const cx of [5, 14]) {
    for (const cy of [5, 9]) {
      walls.push({ x: cx * TILE, y: cy * TILE, w: TILE, h: TILE });
    }
  }
  return {
    width: cols * TILE,
    height: rows * TILE,
    tileSize: TILE,
    walls,
    spawn: { x: (cols * TILE) / 2, y: (rows * TILE) / 2 },
  };
}

function arenaRoom(): Room {
  // Большая открытая комната — для теста camera-follow на длинных дистанциях.
  const cols = 40;
  const rows = 30;
  return {
    width: cols * TILE,
    height: rows * TILE,
    tileSize: TILE,
    walls: perimeter(cols, rows),
    spawn: { x: (cols * TILE) / 2, y: (rows * TILE) / 2 },
  };
}

/** Каталог доступных layout'ов. Ключ → builder; используется UI-селектором. */
export const ROOMS: Record<string, () => Room> = {
  default: defaultRoom,
  small: smallRoom,
  corridors: corridorsRoom,
  pillars: pillarsRoom,
  arena: arenaRoom,
};

export type RoomId = keyof typeof ROOMS;

/** Дефолтная комната — для backward compat с импортами без аргумента. */
export function buildTestRoom(id: RoomId = 'default'): Room {
  return ROOMS[id]();
}

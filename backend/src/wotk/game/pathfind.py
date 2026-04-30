"""Grid pathfinding через A* (Manhattan heuristic).

Используется AI'ем когда mob нужен path вокруг препятствий. В прямой видимости
(line-of-sight) pathfinding skipping'ся — mob идёт напрямую (см. ai.step_ai).

Walls конвертируются в blocked-cells по grid 32×32px (см. tile size в room.ts).
Сетка считается на лету; для больших комнат можно cache'ить по hash(walls).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rect:
    """AABB в pixel-координатах."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True, slots=True)
class GridPoint:
    """Cell coordinates (col, row)."""

    col: int
    row: int


def _world_to_grid(x: float, y: float, grid_size: int) -> GridPoint:
    return GridPoint(int(x // grid_size), int(y // grid_size))


def _grid_to_world(p: GridPoint, grid_size: int) -> tuple[float, float]:
    """Center-of-cell в world coords."""
    return (p.col * grid_size + grid_size / 2, p.row * grid_size + grid_size / 2)


def _build_blocked(walls: list[Rect], grid_size: int) -> set[GridPoint]:
    """Конвертировать walls в set blocked cells.

    Cell считается blocked если её центр пересекает любой wall AABB.
    """
    blocked: set[GridPoint] = set()
    for w in walls:
        col_min = int(w.x // grid_size)
        col_max = int((w.x + w.w) // grid_size)
        row_min = int(w.y // grid_size)
        row_max = int((w.y + w.h) // grid_size)
        for c in range(col_min, col_max + 1):
            for r in range(row_min, row_max + 1):
                blocked.add(GridPoint(c, r))
    return blocked


def _manhattan(a: GridPoint, b: GridPoint) -> int:
    return abs(a.col - b.col) + abs(a.row - b.row)


_NEIGHBOURS = (
    GridPoint(1, 0),
    GridPoint(-1, 0),
    GridPoint(0, 1),
    GridPoint(0, -1),
)


def find_path(
    *,
    start: tuple[float, float],
    goal: tuple[float, float],
    walls: list[Rect],
    grid_size: int = 32,
    max_explore: int = 5000,
) -> list[tuple[float, float]]:
    """A* path в world-coords. Cells = grid_size × grid_size px.

    :param start: Стартовая позиция в world-coords.
    :param goal: Целевая позиция.
    :param walls: Препятствия как AABB rectangles.
    :param grid_size: Размер cell'а (default 32 — совпадает с tile size).
    :param max_explore: Cap на количество cells для exploration (DoS-protect).
    :returns: Список waypoint'ов в world-coords (центры cells), включая
        первую и последнюю точку. Пустой list если path не найден.
    """
    start_p = _world_to_grid(start[0], start[1], grid_size)
    goal_p = _world_to_grid(goal[0], goal[1], grid_size)

    if start_p == goal_p:
        return [start, goal]

    blocked = _build_blocked(walls, grid_size)
    if goal_p in blocked:
        return []

    # priority queue: (f_score, counter, cell)
    counter = 0
    open_heap: list[tuple[int, int, GridPoint]] = [(0, counter, start_p)]
    came_from: dict[GridPoint, GridPoint] = {}
    g_score: dict[GridPoint, int] = {start_p: 0}
    explored = 0

    while open_heap and explored < max_explore:
        explored += 1
        _, _, current = heapq.heappop(open_heap)

        if current == goal_p:
            # Reconstruct path.
            path_cells = [current]
            while current in came_from:
                current = came_from[current]
                path_cells.append(current)
            path_cells.reverse()
            return [_grid_to_world(p, grid_size) for p in path_cells]

        for d in _NEIGHBOURS:
            neighbour = GridPoint(current.col + d.col, current.row + d.row)
            if neighbour in blocked:
                continue
            tentative_g = g_score[current] + 1
            if tentative_g < g_score.get(neighbour, 1 << 30):
                came_from[neighbour] = current
                g_score[neighbour] = tentative_g
                f_score = tentative_g + _manhattan(neighbour, goal_p)
                counter += 1
                heapq.heappush(open_heap, (f_score, counter, neighbour))

    return []  # path not found / max_explore exceeded


__all__ = ["Rect", "find_path"]

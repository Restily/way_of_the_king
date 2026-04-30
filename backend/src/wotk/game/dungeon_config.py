"""TypedDicts describing the shape of ``dungeon.config.floors`` (W6 FloorConfig schema).

Mirror of ``realtime/src/game/dungeonConfig.ts`` — keep in sync.

The ``dungeon.config`` JSONB column stores a :class:`DungeonConfig` dict.
At /enter time the full config is embedded in the ws_token JWT so that the
Colyseus room can read per-floor geometry and spawn tables without a DB round-trip.

Schema version: ``v=1``.  Increment to ``v=2`` and gate on the field if
breaking shape changes are needed.
"""

from __future__ import annotations

from typing import TypedDict


class Vec2(TypedDict):
    """2-D integer coordinate.

    :cvar x: Horizontal pixel position.
    :cvar y: Vertical pixel position.
    """

    x: int
    y: int


class WallRect(TypedDict):
    """Axis-aligned wall rectangle in pixel space.

    :cvar x: Left edge (pixels).
    :cvar y: Top edge (pixels).
    :cvar w: Width (pixels).
    :cvar h: Height (pixels).
    """

    x: int
    y: int
    w: int
    h: int


class FloorConfig(TypedDict, total=False):
    """Configuration for a single floor inside a dungeon.

    :cvar floor: 0-based floor index; must equal position in ``DungeonConfig.floors``.
    :cvar walls: Perimeter and obstacle rectangles for collision detection.
    :cvar spawn_points: Candidate anchor positions for mob spawning.
        The server picks a subset based on ``mob_pack`` length.
    :cvar mob_pack: Ordered list of ``mob_def`` IDs to spawn on this floor
        (e.g. ``["skeleton_warrior", "zombie", "skeleton_archer"]``).
        Ignored on boss floors (``is_boss_floor=True``).
    :cvar is_boss_floor: True for the last floor.
    :cvar boss_id: ID of the boss mob_def to spawn on boss floors (W6-012).
        Optional — only present when ``is_boss_floor=True``.
    """

    floor: int
    walls: list[WallRect]
    spawn_points: list[Vec2]
    mob_pack: list[str]
    is_boss_floor: bool
    boss_id: str  # optional (W6-012): boss mob_def ID on boss floors


class DungeonConfig(TypedDict):
    """Top-level dungeon configuration stored in ``dungeons.config`` JSONB.

    :cvar v: Schema version (= 1).  Bump when the shape changes incompatibly.
    :cvar floors: Ordered list of :class:`FloorConfig`; index must equal ``floor`` field.
    """

    v: int
    floors: list[FloorConfig]

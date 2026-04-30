"""Seed данжей в ``dungeons`` table — 6 шт минимум для MVP.

UPSERT-семантика: повторный запуск **обновляет** существующие строки
(это позволяет править балансные значения без ручного SQL). Если хочешь
полный wipe — DELETE FROM dungeons вручную перед запуском.

Запуск::

    cd backend && uv run python -m scripts.seed_dungeons

Список данжей:

* ``crypt_normal`` (CRYPT/NORMAL, lvl 1, cheap entry)
* ``crypt_hard`` (CRYPT/HARD, lvl 5)
* ``forest_normal`` (FOREST/NORMAL, lvl 1)
* ``forest_hard`` (FOREST/HARD, lvl 8)
* ``castle_normal`` (CASTLE/NORMAL, lvl 12)
* ``castle_mythic`` (CASTLE/MYTHIC, lvl 25)

Конфиг floors — placeholder (loot tables будут заполнены в W4 при реализации
combat/encounter spawning).
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert

from wotk.core.db import session_scope
from wotk.domain.enums import Difficulty, DungeonTheme
from wotk.domain.models import Dungeon

log = structlog.get_logger()


def _placeholder_config(floors: int) -> dict[str, Any]:
    """Минимальный config для seed — структура для W4 расширится.

    :param floors: Количество этажей.
    :returns: Dict готовый для JSONB.
    """
    return {
        "v": 1,
        "floors": [
            {
                "floor": i,
                "encounter_count": 2 + (i // 2),
                "boss_floor": (i == floors - 1),
            }
            for i in range(floors)
        ],
        "loot_table": {"weight_legendary": 1, "weight_epic": 5},
    }


# ---------------------------------------------------------------------------
# crypt_normal — real FloorConfig (W6-001)
# ---------------------------------------------------------------------------

#: Стандартная геометрия комнаты — периметр 40×30 tiles × 32px.
#: Совпадает с ROOM_WALLS/TILE/ROOM_COLS/ROOM_ROWS в DungeonRoom.ts.
_CRYPT_WALLS = [
    {"x": 0, "y": 0, "w": 1280, "h": 32},
    {"x": 0, "y": 928, "w": 1280, "h": 32},
    {"x": 0, "y": 0, "w": 32, "h": 960},
    {"x": 1248, "y": 0, "w": 32, "h": 960},
]

#: Кандидаты для спауна — 5 позиций, распределённых по комнате.
_CRYPT_SPAWN_POINTS = [
    {"x": 640, "y": 480},
    {"x": 800, "y": 400},
    {"x": 500, "y": 600},
    {"x": 900, "y": 700},
    {"x": 700, "y": 300},
]


def _crypt_normal_config() -> dict[str, Any]:
    """FloorConfig для ``crypt_normal`` (5 floors, W6-001 shape).

    W6-012: Floor 4 — boss floor с ``boss_id="crypt_lich"``, ``mob_pack=[]``
    (игнорируется на boss floor'ах, спаун только босса).

    :returns: DungeonConfig dict готовый для JSONB.
    """
    mob_packs: list[list[str]] = [
        ["skeleton_warrior", "zombie", "skeleton_archer"],  # floor 0
        ["skeleton_warrior", "skeleton_warrior", "zombie"],  # floor 1
        ["zombie", "skeleton_archer", "skeleton_archer"],   # floor 2
        ["skeleton_warrior", "skeleton_warrior", "skeleton_archer"],  # floor 3
        [],  # floor 4 — boss floor, mob_pack ignored
    ]
    floors = []
    for i in range(5):
        floor_cfg: dict[str, Any] = {
            "floor": i,
            "walls": _CRYPT_WALLS,
            "spawn_points": _CRYPT_SPAWN_POINTS,
            "mob_pack": mob_packs[i],
            "is_boss_floor": (i == 4),
        }
        if i == 4:
            floor_cfg["boss_id"] = "crypt_lich"
        floors.append(floor_cfg)
    return {"v": 1, "floors": floors}


DUNGEONS: list[dict[str, Any]] = [
    {
        "id": "crypt_normal",
        "name_key": "dungeon.crypt_normal.name",
        "theme": DungeonTheme.CRYPT,
        "difficulty": Difficulty.NORMAL,
        "min_level": 1,
        "entry_cost_gold": 50,
        "entry_cost_energy": 10,
        "daily_limit": 5,
        "floors_count": 5,
        "config": _crypt_normal_config(),
        "xp_base": 100,
        "gold_base": 100,
        "is_enabled": True,
        "act": 1,
        "location": 1,
    },
    {
        "id": "crypt_hard",
        "name_key": "dungeon.crypt_hard.name",
        "theme": DungeonTheme.CRYPT,
        "difficulty": Difficulty.HARD,
        "min_level": 5,
        "entry_cost_gold": 150,
        "entry_cost_energy": 15,
        "daily_limit": 3,
        "floors_count": 7,
        "config": _placeholder_config(7),
        "xp_base": 250,
        "gold_base": 300,
        "is_enabled": True,
        "act": 1,
        "location": 2,
    },
    {
        "id": "forest_normal",
        "name_key": "dungeon.forest_normal.name",
        "theme": DungeonTheme.FOREST,
        "difficulty": Difficulty.NORMAL,
        "min_level": 1,
        "entry_cost_gold": 50,
        "entry_cost_energy": 10,
        "daily_limit": 5,
        "floors_count": 5,
        "config": _placeholder_config(5),
        "xp_base": 100,
        "gold_base": 100,
        "is_enabled": True,
        "act": 2,
        "location": 1,
    },
    {
        "id": "forest_hard",
        "name_key": "dungeon.forest_hard.name",
        "theme": DungeonTheme.FOREST,
        "difficulty": Difficulty.HARD,
        "min_level": 8,
        "entry_cost_gold": 200,
        "entry_cost_energy": 15,
        "daily_limit": 3,
        "floors_count": 7,
        "config": _placeholder_config(7),
        "xp_base": 350,
        "gold_base": 400,
        "is_enabled": True,
        "act": 2,
        "location": 2,
    },
    {
        "id": "castle_normal",
        "name_key": "dungeon.castle_normal.name",
        "theme": DungeonTheme.CASTLE,
        "difficulty": Difficulty.NORMAL,
        "min_level": 12,
        "entry_cost_gold": 300,
        "entry_cost_energy": 15,
        "daily_limit": 5,
        "floors_count": 8,
        "config": _placeholder_config(8),
        "xp_base": 500,
        "gold_base": 600,
        "is_enabled": True,
        "act": 3,
        "location": 1,
    },
    {
        "id": "castle_mythic",
        "name_key": "dungeon.castle_mythic.name",
        "theme": DungeonTheme.CASTLE,
        "difficulty": Difficulty.MYTHIC,
        "min_level": 25,
        "entry_cost_gold": 1000,
        "entry_cost_energy": 25,
        "daily_limit": 2,
        "floors_count": 10,
        "config": _placeholder_config(10),
        "xp_base": 1500,
        "gold_base": 2000,
        "is_enabled": True,
        "act": 3,
        "location": 2,
    },
]


async def seed_dungeons() -> int:
    """UPSERT :data:`DUNGEONS` в ``dungeons``.

    Existing rows получают новые значения (entry_cost, gold_base, и т.п.) —
    позволяет балансировать без ручного SQL.

    :returns: Количество обработанных rows.
    """
    async with session_scope() as session:
        for spec in DUNGEONS:
            # SQLAlchemy enums → int для UPSERT (pg_insert не дёргает
            # IntEnumColumn process_bind_param через session.add path).
            values = {
                **spec,
                "theme": int(spec["theme"]),
                "difficulty": int(spec["difficulty"]),
            }
            stmt = pg_insert(Dungeon).values(**values)
            update_cols = {
                k: stmt.excluded[k]
                for k in values
                if k != "id"  # PK не апдейтим
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_=update_cols,
            )
            await session.execute(stmt)
    return len(DUNGEONS)


async def main() -> None:
    """CLI entry: UPSERT dungeons + summary."""
    n = await seed_dungeons()
    log.info("seed_dungeons_done", upserted=n)
    print(f"dungeons: upserted {n}")


if __name__ == "__main__":
    asyncio.run(main())

"""0009_dungeon_campaign_meta: Добавляет act + location к таблице dungeons.

Revision ID: 0009_dungeon_campaign_meta
Revises: 0008_dungeons
Create Date: 2026-04-30 12:00:00

Добавляет два nullable INT колонки в ``dungeons``:

* ``act``      — номер акта (1..5), NULL для туториальных данжей.
* ``location`` — номер локации внутри акта (1..10), NULL для туториальных.

CHECK-ограничения соответствуют ``campaign_progress`` (DATABASE.md §8.5):
``act BETWEEN 1 AND 5``, ``location BETWEEN 1 AND 10``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_dungeon_campaign_meta"
down_revision: str | None = "0008_dungeons"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавить act + location к ``dungeons``, с CHECK-ограничениями."""
    op.execute(
        sa.DDL(
            """
            ALTER TABLE dungeons
                ADD COLUMN act      INT,
                ADD COLUMN location INT,
                ADD CONSTRAINT ck_dungeons_act CHECK (act IS NULL OR act BETWEEN 1 AND 5),
                ADD CONSTRAINT ck_dungeons_location CHECK (location IS NULL OR location BETWEEN 1 AND 10);
            """
        )
    )


def downgrade() -> None:
    """Удалить act + location из ``dungeons``."""
    op.execute(
        sa.DDL(
            """
            ALTER TABLE dungeons
                DROP CONSTRAINT IF EXISTS ck_dungeons_act,
                DROP CONSTRAINT IF EXISTS ck_dungeons_location,
                DROP COLUMN IF EXISTS act,
                DROP COLUMN IF EXISTS location;
            """
        )
    )

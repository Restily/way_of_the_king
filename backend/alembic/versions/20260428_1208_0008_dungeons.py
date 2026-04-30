"""0008_dungeons: §8 dungeons + dungeon_runs + run_encounters + daily_dungeon_entries + campaign_progress

Revision ID: 0008_dungeons
Revises: 0007_items
Create Date: 2026-04-28 12:08:00

Реализует DATABASE.md §8 целиком + finalize FK ``item.escrow_run_id``
к ``dungeon_runs.id`` (отложенная зависимость из миграции 0007).

Триггеры:
* ``trg_run_seed_immutable`` — seed/dungeon_id immutable после INSERT (replay/anti-cheat контракт)
* ``trg_run_activity`` — обновляет ``last_activity_at``/``last_checkpoint_at`` при floor transition

dungeon_runs.status маппинг (DATABASE.md §1.5):
0=IN_PROGRESS, 1=COMPLETED, 2=FAILED, 3=FLED, 4=ABANDONED, 5=SETTLED.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_dungeons"
down_revision: str | None = "0007_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ===== §8.1 dungeons (reference) =====
    op.execute(
        sa.DDL(
            """
            CREATE TABLE dungeons (
                id                TEXT         PRIMARY KEY,
                name_key          TEXT         NOT NULL,
                theme             SMALLINT     NOT NULL,
                difficulty        SMALLINT     NOT NULL,
                min_level         INT          NOT NULL DEFAULT 1,
                entry_cost_gold   BIGINT       NOT NULL,
                entry_cost_energy INT          NOT NULL DEFAULT 10,
                daily_limit       INT          NOT NULL DEFAULT 5,
                floors_count      INT          NOT NULL DEFAULT 5,
                config            JSONB        NOT NULL,
                xp_base           INT          NOT NULL,
                gold_base         BIGINT       NOT NULL,
                is_enabled        BOOLEAN      NOT NULL DEFAULT true,
                created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
                updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
                CONSTRAINT ck_dungeons_theme      CHECK (theme BETWEEN 0 AND 4),
                CONSTRAINT ck_dungeons_difficulty CHECK (difficulty BETWEEN 0 AND 2),
                CONSTRAINT ck_dungeons_min_level  CHECK (min_level >= 1),
                CONSTRAINT ck_dungeons_floors     CHECK (floors_count >= 1)
            );
            """
        )
    )
    op.execute(
        sa.DDL(
            """
            CREATE INDEX ix_dungeons_enabled
                ON dungeons (is_enabled, min_level);
            """
        )
    )
    op.execute(
        sa.DDL(
            """
            CREATE TRIGGER trg_dungeons_updated_at
                BEFORE UPDATE ON dungeons
                FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
            """
        )
    )

    # ===== §8.2 dungeon_runs =====
    op.execute(
        sa.DDL(
            """
            CREATE TABLE dungeon_runs (
                id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
                profile_id          BIGINT       NOT NULL,
                hero_id             BIGINT       NOT NULL,
                dungeon_id          TEXT         NOT NULL,
                seed                BYTEA        NOT NULL,
                status              SMALLINT     NOT NULL DEFAULT 0,
                current_floor       INT          NOT NULL DEFAULT 0,
                hero_state          JSONB        NOT NULL,
                pending_gold        BIGINT       NOT NULL DEFAULT 0,
                entry_paid_gold     BIGINT       NOT NULL,
                entry_paid_energy   INT          NOT NULL,
                revives_used        INT          NOT NULL DEFAULT 0,
                realtime_node_id    TEXT,
                started_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
                last_activity_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
                last_checkpoint_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
                finished_at         TIMESTAMPTZ,
                expires_at          TIMESTAMPTZ  NOT NULL,
                CONSTRAINT fk_runs_profile FOREIGN KEY (profile_id)
                    REFERENCES profile(id),
                CONSTRAINT fk_runs_hero FOREIGN KEY (hero_id)
                    REFERENCES hero(id),
                CONSTRAINT fk_runs_dungeon FOREIGN KEY (dungeon_id)
                    REFERENCES dungeons(id),
                CONSTRAINT ck_runs_status        CHECK (status BETWEEN 0 AND 5),
                CONSTRAINT ck_runs_floor_nonneg  CHECK (current_floor >= 0),
                CONSTRAINT ck_runs_seed_size     CHECK (octet_length(seed) = 32),
                CONSTRAINT ck_runs_pending_gold  CHECK (pending_gold >= 0),
                CONSTRAINT ck_runs_revives       CHECK (revives_used >= 0)
            );
            """
        )
    )
    # Только один активный run на героя.
    op.execute(
        sa.DDL(
            """
            CREATE UNIQUE INDEX uq_runs_one_active_per_hero
                ON dungeon_runs (hero_id) WHERE status = 0;
            """
        )
    )
    op.execute(
        sa.DDL(
            """
            CREATE INDEX ix_runs_profile_started
                ON dungeon_runs (profile_id, started_at DESC);
            """
        )
    )
    op.execute(
        sa.DDL(
            """
            CREATE INDEX ix_runs_status_expires
                ON dungeon_runs (status, expires_at) WHERE status = 0;
            """
        )
    )
    op.execute(
        sa.DDL(
            """
            CREATE INDEX ix_runs_dungeon_status
                ON dungeon_runs (dungeon_id, status);
            """
        )
    )

    # ===== Seed-immutability trigger (§8.2) =====
    # NB: используем raw op.execute(str), а не sa.DDL — функция содержит
    # ``RAISE EXCEPTION 'msg %' , arg`` где ``%`` — placeholder PostgreSQL'а.
    # ``sa.DDL`` бы интерпретировал его как Python format-char и упал.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_run_seed_immutable()
        RETURNS TRIGGER AS $$
        BEGIN
          IF NEW.seed IS DISTINCT FROM OLD.seed THEN
            RAISE EXCEPTION 'dungeon_runs.seed is immutable (run_id=%)', OLD.id;
          END IF;
          IF NEW.dungeon_id IS DISTINCT FROM OLD.dungeon_id THEN
            RAISE EXCEPTION 'dungeon_runs.dungeon_id is immutable (run_id=%)', OLD.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        sa.DDL(
            """
            CREATE TRIGGER trg_runs_seed_immutable
                BEFORE UPDATE ON dungeon_runs
                FOR EACH ROW EXECUTE FUNCTION trg_run_seed_immutable();
            """
        )
    )

    # ===== Activity-update trigger (§12.3) =====
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_run_activity()
        RETURNS TRIGGER AS $$
        BEGIN
          IF NEW.current_floor != OLD.current_floor OR
             NEW.pending_gold != OLD.pending_gold THEN
            NEW.last_activity_at = now();
            NEW.last_checkpoint_at = now();
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        sa.DDL(
            """
            CREATE TRIGGER trg_runs_activity
                BEFORE UPDATE ON dungeon_runs
                FOR EACH ROW
                WHEN (OLD.status = 0)
                EXECUTE FUNCTION trg_run_activity();
            """
        )
    )

    # ===== Finalize FK item.escrow_run_id → dungeon_runs.id =====
    op.execute(
        sa.DDL(
            """
            ALTER TABLE item
                ADD CONSTRAINT fk_item_escrow_run
                FOREIGN KEY (escrow_run_id) REFERENCES dungeon_runs(id);
            """
        )
    )

    # ===== §8.3 run_encounters =====
    op.execute(
        sa.DDL(
            """
            CREATE TABLE run_encounters (
                id              BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                run_id          UUID         NOT NULL,
                floor           INT          NOT NULL,
                encounter_idx   INT          NOT NULL,
                enemies_spawned JSONB        NOT NULL,
                combat_summary  JSONB        NOT NULL,
                loot_rolled     JSONB        NOT NULL DEFAULT '[]'::jsonb,
                gold_rolled     BIGINT       NOT NULL DEFAULT 0,
                result          SMALLINT     NOT NULL,
                created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
                CONSTRAINT fk_encounters_run FOREIGN KEY (run_id)
                    REFERENCES dungeon_runs(id) ON DELETE CASCADE,
                CONSTRAINT uq_encounters_run_floor_idx UNIQUE (run_id, floor, encounter_idx),
                CONSTRAINT ck_encounters_result CHECK (result BETWEEN 0 AND 2),
                CONSTRAINT ck_encounters_floor_pos CHECK (floor >= 0),
                -- combat_summary должен иметь обязательный version-key.
                -- ``->`` без `?` сначала возвращает NULL, и CHECK пропускает NULL —
                -- поэтому явно требуем наличие ключа `?` + правильный тип.
                CONSTRAINT ck_encounters_summary_version CHECK (
                    combat_summary ? 'v'
                    AND jsonb_typeof(combat_summary -> 'v') = 'number'
                )
            );
            """
        )
    )
    op.execute(
        sa.DDL("CREATE INDEX ix_encounters_run ON run_encounters (run_id);")
    )

    # ===== §8.4 daily_dungeon_entries =====
    op.execute(
        sa.DDL(
            """
            CREATE TABLE daily_dungeon_entries (
                profile_id  BIGINT       NOT NULL,
                dungeon_id  TEXT         NOT NULL,
                date_utc    DATE         NOT NULL,
                count       INT          NOT NULL DEFAULT 0,
                updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
                CONSTRAINT pk_daily_entries PRIMARY KEY (profile_id, dungeon_id, date_utc),
                CONSTRAINT fk_daily_entries_profile FOREIGN KEY (profile_id)
                    REFERENCES profile(id) ON DELETE CASCADE,
                CONSTRAINT fk_daily_entries_dungeon FOREIGN KEY (dungeon_id)
                    REFERENCES dungeons(id),
                CONSTRAINT ck_daily_entries_count CHECK (count >= 0)
            );
            """
        )
    )
    op.execute(
        sa.DDL(
            "CREATE INDEX ix_daily_entries_date ON daily_dungeon_entries (date_utc);"
        )
    )
    op.execute(
        sa.DDL(
            """
            CREATE TRIGGER trg_daily_entries_updated_at
                BEFORE UPDATE ON daily_dungeon_entries
                FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
            """
        )
    )

    # ===== §8.5 campaign_progress =====
    op.execute(
        sa.DDL(
            """
            CREATE TABLE campaign_progress (
                hero_id             BIGINT       NOT NULL,
                act                 INT          NOT NULL,
                location            INT          NOT NULL,
                first_completed_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
                best_clear_time_s   INT,
                completion_count    INT          NOT NULL DEFAULT 1,
                CONSTRAINT pk_campaign_progress PRIMARY KEY (hero_id, act, location),
                CONSTRAINT fk_campaign_hero FOREIGN KEY (hero_id)
                    REFERENCES hero(id) ON DELETE CASCADE,
                CONSTRAINT ck_campaign_act      CHECK (act BETWEEN 1 AND 5),
                CONSTRAINT ck_campaign_loc      CHECK (location BETWEEN 1 AND 10),
                CONSTRAINT ck_campaign_clear_t  CHECK (best_clear_time_s IS NULL OR best_clear_time_s > 0),
                CONSTRAINT ck_campaign_count    CHECK (completion_count >= 1)
            );
            """
        )
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS campaign_progress CASCADE;")
    op.execute("DROP TABLE IF EXISTS daily_dungeon_entries CASCADE;")
    op.execute("DROP TABLE IF EXISTS run_encounters CASCADE;")
    op.execute(
        "ALTER TABLE item DROP CONSTRAINT IF EXISTS fk_item_escrow_run;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_runs_activity ON dungeon_runs;"
    )
    op.execute("DROP FUNCTION IF EXISTS trg_run_activity();")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_runs_seed_immutable ON dungeon_runs;"
    )
    op.execute("DROP FUNCTION IF EXISTS trg_run_seed_immutable();")
    op.execute("DROP TABLE IF EXISTS dungeon_runs CASCADE;")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_dungeons_updated_at ON dungeons;"
    )
    op.execute("DROP TABLE IF EXISTS dungeons CASCADE;")

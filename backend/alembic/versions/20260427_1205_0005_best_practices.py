"""0005_best_practices: §3-§5 best-practices delta

Revision ID: 0005_best_practices
Revises: 0004_transaction
Create Date: 2026-04-27 12:05:00

Применяет §3-§5 best-practices delta из DATABASE.md v0.2.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_best_practices"
down_revision: str | None = "0004_transaction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ===== §3.1 profile =====
    op.execute("DROP INDEX IF EXISTS ix_profile_last_seen_at;")
    op.execute("ALTER TABLE profile SET (fillfactor = 90);")

    # ===== §3.2 referral =====
    # NOT VALID: пропускаем full-table scan под AccessExclusiveLock'ом.
    # Существующие строки валидируются позже (VALIDATE CONSTRAINT) под
    # ShareUpdateExclusiveLock — не блокирует writes. На пустой таблице
    # эффект тот же; при rollout на заполненную — критично.
    op.execute(
        """
        ALTER TABLE referral
          ADD CONSTRAINT ck_referral_no_self
          CHECK (referrer_profile_id != referred_profile_id) NOT VALID;
        """
    )
    op.execute("ALTER TABLE referral VALIDATE CONSTRAINT ck_referral_no_self;")

    # ===== §5.2 transaction: append-only guard =====
    # Generic-функция: переиспользуется на treasury_log/audit_events
    # (миграции 0010/0011) — TG_TABLE_NAME даёт корректный error message.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_append_only_guard()
        RETURNS TRIGGER AS $$
        BEGIN
          RAISE EXCEPTION '% is append-only (no UPDATE/DELETE allowed)', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_transaction_block_update
          BEFORE UPDATE ON "transaction"
          FOR EACH ROW EXECUTE FUNCTION trg_append_only_guard();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_transaction_block_delete
          BEFORE DELETE ON "transaction"
          FOR EACH ROW EXECUTE FUNCTION trg_append_only_guard();
        """
    )

    # ===== §13.1 / §13.4 energy regen =====
    # Read-path (`/me`, инвентарь): чистая SQL-функция, планировщик инлайнит.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION current_energy(uid BIGINT)
        RETURNS INT AS $$
          SELECT LEAST(
            energy + GREATEST(
              EXTRACT(EPOCH FROM (now() - energy_updated_at))::INT / 360,
              0
            ),
            energy_cap
          )
          FROM balance WHERE profile_id = uid;
        $$ LANGUAGE sql STABLE;
        """
    )
    # Write-path: материализует регенерацию + advance energy_updated_at.
    # Используется строго перед spend-операцией, под FOR UPDATE.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION regen_energy_for_profile(uid BIGINT)
        RETURNS INT AS $$
        DECLARE
          e INT;
          cap INT;
          last_update TIMESTAMPTZ;
          regen_amount INT;
          new_energy INT;
        BEGIN
          SELECT energy, energy_cap, energy_updated_at
            INTO e, cap, last_update
          FROM balance WHERE profile_id = uid FOR UPDATE;

          IF e IS NULL OR e >= cap THEN
            RETURN e;
          END IF;

          regen_amount := EXTRACT(EPOCH FROM (now() - last_update))::INT / 360;
          IF regen_amount = 0 THEN
            RETURN e;
          END IF;

          new_energy := LEAST(e + regen_amount, cap);
          UPDATE balance
             SET energy = new_energy,
                 energy_updated_at = energy_updated_at
                                     + (regen_amount * INTERVAL '6 minutes')
           WHERE profile_id = uid;
          RETURN new_energy;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS current_energy(BIGINT);")
    op.execute("DROP FUNCTION IF EXISTS regen_energy_for_profile(BIGINT);")
    op.execute(
        'DROP TRIGGER IF EXISTS trg_transaction_block_delete ON "transaction";'
    )
    op.execute(
        'DROP TRIGGER IF EXISTS trg_transaction_block_update ON "transaction";'
    )
    op.execute("DROP FUNCTION IF EXISTS trg_append_only_guard();")
    op.execute(
        """
        ALTER TABLE referral
          DROP CONSTRAINT IF EXISTS ck_referral_no_self;
        """
    )
    op.execute("ALTER TABLE profile RESET (fillfactor);")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_profile_last_seen_at
          ON profile (last_seen_at)
          WHERE NOT is_blocked;
        """
    )

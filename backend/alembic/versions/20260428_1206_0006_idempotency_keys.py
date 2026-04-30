"""0006_idempotency_keys: §11.2 idempotency_keys table

Revision ID: 0006_idempotency_keys
Revises: 0005_best_practices
Create Date: 2026-04-28 12:06:00

Реализует §11.2 — кэш ответов для idempotent POST-операций. Best-practices
из DATABASE.md v0.2:

* PK = ``(key UUID, profile_id BIGINT)`` — UUID v4 от клиента + защита от
  collisions между юзерами.
* ``request_hash`` BYTEA(32) (SHA-256), не TEXT(64) — вдвое меньше места,
  быстрее ``=``-сравнение.
* CHECK ``ck_idem_body_size`` ограничивает закэшированный response 64 KB —
  защита от раздувания таблицы.
* CHECK ``ck_idem_request_hash_len`` фиксирует размер 32 байта.
* ``is_payment_critical`` BOOLEAN — дискриминатор для tiered TTL (2h / 24h),
  выставляется на endpoint-уровне.
* ``ON DELETE CASCADE`` к ``profile`` — удалённый профиль не оставляет
  висящие idempotency-записи.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_idempotency_keys"
down_revision: str | None = "0005_best_practices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.DDL(
            """
            CREATE TABLE idempotency_keys (
                key                  UUID         NOT NULL,
                profile_id           BIGINT       NOT NULL,
                endpoint             TEXT         NOT NULL,
                request_hash         BYTEA        NOT NULL,
                response_status      INT          NOT NULL,
                response_body        JSONB,
                is_payment_critical  BOOLEAN      NOT NULL DEFAULT false,
                created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
                expires_at           TIMESTAMPTZ  NOT NULL,
                CONSTRAINT pk_idem PRIMARY KEY (key, profile_id),
                CONSTRAINT fk_idem_profile FOREIGN KEY (profile_id)
                    REFERENCES profile(id) ON DELETE CASCADE,
                CONSTRAINT ck_idem_body_size CHECK (
                    response_body IS NULL OR pg_column_size(response_body) <= 65536
                ),
                CONSTRAINT ck_idem_request_hash_len CHECK (
                    octet_length(request_hash) = 32
                )
            );
            """
        )
    )
    op.execute(
        sa.DDL(
            """
            CREATE INDEX ix_idem_expires ON idempotency_keys (expires_at);
            """
        )
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_keys CASCADE;")

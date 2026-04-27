"""0001_profile_balance: profile + balance + updated_at trigger

Revision ID: 0001_profile_balance
Revises:
Create Date: 2026-04-27 12:01:00

Реализует:
- §3.1 profile
- §5.1 balance
- §12.1 trg_set_updated_at универсальная функция
- Триггеры updated_at для profile и balance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_profile_balance"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ===== §12.1: универсальный updated_at trigger =====
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ===== §3.1 profile =====
    op.create_table(
        "profile",
        sa.Column(
            "id",
            sa.BigInteger,
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("telegram_id", sa.BigInteger, nullable=False),
        sa.Column("telegram_username", sa.String, nullable=True),
        sa.Column("telegram_first_name", sa.String, nullable=True),
        sa.Column(
            "locale", sa.String, nullable=False, server_default=sa.text("'ru'")
        ),
        sa.Column("ip_country", sa.String, nullable=True),
        sa.Column(
            "is_blocked",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("block_reason", sa.String, nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_admin",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "withdrawal_2fa_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("telegram_id", name="uq_profile_telegram_id"),
        sa.CheckConstraint(
            "locale IN ('ru','en','es','pt','zh','ar')",
            name="ck_profile_locale",
        ),
    )
    op.create_index("ix_profile_telegram_id", "profile", ["telegram_id"])
    op.create_index(
        "ix_profile_last_seen_at",
        "profile",
        ["last_seen_at"],
        postgresql_where=sa.text("NOT is_blocked"),
    )
    op.create_index(
        "ix_profile_admin",
        "profile",
        ["id"],
        postgresql_where=sa.text("is_admin"),
    )
    op.execute(
        """
        CREATE TRIGGER trg_profile_updated_at
        BEFORE UPDATE ON profile
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
        """
    )

    # ===== §5.1 balance =====
    op.create_table(
        "balance",
        sa.Column(
            "profile_id",
            sa.BigInteger,
            sa.ForeignKey(
                "profile.id", ondelete="CASCADE", name="fk_balance_profile"
            ),
            primary_key=True,
        ),
        sa.Column(
            "gold", sa.BigInteger, nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "energy", sa.Integer, nullable=False, server_default=sa.text("100")
        ),
        sa.Column(
            "energy_cap",
            sa.Integer,
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "energy_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("gold >= 0", name="ck_balance_gold_nonneg"),
        sa.CheckConstraint(
            "energy >= 0 AND energy <= energy_cap",
            name="ck_balance_energy",
        ),
    )
    op.execute(
        """
        CREATE TRIGGER trg_balance_updated_at
        BEFORE UPDATE ON balance
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_balance_updated_at ON balance;")
    op.drop_table("balance")
    op.execute("DROP TRIGGER IF EXISTS trg_profile_updated_at ON profile;")
    op.drop_index("ix_profile_admin", table_name="profile")
    op.drop_index("ix_profile_last_seen_at", table_name="profile")
    op.drop_index("ix_profile_telegram_id", table_name="profile")
    op.drop_table("profile")
    op.execute("DROP FUNCTION IF EXISTS trg_set_updated_at();")

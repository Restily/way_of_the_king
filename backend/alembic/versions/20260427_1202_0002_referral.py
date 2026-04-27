"""0002_referral: referral table

Revision ID: 0002_referral
Revises: 0001_profile_balance
Create Date: 2026-04-27 12:02:00

Реализует §3.2 referral.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_referral"
down_revision: str | None = "0001_profile_balance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "referral",
        sa.Column(
            "id",
            sa.BigInteger,
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "referrer_profile_id",
            sa.BigInteger,
            sa.ForeignKey("profile.id", name="fk_referral_referrer"),
            nullable=False,
        ),
        sa.Column(
            "referred_profile_id",
            sa.BigInteger,
            sa.ForeignKey("profile.id", name="fk_referral_referred"),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "bonus_paid_gold",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "referred_profile_id", name="uq_referral_referred"
        ),
    )
    op.create_index(
        "ix_referral_referrer_active",
        "referral",
        ["referrer_profile_id", "expires_at"],
        postgresql_where=sa.text("confirmed_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_referral_referrer_active", table_name="referral")
    op.drop_table("referral")

"""0003_hero: hero table

Revision ID: 0003_hero
Revises: 0002_referral
Create Date: 2026-04-27 12:03:00

Реализует §4.1 hero.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_hero"
down_revision: str | None = "0002_referral"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hero",
        sa.Column(
            "id",
            sa.BigInteger,
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "profile_id",
            sa.BigInteger,
            sa.ForeignKey(
                "profile.id", ondelete="CASCADE", name="fk_hero_profile"
            ),
            nullable=False,
        ),
        sa.Column("class", sa.SmallInteger, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column(
            "level",
            sa.Integer,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "xp",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "unspent_points",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{\"stat\":0,\"skill\":0}'::jsonb"),
        ),
        sa.Column(
            "base_stats",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text(
                "'{\"str\":10,\"dex\":5,\"int\":3}'::jsonb"
            ),
        ),
        sa.Column(
            "passives",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "active_skills",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("class BETWEEN 0 AND 2", name="ck_hero_class"),
        sa.CheckConstraint(
            "level BETWEEN 1 AND 100", name="ck_hero_level"
        ),
        sa.CheckConstraint("xp >= 0", name="ck_hero_xp"),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 3 AND 20", name="ck_hero_name_len"
        ),
        sa.CheckConstraint(
            """
            jsonb_typeof(unspent_points) = 'object'
            AND jsonb_typeof(unspent_points->'stat') = 'number'
            AND jsonb_typeof(unspent_points->'skill') = 'number'
            AND (unspent_points->>'stat')::int >= 0
            AND (unspent_points->>'skill')::int >= 0
            """,
            name="ck_hero_unspent_points",
        ),
    )
    # MVP: один hero определённого класса на profile
    op.create_index(
        "uq_hero_profile_class",
        "hero",
        ["profile_id", "class"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_hero_profile",
        "hero",
        ["profile_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_hero_level",
        "hero",
        ["level"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(
        """
        CREATE TRIGGER trg_hero_updated_at
        BEFORE UPDATE ON hero
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_hero_updated_at ON hero;")
    op.drop_index("ix_hero_level", table_name="hero")
    op.drop_index("ix_hero_profile", table_name="hero")
    op.drop_index("uq_hero_profile_class", table_name="hero")
    op.drop_table("hero")

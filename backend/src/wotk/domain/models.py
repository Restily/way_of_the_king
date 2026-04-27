"""SQLAlchemy 2.0 модели для §1-§5 DATABASE.md.

Скоуп MVP:
- §3.1 Profile
- §3.2 Referral
- §4.1 Hero
- §5.1 Balance
- §5.2 Transaction

Item / ItemBase / AffixDefinition (§6) и далее — добавляются в соответствующих фазах.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from wotk.domain.enums import (
    HeroClass,
    IntEnumColumn,
    TransactionType,
    enum_range_check,
)

# ============================================================================
# Base
# ============================================================================


class Base(DeclarativeBase):
    """Корневой DeclarativeBase для всех моделей."""

    type_annotation_map = {  # noqa: RUF012
        # Default mapping for built-in types
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }


# Шорткат для частых типов колонок
def _ts_column(*, default_now: bool = True, nullable: bool = False) -> Any:
    """TIMESTAMPTZ колонка с server_default=now() при default_now=True."""
    kwargs: dict[str, Any] = {"nullable": nullable}
    if default_now:
        kwargs["server_default"] = func.now()
    return mapped_column(DateTime(timezone=True), **kwargs)


# ============================================================================
# §3.1 profile
# ============================================================================


class Profile(Base):
    """Главная таблица аккаунтов. Один Telegram-юзер = одна запись."""

    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_username: Mapped[str | None] = mapped_column(String, nullable=True)
    telegram_first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    locale: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'ru'")
    )
    ip_country: Mapped[str | None] = mapped_column(String, nullable=True)
    is_blocked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    block_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    withdrawal_2fa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = _ts_column()
    updated_at: Mapped[datetime] = _ts_column()
    last_seen_at: Mapped[datetime | None] = _ts_column(default_now=False, nullable=True)

    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_profile_telegram_id"),
        CheckConstraint(
            "locale IN ('ru','en','es','pt','zh','ar')",
            name="ck_profile_locale",
        ),
        Index("ix_profile_telegram_id", "telegram_id"),
        Index(
            "ix_profile_last_seen_at",
            "last_seen_at",
            postgresql_where=text("NOT is_blocked"),
        ),
        Index("ix_profile_admin", "id", postgresql_where=text("is_admin")),
    )


# ============================================================================
# §3.2 referral
# ============================================================================


class Referral(Base):
    """Реферальная программа. Учитывает только подтверждённых рефералов."""

    __tablename__ = "referral"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    referrer_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profile.id", name="fk_referral_referrer"), nullable=False
    )
    referred_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profile.id", name="fk_referral_referred"), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = _ts_column(default_now=False, nullable=True)
    bonus_paid_gold: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = _ts_column()

    __table_args__ = (
        UniqueConstraint("referred_profile_id", name="uq_referral_referred"),
        Index(
            "ix_referral_referrer_active",
            "referrer_profile_id",
            "expires_at",
            postgresql_where=text("confirmed_at IS NOT NULL"),
        ),
    )


# ============================================================================
# §4.1 hero
# ============================================================================


class Hero(Base):
    """Игровой персонаж (knight в MVP, archer/necromancer постMVP)."""

    __tablename__ = "hero"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="CASCADE", name="fk_hero_profile"),
        nullable=False,
    )
    # SQLAlchemy reserved name — column DB-name "class" через первый аргумент
    hero_class: Mapped[HeroClass] = mapped_column(
        "class", IntEnumColumn(HeroClass), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    xp: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    unspent_points: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{\"stat\":0,\"skill\":0}'::jsonb")
    )
    base_stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{\"str\":10,\"dex\":5,\"int\":3}'::jsonb"),
    )
    passives: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    active_skills: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = _ts_column()
    updated_at: Mapped[datetime] = _ts_column()
    deleted_at: Mapped[datetime | None] = _ts_column(default_now=False, nullable=True)

    __table_args__ = (
        enum_range_check("ck_hero_class", "class", HeroClass),
        CheckConstraint("level BETWEEN 1 AND 100", name="ck_hero_level"),
        CheckConstraint("xp >= 0", name="ck_hero_xp"),
        CheckConstraint(
            "char_length(name) BETWEEN 3 AND 20", name="ck_hero_name_len"
        ),
        CheckConstraint(
            """
            jsonb_typeof(unspent_points) = 'object'
            AND jsonb_typeof(unspent_points->'stat') = 'number'
            AND jsonb_typeof(unspent_points->'skill') = 'number'
            AND (unspent_points->>'stat')::int >= 0
            AND (unspent_points->>'skill')::int >= 0
            """,
            name="ck_hero_unspent_points",
        ),
        # MVP: один hero определённого класса на profile (partial unique)
        Index(
            "uq_hero_profile_class",
            "profile_id",
            "class",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_hero_profile",
            "profile_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_hero_level", "level", postgresql_where=text("deleted_at IS NULL")
        ),
    )


# ============================================================================
# §5.1 balance
# ============================================================================


class Balance(Base):
    """Балансы и энергия профиля. Только GOLD в MVP."""

    __tablename__ = "balance"

    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="CASCADE", name="fk_balance_profile"),
        primary_key=True,
    )
    gold: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    energy: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("100")
    )
    energy_cap: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("100")
    )
    energy_updated_at: Mapped[datetime] = _ts_column()
    updated_at: Mapped[datetime] = _ts_column()

    __table_args__ = (
        CheckConstraint("gold >= 0", name="ck_balance_gold_nonneg"),
        CheckConstraint(
            "energy >= 0 AND energy <= energy_cap", name="ck_balance_energy"
        ),
    )


# ============================================================================
# §5.2 transaction
# ============================================================================


class Transaction(Base):
    """Аудит-лог движений gold. Каждое изменение balance.gold = запись здесь.

    Имя таблицы `transaction` — non-reserved в PG, SA квотирует автоматически.
    Партиционирование (PARTITION BY RANGE created_at) добавляется в Alembic-миграции,
    не в модели.
    """

    __tablename__ = "transaction"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", name="fk_transaction_profile"),
        nullable=False,
    )
    type: Mapped[TransactionType] = mapped_column(
        IntEnumColumn(TransactionType), nullable=False
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = _ts_column()

    __table_args__ = (
        enum_range_check("ck_transaction_type", "type", TransactionType),
        UniqueConstraint("idempotency_key", name="uq_transaction_idempotency"),
        Index(
            "ix_transaction_profile_created",
            "profile_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_transaction_type_created",
            "type",
            text("created_at DESC"),
        ),
        Index(
            "ix_transaction_ref_run",
            text("(ref->>'run_id')"),
            postgresql_where=text("ref ? 'run_id'"),
        ),
    )


__all__ = [
    "Balance",
    "Base",
    "Hero",
    "Profile",
    "Referral",
    "Transaction",
]

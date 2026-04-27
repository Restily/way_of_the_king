"""SQLAlchemy 2.0 модели для §1-§5 :file:`docs/DATABASE.md`.

Скоуп MVP:

* §3.1 :class:`Profile`
* §3.2 :class:`Referral`
* §4.1 :class:`Hero`
* §5.1 :class:`Balance`
* §5.2 :class:`Transaction`

:class:`Item` / :class:`ItemBase` / :class:`AffixDefinition` (§6) и далее —
добавляются в соответствующих фазах.
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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
    """Корневой :class:`DeclarativeBase` для всех моделей.

    Содержит ``type_annotation_map`` для автоматического маппинга
    Python-типов в SQLAlchemy-колонки (dict → JSONB, list → JSONB).
    """

    type_annotation_map = {  # noqa: RUF012
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }


def _ts_column(*, default_now: bool = True, nullable: bool = False) -> Any:
    """Helper для TIMESTAMPTZ-колонки с ``server_default=now()``.

    Сокращает повторяющиеся аргументы ``mapped_column(DateTime(timezone=True), …)``.

    :param default_now: Если ``True`` — добавляет ``server_default=now()``.
    :param nullable: Разрешён ли NULL.
    :returns: SQLAlchemy ``mapped_column`` instance.
    """
    kwargs: dict[str, Any] = {"nullable": nullable}
    if default_now:
        kwargs["server_default"] = func.now()
    return mapped_column(DateTime(timezone=True), **kwargs)


# ============================================================================
# §3.1 profile
# ============================================================================


class Profile(Base):
    """Главная таблица аккаунтов. Один Telegram-юзер = одна запись.

    Создаётся автоматически в ``POST /auth/login`` при первом входе.
    Связь с Telegram через unique ``telegram_id``.

    Денормализованные поля (``telegram_username``, ``telegram_first_name``,
    ``ip_country``) обновляются на каждом login — но через conditional set,
    чтобы не плодить пустые UPDATE.
    """

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
    """Реферальная программа. Учитывает только подтверждённых рефералов.

    ``referred_profile_id`` — UNIQUE: один профиль можно пригласить только
    один раз (защищает от двойных бонусов). ``confirmed_at`` ставится после
    прохождения tutorial.

    Окно начислений 30 дней (``expires_at``) — после этого реферрер
    перестаёт получать % с дохода реферала.
    """

    __tablename__ = "referral"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    referrer_profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", name="fk_referral_referrer"),
        nullable=False,
    )
    referred_profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", name="fk_referral_referred"),
        nullable=False,
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
    """Игровой персонаж (knight в MVP, archer/necromancer постMVP).

    Связь 1:N с :class:`Profile` через ``profile_id`` ON DELETE CASCADE.
    Партиал-уникальный индекс ``uq_hero_profile_class`` гарантирует
    "не более одного hero определённого класса на профиль".

    JSONB-колонки (``base_stats``, ``unspent_points``, ``passives``,
    ``active_skills``) — для гибкости. Аналитика по их содержимому пока
    не нужна; если потребуется — выделим в отдельные таблицы.

    ``level`` — денормализованная копия ``compute_level(xp)`` для индексов
    и быстрых leaderboard-запросов. Source of truth — функция
    :func:`wotk.game.leveling.compute_level`. При изменении ``xp``
    обязательно пересчитывать ``level`` в той же транзакции (см. apply_xp).
    """

    __tablename__ = "hero"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="CASCADE", name="fk_hero_profile"),
        nullable=False,
    )
    # SQLAlchemy reserved name — column DB-name "class" через первый аргумент.
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
    """Балансы и энергия профиля. Только GOLD в MVP.

    Создаётся автоматически с :class:`Profile` в ``/auth/login``.
    PK = ``profile_id`` (1:1 связь с Profile, ON DELETE CASCADE).

    ``gold`` хранится в "копейках" (1 UI gold = 1000 в БД) — позволяет
    bigint-арифметику без дробей.

    ``energy`` использует lazy regen pattern (см. :func:`wotk.game.energy.compute_regenerated`):
    значение в БД отстаёт от "реального", актуальное вычисляется при чтении.
    Запись только при spend-операциях.
    """

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
    """Аудит-лог движений gold. Каждое изменение ``balance.gold`` = запись здесь.

    Имя таблицы ``transaction`` — non-reserved в PG, SA квотирует автоматически.
    Партиционирование (``PARTITION BY RANGE created_at``) реализовано
    в Alembic-миграции (``op.execute("CREATE TABLE … PARTITION BY …")``),
    не в модели — SA не поддерживает это в ORM-DDL.

    Колонка ``balance_after`` = defensive copy: позволяет reconciliation
    cron быстро находить расхождения (``balance.gold`` vs
    ``last transaction.balance_after``).

    Колонка ``currency`` отсутствует — таблица хранит только GOLD.
    WOTK accounting в ``deposit`` / ``withdrawal``.
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

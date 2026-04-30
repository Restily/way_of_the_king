"""SQLAlchemy 2.0 модели для §1-§5 + §11.2 :file:`docs/DATABASE.md`.

Скоуп MVP:

* §3.1 :class:`Profile`
* §3.2 :class:`Referral`
* §4.1 :class:`Hero`
* §5.1 :class:`Balance`
* §5.2 :class:`Transaction`
* §11.2 :class:`IdempotencyKey`

:class:`Item` / :class:`ItemBase` / :class:`AffixDefinition` (§6) и далее —
добавляются в соответствующих фазах.
"""

from __future__ import annotations

import uuid
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
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from wotk.domain.enums import (
    AffixType,
    Difficulty,
    DungeonTheme,
    EncounterResult,
    EquipmentSlot,
    HeroClass,
    IntEnumColumn,
    Rarity,
    RunStatus,
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
        Index("ix_profile_admin", "id", postgresql_where=text("is_admin")),
        # ix_profile_last_seen_at intentionally omitted — see DATABASE.md §3.1.
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
        CheckConstraint(
            "referrer_profile_id != referred_profile_id",
            name="ck_referral_no_self",
        ),
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
    idempotency_key: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
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


# ============================================================================
# §11.2 idempotency_keys
# ============================================================================


class IdempotencyKey(Base):
    """Кэш ответов для idempotent POST-операций (DATABASE.md §11.2).

    PK = ``(key, profile_id)``. Один и тот же UUID разных юзеров не
    конфликтует. Существующая запись с тем же ``request_hash`` возвращает
    закэшированный ``response_status`` + ``response_body``; запись с
    ОТЛИЧАЮЩИМСЯ hash на тот же key — клиентская ошибка (422).

    ``request_hash`` — SHA-256 от тела запроса, ровно 32 байта (CHECK
    в БД). ``response_body`` ограничен 64 KB через CHECK на
    ``pg_column_size`` — защита от раздувания таблицы.

    TTL: 2h non-payment / 24h payment-critical (см. §11.2). Cleanup
    выполняется cron'ом ``cleanup_expired_idempotency_keys`` (Arq).
    """

    __tablename__ = "idempotency_keys"

    key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="CASCADE", name="fk_idem_profile"),
        nullable=False,
    )
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    is_payment_critical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = _ts_column()
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        PrimaryKeyConstraint("key", "profile_id", name="pk_idem"),
        CheckConstraint(
            "response_body IS NULL OR pg_column_size(response_body) <= 65536",
            name="ck_idem_body_size",
        ),
        CheckConstraint(
            "octet_length(request_hash) = 32",
            name="ck_idem_request_hash_len",
        ),
        Index("ix_idem_expires", "expires_at"),
    )


# ============================================================================
# §6.1 item_base
# ============================================================================


class ItemBase(Base):
    """Статичный каталог базовых типов предметов (DATABASE.md §6.1).

    Заполняется через ``scripts/seed_reference.py``, обновляется миграциями.
    ``kind`` — natural stable key (``sword_2h_iron``, ``bow_long_oak``),
    используется как i18n якорь и в loot-tables data-конфигах.

    ``base_stats`` JSONB — open-shape (для меча: ``{min_dmg, max_dmg, as}``,
    для брони: ``{def, hp_bonus}``). Структура валидируется на app-уровне
    при загрузке seed.
    """

    __tablename__ = "item_base"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    slot: Mapped[EquipmentSlot] = mapped_column(
        IntEnumColumn(EquipmentSlot), nullable=False
    )
    min_ilvl: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    base_stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_two_handed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = _ts_column()

    __table_args__ = (
        UniqueConstraint("kind", name="uq_item_base_kind"),
        enum_range_check("ck_item_base_slot", "slot", EquipmentSlot),
        CheckConstraint("min_ilvl >= 1", name="ck_item_base_min_ilvl"),
        Index("ix_item_base_slot", "slot"),
    )


# ============================================================================
# §6.2 affix_definition
# ============================================================================


class AffixDefinition(Base):
    """Список всех возможных аффиксов для генерации предметов (DATABASE.md §6.2).

    Алгоритм генерации в :mod:`wotk.game.loot` (pure functions). Этот класс —
    persistence-side; адаптер ``loot_db.load_affix_pool`` загружает строки
    в :class:`wotk.game.loot.AffixDefinition` dataclass.

    ``mod_group`` обеспечивает взаимную исключаемость: все tier'ы одного
    аффикса делят группу (``flat_str_t1`` и ``flat_str_t2`` → ``mod_group="flat_str"``).
    """

    __tablename__ = "affix_definition"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    affix_type: Mapped[AffixType] = mapped_column(
        IntEnumColumn(AffixType), nullable=False
    )
    mod_group: Mapped[str] = mapped_column(String, nullable=False)
    min_ilvl: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    tier: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    weight: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("100")
    )
    applicable_slots: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    tags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    spawn_weights: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    mod_type: Mapped[str] = mapped_column(String, nullable=False)
    value_min: Mapped[int] = mapped_column(Integer, nullable=False)
    value_max: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _ts_column()

    __table_args__ = (
        UniqueConstraint(
            "mod_group", "mod_type", "tier", name="uq_affix_def_natural"
        ),
        enum_range_check("ck_affix_type", "affix_type", AffixType),
        CheckConstraint("value_min <= value_max", name="ck_affix_value_range"),
        CheckConstraint("tier BETWEEN 1 AND 10", name="ck_affix_tier"),
        CheckConstraint("weight > 0", name="ck_affix_weight_pos"),
        CheckConstraint("min_ilvl >= 1", name="ck_affix_min_ilvl"),
        Index("ix_affix_def_type_ilvl", "affix_type", "min_ilvl"),
        Index("ix_affix_def_modgroup", "mod_group"),
        Index("ix_affix_def_tags", "tags", postgresql_using="gin"),
        Index("ix_affix_def_slots", "applicable_slots", postgresql_using="gin"),
    )


# ============================================================================
# §6.3 item
# ============================================================================


class Item(Base):
    """Экземпляр предмета владельца (DATABASE.md §6.3).

    ``affixes`` — JSONB snapshot ``[{id, value, t, vmin, vmax}]`` на момент
    дропа. Балансные правки ``affix_definition`` не меняют существующие
    предметы (PoE/D2 практика, см. §6.3.1).

    Состояния (взаимно исключаемые, защищено CHECK ``ck_item_state_exclusive``):

    * ``equipped_on + equipped_slot`` — надет на героя
    * ``inventory_position`` — в сумке (0..47)
    * ``is_in_market_escrow`` — выставлен на маркете (v1)
    * ``escrow_run_id`` — поднят в активном ране (см. RUN-LIFECYCLE.md)
    * Если все NULL/false — «orphaned», cleanup cron'ом

    FK ``escrow_run_id`` → ``dungeon_runs.id`` добавится в миграции 0008
    (циклическая зависимость через CREATE TABLE order).
    """

    __tablename__ = "item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", name="fk_item_profile"),
        nullable=False,
    )
    base_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("item_base.id", name="fk_item_base"),
        nullable=False,
    )
    rarity: Mapped[Rarity] = mapped_column(IntEnumColumn(Rarity), nullable=False)
    ilvl: Mapped[int] = mapped_column(Integer, nullable=False)
    affixes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    equipped_on: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("hero.id", name="fk_item_hero"),
        nullable=True,
    )
    equipped_slot: Mapped[EquipmentSlot | None] = mapped_column(
        IntEnumColumn(EquipmentSlot), nullable=True
    )
    inventory_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_in_market_escrow: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # FK к dungeon_runs добавится в миграции 0008.
    escrow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = _ts_column()
    updated_at: Mapped[datetime] = _ts_column()

    __table_args__ = (
        enum_range_check("ck_item_rarity", "rarity", Rarity),
        CheckConstraint("ilvl >= 1", name="ck_item_ilvl_pos"),
        CheckConstraint(
            "equipped_slot IS NULL OR equipped_slot BETWEEN 0 AND 5",
            name="ck_item_equip_slot",
        ),
        CheckConstraint(
            """
            (equipped_on IS NULL AND equipped_slot IS NULL)
            OR (equipped_on IS NOT NULL AND equipped_slot IS NOT NULL)
            """,
            name="ck_item_equip_pair",
        ),
        CheckConstraint(
            "inventory_position IS NULL OR (inventory_position BETWEEN 0 AND 47)",
            name="ck_item_inv_pos",
        ),
        # Item не может быть одновременно в нескольких "местах".
        CheckConstraint(
            """
            (CASE WHEN equipped_on IS NOT NULL THEN 1 ELSE 0 END
           + CASE WHEN inventory_position IS NOT NULL THEN 1 ELSE 0 END
           + CASE WHEN is_in_market_escrow THEN 1 ELSE 0 END
           + CASE WHEN escrow_run_id IS NOT NULL THEN 1 ELSE 0 END
            ) <= 1
            """,
            name="ck_item_state_exclusive",
        ),
        Index(
            "uq_item_equipment_slot",
            "equipped_on",
            "equipped_slot",
            unique=True,
            postgresql_where=text("equipped_on IS NOT NULL"),
        ),
        Index(
            "uq_item_inventory_position",
            "owner_profile_id",
            "inventory_position",
            unique=True,
            postgresql_where=text("inventory_position IS NOT NULL"),
        ),
        Index(
            "ix_item_owner",
            "owner_profile_id",
            postgresql_where=text(
                "NOT is_in_market_escrow AND escrow_run_id IS NULL"
            ),
        ),
        Index(
            "ix_item_owner_equipped",
            "owner_profile_id",
            "equipped_on",
            postgresql_where=text("equipped_on IS NOT NULL"),
        ),
        Index("ix_item_rarity", "rarity"),
        Index(
            "ix_item_escrow_run",
            "escrow_run_id",
            postgresql_where=text("escrow_run_id IS NOT NULL"),
        ),
        Index(
            "ix_item_affixes_gin",
            "affixes",
            postgresql_using="gin",
            postgresql_ops={"affixes": "jsonb_path_ops"},
        ),
    )


# ============================================================================
# §8.1 dungeons (reference)
# ============================================================================


class Dungeon(Base):
    """Reference-каталог данжей (DATABASE.md §8.1).

    PK = TEXT (``crypt_normal``, ``forest_hard``) — позволяет stable-references
    из дизайн-документов и i18n. Конфиг floors/encounters/loot — в JSONB
    ``config`` (open shape, валидируется в game-логике при загрузке run'а).
    """

    __tablename__ = "dungeons"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name_key: Mapped[str] = mapped_column(String, nullable=False)
    theme: Mapped[DungeonTheme] = mapped_column(
        IntEnumColumn(DungeonTheme), nullable=False
    )
    difficulty: Mapped[Difficulty] = mapped_column(
        IntEnumColumn(Difficulty), nullable=False
    )
    min_level: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    entry_cost_gold: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_cost_energy: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("10")
    )
    daily_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    floors_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    xp_base: Mapped[int] = mapped_column(Integer, nullable=False)
    gold_base: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Кампания: act и location NULL у туториальных данжей.
    act: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = _ts_column()
    updated_at: Mapped[datetime] = _ts_column()

    __table_args__ = (
        enum_range_check("ck_dungeons_theme", "theme", DungeonTheme),
        enum_range_check("ck_dungeons_difficulty", "difficulty", Difficulty),
        CheckConstraint("min_level >= 1", name="ck_dungeons_min_level"),
        CheckConstraint("floors_count >= 1", name="ck_dungeons_floors"),
        CheckConstraint(
            "act IS NULL OR act BETWEEN 1 AND 5", name="ck_dungeons_act"
        ),
        CheckConstraint(
            "location IS NULL OR location BETWEEN 1 AND 10",
            name="ck_dungeons_location",
        ),
        Index("ix_dungeons_enabled", "is_enabled", "min_level"),
    )


# ============================================================================
# §8.2 dungeon_runs
# ============================================================================


class DungeonRun(Base):
    """Активный или завершённый run в данже (DATABASE.md §8.2 + RUN-LIFECYCLE.md).

    PK = UUID — выдаётся клиенту в ws_token и в эскроу-предметах. Партиал
    unique ``uq_runs_one_active_per_hero`` (status=IN_PROGRESS) гарантирует
    "не более одного активного run'а на героя".

    ``seed`` (32 байта) фиксируется при INSERT и БД-уровень триггер
    ``trg_runs_seed_immutable`` запрещает его изменение — это контракт
    reproducible RNG для replay/anti-cheat.
    """

    __tablename__ = "dungeon_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profile.id", name="fk_runs_profile"), nullable=False
    )
    hero_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("hero.id", name="fk_runs_hero"), nullable=False
    )
    dungeon_id: Mapped[str] = mapped_column(
        String, ForeignKey("dungeons.id", name="fk_runs_dungeon"), nullable=False
    )
    seed: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        IntEnumColumn(RunStatus), nullable=False, server_default=text("0")
    )
    current_floor: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    hero_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    pending_gold: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    entry_paid_gold: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_paid_energy: Mapped[int] = mapped_column(Integer, nullable=False)
    revives_used: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    realtime_node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = _ts_column()
    last_activity_at: Mapped[datetime] = _ts_column()
    last_checkpoint_at: Mapped[datetime] = _ts_column()
    finished_at: Mapped[datetime | None] = _ts_column(default_now=False, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        enum_range_check("ck_runs_status", "status", RunStatus),
        CheckConstraint("current_floor >= 0", name="ck_runs_floor_nonneg"),
        CheckConstraint("octet_length(seed) = 32", name="ck_runs_seed_size"),
        CheckConstraint("pending_gold >= 0", name="ck_runs_pending_gold"),
        CheckConstraint("revives_used >= 0", name="ck_runs_revives"),
        Index(
            "uq_runs_one_active_per_hero",
            "hero_id",
            unique=True,
            postgresql_where=text("status = 0"),
        ),
        Index(
            "ix_runs_profile_started",
            "profile_id",
            text("started_at DESC"),
        ),
        Index(
            "ix_runs_status_expires",
            "status",
            "expires_at",
            postgresql_where=text("status = 0"),
        ),
        Index("ix_runs_dungeon_status", "dungeon_id", "status"),
    )


# ============================================================================
# §8.3 run_encounters
# ============================================================================


class RunEncounter(Base):
    """Лог боёв в ране для replay-аудита (DATABASE.md §8.3).

    ``combat_summary`` JSONB обязательно содержит ключ ``v`` (number) —
    версия схемы summary. CHECK на DB-уровне.
    """

    __tablename__ = "run_encounters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "dungeon_runs.id", ondelete="CASCADE", name="fk_encounters_run"
        ),
        nullable=False,
    )
    floor: Mapped[int] = mapped_column(Integer, nullable=False)
    encounter_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    enemies_spawned: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    combat_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    loot_rolled: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    gold_rolled: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    result: Mapped[EncounterResult] = mapped_column(
        IntEnumColumn(EncounterResult), nullable=False
    )
    created_at: Mapped[datetime] = _ts_column()

    __table_args__ = (
        UniqueConstraint(
            "run_id", "floor", "encounter_idx", name="uq_encounters_run_floor_idx"
        ),
        enum_range_check("ck_encounters_result", "result", EncounterResult),
        CheckConstraint("floor >= 0", name="ck_encounters_floor_pos"),
        CheckConstraint(
            "combat_summary ? 'v' "
            "AND jsonb_typeof(combat_summary -> 'v') = 'number'",
            name="ck_encounters_summary_version",
        ),
        Index("ix_encounters_run", "run_id"),
    )


# ============================================================================
# §8.4 daily_dungeon_entries
# ============================================================================


class DailyDungeonEntry(Base):
    """Учёт лимитов входов в данж в сутки (DATABASE.md §8.4).

    PK = (profile_id, dungeon_id, date_utc). UPSERT через
    ``ON CONFLICT (profile_id, dungeon_id, date_utc) DO UPDATE`` в /enter handler.
    """

    __tablename__ = "daily_dungeon_entries"

    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="CASCADE", name="fk_daily_entries_profile"),
        nullable=False,
    )
    dungeon_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("dungeons.id", name="fk_daily_entries_dungeon"),
        nullable=False,
    )
    date_utc: Mapped[datetime] = mapped_column(
        # DATE без timezone — UTC-день, см. SPEC.md
        DateTime(timezone=False), nullable=False
    )
    count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = _ts_column()

    __table_args__ = (
        PrimaryKeyConstraint(
            "profile_id", "dungeon_id", "date_utc", name="pk_daily_entries"
        ),
        CheckConstraint("count >= 0", name="ck_daily_entries_count"),
        Index("ix_daily_entries_date", "date_utc"),
    )


# ============================================================================
# §8.5 campaign_progress
# ============================================================================


class CampaignProgress(Base):
    """Прогрессия кампании на персонажа (DATABASE.md §8.5).

    PK = (hero_id, act, location). UPSERT при каждом успешном clear
    (увеличиваем completion_count, обновляем best_clear_time_s если лучше).
    """

    __tablename__ = "campaign_progress"

    hero_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("hero.id", ondelete="CASCADE", name="fk_campaign_hero"),
        nullable=False,
    )
    act: Mapped[int] = mapped_column(Integer, nullable=False)
    location: Mapped[int] = mapped_column(Integer, nullable=False)
    first_completed_at: Mapped[datetime] = _ts_column()
    best_clear_time_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )

    __table_args__ = (
        PrimaryKeyConstraint("hero_id", "act", "location", name="pk_campaign_progress"),
        CheckConstraint("act BETWEEN 1 AND 5", name="ck_campaign_act"),
        CheckConstraint("location BETWEEN 1 AND 10", name="ck_campaign_loc"),
        CheckConstraint(
            "best_clear_time_s IS NULL OR best_clear_time_s > 0",
            name="ck_campaign_clear_t",
        ),
        CheckConstraint("completion_count >= 1", name="ck_campaign_count"),
    )


__all__ = [
    "AffixDefinition",
    "Balance",
    "Base",
    "CampaignProgress",
    "DailyDungeonEntry",
    "Dungeon",
    "DungeonRun",
    "Hero",
    "IdempotencyKey",
    "Item",
    "ItemBase",
    "Profile",
    "Referral",
    "RunEncounter",
    "Transaction",
]

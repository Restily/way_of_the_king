"""Enum-маппинги SMALLINT → код для domain-слоя.

Источник истины — :file:`docs/DATABASE.md` §1.5.

Правила (из docs):

* Никогда не переиспользовать значение. После удаления code устаревший
  value становится ``_DEPRECATED_<old_name>``.
* Новые значения добавляются в конец, никогда не вставляются в середину.
* При выводе на UI/логи — конвертировать в строку через ``name``,
  не сырую цифру.

**Скоуп MVP (§1-§5):** только :class:`HeroClass` и :class:`TransactionType`.
Остальные enum'ы (``item.rarity``, ``dungeon.theme``, …) добавляются
в соответствующих фазах.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, TypeVar

from sqlalchemy import CheckConstraint, SmallInteger
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

E = TypeVar("E", bound=IntEnum)


# ============================================================================
# Enum классы (§1.5 DATABASE.md)
# ============================================================================


class HeroClass(IntEnum):
    """Класс игрового персонажа (``hero.class`` в БД).

    Значения являются авторитетным маппингом для колонки ``hero.class``
    типа SMALLINT. См. :func:`enum_range_check` для генерации
    DB CHECK constraint.

    :cvar KNIGHT: Танк/melee, основной стат STR.
    :cvar ARCHER: DPS/ranged (постMVP).
    :cvar NECROMANCER: Caster/summoner (постMVP).
    """

    KNIGHT = 0
    ARCHER = 1
    NECROMANCER = 2


class TransactionType(IntEnum):
    """Тип финансовой операции в gold ledger (``transaction.type`` в БД).

    Все значения относятся к gold-ledger'у. Движения WOTK учитываются
    отдельно в таблицах ``deposit`` / ``withdrawal``.

    Значения 3–9, 12–13, 17–22 относятся к фичам v1+ (PVP, маркет, крафт,
    монетизация). Они зарезервированы в enum, но фактически insert'ятся
    только когда соответствующая фича приедет.
    """

    DUNGEON_ENTRY = 0
    DUNGEON_REWARD = 1
    DUNGEON_REVIVE = 2
    PVP_BET = 3  # v1.1
    PVP_REWARD = 4  # v1.1
    PVP_FEE = 5  # v1.1
    MARKET_LIST_FEE = 6  # v1
    MARKET_BUY = 7  # v1
    MARKET_SELL = 8  # v1
    MARKET_FEE = 9  # v1
    SHOP_BUY = 10
    SHOP_SELL = 11
    SHOP_REROLL = 12
    SHOP_SALVAGE = 13
    DEPOSIT = 14
    WITHDRAW = 15
    WITHDRAW_REFUND = 16
    DAILY_REWARD = 17
    REFERRAL_BONUS = 18
    AIRDROP = 19
    KORONA_PURCHASE = 20
    ENERGY_PURCHASE = 21
    ADMIN_ADJUST = 22


# ============================================================================
# SQLAlchemy TypeDecorator: IntEnum ↔ SMALLINT
# ============================================================================


class IntEnumColumn(TypeDecorator[E]):
    """Прозрачно конвертирует Python ``IntEnum`` в ``SMALLINT`` PostgreSQL.

    Использование::

        class Hero(Base):
            class_: Mapped[HeroClass] = mapped_column(
                "class", IntEnumColumn(HeroClass), nullable=False,
            )

    На bind: проверяет что значение принадлежит enum (защита от
    случайных int'ов вне диапазона). На fetch: возвращает экземпляр enum.

    :cvar impl: SMALLINT — backing storage type.
    :cvar cache_ok: True — безопасно кэшировать в SA statement cache.
    :ivar enum_class: Класс enum, с которым связана колонка.
    """

    impl = SmallInteger
    cache_ok = True

    def __init__(self, enum_class: type[E]) -> None:
        """Создать TypeDecorator для конкретного enum-класса.

        :param enum_class: Подкласс :class:`enum.IntEnum`.
        """
        super().__init__()
        self.enum_class = enum_class

    def process_bind_param(
        self, value: E | int | None, dialect: Dialect
    ) -> int | None:
        """Конвертация Python → SMALLINT при INSERT/UPDATE.

        :param value: Значение enum, raw int (валидное), или None.
        :param dialect: SA dialect (не используется).
        :returns: Целое для записи в БД, либо None.
        :raises ValueError: Если ``int(value)`` не принадлежит enum.
        """
        if value is None:
            return None
        if isinstance(value, self.enum_class):
            return int(value)
        return self.enum_class(int(value)).value

    def process_result_value(
        self, value: int | None, dialect: Dialect
    ) -> E | None:
        """Конвертация SMALLINT → Python при SELECT.

        :param value: Целое из БД либо None.
        :param dialect: SA dialect (не используется).
        :returns: Экземпляр enum, либо None.
        :raises ValueError: Если значение в БД не валидно для enum
            (data corruption / неучтённое legacy значение).
        """
        if value is None:
            return None
        return self.enum_class(value)

    def copy(self, **kw: Any) -> "IntEnumColumn[E]":
        """Создать копию TypeDecorator (требуется SA для cloning).

        :param kw: Дополнительные kwargs (игнорируются).
        :returns: Новый ``IntEnumColumn`` с тем же enum_class.
        """
        return IntEnumColumn(self.enum_class)


def enum_range_check(
    name: str, column: str, enum_class: type[IntEnum]
) -> CheckConstraint:
    """Генерирует ``CHECK BETWEEN min AND max`` из значений ``IntEnum``.

    Использование в ``__table_args__``::

        enum_range_check("ck_hero_class", "class", HeroClass)

    При добавлении нового значения в IntEnum CHECK в model автоматически
    расширяется. Однако в продакшене нужна Alembic-миграция с
    ``ALTER TABLE … DROP CONSTRAINT … ADD CONSTRAINT`` — миграции
    иммутабельны, их CHECK не подтягивается из enum.

    :param name: Имя CONSTRAINT в БД (``ck_<table>_<column>``).
    :param column: Имя колонки.
    :param enum_class: Подкласс :class:`enum.IntEnum`.
    :returns: SA :class:`CheckConstraint` с диапазоном
        ``column BETWEEN min(enum_values) AND max(enum_values)``.
    """
    values = [m.value for m in enum_class]
    return CheckConstraint(
        f"{column} BETWEEN {min(values)} AND {max(values)}", name=name
    )

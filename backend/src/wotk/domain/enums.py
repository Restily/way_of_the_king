"""Enum-маппинги SMALLINT → код для domain-слоя.

Источник истины — `docs/DATABASE.md` §1.5.

Правила (из docs):
- Никогда не переиспользовать значение. После удаления code устаревший
  value становится `_DEPRECATED_<old_name>`.
- Новые значения добавляются в конец, никогда не вставляются в середину.
- При выводе на UI/логи — конвертировать в строку через name, не сырую цифру.

Скоуп MVP (§1-§5): только HeroClass и TransactionType.
Остальные enum'ы (item.rarity, dungeon.theme, etc.) добавляются
в соответствующих фазах.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, TypeVar

from sqlalchemy import SmallInteger
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

E = TypeVar("E", bound=IntEnum)


# ============================================================================
# Enum классы (§1.5)
# ============================================================================


class HeroClass(IntEnum):
    """`hero.class` — класс игрового персонажа."""

    KNIGHT = 0
    ARCHER = 1
    NECROMANCER = 2


class TransactionType(IntEnum):
    """`transaction.type` — тип финансовой операции (gold ledger).

    Все значения — gold ledger. WOTK движения — в `deposit`/`withdrawal`.
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
    """Прозрачно конвертирует Python `IntEnum` в `SMALLINT` PostgreSQL.

    Использование:
        class Hero(Base):
            class_: Mapped[HeroClass] = mapped_column(
                "class", IntEnumColumn(HeroClass), nullable=False
            )

    На bind: проверяет что значение принадлежит enum (защита от
    случайных int'ов вне диапазона).
    На fetch: возвращает экземпляр enum.
    """

    impl = SmallInteger
    cache_ok = True

    def __init__(self, enum_class: type[E]) -> None:
        super().__init__()
        self.enum_class = enum_class

    def process_bind_param(  # noqa: D102
        self, value: E | int | None, dialect: Dialect
    ) -> int | None:
        if value is None:
            return None
        if isinstance(value, self.enum_class):
            return int(value)
        # raise если int вне валидных значений enum
        return self.enum_class(int(value)).value

    def process_result_value(  # noqa: D102
        self, value: int | None, dialect: Dialect
    ) -> E | None:
        if value is None:
            return None
        return self.enum_class(value)

    def copy(self, **kw: Any) -> "IntEnumColumn[E]":  # noqa: D102, ARG002
        return IntEnumColumn(self.enum_class)

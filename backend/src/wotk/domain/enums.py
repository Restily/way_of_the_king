"""Enum-маппинги SMALLINT → код для domain-слоя.

Источник истины — :file:`docs/DATABASE.md` §1.5.

Правила (из docs):

* Никогда не переиспользовать значение. После удаления code устаревший
  value становится ``_DEPRECATED_<old_name>``.
* Новые значения добавляются в конец, никогда не вставляются в середину.
* При выводе на UI/логи — конвертировать в строку через ``name``,
  не сырую цифру.

**Скоуп текущей фазы:** §1-§5 + §6 (items/affixes). §8 (dungeons) добавится
в W3-011, §7 (wallets/withdrawals) — Phase 7.
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


class EquipmentSlot(IntEnum):
    """Слот экипировки (``item.equipped_slot`` и ``item_base.slot`` в БД).

    Маппинг из DATABASE.md §1.5. ``OFFHAND`` (3) валиден только если у hero'я
    в ``WEAPON`` (2) НЕ ``is_two_handed=true`` — это валидируется в
    application-слое equip-эндпоинта (Phase 5/W4).
    """

    HELMET = 0
    CHEST = 1
    WEAPON = 2
    OFFHAND = 3
    BOOTS = 4
    RING = 5


class Rarity(IntEnum):
    """Редкость предмета (``item.rarity`` в БД).

    Влияет на ``AFFIX_COUNT_DISTRIBUTION`` в :mod:`wotk.game.loot` —
    rarity → распределение количества аффиксов.
    """

    COMMON = 0
    MAGIC = 1
    RARE = 2
    EPIC = 3
    LEGENDARY = 4


class AffixType(IntEnum):
    """Тип аффикса (``affix_definition.affix_type`` в БД).

    Зеркало :class:`wotk.game.loot.AffixType` — обязательно держать
    значения синхронными (тест в test_enums.py проверяет).
    """

    PREFIX = 0
    SUFFIX = 1
    IMPLICIT = 2


class DungeonTheme(IntEnum):
    """Тема данжа (``dungeons.theme`` в БД, §1.5).

    Влияет на tile/sprite paks (когда появятся assets) и loot-pool flavour.
    """

    CRYPT = 0
    FOREST = 1
    CASTLE = 2
    TOWER = 3
    SWAMP = 4


class Difficulty(IntEnum):
    """Сложность данжа (``dungeons.difficulty`` в БД, §1.5).

    Multiplier применяется к mob HP/damage/loot quality (формулы в SPEC.md).
    """

    NORMAL = 0
    HARD = 1
    MYTHIC = 2


class RunStatus(IntEnum):
    """Жизненный цикл прохождения данжа (``dungeon_runs.status`` в БД, §1.5).

    State-machine (см. RUN-LIFECYCLE.md):
    IN_PROGRESS → {COMPLETED|FAILED|FLED|ABANDONED} → SETTLED
    """

    IN_PROGRESS = 0
    COMPLETED = 1
    FAILED = 2
    FLED = 3
    ABANDONED = 4
    SETTLED = 5


class EncounterResult(IntEnum):
    """Результат отдельного encounter'а в ране (``run_encounters.result``)."""

    WIN = 0
    LOSS = 1
    FLED = 2


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

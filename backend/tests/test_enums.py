"""Anti-drift тесты на enum-маппинги: код vs DATABASE.md §1.5."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wotk.domain.enums import HeroClass, TransactionType

DATABASE_MD = Path(__file__).resolve().parents[2] / "docs" / "DATABASE.md"


def _parse_enum_table(section_anchor: str) -> dict[int, str]:
    """Парсит markdown-таблицу с маппингом из §1.5.

    Ищет heading `#### \`<section_anchor>\`` и читает следующую
    таблицу `| Value | Code |...` до пустой строки.
    """
    text = DATABASE_MD.read_text(encoding="utf-8")
    pattern = rf"#### `{re.escape(section_anchor)}`.*?\n(\|[^\n]+\n)+"
    match = re.search(pattern, text)
    if not match:
        raise AssertionError(
            f"Section #### `{section_anchor}` not found in DATABASE.md"
        )

    block = match.group(0)
    result: dict[int, str] = {}
    for line in block.splitlines():
        # Строки данных: "| 0 | KNIGHT |" или "| 6 | MARKET_LIST_FEE | v1 |"
        m = re.match(r"^\|\s*(\d+)\s*\|\s*([A-Z_][A-Z0-9_]*)\s*\|", line)
        if m:
            value = int(m.group(1))
            name = m.group(2)
            result[value] = name
    return result


@pytest.mark.parametrize(
    ("enum_class", "section_anchor"),
    [
        (HeroClass, "hero.class"),
        (TransactionType, "transaction.type"),
    ],
)
def test_enum_matches_database_md(
    enum_class: type, section_anchor: str
) -> None:
    """Каждое значение enum в коде ↔ запись в §1.5 DATABASE.md."""
    expected = _parse_enum_table(section_anchor)
    actual = {member.value: member.name for member in enum_class}

    assert actual == expected, (
        f"{enum_class.__name__} drift from DATABASE.md §1.5 `{section_anchor}`:\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual}"
    )


def test_hero_class_no_gaps() -> None:
    """HeroClass значения должны быть непрерывными от 0."""
    values = sorted(member.value for member in HeroClass)
    assert values == list(range(len(values))), (
        f"HeroClass has gaps in values: {values}"
    )


def test_transaction_type_starts_at_zero() -> None:
    """TransactionType: первое значение = 0 (DUNGEON_ENTRY)."""
    assert TransactionType.DUNGEON_ENTRY == 0


def test_int_enum_column_validates_range() -> None:
    """IntEnumColumn должен отклонить int вне валидных значений."""
    from sqlalchemy.engine import Dialect

    from wotk.domain.enums import IntEnumColumn

    col = IntEnumColumn(HeroClass)
    fake_dialect: Dialect = None  # type: ignore[assignment]

    # Валидные значения проходят
    assert col.process_bind_param(HeroClass.KNIGHT, fake_dialect) == 0
    assert col.process_bind_param(2, fake_dialect) == 2

    # Невалидное значение → ValueError
    with pytest.raises(ValueError):
        col.process_bind_param(99, fake_dialect)


def test_int_enum_column_roundtrip() -> None:
    """fetch возвращает enum-экземпляр, не сырой int."""
    from sqlalchemy.engine import Dialect

    from wotk.domain.enums import IntEnumColumn

    col = IntEnumColumn(HeroClass)
    fake_dialect: Dialect = None  # type: ignore[assignment]

    result = col.process_result_value(1, fake_dialect)
    assert result is HeroClass.ARCHER
    assert isinstance(result, HeroClass)

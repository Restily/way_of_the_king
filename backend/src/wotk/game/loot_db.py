"""Адаптер между pure-functions :mod:`wotk.game.loot` и SQLAlchemy-моделями.

:func:`load_affix_pool` загружает строки из :class:`AffixDefinition` table и
конвертирует в loot dataclasses (фильтрует по slot + min_ilvl).
:func:`materialize_item` берёт :class:`GeneratedItem` и INSERT'ит в ``item``
table со snapshot affixes JSONB (``[{id,value,t,vmin,vmax}]`` per §6.3.1).

loot.py остаётся pure (random.Random + dataclasses, без I/O); этот модуль
делает всю работу с БД.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.domain.models import AffixDefinition as AffixDefinitionRow
from wotk.domain.models import Item
from wotk.game.loot import AffixDefinition as LootAffixDefinition
from wotk.game.loot import GeneratedItem


async def load_affix_pool(
    session: AsyncSession,
    *,
    slot: int,
    ilvl: int,
) -> tuple[LootAffixDefinition, ...]:
    """Загрузить пул аффиксов применимых к слоту и ilvl-порогу.

    Использует GIN-индекс ``ix_affix_def_slots`` через ``@>`` containment.
    Дополнительно фильтрует ``min_ilvl <= ilvl``.

    :param session: Async DB session.
    :param slot: ``EquipmentSlot.value`` целевого предмета.
    :param ilvl: Item level (от моба-дроппера).
    :returns: Tuple с готовыми ``loot.AffixDefinition`` для feed в
        ``generate_affixes()``.
    """
    stmt = (
        select(AffixDefinitionRow)
        .where(
            AffixDefinitionRow.applicable_slots.contains([slot]),
            AffixDefinitionRow.min_ilvl <= ilvl,
        )
        .order_by(AffixDefinitionRow.id)
    )
    rows = (await session.scalars(stmt)).all()
    return tuple(_row_to_loot(row) for row in rows)


def _row_to_loot(row: AffixDefinitionRow) -> LootAffixDefinition:
    """Конвертировать SQLAlchemy строку в pure dataclass для loot.py.

    :param row: ORM-объект из ``affix_definition`` table.
    :returns: ``LootAffixDefinition`` готовый для weighted-random.
    """
    return LootAffixDefinition(
        id=row.id,
        affix_type=row.affix_type,
        mod_group=row.mod_group,
        applicable_slots=tuple(int(s) for s in row.applicable_slots),
        min_ilvl=row.min_ilvl,
        weight=row.weight,
        value_min=row.value_min,
        value_max=row.value_max,
        mod_type=row.mod_type,
        tags=frozenset(str(t) for t in row.tags),
        spawn_weights=dict(row.spawn_weights) if row.spawn_weights else None,
        tier=row.tier,
    )


def _build_affixes_snapshot(
    generated: GeneratedItem,
    pool: tuple[LootAffixDefinition, ...],
) -> list[dict[str, int | str]]:
    """Сформировать snapshot ``[{id,value,t,vmin,vmax,mod_type}]`` для ``item.affixes``.

    Snapshot фиксирует tier/value_min/value_max + mod_type на момент дропа.
    ``mod_type`` нужен для ``hero_stats.compute_hero_combat_stats``, иначе
    эффект affix'а нельзя применить без отдельного JOIN на affix_definition.
    DATABASE.md §6.3.1 + W4 hero_stats integration.

    :raises KeyError: Если RolledAffix.affix_id отсутствует в pool —
        contract violation (loot.py выбирает только из переданного pool).
    """
    by_id = {a.id: a for a in pool}
    return [
        {
            "id": rolled.affix_id,
            "value": rolled.value,
            "t": by_id[rolled.affix_id].tier,
            "vmin": by_id[rolled.affix_id].value_min,
            "vmax": by_id[rolled.affix_id].value_max,
            "mod_type": by_id[rolled.affix_id].mod_type,
        }
        for rolled in generated.affixes
    ]


async def materialize_item(
    session: AsyncSession,
    *,
    generated: GeneratedItem,
    pool: tuple[LootAffixDefinition, ...],
    owner_profile_id: int,
    escrow_run_id: uuid.UUID | None = None,
) -> Item:
    """Создать запись в ``item`` table из :class:`GeneratedItem`.

    State semantics: новый item создаётся в ``escrow_run_id`` если задан
    (поднят в активном ране), иначе orphaned (для вызовов вне run-flow,
    например seed-скриптов).

    :param session: Async DB session — caller отвечает за transaction.
    :param generated: Result of :func:`wotk.game.loot.generate_item`.
    :param pool: Тот же pool что использовался в generate_item (для snapshot).
    :param owner_profile_id: PK профиля, владельца предмета.
    :param escrow_run_id: UUID активного ``dungeon_run``, если предмет
        материализуется как part of run pickup. ``None`` для seed/admin.
    :returns: Созданный :class:`Item` (после ``flush()``, с присвоенным id).
    """
    affixes_snapshot: list[dict[str, Any]] = list(
        _build_affixes_snapshot(generated, pool)
    )
    item = Item(
        owner_profile_id=owner_profile_id,
        base_id=generated.base_id,
        rarity=generated.rarity,
        ilvl=generated.ilvl,
        affixes=affixes_snapshot,
        escrow_run_id=escrow_run_id,
    )
    session.add(item)
    await session.flush()
    return item


__all__ = [
    "load_affix_pool",
    "materialize_item",
]

"""Loot generation: rarity → affix count → weighted selection → value roll.

Алгоритм взят из Path of Exile (де-факто референс) с упрощениями для MVP.
См. :file:`docs/LOOT-DESIGN.md` (TODO).

Pure functions, без I/O. Адаптер для SQLAlchemy-моделей появится в Phase 5
когда таблицы ``item_base`` / ``affix_definition`` будут реализованы
(сейчас они только в DATABASE.md §6).

Алгоритм (PoE-style):

1. Roll rarity (см. :func:`roll_rarity`) — вне этого модуля.
2. По rarity выбрать ``affix_count`` через :func:`sample_affix_count`.
3. Отфильтровать ``affix_definitions`` по slot и ``min_ilvl``.
4. Для каждого аффикса:

   * выбрать сторону (prefix/suffix) с откатом если переполнена;
   * weighted random выбор из pool с учётом ``mod_group`` exclusion;
   * uniform integer roll внутри ``[value_min, value_max]``.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import IntEnum

from wotk.domain.enums import HeroClass  # noqa: F401  # для будущих per-class affixes


class AffixType(IntEnum):
    """Совпадает с ``affix_definition.affix_type`` enum (см. §1.5)."""

    PREFIX = 0
    SUFFIX = 1
    IMPLICIT = 2


class Rarity(IntEnum):
    """Совпадает с ``items.rarity`` enum (см. §1.5)."""

    COMMON = 0
    MAGIC = 1
    RARE = 2
    EPIC = 3
    LEGENDARY = 4


# ============================================================================
# Affix count distribution per rarity
# ============================================================================
#
# PoE rare = 4:5:6 affixes с весами 8:3:1 (P(4)=66.7%, P(5)=25%, P(6)=8.3%).
# Для Telegram Mini App (короткие сессии) сместили распределение к меньшему
# числу аффиксов — chase-loot не должен быть слишком разреженным.

#: Лимиты сторон (prefix_limit, suffix_limit) по rarity.
SIDE_LIMITS: dict[Rarity, tuple[int, int]] = {
    Rarity.COMMON: (0, 0),
    Rarity.MAGIC: (1, 1),
    Rarity.RARE: (3, 3),
    Rarity.EPIC: (3, 3),
    Rarity.LEGENDARY: (3, 3),
}

#: Распределение количества аффиксов по rarity. ``[(count, weight), ...]``.
AFFIX_COUNT_DISTRIBUTION: dict[Rarity, list[tuple[int, int]]] = {
    Rarity.COMMON: [(0, 1)],
    Rarity.MAGIC: [(1, 3), (2, 1)],          # 75% / 25%
    Rarity.RARE: [(3, 7), (4, 3)],           # 70% / 30%
    Rarity.EPIC: [(4, 6), (5, 4)],           # 60% / 40%
    Rarity.LEGENDARY: [(5, 7), (6, 3)],      # 70% / 30%
}


# ============================================================================
# Data classes
# ============================================================================


@dataclass(frozen=True, slots=True)
class AffixDefinition:
    """Snapshot из ``affix_definition`` table для in-memory rolling.

    Адаптер из SQLAlchemy-модели делается в Phase 5, тогда же
    добавляется repository.

    :ivar id: Stable slug, например ``prefix_str_t1``.
    :ivar affix_type: PREFIX / SUFFIX / IMPLICIT.
    :ivar mod_group: Группа для mutual exclusion. Все tiers одного аффикса
        делят группу. Пример: все ``life_flat_t1..t5`` → ``mod_group="life_flat"``.
    :ivar applicable_slots: Кортеж slot.value (см. EquipmentSlot enum).
    :ivar min_ilvl: Минимальный item level для появления.
    :ivar weight: Базовый вес для weighted random.
    :ivar value_min: Нижняя граница uniform-roll'а.
    :ivar value_max: Верхняя граница uniform-roll'а.
    :ivar tags: Опциональные теги для tag-based weight override (PoE-style).
    :ivar spawn_weights: Опциональный override веса по тегам base'а.
        Если задан и тег base'а есть в ключах — используется этот вес
        (leftmost tag wins).
    :ivar tier: Display-only tier для UI (T1 lowest..T5+ highest).
        Не алгоритмический gate.
    """

    id: str
    affix_type: AffixType
    mod_group: str
    applicable_slots: tuple[int, ...]
    min_ilvl: int
    weight: int
    value_min: int
    value_max: int
    tags: frozenset[str] = field(default_factory=frozenset)
    spawn_weights: dict[str, int] | None = None
    tier: int = 1


@dataclass(frozen=True, slots=True)
class RolledAffix:
    """Результат роллинга аффикса для конкретного предмета.

    :ivar affix_id: ``AffixDefinition.id``.
    :ivar value: Целое из ``[value_min, value_max]``.
    """

    affix_id: str
    value: int


@dataclass(frozen=True, slots=True)
class GeneratedItem:
    """Финальный сгенерированный предмет (сериализуется в ``items.affixes`` JSONB).

    :ivar base_id: ``ItemBase.id``.
    :ivar slot: Целевой EquipmentSlot.value.
    :ivar ilvl: Уровень предмета (равен уровню моба-дроппера).
    :ivar rarity: Rarity enum.
    :ivar affixes: Список ролов в порядке выбора (порядок имеет значение
        для отображения, не для геймплея).
    """

    base_id: str
    slot: int
    ilvl: int
    rarity: Rarity
    affixes: tuple[RolledAffix, ...]


# ============================================================================
# Algorithm
# ============================================================================


def sample_affix_count(rng: random.Random, rarity: Rarity) -> int:
    """Случайное количество аффиксов для предмета данного rarity.

    Использует распределение из :data:`AFFIX_COUNT_DISTRIBUTION`.

    :param rng: ``random.Random`` инстанс с фиксированным seed для
        детерминированности.
    :param rarity: Rarity предмета.
    :returns: Целое количество аффиксов (≥ 0).
    """
    dist = AFFIX_COUNT_DISTRIBUTION[rarity]
    counts, weights = zip(*dist, strict=True)
    return rng.choices(counts, weights=weights, k=1)[0]


def effective_weight(affix: AffixDefinition, base_tags: Iterable[str]) -> int:
    """Вычислить вес аффикса с учётом tag-based override (PoE leftmost wins).

    Если у аффикса задан ``spawn_weights`` — итерируемся по тегам base'а
    в порядке (leftmost first) и берём первый совпавший override.
    Если нет совпадений — возвращаем ``affix.weight``.

    :param affix: Определение аффикса.
    :param base_tags: Теги item base'а в порядке приоритета.
    :returns: Финальный вес для weighted random. ``0`` = аффикс не появится.
    """
    if not affix.spawn_weights:
        return affix.weight
    for tag in base_tags:
        if tag in affix.spawn_weights:
            return affix.spawn_weights[tag]
    return affix.weight


def _pick_side(
    rng: random.Random,
    prefix_count: int,
    suffix_count: int,
    max_prefix: int,
    max_suffix: int,
) -> AffixType | None:
    """Выбрать сторону (prefix/suffix) для следующего аффикса.

    50/50 бросок, с откатом на другую сторону если выпавшая исчерпана.

    :returns: AffixType.PREFIX / AffixType.SUFFIX, либо ``None`` если обе
        стороны заполнены.
    """
    prefix_full = prefix_count >= max_prefix
    suffix_full = suffix_count >= max_suffix
    if prefix_full and suffix_full:
        return None
    if prefix_full:
        return AffixType.SUFFIX
    if suffix_full:
        return AffixType.PREFIX
    return AffixType.PREFIX if rng.random() < 0.5 else AffixType.SUFFIX


def generate_affixes(
    rng: random.Random,
    *,
    rarity: Rarity,
    slot: int,
    ilvl: int,
    base_tags: Iterable[str],
    affix_pool: Iterable[AffixDefinition],
) -> tuple[RolledAffix, ...]:
    """Сгенерировать список аффиксов для предмета.

    Алгоритм PoE-style: для каждого следующего аффикса выбирается сторона
    50/50, дальше weighted random из доступного пула с учётом mod_group
    exclusion.

    :param rng: ``random.Random`` с фиксированным seed.
    :param rarity: Rarity предмета.
    :param slot: EquipmentSlot.value предмета.
    :param ilvl: Item level.
    :param base_tags: Теги item base'а (для tag-based weight override).
    :param affix_pool: Полный список доступных аффиксов (фильтрация
        по slot и ilvl делается внутри).
    :returns: Кортеж :class:`RolledAffix` в порядке выбора.
    """
    affix_count = sample_affix_count(rng, rarity)
    if affix_count == 0:
        return ()

    base_tags_tuple = tuple(base_tags)

    # Pre-filter: только аффиксы для нашего slot + ilvl
    candidates: list[AffixDefinition] = [
        a
        for a in affix_pool
        if slot in a.applicable_slots and a.min_ilvl <= ilvl
    ]

    max_prefix, max_suffix = SIDE_LIMITS[rarity]
    used_groups: set[str] = set()
    rolled: list[RolledAffix] = []
    prefix_count = 0
    suffix_count = 0

    for _ in range(affix_count):
        side = _pick_side(
            rng, prefix_count, suffix_count, max_prefix, max_suffix
        )
        if side is None:
            break

        # Отфильтровать pool: нужная сторона + не использованная mod_group
        side_pool = [
            a
            for a in candidates
            if a.affix_type == side and a.mod_group not in used_groups
        ]
        if not side_pool:
            # Сторона есть свободные слоты, но нет аффиксов под наши условия.
            # Не пробуем другую сторону — это эмерджентно балансирует rare
            # предметы (4 аффикса гарантированы только если pool достаточен).
            break

        weights = [effective_weight(a, base_tags_tuple) for a in side_pool]
        if sum(weights) == 0:
            break

        chosen = rng.choices(side_pool, weights=weights, k=1)[0]
        value = rng.randint(chosen.value_min, chosen.value_max)
        rolled.append(RolledAffix(affix_id=chosen.id, value=value))
        used_groups.add(chosen.mod_group)
        if side == AffixType.PREFIX:
            prefix_count += 1
        else:
            suffix_count += 1

    return tuple(rolled)


def generate_item(
    rng: random.Random,
    *,
    base_id: str,
    slot: int,
    ilvl: int,
    rarity: Rarity,
    base_tags: Iterable[str],
    affix_pool: Iterable[AffixDefinition],
) -> GeneratedItem:
    """High-level wrapper: rarity + base + ilvl → готовый предмет.

    Каркас под Phase 5 — приёмник для ``DropEvent`` из боя.

    :returns: :class:`GeneratedItem` готовый для сохранения в ``items``.
    """
    affixes = generate_affixes(
        rng,
        rarity=rarity,
        slot=slot,
        ilvl=ilvl,
        base_tags=base_tags,
        affix_pool=affix_pool,
    )
    return GeneratedItem(
        base_id=base_id,
        slot=slot,
        ilvl=ilvl,
        rarity=rarity,
        affixes=affixes,
    )


# ============================================================================
# Roll quality (UI helper)
# ============================================================================


def roll_quality_pct(value: int, value_min: int, value_max: int) -> int:
    """Качество ролла в процентах для UI (red/yellow/green indicator).

    Для отображения tooltip'а: ``"Strength +12 (87% roll)"``.

    :param value: Сролленное значение.
    :param value_min: Нижняя граница диапазона.
    :param value_max: Верхняя граница.
    :returns: Целое 0..100. Для ``value_min == value_max`` возвращается 100.
    """
    if value_max <= value_min:
        return 100
    pct = (value - value_min) / (value_max - value_min) * 100
    return max(0, min(100, round(pct)))

"""Seed reference-данных: ``item_base`` + ``affix_definition``.

Идемпотентный — пропускает строки которые уже существуют (по UNIQUE
constraint'ам ``uq_item_base_kind`` и ``uq_affix_def_natural``).

Запуск::

    cd backend && uv run python -m scripts.seed_reference

Содержимое — MVP-набор:

* **10 base items** покрывающих все 6 слотов (HELMET/CHEST/WEAPON/OFFHAND/BOOTS/RING)
* **~30 affixes** покрывающих основные mod_groups (flat_str/dex/int, flat_hp/mana,
  pct_atk/def, flat_phys/fire/cold_dmg, pct_resist_*) с T1-T3 для каждой группы

Это чисто placeholder-балансы для разработки; финальные значения тюнятся в W4+
при появлении реальных combat-формул.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy import select

from wotk.core.db import session_scope
from wotk.domain.enums import AffixType, EquipmentSlot
from wotk.domain.models import AffixDefinition, ItemBase

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Base items
# ---------------------------------------------------------------------------

#: 10 базовых предметов покрывающих все 6 EquipmentSlot.
#: ``base_stats`` структура зависит от слота: weapon → {min_dmg,max_dmg,as},
#: armor → {def, hp_bonus}, accessory → {hp_bonus} | etc.
BASE_ITEMS: list[dict[str, Any]] = [
    # WEAPON (one-handed)
    {
        "kind": "sword_short_iron",
        "slot": EquipmentSlot.WEAPON,
        "min_ilvl": 1,
        "base_stats": {"min_dmg": 5, "max_dmg": 9, "as": 1.2},
        "is_two_handed": False,
    },
    # WEAPON (two-handed)
    {
        "kind": "sword_2h_iron",
        "slot": EquipmentSlot.WEAPON,
        "min_ilvl": 5,
        "base_stats": {"min_dmg": 12, "max_dmg": 22, "as": 0.8},
        "is_two_handed": True,
    },
    # WEAPON (ranged 2h, для archer в постMVP)
    {
        "kind": "bow_short_oak",
        "slot": EquipmentSlot.WEAPON,
        "min_ilvl": 1,
        "base_stats": {"min_dmg": 4, "max_dmg": 11, "as": 1.4},
        "is_two_handed": True,
    },
    # OFFHAND (shield)
    {
        "kind": "buckler_iron",
        "slot": EquipmentSlot.OFFHAND,
        "min_ilvl": 1,
        "base_stats": {"def": 8, "block_pct": 15},
        "is_two_handed": False,
    },
    # HELMET
    {
        "kind": "helm_leather",
        "slot": EquipmentSlot.HELMET,
        "min_ilvl": 1,
        "base_stats": {"def": 4, "hp_bonus": 0},
        "is_two_handed": False,
    },
    {
        "kind": "helm_iron",
        "slot": EquipmentSlot.HELMET,
        "min_ilvl": 5,
        "base_stats": {"def": 10, "hp_bonus": 5},
        "is_two_handed": False,
    },
    # CHEST
    {
        "kind": "chest_leather",
        "slot": EquipmentSlot.CHEST,
        "min_ilvl": 1,
        "base_stats": {"def": 8, "hp_bonus": 0},
        "is_two_handed": False,
    },
    {
        "kind": "chest_iron",
        "slot": EquipmentSlot.CHEST,
        "min_ilvl": 5,
        "base_stats": {"def": 18, "hp_bonus": 10},
        "is_two_handed": False,
    },
    # BOOTS
    {
        "kind": "boots_leather",
        "slot": EquipmentSlot.BOOTS,
        "min_ilvl": 1,
        "base_stats": {"def": 3, "ms_pct": 5},
        "is_two_handed": False,
    },
    # RING
    {
        "kind": "ring_bronze",
        "slot": EquipmentSlot.RING,
        "min_ilvl": 1,
        "base_stats": {"hp_bonus": 5},
        "is_two_handed": False,
    },
]


# ---------------------------------------------------------------------------
# Affixes
# ---------------------------------------------------------------------------

#: Slot-наборы для частых случаев.
ALL_ARMOR = [
    EquipmentSlot.HELMET.value,
    EquipmentSlot.CHEST.value,
    EquipmentSlot.BOOTS.value,
]
WEAPON_ONLY = [EquipmentSlot.WEAPON.value]
ALL_SLOTS = [s.value for s in EquipmentSlot]


def _affix_tiers(
    *,
    mod_group: str,
    mod_type: str,
    affix_type: AffixType,
    applicable_slots: list[int],
    tags: list[str] | None = None,
    base_value: int,
    tier_step: int = 5,
    tier_ilvl_step: int = 10,
    tier_count: int = 3,
) -> list[dict[str, Any]]:
    """Сгенерировать N tier'ов одного аффикса с растущими value/min_ilvl.

    :returns: список dict'ов готовых к INSERT.
    """
    out: list[dict[str, Any]] = []
    for tier in range(1, tier_count + 1):
        vmin = base_value + (tier - 1) * tier_step
        vmax = vmin + tier_step
        out.append(
            {
                "affix_type": affix_type,
                "mod_group": mod_group,
                "min_ilvl": 1 + (tier - 1) * tier_ilvl_step,
                "tier": tier,
                "weight": 100 - (tier - 1) * 20,
                "applicable_slots": applicable_slots,
                "tags": tags or [],
                "spawn_weights": None,
                "mod_type": mod_type,
                "value_min": vmin,
                "value_max": vmax,
            }
        )
    return out


AFFIXES: list[dict[str, Any]] = [
    # Stat prefixes (могут падать на любую броню)
    *_affix_tiers(
        mod_group="flat_str",
        mod_type="flat_str",
        affix_type=AffixType.PREFIX,
        applicable_slots=ALL_ARMOR,
        tags=["str"],
        base_value=5,
    ),
    *_affix_tiers(
        mod_group="flat_dex",
        mod_type="flat_dex",
        affix_type=AffixType.PREFIX,
        applicable_slots=ALL_ARMOR,
        tags=["dex"],
        base_value=5,
    ),
    *_affix_tiers(
        mod_group="flat_int",
        mod_type="flat_int",
        affix_type=AffixType.PREFIX,
        applicable_slots=ALL_ARMOR,
        tags=["int"],
        base_value=5,
    ),
    # HP / Mana prefix
    *_affix_tiers(
        mod_group="flat_hp",
        mod_type="flat_hp",
        affix_type=AffixType.PREFIX,
        applicable_slots=ALL_SLOTS,
        tags=["life"],
        base_value=20,
        tier_step=15,
    ),
    *_affix_tiers(
        mod_group="flat_mana",
        mod_type="flat_mana",
        affix_type=AffixType.PREFIX,
        applicable_slots=ALL_ARMOR,
        tags=["mana"],
        base_value=10,
    ),
    # Weapon prefixes (% атаки, флэт-урон)
    *_affix_tiers(
        mod_group="pct_atk",
        mod_type="pct_atk",
        affix_type=AffixType.PREFIX,
        applicable_slots=WEAPON_ONLY,
        tags=["damage"],
        base_value=10,
        tier_step=10,
    ),
    *_affix_tiers(
        mod_group="flat_phys_dmg",
        mod_type="flat_phys_dmg",
        affix_type=AffixType.PREFIX,
        applicable_slots=WEAPON_ONLY,
        tags=["physical", "damage"],
        base_value=3,
    ),
    # Suffixes
    *_affix_tiers(
        mod_group="pct_def",
        mod_type="pct_def",
        affix_type=AffixType.SUFFIX,
        applicable_slots=ALL_ARMOR,
        tags=["defense"],
        base_value=10,
    ),
    *_affix_tiers(
        mod_group="pct_crit",
        mod_type="pct_crit",
        affix_type=AffixType.SUFFIX,
        applicable_slots=WEAPON_ONLY,
        tags=["crit"],
        base_value=5,
    ),
    *_affix_tiers(
        mod_group="pct_resist_fire",
        mod_type="pct_resist_fire",
        affix_type=AffixType.SUFFIX,
        applicable_slots=ALL_ARMOR,
        tags=["resistance", "fire"],
        base_value=10,
    ),
    *_affix_tiers(
        mod_group="pct_resist_cold",
        mod_type="pct_resist_cold",
        affix_type=AffixType.SUFFIX,
        applicable_slots=ALL_ARMOR,
        tags=["resistance", "cold"],
        base_value=10,
    ),
]


async def seed_item_bases() -> tuple[int, int]:
    """Идемпотентно вставить :data:`BASE_ITEMS` в ``item_base``.

    :returns: ``(inserted_count, skipped_count)``.
    """
    inserted = 0
    skipped = 0
    async with session_scope() as session:
        existing = {
            row[0]
            for row in (
                await session.execute(select(ItemBase.kind))
            ).all()
        }
        for spec in BASE_ITEMS:
            if spec["kind"] in existing:
                skipped += 1
                continue
            session.add(ItemBase(**spec))
            inserted += 1
    return inserted, skipped


async def seed_affixes() -> tuple[int, int]:
    """Идемпотентно вставить :data:`AFFIXES` в ``affix_definition``.

    Проверяет натуральный ключ ``(mod_group, mod_type, tier)``.

    :returns: ``(inserted_count, skipped_count)``.
    """
    inserted = 0
    skipped = 0
    async with session_scope() as session:
        existing = {
            (row[0], row[1], row[2])
            for row in (
                await session.execute(
                    select(
                        AffixDefinition.mod_group,
                        AffixDefinition.mod_type,
                        AffixDefinition.tier,
                    )
                )
            ).all()
        }
        for spec in AFFIXES:
            key = (spec["mod_group"], spec["mod_type"], spec["tier"])
            if key in existing:
                skipped += 1
                continue
            session.add(AffixDefinition(**spec))
            inserted += 1
    return inserted, skipped


async def main() -> None:
    """CLI entry: засеить bases + affixes, залогировать summary."""
    bases_in, bases_skip = await seed_item_bases()
    affs_in, affs_skip = await seed_affixes()
    log.info(
        "seed_reference_done",
        bases_inserted=bases_in,
        bases_skipped=bases_skip,
        affixes_inserted=affs_in,
        affixes_skipped=affs_skip,
    )
    print(
        f"item_base: +{bases_in} (skipped {bases_skip}); "
        f"affix_definition: +{affs_in} (skipped {affs_skip})"
    )


if __name__ == "__main__":
    asyncio.run(main())

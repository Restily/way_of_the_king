"""Интеграционные тесты §6 моделей: ItemBase + AffixDefinition + Item."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.domain.enums import AffixType, EquipmentSlot, HeroClass, Rarity
from wotk.domain.models import (
    AffixDefinition,
    Hero,
    Item,
    ItemBase,
    Profile,
)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


async def _make_profile(session: AsyncSession, *, telegram_id: int) -> Profile:
    p = Profile(telegram_id=telegram_id)
    session.add(p)
    await session.flush()
    return p


async def _make_hero(session: AsyncSession, profile: Profile) -> Hero:
    h = Hero(profile_id=profile.id, hero_class=HeroClass.KNIGHT, name="TestHero")
    session.add(h)
    await session.flush()
    return h


async def _make_base(
    session: AsyncSession, *, kind: str, slot: EquipmentSlot = EquipmentSlot.WEAPON
) -> ItemBase:
    b = ItemBase(
        kind=kind, slot=slot, min_ilvl=1, base_stats={"min_dmg": 5, "max_dmg": 10}
    )
    session.add(b)
    await session.flush()
    return b


# ---------------------------------------------------------------------------
# ItemBase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_item_base_unique_kind(db_session: AsyncSession) -> None:
    await _make_base(db_session, kind="sword_short_iron")
    db_session.add(
        ItemBase(
            kind="sword_short_iron",
            slot=EquipmentSlot.WEAPON,
            base_stats={"min_dmg": 1, "max_dmg": 2},
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_item_base_slot_check(db_session: AsyncSession) -> None:
    """Слот вне диапазона enum → IntegrityError."""
    from sqlalchemy import text

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO item_base (kind, slot, min_ilvl, base_stats) "
                "VALUES ('cheat', 99, 1, '{}'::jsonb)"
            )
        )
        await db_session.flush()


# ---------------------------------------------------------------------------
# AffixDefinition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_affix_def_unique_natural_key(db_session: AsyncSession) -> None:
    db_session.add(
        AffixDefinition(
            affix_type=AffixType.PREFIX,
            mod_group="flat_str",
            tier=1,
            applicable_slots=[EquipmentSlot.HELMET.value],
            mod_type="flat_str",
            value_min=1,
            value_max=5,
        )
    )
    await db_session.flush()
    db_session.add(
        AffixDefinition(
            affix_type=AffixType.PREFIX,
            mod_group="flat_str",
            tier=1,  # тот же tier + mod_group + mod_type → конфликт
            applicable_slots=[EquipmentSlot.CHEST.value],
            mod_type="flat_str",
            value_min=10,
            value_max=20,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_affix_def_value_range_check(db_session: AsyncSession) -> None:
    db_session.add(
        AffixDefinition(
            affix_type=AffixType.SUFFIX,
            mod_group="g",
            tier=1,
            applicable_slots=[0],
            mod_type="m",
            value_min=10,
            value_max=5,  # max < min — fail
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_affix_def_weight_must_be_positive(db_session: AsyncSession) -> None:
    db_session.add(
        AffixDefinition(
            affix_type=AffixType.PREFIX,
            mod_group="g",
            tier=1,
            weight=0,  # > 0 required
            applicable_slots=[0],
            mod_type="m",
            value_min=1,
            value_max=2,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_item_create_orphaned(db_session: AsyncSession) -> None:
    profile = await _make_profile(db_session, telegram_id=70001)
    base = await _make_base(db_session, kind="sword_a")

    item = Item(
        owner_profile_id=profile.id,
        base_id=base.id,
        rarity=Rarity.COMMON,
        ilvl=1,
    )
    db_session.add(item)
    await db_session.flush()

    fetched = await db_session.scalar(select(Item).where(Item.id == item.id))
    assert fetched is not None
    assert fetched.affixes == []
    assert fetched.equipped_on is None
    assert fetched.inventory_position is None


@pytest.mark.asyncio
async def test_item_equip_pair_constraint(db_session: AsyncSession) -> None:
    """equipped_on без equipped_slot — fail; и наоборот."""
    profile = await _make_profile(db_session, telegram_id=70002)
    hero = await _make_hero(db_session, profile)
    base = await _make_base(db_session, kind="sword_b")

    item = Item(
        owner_profile_id=profile.id,
        base_id=base.id,
        rarity=Rarity.COMMON,
        ilvl=1,
        equipped_on=hero.id,
        # equipped_slot НЕ задан — должно упасть
    )
    db_session.add(item)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_item_state_exclusive(db_session: AsyncSession) -> None:
    """Item не может быть одновременно в инвентаре И equipped."""
    profile = await _make_profile(db_session, telegram_id=70003)
    hero = await _make_hero(db_session, profile)
    base = await _make_base(db_session, kind="sword_c")

    item = Item(
        owner_profile_id=profile.id,
        base_id=base.id,
        rarity=Rarity.COMMON,
        ilvl=1,
        equipped_on=hero.id,
        equipped_slot=EquipmentSlot.WEAPON,
        inventory_position=0,  # одновременно equipped и в инвентаре — fail
    )
    db_session.add(item)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_item_one_per_equip_slot(db_session: AsyncSession) -> None:
    """Два item'а в одном слоте у одного героя → fail."""
    profile = await _make_profile(db_session, telegram_id=70004)
    hero = await _make_hero(db_session, profile)
    base = await _make_base(db_session, kind="sword_d")

    item1 = Item(
        owner_profile_id=profile.id,
        base_id=base.id,
        rarity=Rarity.COMMON,
        ilvl=1,
        equipped_on=hero.id,
        equipped_slot=EquipmentSlot.WEAPON,
    )
    db_session.add(item1)
    await db_session.flush()

    item2 = Item(
        owner_profile_id=profile.id,
        base_id=base.id,
        rarity=Rarity.MAGIC,
        ilvl=1,
        equipped_on=hero.id,
        equipped_slot=EquipmentSlot.WEAPON,  # тот же слот — fail
    )
    db_session.add(item2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_item_one_per_inventory_position(db_session: AsyncSession) -> None:
    profile = await _make_profile(db_session, telegram_id=70005)
    base = await _make_base(db_session, kind="sword_e")

    item1 = Item(
        owner_profile_id=profile.id,
        base_id=base.id,
        rarity=Rarity.COMMON,
        ilvl=1,
        inventory_position=5,
    )
    db_session.add(item1)
    await db_session.flush()

    item2 = Item(
        owner_profile_id=profile.id,
        base_id=base.id,
        rarity=Rarity.COMMON,
        ilvl=1,
        inventory_position=5,  # тот же owner + та же ячейка — fail
    )
    db_session.add(item2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_item_inventory_position_range(db_session: AsyncSession) -> None:
    profile = await _make_profile(db_session, telegram_id=70006)
    base = await _make_base(db_session, kind="sword_f")

    item = Item(
        owner_profile_id=profile.id,
        base_id=base.id,
        rarity=Rarity.COMMON,
        ilvl=1,
        inventory_position=48,  # MVP cap = 47
    )
    db_session.add(item)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_item_affixes_jsonb_snapshot_shape(db_session: AsyncSession) -> None:
    """affixes JSONB сохраняет полный snapshot и читается обратно."""
    profile = await _make_profile(db_session, telegram_id=70007)
    base = await _make_base(db_session, kind="sword_g")

    snapshot = [
        {"id": 42, "value": 15, "t": 3, "vmin": 10, "vmax": 20},
        {"id": 99, "value": 7, "t": 1, "vmin": 5, "vmax": 10},
    ]
    item = Item(
        owner_profile_id=profile.id,
        base_id=base.id,
        rarity=Rarity.RARE,
        ilvl=20,
        affixes=snapshot,
    )
    db_session.add(item)
    await db_session.flush()

    fetched = await db_session.scalar(select(Item).where(Item.id == item.id))
    assert fetched is not None
    assert fetched.affixes == snapshot

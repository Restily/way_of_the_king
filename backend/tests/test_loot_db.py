"""Тесты адаптера :mod:`wotk.game.loot_db` (DB ↔ pure loot.py)."""

from __future__ import annotations

import random

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.domain.enums import AffixType, EquipmentSlot, HeroClass, Rarity
from wotk.domain.models import (
    AffixDefinition as AffixDefinitionRow,
)
from wotk.domain.models import (
    Hero,
    Item,
    ItemBase,
    Profile,
)
from wotk.game.loot import generate_item
from wotk.game.loot_db import load_affix_pool, materialize_item


async def _seed_minimal(session: AsyncSession) -> tuple[Profile, ItemBase]:
    """Создать profile + 1 item_base + 6 affix_definition (3 prefix + 3 suffix)."""
    profile = Profile(telegram_id=72001)
    session.add(profile)
    base = ItemBase(
        kind="test_sword",
        slot=EquipmentSlot.WEAPON,
        min_ilvl=1,
        base_stats={"min_dmg": 5, "max_dmg": 10},
    )
    session.add(base)
    await session.flush()

    weapon = EquipmentSlot.WEAPON.value
    affixes = [
        AffixDefinitionRow(
            affix_type=AffixType.PREFIX,
            mod_group=f"prefix_{i}",
            tier=1,
            weight=100,
            applicable_slots=[weapon],
            mod_type=f"prefix_mod_{i}",
            value_min=10,
            value_max=20,
            min_ilvl=1,
        )
        for i in range(3)
    ] + [
        AffixDefinitionRow(
            affix_type=AffixType.SUFFIX,
            mod_group=f"suffix_{i}",
            tier=1,
            weight=100,
            applicable_slots=[weapon],
            mod_type=f"suffix_mod_{i}",
            value_min=5,
            value_max=15,
            min_ilvl=1,
        )
        for i in range(3)
    ]
    session.add_all(affixes)
    # Также один аффикс с min_ilvl=50 — для теста ilvl-фильтра
    session.add(
        AffixDefinitionRow(
            affix_type=AffixType.PREFIX,
            mod_group="high_tier_only",
            tier=5,
            weight=100,
            applicable_slots=[weapon],
            mod_type="high_tier_mod",
            value_min=100,
            value_max=200,
            min_ilvl=50,
        )
    )
    await session.flush()
    return profile, base


@pytest.mark.asyncio
async def test_load_affix_pool_filters_by_slot(db_session: AsyncSession) -> None:
    await _seed_minimal(db_session)
    # WEAPON pool — 7 аффиксов (включая high-tier на ilvl 100)
    pool = await load_affix_pool(
        db_session, slot=EquipmentSlot.WEAPON.value, ilvl=100
    )
    assert len(pool) == 7
    # HELMET pool — 0 (никто из засеянных не applicable)
    pool_helmet = await load_affix_pool(
        db_session, slot=EquipmentSlot.HELMET.value, ilvl=100
    )
    assert pool_helmet == ()


@pytest.mark.asyncio
async def test_load_affix_pool_filters_by_ilvl(db_session: AsyncSession) -> None:
    await _seed_minimal(db_session)
    # ilvl=10 → high-tier (min_ilvl=50) исключён
    pool = await load_affix_pool(
        db_session, slot=EquipmentSlot.WEAPON.value, ilvl=10
    )
    assert len(pool) == 6
    assert all(a.min_ilvl <= 10 for a in pool)


@pytest.mark.asyncio
async def test_materialize_item_writes_snapshot(db_session: AsyncSession) -> None:
    profile, base = await _seed_minimal(db_session)
    pool = await load_affix_pool(
        db_session, slot=EquipmentSlot.WEAPON.value, ilvl=10
    )
    rng = random.Random(42)
    generated = generate_item(
        rng,
        base_id=base.id,
        slot=EquipmentSlot.WEAPON.value,
        ilvl=10,
        rarity=Rarity.RARE,  # 3-4 affixes per loot.py distribution
        base_tags=["sword"],
        affix_pool=pool,
    )

    item = await materialize_item(
        db_session,
        generated=generated,
        pool=pool,
        owner_profile_id=profile.id,
    )

    assert item.id is not None
    assert item.rarity == Rarity.RARE
    assert item.ilvl == 10
    assert item.base_id == base.id
    assert item.escrow_run_id is None
    assert len(item.affixes) == len(generated.affixes)
    # Snapshot теперь включает mod_type — нужен для hero_stats без JOIN.
    for snap in item.affixes:
        assert set(snap.keys()) == {"id", "value", "t", "vmin", "vmax", "mod_type"}
        assert snap["vmin"] <= snap["value"] <= snap["vmax"]
        assert isinstance(snap["mod_type"], str)


@pytest.mark.asyncio
async def test_materialize_item_with_escrow_run_id(
    db_session: AsyncSession,
) -> None:
    """escrow_run_id выставляется при materialize в активном ране.

    После миграции 0008 ``item.escrow_run_id`` имеет FK к ``dungeon_runs``,
    поэтому нужен реальный run, не fake UUID.
    """
    import secrets as _secrets
    from datetime import UTC as _UTC
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from wotk.domain.enums import Difficulty, DungeonTheme, HeroClass
    from wotk.domain.models import Dungeon, DungeonRun, Hero

    profile, base = await _seed_minimal(db_session)
    hero = Hero(profile_id=profile.id, hero_class=HeroClass.KNIGHT, name="Esc")
    db_session.add(hero)
    dungeon = Dungeon(
        id="loot_test_d",
        name_key="x",
        theme=DungeonTheme.CRYPT,
        difficulty=Difficulty.NORMAL,
        entry_cost_gold=100,
        config={"v": 1},
        xp_base=10,
        gold_base=10,
    )
    db_session.add(dungeon)
    await db_session.flush()
    run = DungeonRun(
        profile_id=profile.id,
        hero_id=hero.id,
        dungeon_id=dungeon.id,
        seed=_secrets.token_bytes(32),
        hero_state={"hp": 100},
        entry_paid_gold=100,
        entry_paid_energy=10,
        expires_at=_dt.now(_UTC) + _td(hours=1),
    )
    db_session.add(run)
    await db_session.flush()

    pool = await load_affix_pool(
        db_session, slot=EquipmentSlot.WEAPON.value, ilvl=5
    )
    rng = random.Random(0)
    generated = generate_item(
        rng,
        base_id=base.id,
        slot=EquipmentSlot.WEAPON.value,
        ilvl=5,
        rarity=Rarity.MAGIC,
        base_tags=["sword"],
        affix_pool=pool,
    )
    item = await materialize_item(
        db_session,
        generated=generated,
        pool=pool,
        owner_profile_id=profile.id,
        escrow_run_id=run.id,
    )
    assert item.escrow_run_id == run.id
    assert item.equipped_on is None
    assert item.inventory_position is None


@pytest.mark.asyncio
async def test_materialize_common_no_affixes(db_session: AsyncSession) -> None:
    """COMMON rarity → 0 аффиксов (per AFFIX_COUNT_DISTRIBUTION в loot.py)."""
    profile, base = await _seed_minimal(db_session)
    pool = await load_affix_pool(
        db_session, slot=EquipmentSlot.WEAPON.value, ilvl=5
    )
    rng = random.Random(1)
    generated = generate_item(
        rng,
        base_id=base.id,
        slot=EquipmentSlot.WEAPON.value,
        ilvl=5,
        rarity=Rarity.COMMON,
        base_tags=["sword"],
        affix_pool=pool,
    )
    item = await materialize_item(
        db_session, generated=generated, pool=pool, owner_profile_id=profile.id
    )
    assert item.affixes == []


# Suppress unused warnings (Hero/HeroClass might be used by future tests).
_ = (Hero, HeroClass, Item)

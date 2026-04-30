"""Тесты hero_stats.compute_hero_combat_stats и /me/combat-stats endpoint."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.domain.enums import EquipmentSlot, Rarity
from wotk.domain.models import Hero, Item, ItemBase, Profile
from wotk.game.hero_stats import EquippedItemSnapshot, compute_hero_combat_stats

from ._helpers import login_e2e


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


def test_naked_hero_baseline_stats() -> None:
    """Без equipment — только base_stats + level scaling.

    ATK = 0 без оружия (per stats.py формула: avg_weapon_dmg × (1+str×0.02))
    — это by-design: голый Knight не наносит урона без оружия.
    """
    s = compute_hero_combat_stats(
        base_stats={"str": 10, "dex": 5, "int": 3},
        level=1,
        equipped=[],
    )
    assert s.hp > 0
    assert s.atk == 0  # без оружия
    assert s.crit_chance_pct > 0


def test_equipped_weapon_increases_atk() -> None:
    """Weapon с min_dmg/max_dmg → atk выше чем у naked."""
    naked = compute_hero_combat_stats(
        base_stats={"str": 10, "dex": 5, "int": 3},
        level=1,
        equipped=[],
    )
    geared = compute_hero_combat_stats(
        base_stats={"str": 10, "dex": 5, "int": 3},
        level=1,
        equipped=[
            EquippedItemSnapshot(
                slot=EquipmentSlot.WEAPON.value,
                base_stats={"min_dmg": 50, "max_dmg": 100, "as": 1.0},
                affixes=[],
            )
        ],
    )
    assert geared.atk > naked.atk


def test_equipped_armor_increases_def() -> None:
    geared = compute_hero_combat_stats(
        base_stats={"str": 10, "dex": 5, "int": 3},
        level=1,
        equipped=[
            EquippedItemSnapshot(
                slot=EquipmentSlot.CHEST.value,
                base_stats={"def": 25, "hp_bonus": 10},
                affixes=[],
            )
        ],
    )
    assert geared.def_ >= 25


def test_flat_str_affix_adds_to_str_then_to_derived() -> None:
    """flat_str affix +20 → str становится 30 → влияет на HP/ATK."""
    naked = compute_hero_combat_stats(
        base_stats={"str": 10, "dex": 5, "int": 3},
        level=1,
        equipped=[],
    )
    with_str = compute_hero_combat_stats(
        base_stats={"str": 10, "dex": 5, "int": 3},
        level=1,
        equipped=[
            EquippedItemSnapshot(
                slot=EquipmentSlot.HELMET.value,
                base_stats={},
                affixes=[
                    {
                        "id": 1,
                        "value": 20,
                        "t": 1,
                        "vmin": 15,
                        "vmax": 25,
                        "mod_type": "flat_str",
                    }
                ],
            )
        ],
    )
    assert with_str.hp > naked.hp


def test_pct_atk_affix_multiplies_atk() -> None:
    base_eq = [
        EquippedItemSnapshot(
            slot=EquipmentSlot.WEAPON.value,
            base_stats={"min_dmg": 10, "max_dmg": 20, "as": 1.0},
            affixes=[],
        )
    ]
    no_pct = compute_hero_combat_stats(
        base_stats={"str": 10, "dex": 5, "int": 3},
        level=1,
        equipped=base_eq,
    )
    pct50 = compute_hero_combat_stats(
        base_stats={"str": 10, "dex": 5, "int": 3},
        level=1,
        equipped=[
            EquippedItemSnapshot(
                slot=EquipmentSlot.WEAPON.value,
                base_stats={"min_dmg": 10, "max_dmg": 20, "as": 1.0},
                affixes=[
                    {
                        "id": 2,
                        "value": 50,
                        "t": 1,
                        "vmin": 40,
                        "vmax": 60,
                        "mod_type": "pct_atk",
                    }
                ],
            )
        ],
    )
    # +50% atk
    assert pct50.atk > int(no_pct.atk * 1.4)


def test_resist_fire_affix() -> None:
    geared = compute_hero_combat_stats(
        base_stats={"str": 10, "dex": 5, "int": 3},
        level=1,
        equipped=[
            EquippedItemSnapshot(
                slot=EquipmentSlot.CHEST.value,
                base_stats={"def": 5},
                affixes=[
                    {
                        "id": 3,
                        "value": 30,
                        "t": 1,
                        "vmin": 20,
                        "vmax": 40,
                        "mod_type": "pct_resist_fire",
                    }
                ],
            )
        ],
    )
    assert geared.resist_fire_pct >= 30


def test_unknown_mod_type_ignored() -> None:
    """Affix без распознанного mod_type не падает."""
    s = compute_hero_combat_stats(
        base_stats={"str": 10, "dex": 5, "int": 3},
        level=1,
        equipped=[
            EquippedItemSnapshot(
                slot=EquipmentSlot.RING.value,
                base_stats={},
                affixes=[
                    {
                        "id": 99,
                        "value": 100,
                        "mod_type": "unknown_future_mod",
                    }
                ],
            )
        ],
    )
    assert s.hp > 0  # didn't crash on unknown mod_type


# ---------------------------------------------------------------------------
# /me/combat-stats endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_combat_stats_endpoint_no_hero(client: AsyncClient) -> None:
    access = await login_e2e(client, telegram_id=85001)
    r = await client.get(
        "/api/v1/me/combat-stats",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "hero_not_created"


@pytest.mark.asyncio
async def test_combat_stats_endpoint_naked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access = await login_e2e(client, telegram_id=85002)
    # Create hero
    await client.post(
        "/api/v1/heroes",
        json={"name": "Knight"},
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    r = await client.get(
        "/api/v1/me/combat-stats",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["hp"] > 0
    # Naked = no weapon → atk == 0 (by formula)
    assert data["atk"] == 0
    assert "crit_chance_pct" in data


@pytest.mark.asyncio
async def test_combat_stats_endpoint_with_equipped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access = await login_e2e(client, telegram_id=85003)
    await client.post(
        "/api/v1/heroes",
        json={"name": "Knight2"},
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )

    # Manually create item_base + equipped item
    profile = await db_session.scalar(
        select(Profile).where(Profile.telegram_id == 85003)
    )
    assert profile is not None
    hero = await db_session.scalar(
        select(Hero).where(Hero.profile_id == profile.id)
    )
    assert hero is not None

    base = ItemBase(
        kind="big_sword",
        slot=EquipmentSlot.WEAPON,
        base_stats={"min_dmg": 100, "max_dmg": 200, "as": 1.0},
    )
    db_session.add(base)
    await db_session.flush()
    item = Item(
        owner_profile_id=profile.id,
        base_id=base.id,
        rarity=Rarity.RARE,
        ilvl=10,
        equipped_on=hero.id,
        equipped_slot=EquipmentSlot.WEAPON,
    )
    db_session.add(item)
    await db_session.commit()

    r = await client.get(
        "/api/v1/me/combat-stats",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200
    # ATK с weapon 100-200 значительно выше baseline
    assert r.json()["atk"] >= 100

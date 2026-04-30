"""Тесты inventory endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.domain.enums import EquipmentSlot, Rarity
from wotk.domain.models import Hero, Item, ItemBase, Profile

from ._helpers import login_e2e


async def _setup_user(
    client: AsyncClient, db_session: AsyncSession, *, telegram_id: int
) -> tuple[str, int, int]:
    """Login + create hero. Returns (access_token, profile_id, hero_id)."""
    access = await login_e2e(client, telegram_id=telegram_id)
    headers = {"Authorization": f"Bearer {access}"}
    r = await client.post(
        "/api/v1/heroes",
        json={"name": "InvKnight"},
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201
    profile = await db_session.scalar(
        select(Profile).where(Profile.telegram_id == telegram_id)
    )
    assert profile is not None
    hero = await db_session.scalar(
        select(Hero).where(Hero.profile_id == profile.id)
    )
    assert hero is not None
    return access, profile.id, hero.id


async def _make_base(
    db_session: AsyncSession, *, kind: str, slot: EquipmentSlot
) -> int:
    base = ItemBase(
        kind=kind, slot=slot, base_stats={"min_dmg": 1, "max_dmg": 2}
    )
    db_session.add(base)
    await db_session.commit()
    return base.id


async def _put_in_inventory(
    db_session: AsyncSession,
    *,
    profile_id: int,
    base_id: int,
    position: int,
    rarity: Rarity = Rarity.COMMON,
) -> int:
    item = Item(
        owner_profile_id=profile_id,
        base_id=base_id,
        rarity=rarity,
        ilvl=1,
        inventory_position=position,
    )
    db_session.add(item)
    await db_session.commit()
    return item.id


# ---------------------------------------------------------------------------
# GET /inventory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_inventory_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/api/v1/inventory")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_inventory_empty(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, _, _ = await _setup_user(client, db_session, telegram_id=84001)
    r = await client.get(
        "/api/v1/inventory", headers={"Authorization": f"Bearer {access}"}
    )
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_get_inventory_with_items(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, profile_id, _ = await _setup_user(
        client, db_session, telegram_id=84002
    )
    base_id = await _make_base(db_session, kind="b1", slot=EquipmentSlot.WEAPON)
    item_id = await _put_in_inventory(
        db_session, profile_id=profile_id, base_id=base_id, position=0
    )

    r = await client.get(
        "/api/v1/inventory", headers={"Authorization": f"Bearer {access}"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == item_id
    assert data["items"][0]["base_kind"] == "b1"


@pytest.mark.asyncio
async def test_get_inventory_filters_by_slot(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, profile_id, _ = await _setup_user(
        client, db_session, telegram_id=84003
    )
    weapon_id = await _make_base(db_session, kind="w", slot=EquipmentSlot.WEAPON)
    helm_id = await _make_base(db_session, kind="h", slot=EquipmentSlot.HELMET)
    await _put_in_inventory(
        db_session, profile_id=profile_id, base_id=weapon_id, position=0
    )
    await _put_in_inventory(
        db_session, profile_id=profile_id, base_id=helm_id, position=1
    )

    r = await client.get(
        f"/api/v1/inventory?slot={EquipmentSlot.WEAPON.value}",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["base_kind"] == "w"


# ---------------------------------------------------------------------------
# POST /items/{id}/equip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_equip_basic(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, profile_id, hero_id = await _setup_user(
        client, db_session, telegram_id=84010
    )
    base_id = await _make_base(db_session, kind="sword", slot=EquipmentSlot.WEAPON)
    item_id = await _put_in_inventory(
        db_session, profile_id=profile_id, base_id=base_id, position=5
    )

    r = await client.post(
        f"/api/v1/items/{item_id}/equip",
        json={"slot": EquipmentSlot.WEAPON.value},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["equipped_on"] == hero_id
    assert data["equipped_slot"] == EquipmentSlot.WEAPON.value
    assert data["inventory_position"] is None


@pytest.mark.asyncio
async def test_equip_slot_mismatch_returns_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, profile_id, _ = await _setup_user(
        client, db_session, telegram_id=84011
    )
    base_id = await _make_base(db_session, kind="helm", slot=EquipmentSlot.HELMET)
    item_id = await _put_in_inventory(
        db_session, profile_id=profile_id, base_id=base_id, position=0
    )

    r = await client.post(
        f"/api/v1/items/{item_id}/equip",
        json={"slot": EquipmentSlot.WEAPON.value},  # mismatch
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "slot_mismatch"


@pytest.mark.asyncio
async def test_equip_swaps_existing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Equip второго item'а в занятый слот → swap (первый ушёл в inventory)."""
    access, profile_id, hero_id = await _setup_user(
        client, db_session, telegram_id=84012
    )
    base_id = await _make_base(db_session, kind="sw", slot=EquipmentSlot.WEAPON)
    item1_id = await _put_in_inventory(
        db_session, profile_id=profile_id, base_id=base_id, position=0
    )
    item2_id = await _put_in_inventory(
        db_session, profile_id=profile_id, base_id=base_id, position=1, rarity=Rarity.RARE
    )

    # Equip item1
    r1 = await client.post(
        f"/api/v1/items/{item1_id}/equip",
        json={"slot": EquipmentSlot.WEAPON.value},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r1.status_code == 200
    assert r1.json()["equipped_on"] == hero_id

    # Equip item2 (swap)
    r2 = await client.post(
        f"/api/v1/items/{item2_id}/equip",
        json={"slot": EquipmentSlot.WEAPON.value},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r2.status_code == 200
    assert r2.json()["equipped_on"] == hero_id

    # Verify item1 теперь в inventory
    inv = await client.get(
        "/api/v1/inventory", headers={"Authorization": f"Bearer {access}"}
    )
    items = {it["id"]: it for it in inv.json()["items"]}
    assert items[item1_id]["equipped_on"] is None
    assert items[item1_id]["inventory_position"] is not None
    assert items[item2_id]["equipped_on"] == hero_id


@pytest.mark.asyncio
async def test_equip_not_owner_returns_403(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, profile_a_id, _ = await _setup_user(
        client, db_session, telegram_id=84013
    )
    access_b = await login_e2e(client, telegram_id=84014)
    base_id = await _make_base(db_session, kind="sw2", slot=EquipmentSlot.WEAPON)
    item_id = await _put_in_inventory(
        db_session, profile_id=profile_a_id, base_id=base_id, position=0
    )

    r = await client.post(
        f"/api/v1/items/{item_id}/equip",
        json={"slot": EquipmentSlot.WEAPON.value},
        headers={"Authorization": f"Bearer {access_b}"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /items/{id}/unequip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unequip_basic(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, profile_id, hero_id = await _setup_user(
        client, db_session, telegram_id=84020
    )
    base_id = await _make_base(db_session, kind="sw3", slot=EquipmentSlot.WEAPON)
    item_id = await _put_in_inventory(
        db_session, profile_id=profile_id, base_id=base_id, position=10
    )
    # Equip first
    await client.post(
        f"/api/v1/items/{item_id}/equip",
        json={"slot": EquipmentSlot.WEAPON.value},
        headers={"Authorization": f"Bearer {access}"},
    )
    # Now unequip
    r = await client.post(
        f"/api/v1/items/{item_id}/unequip",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["equipped_on"] is None
    assert data["inventory_position"] is not None


@pytest.mark.asyncio
async def test_unequip_not_equipped_returns_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, profile_id, _ = await _setup_user(
        client, db_session, telegram_id=84021
    )
    base_id = await _make_base(db_session, kind="sw4", slot=EquipmentSlot.WEAPON)
    item_id = await _put_in_inventory(
        db_session, profile_id=profile_id, base_id=base_id, position=0
    )
    # Item не надет → unequip → 409
    r = await client.post(
        f"/api/v1/items/{item_id}/unequip",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "item_not_equipped"


@pytest.mark.asyncio
async def test_unequip_inventory_full(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Inventory заполнен 48 items → unequip → 409."""
    access, profile_id, _ = await _setup_user(
        client, db_session, telegram_id=84022
    )
    base_id = await _make_base(db_session, kind="sw5", slot=EquipmentSlot.WEAPON)
    # Equip первый item
    eq_item_id = await _put_in_inventory(
        db_session, profile_id=profile_id, base_id=base_id, position=0
    )
    await client.post(
        f"/api/v1/items/{eq_item_id}/equip",
        json={"slot": EquipmentSlot.WEAPON.value},
        headers={"Authorization": f"Bearer {access}"},
    )
    # Заполняем все 48 ячеек
    for pos in range(48):
        await _put_in_inventory(
            db_session, profile_id=profile_id, base_id=base_id, position=pos
        )
    # Try unequip — некуда положить
    r = await client.post(
        f"/api/v1/items/{eq_item_id}/unequip",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "inventory_full"

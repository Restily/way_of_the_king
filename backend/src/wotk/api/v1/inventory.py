"""Inventory endpoints: GET /inventory + POST /items/{id}/equip + POST /items/{id}/unequip."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.api.deps import current_profile, find_first_free_inventory_slot, load_active_hero
from wotk.core.db import get_session
from wotk.domain.enums import EquipmentSlot
from wotk.domain.models import Item, ItemBase, Profile

log = structlog.get_logger()
router = APIRouter(tags=["inventory"])


ERR_ITEM_NOT_FOUND = "item_not_found"
ERR_ITEM_NOT_OWNER = "item_not_owner"
ERR_NOT_IN_INVENTORY = "item_not_in_inventory"
ERR_NOT_EQUIPPED = "item_not_equipped"
ERR_NO_HERO = "hero_not_created"
ERR_SLOT_MISMATCH = "slot_mismatch"
ERR_INVENTORY_FULL = "inventory_full"


class ItemDTO(BaseModel):
    """Item для UI с denormalized base_kind (joined)."""

    id: int
    base_id: int
    base_kind: str
    base_slot: int
    rarity: int
    ilvl: int
    affixes: list[dict]
    equipped_on: int | None
    equipped_slot: int | None
    inventory_position: int | None


class InventoryResponse(BaseModel):
    items: list[ItemDTO]
    total: int


class EquipRequest(BaseModel):
    slot: int = Field(ge=0, le=5)


# ---------------------------------------------------------------------------
# GET /inventory
# ---------------------------------------------------------------------------


@router.get("/inventory", response_model=InventoryResponse)
async def get_inventory(
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
    offset: int = 0,
    slot: int | None = None,
    rarity_min: int | None = None,
) -> InventoryResponse:
    """Список items юзера (включает equipped + inventory; исключает escrow).

    Сортировка: rarity DESC, ilvl DESC.

    :param limit: 1..200.
    :param offset: 0+.
    :param slot: Если задан — фильтр по item_base.slot.
    :param rarity_min: Если задан — рарность >= rarity_min.
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    stmt = (
        select(Item, ItemBase.kind, ItemBase.slot)
        .join(ItemBase, Item.base_id == ItemBase.id)
        .where(
            Item.owner_profile_id == profile.id,
            Item.is_in_market_escrow.is_(False),
            Item.escrow_run_id.is_(None),
        )
    )
    if slot is not None:
        stmt = stmt.where(ItemBase.slot == slot)
    if rarity_min is not None:
        stmt = stmt.where(Item.rarity >= rarity_min)
    stmt = stmt.order_by(Item.rarity.desc(), Item.ilvl.desc()).limit(limit).offset(offset)

    rows = (await session.execute(stmt)).all()
    items = [
        _to_dto(item, base_kind=base_kind, base_slot=int(base_slot))
        for item, base_kind, base_slot in rows
    ]
    return InventoryResponse(items=items, total=len(items))


# ---------------------------------------------------------------------------
# POST /items/{id}/equip
# ---------------------------------------------------------------------------


@router.post("/items/{item_id}/equip", response_model=ItemDTO)
async def equip_item(
    item_id: int,
    body: EquipRequest,
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
) -> ItemDTO:
    """Надеть item на hero в указанный slot.

    Семантика:

    1. Verify ownership.
    2. Item должен быть в inventory (``inventory_position IS NOT NULL``).
    3. Slot должен совпадать с ``item_base.slot``.
    4. Если в этом slot'е что-то надето — снять (положить в первую free ячейку).
    5. Set ``equipped_on=hero.id``, ``equipped_slot=body.slot``, ``inventory_position=NULL``.

    Под FOR UPDATE на item — concurrent equip не race'ится.
    """
    item = await session.scalar(
        select(Item).where(Item.id == item_id).with_for_update()
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=ERR_ITEM_NOT_FOUND)
    if item.owner_profile_id != profile.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ERR_ITEM_NOT_OWNER)
    if item.inventory_position is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=ERR_NOT_IN_INVENTORY
        )

    base = await session.get(ItemBase, item.base_id)
    assert base is not None  # FK enforces
    if int(base.slot) != body.slot:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=ERR_SLOT_MISMATCH
        )

    hero = await load_active_hero(session, profile_id=profile.id)
    if hero is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ERR_NO_HERO)

    # Если что-то уже equipped в этом слоте — снимаем (swap).
    currently_equipped = await session.scalar(
        select(Item)
        .where(
            Item.equipped_on == hero.id,
            Item.equipped_slot == body.slot,
        )
        .with_for_update()
    )
    if currently_equipped is not None and currently_equipped.id != item.id:
        free_pos = await find_first_free_inventory_slot(
            session, profile_id=profile.id
        )
        # Item который мы equip'аем освобождает свою ячейку — её можно использовать.
        if free_pos is None:
            free_pos = item.inventory_position
        # Освобождаем ячейку нового item'а ПЕРЕД назначением партнёру (constraint).
        item.inventory_position = None
        await session.flush()
        currently_equipped.equipped_on = None
        currently_equipped.equipped_slot = None
        currently_equipped.inventory_position = free_pos
        await session.flush()
    else:
        item.inventory_position = None
        await session.flush()

    item.equipped_on = hero.id
    item.equipped_slot = EquipmentSlot(body.slot)
    await session.flush()

    log.info(
        "item_equipped",
        profile_id=profile.id,
        item_id=item.id,
        hero_id=hero.id,
        slot=body.slot,
    )
    return _to_dto(item, base_kind=base.kind, base_slot=int(base.slot))


# ---------------------------------------------------------------------------
# POST /items/{id}/unequip
# ---------------------------------------------------------------------------


@router.post("/items/{item_id}/unequip", response_model=ItemDTO)
async def unequip_item(
    item_id: int,
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
) -> ItemDTO:
    """Снять item с hero, поместить в первую free ячейку inventory.

    Если inventory full → 409 inventory_full (item остаётся надетым).
    """
    item = await session.scalar(
        select(Item).where(Item.id == item_id).with_for_update()
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=ERR_ITEM_NOT_FOUND)
    if item.owner_profile_id != profile.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ERR_ITEM_NOT_OWNER)
    if item.equipped_on is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=ERR_NOT_EQUIPPED
        )

    free_pos = await find_first_free_inventory_slot(
        session, profile_id=profile.id
    )
    if free_pos is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=ERR_INVENTORY_FULL
        )

    item.equipped_on = None
    item.equipped_slot = None
    item.inventory_position = free_pos
    await session.flush()

    base = await session.get(ItemBase, item.base_id)
    assert base is not None

    log.info(
        "item_unequipped",
        profile_id=profile.id,
        item_id=item.id,
        moved_to_position=free_pos,
    )
    return _to_dto(item, base_kind=base.kind, base_slot=int(base.slot))


def _to_dto(item: Item, *, base_kind: str, base_slot: int) -> ItemDTO:
    """Convert Item ORM-объект в response DTO."""
    return ItemDTO(
        id=item.id,
        base_id=item.base_id,
        base_kind=base_kind,
        base_slot=base_slot,
        rarity=int(item.rarity),
        ilvl=item.ilvl,
        affixes=list(item.affixes),
        equipped_on=item.equipped_on,
        equipped_slot=(
            int(item.equipped_slot) if item.equipped_slot is not None else None
        ),
        inventory_position=item.inventory_position,
    )

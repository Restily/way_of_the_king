"""Тесты dungeon endpoints: GET /dungeons + POST /enter + POST /flee + /finalize.

W5-035: Extended finalize tests — xp_earned, items_rolled materialization,
auto-claim inventory policy, RunEncounter creation.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.domain.enums import (
    Difficulty,
    DungeonTheme,
    EncounterResult,
    HeroClass,
    RunStatus,
    TransactionType,
)
from wotk.domain.models import (
    AffixDefinition,
    Balance,
    CampaignProgress,
    DailyDungeonEntry,
    Dungeon,
    DungeonRun,
    Hero,
    Item,
    ItemBase,
    Profile,
    RunEncounter,
    Transaction,
)
from wotk.domain.enums import AffixType, EquipmentSlot, Rarity

from ._helpers import login_e2e, setup_user_with_funds, sign_internal_body


async def _seed_basic(
    db_session: AsyncSession,
    *,
    dungeon_id: str = "test_d",
    entry_cost_gold: int = 1000,
    entry_cost_energy: int = 10,
    daily_limit: int = 3,
    min_level: int = 1,
    act: int | None = None,
    location: int | None = None,
) -> Dungeon:
    """Создать тестовый dungeon в test DB.

    :param act: Опциональный номер акта (для кампании).
    :param location: Опциональный номер локации (для кампании).
    """
    d = Dungeon(
        id=dungeon_id,
        name_key=f"dungeon.{dungeon_id}.name",
        theme=DungeonTheme.CRYPT,
        difficulty=Difficulty.NORMAL,
        min_level=min_level,
        entry_cost_gold=entry_cost_gold,
        entry_cost_energy=entry_cost_energy,
        daily_limit=daily_limit,
        floors_count=5,
        config={"v": 1, "floors": []},
        xp_base=100,
        gold_base=500,
        act=act,
        location=location,
    )
    db_session.add(d)
    await db_session.commit()
    return d


async def _setup_user_with_funds(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    telegram_id: int,
    gold: int = 10_000,
    energy: int = 100,
) -> tuple[str, int]:
    """Backward-compat wrapper для существующих тестов: возвращает (token, profile_id)."""
    r = await setup_user_with_funds(
        client, db_session, telegram_id=telegram_id, gold=gold, energy=energy
    )
    return r.access_token, r.profile_id


# ---------------------------------------------------------------------------
# GET /dungeons
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_dungeons_empty_when_no_hero(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access = await login_e2e(client, telegram_id=83001)
    await _seed_basic(db_session)
    r = await client.get(
        "/api/v1/dungeons", headers={"Authorization": f"Bearer {access}"}
    )
    assert r.status_code == 200
    assert r.json() == {"dungeons": []}


@pytest.mark.asyncio
async def test_list_dungeons_filters_by_level(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, _ = await _setup_user_with_funds(client, db_session, telegram_id=83002)
    # Один доступный (level 1), один заблокированный (level 50)
    await _seed_basic(db_session, dungeon_id="d_easy", min_level=1)
    await _seed_basic(db_session, dungeon_id="d_hard", min_level=50)

    r = await client.get(
        "/api/v1/dungeons", headers={"Authorization": f"Bearer {access}"}
    )
    assert r.status_code == 200
    ids = [d["id"] for d in r.json()["dungeons"]]
    assert ids == ["d_easy"]


@pytest.mark.asyncio
async def test_list_dungeons_skips_disabled(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, _ = await _setup_user_with_funds(client, db_session, telegram_id=83003)
    d = await _seed_basic(db_session, dungeon_id="d_off")
    d.is_enabled = False
    await db_session.commit()

    r = await client.get(
        "/api/v1/dungeons", headers={"Authorization": f"Bearer {access}"}
    )
    assert r.status_code == 200
    assert r.json() == {"dungeons": []}


# ---------------------------------------------------------------------------
# POST /dungeons/{id}/enter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_success_debits_and_returns_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=83010, gold=5000, energy=100
    )
    await _seed_basic(
        db_session, dungeon_id="d_enter", entry_cost_gold=1000, entry_cost_energy=10
    )

    r = await client.post(
        "/api/v1/dungeons/d_enter/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["dungeon"]["id"] == "d_enter"
    assert "ws_token" in body and len(body["ws_token"]) > 50
    assert body["ws_url"].startswith(("ws://", "wss://"))

    # Balance debited
    balance = await db_session.scalar(
        select(Balance).where(Balance.profile_id == profile_id)
    )
    assert balance is not None
    assert balance.gold == 4000
    assert balance.energy == 90

    # Transaction created
    tx = await db_session.scalar(
        select(Transaction)
        .where(Transaction.profile_id == profile_id)
        .order_by(Transaction.id.desc())
        .limit(1)
    )
    assert tx is not None
    assert tx.type == TransactionType.DUNGEON_ENTRY
    assert tx.amount == -1000
    assert tx.balance_after == 4000
    assert tx.ref == {"dungeon_id": "d_enter"}

    # Run created
    run = await db_session.scalar(
        select(DungeonRun).where(DungeonRun.id == uuid.UUID(body["run_id"]))
    )
    assert run is not None
    assert run.status == RunStatus.IN_PROGRESS
    assert len(run.seed) == 32
    assert run.entry_paid_gold == 1000


@pytest.mark.asyncio
async def test_enter_insufficient_gold(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, _ = await _setup_user_with_funds(
        client, db_session, telegram_id=83011, gold=100
    )
    await _seed_basic(
        db_session, dungeon_id="d_expensive", entry_cost_gold=1000
    )
    r = await client.post(
        "/api/v1/dungeons/d_expensive/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 402
    assert r.json()["detail"] == "insufficient_gold"


@pytest.mark.asyncio
async def test_enter_insufficient_energy(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, _ = await _setup_user_with_funds(
        client, db_session, telegram_id=83012, gold=10_000, energy=5
    )
    await _seed_basic(
        db_session, dungeon_id="d_tired", entry_cost_energy=10
    )
    r = await client.post(
        "/api/v1/dungeons/d_tired/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 402
    assert r.json()["detail"] == "insufficient_energy"


@pytest.mark.asyncio
async def test_enter_dungeon_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, _ = await _setup_user_with_funds(client, db_session, telegram_id=83013)
    r = await client.post(
        "/api/v1/dungeons/nonexistent/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "dungeon_not_found"


@pytest.mark.asyncio
async def test_enter_idempotent_replay_returns_same_run(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, _ = await _setup_user_with_funds(client, db_session, telegram_id=83014)
    await _seed_basic(db_session, dungeon_id="d_idem")
    idem = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {access}", "Idempotency-Key": idem}

    r1 = await client.post("/api/v1/dungeons/d_idem/enter", headers=headers)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/dungeons/d_idem/enter", headers=headers)
    assert r2.status_code == 201
    assert r1.json()["run_id"] == r2.json()["run_id"]


@pytest.mark.asyncio
async def test_enter_blocks_second_active_run(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, _ = await _setup_user_with_funds(client, db_session, telegram_id=83015)
    await _seed_basic(db_session, dungeon_id="d_first")
    await _seed_basic(db_session, dungeon_id="d_second")

    r = await client.post(
        "/api/v1/dungeons/d_first/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 201

    # Try to enter another → uq_runs_one_active_per_hero ловит
    r2 = await client.post(
        "/api/v1/dungeons/d_second/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r2.status_code == 409
    assert r2.json()["detail"] == "run_already_active"


@pytest.mark.asyncio
async def test_enter_daily_limit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=83016, gold=100_000
    )
    await _seed_basic(db_session, dungeon_id="d_lim", daily_limit=2)

    # Pre-set count to limit
    today = datetime.combine(datetime.now(UTC).date(), datetime.min.time())
    db_session.add(
        DailyDungeonEntry(
            profile_id=profile_id,
            dungeon_id="d_lim",
            date_utc=today,
            count=2,
        )
    )
    await db_session.commit()

    r = await client.post(
        "/api/v1/dungeons/d_lim/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 429
    assert r.json()["detail"] == "daily_limit_reached"


# ---------------------------------------------------------------------------
# POST /runs/{id}/flee
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flee_returns_pending_gold(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=83020
    )
    await _seed_basic(db_session, dungeon_id="d_flee")

    r = await client.post(
        "/api/v1/dungeons/d_flee/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 201
    run_id = r.json()["run_id"]

    # Simulate pending_gold накопленный с пройденных floors
    run = await db_session.scalar(
        select(DungeonRun).where(DungeonRun.id == uuid.UUID(run_id))
    )
    assert run is not None
    run.pending_gold = 250
    await db_session.commit()

    balance_before = await db_session.scalar(
        select(Balance).where(Balance.profile_id == profile_id)
    )
    assert balance_before is not None
    gold_before = balance_before.gold

    rf = await client.post(
        f"/api/v1/runs/{run_id}/flee",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert rf.status_code == 200
    body = rf.json()
    assert body["status"] == "FLED"
    assert body["pending_gold_returned"] == 250

    # Balance updated
    await db_session.refresh(balance_before)
    assert balance_before.gold == gold_before + 250

    # Run status updated
    await db_session.refresh(run)
    assert run.status == RunStatus.FLED
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_flee_not_owner(client: AsyncClient, db_session: AsyncSession) -> None:
    access_a, _ = await _setup_user_with_funds(
        client, db_session, telegram_id=83021
    )
    access_b = await login_e2e(client, telegram_id=83022)
    await _seed_basic(db_session, dungeon_id="d_owner")

    r = await client.post(
        "/api/v1/dungeons/d_owner/enter",
        headers={
            "Authorization": f"Bearer {access_a}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 201
    run_id = r.json()["run_id"]

    # User B tries to flee A's run
    rf = await client.post(
        f"/api/v1/runs/{run_id}/flee",
        headers={"Authorization": f"Bearer {access_b}"},
    )
    assert rf.status_code == 403


@pytest.mark.asyncio
async def test_flee_already_finished_returns_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    access, _ = await _setup_user_with_funds(client, db_session, telegram_id=83023)
    await _seed_basic(db_session, dungeon_id="d_done")

    r = await client.post(
        "/api/v1/dungeons/d_done/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    run_id = r.json()["run_id"]

    # First flee
    rf1 = await client.post(
        f"/api/v1/runs/{run_id}/flee",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert rf1.status_code == 200

    # Second flee → 409
    rf2 = await client.post(
        f"/api/v1/runs/{run_id}/flee",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert rf2.status_code == 409
    assert rf2.json()["detail"] == "run_not_active"


# ---------------------------------------------------------------------------
# POST /internal/runs/{id}/finalize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_finalize_completed_credits_gold(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    import json

    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=83030
    )
    await _seed_basic(db_session, dungeon_id="d_fin")

    r = await client.post(
        "/api/v1/dungeons/d_fin/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    run_id = r.json()["run_id"]

    body = {
        "status": "COMPLETED",
        "hero_state": {"hp": 80, "mana": 50},
        "gold_earned": 1500,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Sig": sign_internal_body(body_bytes),
        },
    )
    assert rf.status_code == 200, rf.text
    assert rf.json()["status"] == "COMPLETED"

    balance = await db_session.scalar(
        select(Balance).where(Balance.profile_id == profile_id)
    )
    assert balance is not None
    # 10000 - 1000 (entry) + 1500 (reward) = 10500
    assert balance.gold == 10500

    run = await db_session.scalar(
        select(DungeonRun).where(DungeonRun.id == uuid.UUID(run_id))
    )
    assert run is not None
    assert run.status == RunStatus.COMPLETED
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_internal_finalize_missing_hmac_returns_401(
    client: AsyncClient,
) -> None:
    fake_run_id = uuid.uuid4()
    rf = await client.post(
        f"/api/v1/internal/runs/{fake_run_id}/finalize",
        json={"status": "COMPLETED", "hero_state": {}},
    )
    assert rf.status_code == 401
    assert rf.json()["detail"] == "missing_internal_signature"


@pytest.mark.asyncio
async def test_internal_finalize_wrong_hmac_returns_401(
    client: AsyncClient,
) -> None:
    fake_run_id = uuid.uuid4()
    rf = await client.post(
        f"/api/v1/internal/runs/{fake_run_id}/finalize",
        json={"status": "COMPLETED", "hero_state": {}},
        headers={"X-Internal-Sig": "deadbeef" * 8},
    )
    assert rf.status_code == 401
    assert rf.json()["detail"] == "invalid_internal_signature"


# ---------------------------------------------------------------------------
# W5-035 tests — xp + items + combat_summary + auto-claim
# ---------------------------------------------------------------------------


async def _seed_item_base(db_session: AsyncSession) -> ItemBase:
    """Создать тестовый ItemBase для materialization тестов."""
    ib = ItemBase(
        kind="test_sword",
        slot=EquipmentSlot.WEAPON,
        min_ilvl=1,
        base_stats={"min_dmg": 5, "max_dmg": 10},
        is_two_handed=False,
    )
    db_session.add(ib)
    await db_session.commit()
    return ib


async def _seed_affix_definition(
    db_session: AsyncSession, *, slot: EquipmentSlot = EquipmentSlot.WEAPON
) -> AffixDefinition:
    """Создать минимальный AffixDefinition для loot rolling тестов."""
    ad = AffixDefinition(
        affix_type=AffixType.PREFIX,
        mod_group="test_flat_str",
        min_ilvl=1,
        tier=1,
        weight=100,
        applicable_slots=[int(slot)],
        tags=[],
        spawn_weights=None,
        mod_type="flat_str",
        value_min=1,
        value_max=5,
    )
    db_session.add(ad)
    await db_session.commit()
    return ad


_FULL_COMBAT_SUMMARY = {
    "v": 1,
    "damage_dealt": 800,
    "damage_taken": 120,
    "duration_s": 45,
    "deaths": 0,
    "events": [],
}


@pytest.mark.asyncio
async def test_internal_finalize_w5_xp_items_combat_summary(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """W5-035: COMPLETED finalize with xp_earned + items_rolled + combat_summary.

    Verifies:
    - hero.xp incremented
    - Item row created with auto-claim (escrow cleared, inventory_position set)
    - RunEncounter row created with combat_summary
    """
    await _seed_item_base(db_session)
    await _seed_affix_definition(db_session)

    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=83040, gold=10_000
    )
    await _seed_basic(db_session, dungeon_id="d_w5")

    r = await client.post(
        "/api/v1/dungeons/d_w5/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["run_id"]

    # Load hero before to check xp delta
    hero_before = await db_session.scalar(
        select(Hero).where(Hero.profile_id == profile_id)
    )
    assert hero_before is not None
    xp_before = hero_before.xp

    body = {
        "status": "COMPLETED",
        "hero_state": {"hp": 80, "mana": 30},
        "gold_earned": 250,
        "xp_earned": 75,
        "items_rolled": [{"rarity": 2}],  # RARE
        "combat_summary": _FULL_COMBAT_SUMMARY,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Sig": sign_internal_body(body_bytes),
        },
    )
    assert rf.status_code == 200, rf.text
    assert rf.json()["status"] == "COMPLETED"

    # hero.xp incremented
    await db_session.refresh(hero_before)
    assert hero_before.xp == xp_before + 75

    # Item created and auto-claimed (inventory_position set, escrow cleared)
    items = (
        await db_session.scalars(
            select(Item).where(Item.owner_profile_id == profile_id)
        )
    ).all()
    assert len(items) == 1, f"Expected 1 item, got {len(items)}"
    item = items[0]
    assert item.inventory_position is not None, "Item should be in inventory after auto-claim"
    assert item.escrow_run_id is None, "escrow_run_id should be cleared after auto-claim"
    assert int(item.rarity) == 2  # RARE

    # RunEncounter created
    encounter = await db_session.scalar(
        select(RunEncounter).where(RunEncounter.run_id == uuid.UUID(run_id))
    )
    assert encounter is not None
    assert encounter.combat_summary["v"] == 1
    assert encounter.combat_summary["damage_dealt"] == 800
    assert encounter.combat_summary["damage_taken"] == 120
    assert encounter.result == EncounterResult.WIN
    assert encounter.gold_rolled == 250
    assert len(encounter.loot_rolled) == 1
    assert encounter.loot_rolled[0]["rarity"] == 2


@pytest.mark.asyncio
async def test_internal_finalize_inventory_full_keeps_escrow(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """W5-035: When inventory is full, items stay in escrow after finalize.

    Pre-fills 48 inventory slots then finalizes with 1 item_rolled.
    Verifies item is created but escrow_run_id remains set (inventory full policy).
    """
    await _seed_item_base(db_session)
    await _seed_affix_definition(db_session)

    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=83041, gold=10_000
    )
    await _seed_basic(db_session, dungeon_id="d_full_inv")

    r = await client.post(
        "/api/v1/dungeons/d_full_inv/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["run_id"]

    # Load the item_base to get its id for pre-filling inventory
    base = await db_session.scalar(select(ItemBase))
    assert base is not None

    # Pre-fill all 48 inventory slots with dummy items
    for pos in range(48):
        dummy = Item(
            owner_profile_id=profile_id,
            base_id=base.id,
            rarity=Rarity.COMMON,
            ilvl=1,
            affixes=[],
            inventory_position=pos,
        )
        db_session.add(dummy)
    await db_session.commit()

    body = {
        "status": "COMPLETED",
        "hero_state": {"hp": 80, "mana": 30},
        "gold_earned": 100,
        "xp_earned": 10,
        "items_rolled": [{"rarity": 0}],  # COMMON
        "combat_summary": _FULL_COMBAT_SUMMARY,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Sig": sign_internal_body(body_bytes),
        },
    )
    assert rf.status_code == 200, rf.text

    # Item was created but escrow_run_id must still be set (inventory full)
    # and inventory_position must be None
    new_item = await db_session.scalar(
        select(Item).where(
            Item.owner_profile_id == profile_id,
            Item.escrow_run_id == uuid.UUID(run_id),
        )
    )
    assert new_item is not None, "Item should exist in escrow after full-inventory finalize"
    assert new_item.inventory_position is None, "Full inventory: item should not be in inventory"
    assert new_item.escrow_run_id is not None, "Full inventory: escrow_run_id should remain"


@pytest.mark.asyncio
async def test_internal_finalize_no_items_no_xp_backward_compat(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """W5-035: FAILED/ABANDONED finalize with minimal body still works (backward compat)."""
    access, _ = await _setup_user_with_funds(client, db_session, telegram_id=83042)
    await _seed_basic(db_session, dungeon_id="d_aban")

    r = await client.post(
        "/api/v1/dungeons/d_aban/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    run_id = r.json()["run_id"]

    body = {"status": "ABANDONED", "hero_state": {"hp": 0, "mana": 0}}
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Sig": sign_internal_body(body_bytes),
        },
    )
    assert rf.status_code == 200, rf.text
    assert rf.json()["status"] == "ABANDONED"


@pytest.mark.asyncio
async def test_internal_finalize_combat_summary_synthesized_when_missing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """W5-035: RunEncounter gets synthesized v=1 summary when combat_summary not sent."""
    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=83043, gold=10_000
    )
    await _seed_basic(db_session, dungeon_id="d_nosumm")

    r = await client.post(
        "/api/v1/dungeons/d_nosumm/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    run_id = r.json()["run_id"]

    body = {
        "status": "COMPLETED",
        "hero_state": {"hp": 100, "mana": 50},
        "gold_earned": 50,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Sig": sign_internal_body(body_bytes),
        },
    )
    assert rf.status_code == 200, rf.text

    encounter = await db_session.scalar(
        select(RunEncounter).where(RunEncounter.run_id == uuid.UUID(run_id))
    )
    assert encounter is not None
    assert encounter.combat_summary["v"] == 1
    assert "damage_dealt" in encounter.combat_summary


@pytest.mark.asyncio
async def test_internal_finalize_rejects_rewards_exceeding_dungeon_cap(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Defense-in-depth: даже под валидной HMAC-подписью gold/xp/items должны
    быть в правдоподобном диапазоне относительно конфига данжа.

    С _seed_basic'ом (gold_base=500, xp_base=100, floors_count=5) +
    multiplier=10 потолки: gold ≤ 25000, xp ≤ 5000, items ≤ 25.
    """
    import json

    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=83099
    )
    await _seed_basic(db_session, dungeon_id="d_cap")

    r = await client.post(
        "/api/v1/dungeons/d_cap/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    run_id = r.json()["run_id"]

    # gold_earned превышает cap (500*5*10 = 25000) — ожидаем 422.
    body = {
        "status": "COMPLETED",
        "hero_state": {"hp": 100, "mana": 50},
        "gold_earned": 50_000,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Sig": sign_internal_body(body_bytes),
        },
    )
    assert rf.status_code == 422, rf.text
    assert rf.json()["detail"] == "rewards_exceed_dungeon_cap"

    # Run всё ещё IN_PROGRESS — ничего не закредитилось.
    run = await db_session.scalar(
        select(DungeonRun).where(DungeonRun.id == uuid.UUID(run_id))
    )
    assert run is not None
    assert run.status == RunStatus.IN_PROGRESS

    balance = await db_session.scalar(
        select(Balance).where(Balance.profile_id == profile_id)
    )
    assert balance is not None
    # 10000 - 1000 (entry cost) — никакого reward credit.
    assert balance.gold == 9000


@pytest.mark.asyncio
async def test_internal_finalize_rejects_negative_or_absurd_pydantic_bounds(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Pydantic Field bounds (ge=0, le=10M) отсекают мусор до DB-работы."""
    import json

    access, _ = await _setup_user_with_funds(
        client, db_session, telegram_id=83100
    )
    await _seed_basic(db_session, dungeon_id="d_pyd")

    r = await client.post(
        "/api/v1/dungeons/d_pyd/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    run_id = r.json()["run_id"]

    # Отрицательное значение — Pydantic ge=0.
    body = {
        "status": "COMPLETED",
        "hero_state": {"hp": 100, "mana": 50},
        "gold_earned": -100,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Sig": sign_internal_body(body_bytes),
        },
    )
    assert rf.status_code == 422, rf.text


# ---------------------------------------------------------------------------
# W6-021: campaign_progress UPSERT on finalize COMPLETED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_completed_inserts_campaign_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """W6-021: первый COMPLETED finalize создаёт campaign_progress (count=1)."""
    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=86001, gold=10_000
    )
    # Данж с act+location — кампанийный.
    await _seed_basic(
        db_session, dungeon_id="d_cp_insert", act=1, location=1
    )

    r = await client.post(
        "/api/v1/dungeons/d_cp_insert/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["run_id"]

    body = {
        "status": "COMPLETED",
        "hero_state": {"hp": 90, "mana": 40},
        "gold_earned": 200,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Sig": sign_internal_body(body_bytes),
        },
    )
    assert rf.status_code == 200, rf.text

    # Проверяем campaign_progress создан.
    run_row = await db_session.scalar(
        select(DungeonRun).where(DungeonRun.id == uuid.UUID(run_id))
    )
    assert run_row is not None
    cp = await db_session.scalar(
        select(CampaignProgress).where(
            CampaignProgress.hero_id == run_row.hero_id,
            CampaignProgress.act == 1,
            CampaignProgress.location == 1,
        )
    )
    assert cp is not None, "campaign_progress должен быть создан"
    assert cp.completion_count == 1
    assert cp.best_clear_time_s is not None and cp.best_clear_time_s >= 1


@pytest.mark.asyncio
async def test_finalize_completed_increments_campaign_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """W6-021: второй COMPLETED finalize инкрементирует completion_count."""
    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=86002, gold=50_000, energy=100
    )
    await _seed_basic(
        db_session, dungeon_id="d_cp_incr", act=2, location=1,
        entry_cost_energy=5, daily_limit=10,
    )

    async def _do_run(gold: int) -> None:
        r = await client.post(
            "/api/v1/dungeons/d_cp_incr/enter",
            headers={
                "Authorization": f"Bearer {access}",
                "Idempotency-Key": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 201, r.text
        rid = r.json()["run_id"]
        b = {
            "status": "COMPLETED",
            "hero_state": {"hp": 100, "mana": 50},
            "gold_earned": gold,
        }
        bb = json.dumps(b, separators=(",", ":")).encode()
        rf2 = await client.post(
            f"/api/v1/internal/runs/{rid}/finalize",
            content=bb,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Sig": sign_internal_body(bb),
            },
        )
        assert rf2.status_code == 200, rf2.text

    await _do_run(100)
    await _do_run(100)
    await _do_run(100)

    from wotk.domain.models import Hero, Profile
    profile_obj = await db_session.scalar(
        select(Profile).where(Profile.telegram_id == 86002)
    )
    assert profile_obj is not None
    hero = await db_session.scalar(
        select(Hero).where(Hero.profile_id == profile_obj.id)
    )
    assert hero is not None

    cp = await db_session.scalar(
        select(CampaignProgress).where(
            CampaignProgress.hero_id == hero.id,
            CampaignProgress.act == 2,
            CampaignProgress.location == 1,
        )
    )
    assert cp is not None
    assert cp.completion_count == 3


@pytest.mark.asyncio
async def test_finalize_completed_skips_campaign_when_no_act(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """W6-021: данж без act/location не создаёт campaign_progress (skip)."""
    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=86003, gold=10_000
    )
    # act=None, location=None — не кампанийный данж.
    await _seed_basic(db_session, dungeon_id="d_noact")

    r = await client.post(
        "/api/v1/dungeons/d_noact/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    run_id = r.json()["run_id"]

    body = {
        "status": "COMPLETED",
        "hero_state": {"hp": 100, "mana": 50},
        "gold_earned": 50,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Sig": sign_internal_body(body_bytes),
        },
    )
    assert rf.status_code == 200, rf.text

    # Не должно быть campaign_progress.
    from wotk.domain.models import Hero, Profile
    profile_obj = await db_session.scalar(
        select(Profile).where(Profile.telegram_id == 86003)
    )
    assert profile_obj is not None
    hero_obj = await db_session.scalar(
        select(Hero).where(Hero.profile_id == profile_obj.id)
    )
    assert hero_obj is not None
    cp_check = await db_session.scalar(
        select(CampaignProgress).where(
            CampaignProgress.hero_id == hero_obj.id
        )
    )
    assert cp_check is None, "Нет campaign_progress для данжа без act/location"


# ---------------------------------------------------------------------------
# W6-005: 3-floor dungeon end-to-end via /floor-cleared + /finalize
# ---------------------------------------------------------------------------


async def _seed_dungeon_3floors(
    db_session: AsyncSession,
    *,
    dungeon_id: str = "d_3floor",
) -> Dungeon:
    """Создать тестовый 3-этажный dungeon с FloorConfig-совместимым config.

    :param db_session: AsyncSession.
    :param dungeon_id: ID создаваемого данжа.
    :returns: Созданный :class:`Dungeon`.
    """
    d = Dungeon(
        id=dungeon_id,
        name_key=f"dungeon.{dungeon_id}.name",
        theme=DungeonTheme.CRYPT,
        difficulty=Difficulty.NORMAL,
        min_level=1,
        entry_cost_gold=100,
        entry_cost_energy=10,
        daily_limit=5,
        floors_count=3,
        config={
            "v": 1,
            "floors": [
                {
                    "floor": 0,
                    "walls": [{"x": 0, "y": 0, "w": 1280, "h": 32}],
                    "spawn_points": [{"x": 640, "y": 480}],
                    "mob_pack": ["skeleton_warrior", "zombie"],
                    "is_boss_floor": False,
                },
                {
                    "floor": 1,
                    "walls": [{"x": 0, "y": 0, "w": 1280, "h": 32}],
                    "spawn_points": [{"x": 640, "y": 480}],
                    "mob_pack": ["skeleton_warrior", "zombie"],
                    "is_boss_floor": False,
                },
                {
                    "floor": 2,
                    "walls": [{"x": 0, "y": 0, "w": 1280, "h": 32}],
                    "spawn_points": [{"x": 640, "y": 480}],
                    "mob_pack": ["skeleton_warrior"],
                    "is_boss_floor": True,
                },
            ],
        },
        xp_base=100,
        gold_base=500,
    )
    db_session.add(d)
    await db_session.commit()
    return d


_FLOOR_COMBAT_SUMMARY = {
    "v": 1,
    "damage_dealt": 200,
    "damage_taken": 30,
    "duration_s": 15,
    "deaths": 0,
    "events": [],
}


@pytest.mark.asyncio
async def test_w6_three_floor_flow_creates_encounter_rows(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """W6-005: 3-floor dungeon, floor-cleared x2 + finalize -> 3 RunEncounter rows.

    Verifies: 3 RunEncounter rows, accumulated gold, current_floor advances,
    last_checkpoint_at updated, final status = COMPLETED.
    """
    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=87001, gold=10_000
    )
    await _seed_dungeon_3floors(db_session, dungeon_id="d_3f_main")

    r = await client.post(
        "/api/v1/dungeons/d_3f_main/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["run_id"]

    run = await db_session.scalar(
        select(DungeonRun).where(DungeonRun.id == uuid.UUID(run_id))
    )
    assert run is not None
    assert run.current_floor == 0
    checkpoint_after_enter = run.last_checkpoint_at

    # Floor 0 cleared
    body_f0 = {
        "floor": 0, "gold_earned": 150, "xp_earned": 30,
        "items_rolled": [], "combat_summary": _FLOOR_COMBAT_SUMMARY,
        "advance_to_floor": 1,
    }
    body_bytes = json.dumps(body_f0, separators=(",", ":")).encode()
    rf0 = await client.post(
        f"/api/v1/internal/runs/{run_id}/floor-cleared",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Internal-Sig": sign_internal_body(body_bytes)},
    )
    assert rf0.status_code == 200, rf0.text
    assert rf0.json()["current_floor"] == 1

    await db_session.refresh(run)
    assert run.current_floor == 1
    assert run.last_checkpoint_at > checkpoint_after_enter
    checkpoint_after_f0 = run.last_checkpoint_at

    # Floor 1 cleared
    body_f1 = {
        "floor": 1, "gold_earned": 200, "xp_earned": 40,
        "items_rolled": [], "combat_summary": _FLOOR_COMBAT_SUMMARY,
        "advance_to_floor": 2,
    }
    body_bytes = json.dumps(body_f1, separators=(",", ":")).encode()
    rf1 = await client.post(
        f"/api/v1/internal/runs/{run_id}/floor-cleared",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Internal-Sig": sign_internal_body(body_bytes)},
    )
    assert rf1.status_code == 200, rf1.text
    assert rf1.json()["current_floor"] == 2

    await db_session.refresh(run)
    assert run.current_floor == 2
    assert run.last_checkpoint_at > checkpoint_after_f0
    checkpoint_after_f1 = run.last_checkpoint_at

    # Finalize floor 2 (boss floor, terminal)
    body_fin = {
        "status": "COMPLETED", "hero_state": {"hp": 70, "mana": 20},
        "gold_earned": 300, "xp_earned": 50, "items_rolled": [],
        "combat_summary": _FLOOR_COMBAT_SUMMARY,
    }
    body_bytes = json.dumps(body_fin, separators=(",", ":")).encode()
    rf_fin = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Internal-Sig": sign_internal_body(body_bytes)},
    )
    assert rf_fin.status_code == 200, rf_fin.text
    assert rf_fin.json()["status"] == "COMPLETED"

    await db_session.refresh(run)
    assert run.status == RunStatus.COMPLETED
    assert run.finished_at is not None
    assert run.last_checkpoint_at == checkpoint_after_f1

    encounters = (
        await db_session.scalars(
            select(RunEncounter)
            .where(RunEncounter.run_id == uuid.UUID(run_id))
            .order_by(RunEncounter.floor.asc())
        )
    ).all()
    assert len(encounters) == 3, f"Expected 3 encounters, got {len(encounters)}"
    assert encounters[0].floor == 0
    assert encounters[0].gold_rolled == 150
    assert encounters[0].combat_summary["v"] == 1
    assert encounters[0].result == EncounterResult.WIN
    assert encounters[1].floor == 1
    assert encounters[1].gold_rolled == 200
    assert encounters[2].floor == 2
    assert encounters[2].gold_rolled == 300

    # Balance: 10_000 - 100(entry) + 150 + 200 + 300 = 10_550
    balance = await db_session.scalar(
        select(Balance).where(Balance.profile_id == profile_id)
    )
    assert balance is not None
    assert balance.gold == 10_550


@pytest.mark.asyncio
async def test_w6_floor_cleared_rejects_wrong_advance(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """W6-003: /floor-cleared rejects non-sequential floor advance."""
    access, _ = await _setup_user_with_funds(
        client, db_session, telegram_id=87002, gold=10_000
    )
    await _seed_dungeon_3floors(db_session, dungeon_id="d_3f_seq")

    r = await client.post(
        "/api/v1/dungeons/d_3f_seq/enter",
        headers={"Authorization": f"Bearer {access}", "Idempotency-Key": str(uuid.uuid4())},
    )
    run_id = r.json()["run_id"]

    body = {
        "floor": 0, "gold_earned": 100, "xp_earned": 10,
        "items_rolled": [], "combat_summary": _FLOOR_COMBAT_SUMMARY,
        "advance_to_floor": 2,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/floor-cleared",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Internal-Sig": sign_internal_body(body_bytes)},
    )
    assert rf.status_code == 409, rf.text
    assert "bad_floor_advance" in rf.json()["detail"]


@pytest.mark.asyncio
async def test_w6_floor_cleared_rejects_rewards_exceeding_cap(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """W6-003: /floor-cleared caps per-floor gold at dungeon baseline x 10."""
    access, _ = await _setup_user_with_funds(
        client, db_session, telegram_id=87003, gold=10_000
    )
    await _seed_dungeon_3floors(db_session, dungeon_id="d_3f_cap")

    r = await client.post(
        "/api/v1/dungeons/d_3f_cap/enter",
        headers={"Authorization": f"Bearer {access}", "Idempotency-Key": str(uuid.uuid4())},
    )
    run_id = r.json()["run_id"]

    body = {
        "floor": 0, "gold_earned": 9999, "xp_earned": 10,
        "items_rolled": [], "combat_summary": _FLOOR_COMBAT_SUMMARY,
        "advance_to_floor": 1,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/floor-cleared",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Internal-Sig": sign_internal_body(body_bytes)},
    )
    assert rf.status_code == 422, rf.text
    assert rf.json()["detail"] == "rewards_exceed_dungeon_cap"


@pytest.mark.asyncio
async def test_w6_floor_cleared_missing_hmac_returns_401(
    client: AsyncClient,
) -> None:
    """W6-004: /floor-cleared requires HMAC signature."""
    fake_run_id = uuid.uuid4()
    rf = await client.post(
        f"/api/v1/internal/runs/{fake_run_id}/floor-cleared",
        json={"floor": 0, "advance_to_floor": 1},
    )
    assert rf.status_code == 401


# ---------------------------------------------------------------------------
# W6-030: GET /runs/{id}/summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_run_summary_404_for_unknown_run(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /runs/{id}/summary → 404 для несуществующего run_id."""
    access, _ = await _setup_user_with_funds(client, db_session, telegram_id=89001)
    fake_run_id = uuid.uuid4()
    r = await client.get(
        f"/api/v1/runs/{fake_run_id}/summary",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "run_not_found"


@pytest.mark.asyncio
async def test_get_run_summary_403_for_non_owner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /runs/{id}/summary → 403 если run принадлежит другому profile."""
    access_a, _ = await _setup_user_with_funds(client, db_session, telegram_id=89002)
    access_b = await login_e2e(client, telegram_id=89003)
    await _seed_basic(db_session, dungeon_id="d_sum_owner")

    r = await client.post(
        "/api/v1/dungeons/d_sum_owner/enter",
        headers={"Authorization": f"Bearer {access_a}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201
    run_id = r.json()["run_id"]

    # User B cannot see A's run summary
    rs = await client.get(
        f"/api/v1/runs/{run_id}/summary",
        headers={"Authorization": f"Bearer {access_b}"},
    )
    assert rs.status_code == 403
    assert rs.json()["detail"] == "run_not_owner"


@pytest.mark.asyncio
async def test_get_run_summary_409_for_active_run(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /runs/{id}/summary → 409 если run ещё IN_PROGRESS (не terminal)."""
    access, _ = await _setup_user_with_funds(client, db_session, telegram_id=89004)
    await _seed_basic(db_session, dungeon_id="d_sum_active")

    r = await client.post(
        "/api/v1/dungeons/d_sum_active/enter",
        headers={"Authorization": f"Bearer {access}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201
    run_id = r.json()["run_id"]

    rs = await client.get(
        f"/api/v1/runs/{run_id}/summary",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert rs.status_code == 409
    assert rs.json()["detail"] == "run_not_terminal"


@pytest.mark.asyncio
async def test_get_run_summary_200_after_finalize(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /runs/{id}/summary → 200 с корректными данными после COMPLETED finalize.

    Verifies: run_id, status, gold_earned >= 0, floors_cleared == 1
    (one RunEncounter created by finalize), boss_killed, duration_s >= 0.
    """
    access, _ = await _setup_user_with_funds(
        client, db_session, telegram_id=89005, gold=10_000
    )
    await _seed_basic(db_session, dungeon_id="d_sum_ok")

    r = await client.post(
        "/api/v1/dungeons/d_sum_ok/enter",
        headers={"Authorization": f"Bearer {access}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201
    run_id = r.json()["run_id"]

    body = {
        "status": "COMPLETED",
        "hero_state": {"hp": 90, "mana": 40},
        "gold_earned": 500,
        "xp_earned": 50,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Sig": sign_internal_body(body_bytes),
        },
    )
    assert rf.status_code == 200, rf.text

    # Now fetch summary
    rs = await client.get(
        f"/api/v1/runs/{run_id}/summary",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert rs.status_code == 200, rs.text
    data = rs.json()
    assert data["run_id"] == run_id
    assert data["status"] == "COMPLETED"
    assert data["gold_earned"] >= 0
    assert data["floors_cleared"] == 1  # finalize inserted 1 RunEncounter
    assert data["duration_s"] >= 0
    assert isinstance(data["boss_killed"], bool)
    assert isinstance(data["items"], list)
    assert "xp_earned" in data


@pytest.mark.asyncio
async def test_get_run_summary_200_after_flee(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /runs/{id}/summary → 200 для FLED run'а с нулевыми наградами."""
    access, _ = await _setup_user_with_funds(
        client, db_session, telegram_id=89006, gold=10_000
    )
    await _seed_basic(db_session, dungeon_id="d_sum_fled")

    r = await client.post(
        "/api/v1/dungeons/d_sum_fled/enter",
        headers={"Authorization": f"Bearer {access}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201
    run_id = r.json()["run_id"]

    # Flee immediately
    rf = await client.post(
        f"/api/v1/runs/{run_id}/flee",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert rf.status_code == 200

    rs = await client.get(
        f"/api/v1/runs/{run_id}/summary",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert rs.status_code == 200, rs.text
    data = rs.json()
    assert data["status"] == "FLED"
    assert data["boss_killed"] is False
    assert data["floors_cleared"] == 0  # no encounters before flee


# ---------------------------------------------------------------------------
# W6-052: /metrics endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_format(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """W6-052: GET /metrics возвращает text/plain с Prometheus counters.

    Выполняет finalize → проверяет что dungeon_completed_total появился.
    """
    from wotk.core.metrics import reset_all

    reset_all()

    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=96001, gold=10_000
    )
    await _seed_basic(db_session, dungeon_id="d_metrics")

    r = await client.post(
        "/api/v1/dungeons/d_metrics/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["run_id"]

    body = {
        "status": "COMPLETED",
        "hero_state": {"hp": 80, "mana": 50},
        "gold_earned": 200,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    rf = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Internal-Sig": sign_internal_body(body_bytes),
        },
    )
    assert rf.status_code == 200, rf.text

    m = await client.get("/metrics")
    assert m.status_code == 200
    assert "text/plain" in m.headers["content-type"]
    text_body = m.text
    assert "# TYPE dungeon_completed_total counter" in text_body
    assert "dungeon_completed_total{" in text_body
    assert "d_metrics" in text_body

    reset_all()


@pytest.mark.asyncio
async def test_metrics_endpoint_empty_returns_newline(
    client: AsyncClient,
) -> None:
    """W6-052: GET /metrics с пустыми счётчиками возвращает \\n."""
    from wotk.core.metrics import reset_all

    reset_all()
    m = await client.get("/metrics")
    assert m.status_code == 200
    assert m.text == "\n"
    reset_all()


# ---------------------------------------------------------------------------
# W6-053: Admin /admin/runs/{run_id}/encounters endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_get_encounters_returns_sorted_rows(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """W6-053: admin endpoint возвращает RunEncounter rows отсортированные по floor."""
    access, profile_id = await _setup_user_with_funds(
        client, db_session, telegram_id=96010, gold=10_000
    )
    await _seed_dungeon_3floors(db_session, dungeon_id="d_admin_enc")

    r = await client.post(
        "/api/v1/dungeons/d_admin_enc/enter",
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["run_id"]

    # Floor 0 cleared.
    body_f0 = {
        "floor": 0, "gold_earned": 100, "xp_earned": 20,
        "items_rolled": [], "combat_summary": _FLOOR_COMBAT_SUMMARY,
        "advance_to_floor": 1,
    }
    body_bytes = json.dumps(body_f0, separators=(",", ":")).encode()
    rf0 = await client.post(
        f"/api/v1/internal/runs/{run_id}/floor-cleared",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Internal-Sig": sign_internal_body(body_bytes)},
    )
    assert rf0.status_code == 200, rf0.text

    # Finalize floor 1 (simplified — only 2 encounters).
    body_fin = {
        "status": "COMPLETED", "hero_state": {"hp": 70, "mana": 20},
        "gold_earned": 200, "xp_earned": 30, "items_rolled": [],
        "combat_summary": _FLOOR_COMBAT_SUMMARY,
    }
    body_bytes = json.dumps(body_fin, separators=(",", ":")).encode()
    rf_fin = await client.post(
        f"/api/v1/internal/runs/{run_id}/finalize",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Internal-Sig": sign_internal_body(body_bytes)},
    )
    assert rf_fin.status_code == 200, rf_fin.text

    # Set is_admin on profile.
    from wotk.domain.models import Profile as ProfileModel
    profile_obj = await db_session.scalar(
        select(ProfileModel).where(ProfileModel.telegram_id == 96010)
    )
    assert profile_obj is not None
    profile_obj.is_admin = True
    await db_session.commit()

    # Admin request.
    admin_r = await client.get(
        f"/api/v1/admin/runs/{run_id}/encounters",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert admin_r.status_code == 200, admin_r.text
    rows = admin_r.json()
    assert len(rows) == 2
    # Sorted by floor ASC.
    assert rows[0]["floor"] == 0
    assert rows[0]["gold_rolled"] == 100
    assert rows[1]["floor"] == 1
    assert rows[1]["gold_rolled"] == 200


@pytest.mark.asyncio
async def test_admin_encounters_requires_admin(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """W6-053: non-admin юзер получает 403."""
    access, _ = await _setup_user_with_funds(
        client, db_session, telegram_id=96011, gold=5_000
    )
    fake_run_id = uuid.uuid4()
    r = await client.get(
        f"/api/v1/admin/runs/{fake_run_id}/encounters",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "admin_required"


@pytest.mark.asyncio
async def test_admin_encounters_404_unknown_run(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """W6-053: admin запрос на несуществующий run → 404."""
    access, _ = await _setup_user_with_funds(
        client, db_session, telegram_id=96012, gold=5_000
    )
    # Set admin.
    from wotk.domain.models import Profile as ProfileModel
    profile_obj = await db_session.scalar(
        select(ProfileModel).where(ProfileModel.telegram_id == 96012)
    )
    assert profile_obj is not None
    profile_obj.is_admin = True
    await db_session.commit()

    fake_run_id = uuid.uuid4()
    r = await client.get(
        f"/api/v1/admin/runs/{fake_run_id}/encounters",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "run_not_found"


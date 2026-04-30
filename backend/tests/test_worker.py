"""Тесты Arq cron-задач (без поднятия Redis — задачи импортируются как функции)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.domain.enums import Rarity, RunStatus, TransactionType
from wotk.domain.models import (
    Balance,
    DungeonRun,
    IdempotencyKey,
    Item,
    ItemBase,
    Profile,
    Transaction,
)
from wotk.worker.main import (
    cleanup_expired_idempotency_keys,
    cleanup_expired_runs,
    reconcile_balances,
)


@pytest.mark.asyncio
async def test_cleanup_removes_only_expired(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Просроченные удаляются, активные остаются."""
    profile = Profile(telegram_id=80001)
    db_session.add(profile)
    await db_session.flush()

    now = datetime.now(UTC)
    expired = IdempotencyKey(
        key=uuid.uuid4(),
        profile_id=profile.id,
        endpoint="/api/v1/heroes",
        request_hash=b"\x00" * 32,
        response_status=201,
        response_body={"ok": True},
        expires_at=now - timedelta(minutes=5),
    )
    active = IdempotencyKey(
        key=uuid.uuid4(),
        profile_id=profile.id,
        endpoint="/api/v1/heroes",
        request_hash=b"\x01" * 32,
        response_status=201,
        response_body={"ok": True},
        expires_at=now + timedelta(hours=2),
    )
    db_session.add_all([expired, active])
    await db_session.commit()

    # Подменяем session_scope в модуле воркера так, чтобы переиспользовалась
    # фикстура db_session (та же транзакция, тот же engine = test DB).
    @asynccontextmanager
    async def fake_scope():
        yield db_session

    from wotk.worker import main as worker_main

    monkeypatch.setattr(worker_main, "session_scope", fake_scope)

    deleted = await cleanup_expired_idempotency_keys(ctx={})
    assert deleted == 1

    remaining = (await db_session.scalars(select(IdempotencyKey))).all()
    assert len(remaining) == 1
    assert remaining[0].key == active.key


@pytest.mark.asyncio
async def test_reconcile_finds_drift(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drift = balance.gold ≠ last transaction.balance_after → cron находит."""
    profile = Profile(telegram_id=80101)
    db_session.add(profile)
    await db_session.flush()

    balance = Balance(profile_id=profile.id, gold=200)  # Б факт
    db_session.add(balance)
    await db_session.flush()

    # Последняя transaction говорит balance должен быть 100 → drift +100
    db_session.add(
        Transaction(
            profile_id=profile.id,
            type=TransactionType.DUNGEON_REWARD,
            amount=50,
            balance_after=100,  # mismatch
        )
    )
    await db_session.commit()

    @asynccontextmanager
    async def fake_scope():
        yield db_session

    from wotk.worker import main as worker_main

    monkeypatch.setattr(worker_main, "session_scope", fake_scope)

    drifts = await reconcile_balances(ctx={})
    assert drifts == 1


@pytest.mark.asyncio
async def test_reconcile_clean_state_no_drift(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если balance.gold == last transaction.balance_after → 0 drifts."""
    profile = Profile(telegram_id=80102)
    db_session.add(profile)
    await db_session.flush()

    balance = Balance(profile_id=profile.id, gold=500)
    db_session.add(balance)
    await db_session.flush()

    db_session.add(
        Transaction(
            profile_id=profile.id,
            type=TransactionType.DUNGEON_REWARD,
            amount=500,
            balance_after=500,  # match
        )
    )
    await db_session.commit()

    @asynccontextmanager
    async def fake_scope():
        yield db_session

    from wotk.worker import main as worker_main

    monkeypatch.setattr(worker_main, "session_scope", fake_scope)

    drifts = await reconcile_balances(ctx={})
    assert drifts == 0


# ---------------------------------------------------------------------------
# W6-054: cleanup_expired_runs — 50% escrow grace policy
# ---------------------------------------------------------------------------


async def _seed_worker_dungeon(db_session: AsyncSession) -> None:
    """Создать минимальный dungeon для worker-тестов."""
    from wotk.domain.enums import Difficulty, DungeonTheme
    from wotk.domain.models import Dungeon

    d = Dungeon(
        id="d_worker",
        name_key="dungeon.d_worker.name",
        theme=DungeonTheme.CRYPT,
        difficulty=Difficulty.NORMAL,
        min_level=1,
        entry_cost_gold=0,
        entry_cost_energy=0,
        daily_limit=99,
        floors_count=3,
        config={"v": 1, "floors": []},
        xp_base=100,
        gold_base=500,
    )
    db_session.add(d)
    await db_session.flush()


async def _seed_worker_item_base(db_session: AsyncSession) -> ItemBase:
    """Создать минимальный ItemBase для worker-тестов."""
    from wotk.domain.enums import EquipmentSlot

    ib = ItemBase(
        kind="worker_sword",
        slot=EquipmentSlot.WEAPON,
        min_ilvl=1,
        base_stats={"min_dmg": 5, "max_dmg": 10},
        is_two_handed=False,
    )
    db_session.add(ib)
    await db_session.flush()
    return ib


async def _make_expired_run(
    db_session: AsyncSession,
    *,
    profile_id: int,
    hero_id: int,
) -> DungeonRun:
    """Создать expired IN_PROGRESS DungeonRun."""
    import secrets as _secrets

    run = DungeonRun(
        profile_id=profile_id,
        hero_id=hero_id,
        dungeon_id="d_worker",
        seed=_secrets.token_bytes(32),
        hero_state={"hp": 100},
        entry_paid_gold=0,
        entry_paid_energy=0,
        expires_at=datetime(2000, 1, 1, tzinfo=UTC),  # expired
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest.mark.asyncio
async def test_cleanup_expired_runs_moves_half_best_items(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W6-054: cleanup переносит floor(N/2) лучших escrow items в inventory."""
    from wotk.domain.enums import HeroClass
    from wotk.domain.models import Hero

    await _seed_worker_dungeon(db_session)
    base = await _seed_worker_item_base(db_session)

    profile = Profile(telegram_id=81001)
    db_session.add(profile)
    await db_session.flush()

    hero = Hero(
        profile_id=profile.id,
        hero_class=HeroClass.KNIGHT,
        name="WorkerHero",
    )
    db_session.add(hero)
    await db_session.flush()

    run = await _make_expired_run(db_session, profile_id=profile.id, hero_id=hero.id)

    # 4 escrow items of different rarities.
    items = []
    for rarity, ilvl in [
        (Rarity.RARE, 5),
        (Rarity.MAGIC, 4),
        (Rarity.COMMON, 3),
        (Rarity.COMMON, 2),
    ]:
        item = Item(
            owner_profile_id=profile.id,
            base_id=base.id,
            rarity=rarity,
            ilvl=ilvl,
            affixes=[],
            escrow_run_id=run.id,
        )
        db_session.add(item)
        items.append(item)
    await db_session.commit()

    @asynccontextmanager
    async def fake_scope():
        yield db_session

    from wotk.worker import main as worker_main
    monkeypatch.setattr(worker_main, "session_scope", fake_scope)

    count = await cleanup_expired_runs(ctx={})
    assert count == 1  # 1 run abandoned

    # floor(4/2) = 2 best items moved to inventory, 2 stay in escrow.
    await db_session.refresh(run)
    assert run.status == RunStatus.ABANDONED

    all_items = (
        await db_session.scalars(
            select(Item).where(Item.owner_profile_id == profile.id)
        )
    ).all()
    in_inventory = [i for i in all_items if i.inventory_position is not None]
    in_escrow = [i for i in all_items if i.escrow_run_id is not None]

    assert len(in_inventory) == 2, f"Expected 2 in inventory, got {len(in_inventory)}"
    assert len(in_escrow) == 2, f"Expected 2 in escrow, got {len(in_escrow)}"

    # Best 2 items (RARE+MAGIC) should be in inventory.
    moved_rarities = sorted(int(i.rarity) for i in in_inventory)
    assert moved_rarities == sorted(
        [int(Rarity.RARE), int(Rarity.MAGIC)]
    ), f"Wrong items moved: {moved_rarities}"


@pytest.mark.asyncio
async def test_cleanup_expired_runs_odd_count_rounds_down(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W6-054: floor(3/2)=1 — только один item переносится."""
    from wotk.domain.enums import HeroClass
    from wotk.domain.models import Hero

    await _seed_worker_dungeon(db_session)
    base = await _seed_worker_item_base(db_session)

    profile = Profile(telegram_id=81002)
    db_session.add(profile)
    await db_session.flush()

    hero = Hero(
        profile_id=profile.id,
        hero_class=HeroClass.KNIGHT,
        name="WorkerHero2",
    )
    db_session.add(hero)
    await db_session.flush()

    run = await _make_expired_run(db_session, profile_id=profile.id, hero_id=hero.id)

    # 3 escrow items.
    for r in [Rarity.RARE, Rarity.MAGIC, Rarity.COMMON]:
        db_session.add(
            Item(
                owner_profile_id=profile.id,
                base_id=base.id,
                rarity=r,
                ilvl=1,
                affixes=[],
                escrow_run_id=run.id,
            )
        )
    await db_session.commit()

    @asynccontextmanager
    async def fake_scope():
        yield db_session

    from wotk.worker import main as worker_main
    monkeypatch.setattr(worker_main, "session_scope", fake_scope)

    await cleanup_expired_runs(ctx={})

    all_items = (
        await db_session.scalars(
            select(Item).where(Item.owner_profile_id == profile.id)
        )
    ).all()
    in_inventory = [i for i in all_items if i.inventory_position is not None]
    in_escrow = [i for i in all_items if i.escrow_run_id is not None]

    # floor(3/2) = 1 item moved.
    assert len(in_inventory) == 1
    assert len(in_escrow) == 2
    # The RARE item (best) should be the one moved.
    assert int(in_inventory[0].rarity) == int(Rarity.RARE)


@pytest.mark.asyncio
async def test_cleanup_expired_runs_no_items_no_crash(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W6-054: run без escrow items обрабатывается корректно (0 moved)."""
    from wotk.domain.enums import HeroClass
    from wotk.domain.models import Hero

    await _seed_worker_dungeon(db_session)

    profile = Profile(telegram_id=81003)
    db_session.add(profile)
    await db_session.flush()

    hero = Hero(
        profile_id=profile.id,
        hero_class=HeroClass.KNIGHT,
        name="WorkerHero3",
    )
    db_session.add(hero)
    await db_session.flush()

    await _make_expired_run(db_session, profile_id=profile.id, hero_id=hero.id)
    await db_session.commit()

    @asynccontextmanager
    async def fake_scope():
        yield db_session

    from wotk.worker import main as worker_main
    monkeypatch.setattr(worker_main, "session_scope", fake_scope)

    count = await cleanup_expired_runs(ctx={})
    assert count == 1


@pytest.mark.asyncio
async def test_cleanup_expired_runs_skips_non_expired(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W6-054: non-expired IN_PROGRESS run не трогается."""
    from wotk.domain.enums import HeroClass
    from wotk.domain.models import Hero

    await _seed_worker_dungeon(db_session)

    profile = Profile(telegram_id=81004)
    db_session.add(profile)
    await db_session.flush()

    hero = Hero(
        profile_id=profile.id,
        hero_class=HeroClass.KNIGHT,
        name="WorkerHero4",
    )
    db_session.add(hero)
    await db_session.flush()

    import secrets as _secrets

    run = DungeonRun(
        profile_id=profile.id,
        hero_id=hero.id,
        dungeon_id="d_worker",
        seed=_secrets.token_bytes(32),
        hero_state={"hp": 100},
        entry_paid_gold=0,
        entry_paid_energy=0,
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),  # far future
    )
    db_session.add(run)
    await db_session.commit()

    @asynccontextmanager
    async def fake_scope():
        yield db_session

    from wotk.worker import main as worker_main
    monkeypatch.setattr(worker_main, "session_scope", fake_scope)

    count = await cleanup_expired_runs(ctx={})
    assert count == 0

    await db_session.refresh(run)
    assert run.status == RunStatus.IN_PROGRESS

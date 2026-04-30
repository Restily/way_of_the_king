"""Интеграционные тесты §8 моделей: Dungeon + DungeonRun + RunEncounter + DailyDungeonEntry + CampaignProgress."""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.domain.enums import (
    Difficulty,
    DungeonTheme,
    EncounterResult,
    HeroClass,
    RunStatus,
)
from wotk.domain.models import (
    CampaignProgress,
    DailyDungeonEntry,
    Dungeon,
    DungeonRun,
    Hero,
    Profile,
    RunEncounter,
)


async def _make_profile_hero(
    session: AsyncSession, *, telegram_id: int
) -> tuple[Profile, Hero]:
    p = Profile(telegram_id=telegram_id)
    session.add(p)
    await session.flush()
    h = Hero(profile_id=p.id, hero_class=HeroClass.KNIGHT, name="TestKnight")
    session.add(h)
    await session.flush()
    return p, h


async def _make_dungeon(
    session: AsyncSession, *, dungeon_id: str = "test_crypt"
) -> Dungeon:
    d = Dungeon(
        id=dungeon_id,
        name_key=f"dungeon.{dungeon_id}.name",
        theme=DungeonTheme.CRYPT,
        difficulty=Difficulty.NORMAL,
        min_level=1,
        entry_cost_gold=1000,
        entry_cost_energy=10,
        daily_limit=5,
        floors_count=5,
        config={"v": 1, "floors": []},
        xp_base=100,
        gold_base=500,
    )
    session.add(d)
    await session.flush()
    return d


async def _make_run(
    session: AsyncSession, *, profile: Profile, hero: Hero, dungeon: Dungeon
) -> DungeonRun:
    r = DungeonRun(
        profile_id=profile.id,
        hero_id=hero.id,
        dungeon_id=dungeon.id,
        seed=secrets.token_bytes(32),
        hero_state={"hp": 100, "mana": 50},
        entry_paid_gold=1000,
        entry_paid_energy=10,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    session.add(r)
    await session.flush()
    return r


# ---------------------------------------------------------------------------
# Dungeon
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dungeon_create_and_query(db_session: AsyncSession) -> None:
    d = await _make_dungeon(db_session)
    assert d.is_enabled is True
    assert d.daily_limit == 5
    assert d.theme == DungeonTheme.CRYPT


@pytest.mark.asyncio
async def test_dungeon_min_level_check(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO dungeons "
                "(id, name_key, theme, difficulty, min_level, entry_cost_gold, "
                "config, xp_base, gold_base) "
                "VALUES ('bad', 'k', 0, 0, 0, 100, '{}'::jsonb, 1, 1)"
            )
        )
        await db_session.flush()


# ---------------------------------------------------------------------------
# DungeonRun — основная таблица + триггеры
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_create_and_seed_size(db_session: AsyncSession) -> None:
    p, h = await _make_profile_hero(db_session, telegram_id=82001)
    d = await _make_dungeon(db_session)
    r = await _make_run(db_session, profile=p, hero=h, dungeon=d)
    assert r.id is not None
    assert len(r.seed) == 32
    assert r.status == RunStatus.IN_PROGRESS
    assert r.current_floor == 0


@pytest.mark.asyncio
async def test_run_seed_must_be_32_bytes(db_session: AsyncSession) -> None:
    p, h = await _make_profile_hero(db_session, telegram_id=82002)
    d = await _make_dungeon(db_session)
    r = DungeonRun(
        profile_id=p.id,
        hero_id=h.id,
        dungeon_id=d.id,
        seed=b"\x00" * 16,  # < 32 bytes — fail
        hero_state={},
        entry_paid_gold=0,
        entry_paid_energy=0,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(r)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_run_one_active_per_hero(db_session: AsyncSession) -> None:
    p, h = await _make_profile_hero(db_session, telegram_id=82003)
    d = await _make_dungeon(db_session)
    await _make_run(db_session, profile=p, hero=h, dungeon=d)

    r2 = DungeonRun(
        profile_id=p.id,
        hero_id=h.id,  # тот же hero, IN_PROGRESS — fail
        dungeon_id=d.id,
        seed=secrets.token_bytes(32),
        hero_state={},
        entry_paid_gold=0,
        entry_paid_energy=0,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(r2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_run_can_have_two_completed_then_one_active(
    db_session: AsyncSession,
) -> None:
    """uq_runs_one_active_per_hero — partial unique по status=IN_PROGRESS."""
    p, h = await _make_profile_hero(db_session, telegram_id=82004)
    d = await _make_dungeon(db_session)
    r1 = await _make_run(db_session, profile=p, hero=h, dungeon=d)
    r1.status = RunStatus.SETTLED
    await db_session.flush()
    # Теперь можно создать новый IN_PROGRESS на того же hero
    r2 = await _make_run(db_session, profile=p, hero=h, dungeon=d)
    assert r2.id != r1.id


@pytest.mark.asyncio
async def test_run_seed_immutable_trigger(db_session: AsyncSession) -> None:
    """trg_runs_seed_immutable не даёт UPDATE seed после INSERT."""
    p, h = await _make_profile_hero(db_session, telegram_id=82005)
    d = await _make_dungeon(db_session)
    r = await _make_run(db_session, profile=p, hero=h, dungeon=d)
    # Triggers RAISE EXCEPTION приходят как InternalError/ProgrammingError
    # в зависимости от драйвера. asyncpg → wraps в InternalError.
    new_seed = secrets.token_bytes(32)
    with pytest.raises((IntegrityError, ProgrammingError, Exception)) as excinfo:
        await db_session.execute(
            text("UPDATE dungeon_runs SET seed = :seed WHERE id = :id"),
            {"seed": new_seed, "id": r.id},
        )
        await db_session.flush()
    # Сообщение должно содержать "immutable"
    assert "immutable" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_run_dungeon_id_immutable(db_session: AsyncSession) -> None:
    """trg_runs_seed_immutable также блокирует UPDATE dungeon_id."""
    p, h = await _make_profile_hero(db_session, telegram_id=82006)
    d1 = await _make_dungeon(db_session, dungeon_id="d_one")
    d2 = await _make_dungeon(db_session, dungeon_id="d_two")
    r = await _make_run(db_session, profile=p, hero=h, dungeon=d1)
    with pytest.raises((IntegrityError, ProgrammingError, Exception)) as excinfo:
        await db_session.execute(
            text("UPDATE dungeon_runs SET dungeon_id = :did WHERE id = :id"),
            {"did": d2.id, "id": r.id},
        )
        await db_session.flush()
    assert "immutable" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# RunEncounter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_encounter_requires_summary_version(db_session: AsyncSession) -> None:
    """combat_summary без 'v' ключа — fail (ck_encounters_summary_version)."""
    p, h = await _make_profile_hero(db_session, telegram_id=82010)
    d = await _make_dungeon(db_session)
    r = await _make_run(db_session, profile=p, hero=h, dungeon=d)

    enc = RunEncounter(
        run_id=r.id,
        floor=0,
        encounter_idx=0,
        enemies_spawned=[],
        combat_summary={"damage_dealt": 100},  # нет 'v' — fail
        result=EncounterResult.WIN,
    )
    db_session.add(enc)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_encounter_unique_floor_idx(db_session: AsyncSession) -> None:
    p, h = await _make_profile_hero(db_session, telegram_id=82011)
    d = await _make_dungeon(db_session)
    r = await _make_run(db_session, profile=p, hero=h, dungeon=d)

    enc1 = RunEncounter(
        run_id=r.id,
        floor=1,
        encounter_idx=0,
        enemies_spawned=[],
        combat_summary={"v": 1, "damage_dealt": 50},
        result=EncounterResult.WIN,
    )
    db_session.add(enc1)
    await db_session.flush()

    enc2 = RunEncounter(
        run_id=r.id,
        floor=1,
        encounter_idx=0,  # тот же — fail
        enemies_spawned=[],
        combat_summary={"v": 1, "damage_dealt": 60},
        result=EncounterResult.WIN,
    )
    db_session.add(enc2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ---------------------------------------------------------------------------
# DailyDungeonEntry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_entry_pk(db_session: AsyncSession) -> None:
    p, h = await _make_profile_hero(db_session, telegram_id=82020)
    d = await _make_dungeon(db_session)
    today = datetime.combine(date.today(), datetime.min.time())

    entry = DailyDungeonEntry(
        profile_id=p.id, dungeon_id=d.id, date_utc=today, count=1
    )
    db_session.add(entry)
    await db_session.flush()
    assert entry.count == 1


# ---------------------------------------------------------------------------
# CampaignProgress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_campaign_progress_pk_and_constraints(
    db_session: AsyncSession,
) -> None:
    _, h = await _make_profile_hero(db_session, telegram_id=82030)
    cp = CampaignProgress(hero_id=h.id, act=1, location=1)
    db_session.add(cp)
    await db_session.flush()
    assert cp.completion_count == 1


@pytest.mark.asyncio
async def test_campaign_act_range(db_session: AsyncSession) -> None:
    _, h = await _make_profile_hero(db_session, telegram_id=82031)
    db_session.add(CampaignProgress(hero_id=h.id, act=99, location=1))
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ---------------------------------------------------------------------------
# item.escrow_run_id FK (added in migration 0008)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_item_escrow_run_fk_enforced(db_session: AsyncSession) -> None:
    """Item.escrow_run_id с несуществующим UUID — fail FK."""
    import uuid as _uuid

    from wotk.domain.enums import EquipmentSlot, Rarity
    from wotk.domain.models import Item, ItemBase

    p, _ = await _make_profile_hero(db_session, telegram_id=82040)
    base = ItemBase(
        kind="b_escrow",
        slot=EquipmentSlot.WEAPON,
        base_stats={"min_dmg": 1, "max_dmg": 2},
    )
    db_session.add(base)
    await db_session.flush()

    item = Item(
        owner_profile_id=p.id,
        base_id=base.id,
        rarity=Rarity.COMMON,
        ilvl=1,
        escrow_run_id=_uuid.uuid4(),  # несуществующий run
    )
    db_session.add(item)
    with pytest.raises(IntegrityError):
        await db_session.flush()

"""Интеграционные тесты моделей §1-§5 с реальной БД."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.domain.enums import HeroClass, TransactionType
from wotk.domain.models import Balance, Hero, Profile, Referral, Transaction


@pytest.mark.asyncio
async def test_create_profile_and_balance_roundtrip(
    db_session: AsyncSession,
) -> None:
    profile = Profile(
        telegram_id=12345,
        telegram_username="lancelot",
        telegram_first_name="Sir",
        locale="en",
    )
    db_session.add(profile)
    await db_session.flush()

    assert profile.id is not None
    assert profile.is_blocked is False
    assert profile.is_admin is False
    assert profile.withdrawal_2fa_enabled is True

    balance = Balance(profile_id=profile.id)
    db_session.add(balance)
    await db_session.flush()

    fetched = await db_session.scalar(
        select(Balance).where(Balance.profile_id == profile.id)
    )
    assert fetched is not None
    assert fetched.gold == 0
    assert fetched.energy == 100
    assert fetched.energy_cap == 100


@pytest.mark.asyncio
async def test_profile_locale_check_constraint(
    db_session: AsyncSession,
) -> None:
    """locale должен быть из whitelist."""
    profile = Profile(telegram_id=1, locale="xx")
    db_session.add(profile)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_profile_unique_telegram_id(db_session: AsyncSession) -> None:
    db_session.add(Profile(telegram_id=42))
    await db_session.flush()
    db_session.add(Profile(telegram_id=42))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_create_hero(db_session: AsyncSession) -> None:
    profile = Profile(telegram_id=100)
    db_session.add(profile)
    await db_session.flush()

    hero = Hero(
        profile_id=profile.id,
        hero_class=HeroClass.KNIGHT,
        name="Galahad",
        active_skills=["cleave", "shield_bash", "whirlwind", "charge"],
    )
    db_session.add(hero)
    await db_session.flush()

    fetched = await db_session.scalar(select(Hero).where(Hero.id == hero.id))
    assert fetched is not None
    assert fetched.hero_class is HeroClass.KNIGHT
    assert fetched.level == 1
    assert fetched.xp == 0
    assert fetched.unspent_points == {"stat": 0, "skill": 0}
    assert fetched.base_stats == {"str": 10, "dex": 5, "int": 3}


@pytest.mark.asyncio
async def test_hero_class_check_rejects_invalid(
    db_session: AsyncSession,
) -> None:
    """class=99 должен упасть на CHECK constraint (защита даже без enum)."""
    profile = Profile(telegram_id=200)
    db_session.add(profile)
    await db_session.flush()

    # bypass enum: вставка raw int через SQL
    from sqlalchemy import text

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                """
                INSERT INTO hero (profile_id, class, name)
                VALUES (:pid, 99, 'Cheater')
                """
            ),
            {"pid": profile.id},
        )
        await db_session.flush()


@pytest.mark.asyncio
async def test_hero_one_per_class_per_profile(
    db_session: AsyncSession,
) -> None:
    """uq_hero_profile_class: max один Knight на профиль (partial)."""
    profile = Profile(telegram_id=300)
    db_session.add(profile)
    await db_session.flush()

    db_session.add(
        Hero(
            profile_id=profile.id,
            hero_class=HeroClass.KNIGHT,
            name="Arthur",
        )
    )
    await db_session.flush()

    # Второй Knight для того же профиля — должно упасть
    db_session.add(
        Hero(
            profile_id=profile.id,
            hero_class=HeroClass.KNIGHT,
            name="Mordred",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_hero_name_length_check(db_session: AsyncSession) -> None:
    profile = Profile(telegram_id=400)
    db_session.add(profile)
    await db_session.flush()

    # Слишком короткое имя
    db_session.add(
        Hero(profile_id=profile.id, hero_class=HeroClass.KNIGHT, name="X")
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_hero_unspent_points_must_be_object(
    db_session: AsyncSession,
) -> None:
    """CHECK validates unspent_points структуру."""
    profile = Profile(telegram_id=500)
    db_session.add(profile)
    await db_session.flush()

    db_session.add(
        Hero(
            profile_id=profile.id,
            hero_class=HeroClass.KNIGHT,
            name="Bedivere",
            unspent_points={"stat": -1, "skill": 0},  # negative — fail
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_balance_gold_nonneg_check(db_session: AsyncSession) -> None:
    profile = Profile(telegram_id=600)
    db_session.add(profile)
    await db_session.flush()

    balance = Balance(profile_id=profile.id, gold=-1)
    db_session.add(balance)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_transaction_with_enum(db_session: AsyncSession) -> None:
    profile = Profile(telegram_id=700)
    db_session.add(profile)
    await db_session.flush()

    tx = Transaction(
        profile_id=profile.id,
        type=TransactionType.DUNGEON_ENTRY,
        amount=-100,
        balance_after=900,
        ref={"run_id": "abc-123"},
        idempotency_key="test-idem-1",
    )
    db_session.add(tx)
    await db_session.flush()

    fetched = await db_session.scalar(select(Transaction).where(Transaction.id == tx.id))
    assert fetched is not None
    assert fetched.type is TransactionType.DUNGEON_ENTRY
    assert fetched.amount == -100
    assert fetched.ref == {"run_id": "abc-123"}


@pytest.mark.asyncio
async def test_transaction_idempotency_unique(db_session: AsyncSession) -> None:
    profile = Profile(telegram_id=800)
    db_session.add(profile)
    await db_session.flush()

    db_session.add(
        Transaction(
            profile_id=profile.id,
            type=TransactionType.DUNGEON_REWARD,
            amount=50,
            balance_after=50,
            idempotency_key="dup-key",
        )
    )
    await db_session.flush()

    db_session.add(
        Transaction(
            profile_id=profile.id,
            type=TransactionType.DUNGEON_REWARD,
            amount=50,
            balance_after=100,
            idempotency_key="dup-key",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_referral_unique_referred(db_session: AsyncSession) -> None:
    referrer = Profile(telegram_id=900)
    referred = Profile(telegram_id=901)
    db_session.add_all([referrer, referred])
    await db_session.flush()

    expires = datetime.now(UTC) + timedelta(days=30)
    db_session.add(
        Referral(
            referrer_profile_id=referrer.id,
            referred_profile_id=referred.id,
            expires_at=expires,
        )
    )
    await db_session.flush()

    # Второй реферал на того же referred — fail
    other_referrer = Profile(telegram_id=902)
    db_session.add(other_referrer)
    await db_session.flush()
    db_session.add(
        Referral(
            referrer_profile_id=other_referrer.id,
            referred_profile_id=referred.id,
            expires_at=expires,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()

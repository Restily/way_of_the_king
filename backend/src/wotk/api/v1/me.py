"""GET /api/v1/me — текущий профиль + баланс + основной hero."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.api.deps import current_profile
from wotk.core.db import get_session
from wotk.domain.enums import HeroClass
from wotk.domain.models import Balance, Hero, Profile

router = APIRouter(tags=["profile"])


class ProfileInfo(BaseModel):
    id: int
    locale: str
    telegram_username: str | None
    is_admin: bool
    withdrawal_2fa_enabled: bool
    created_at: datetime


class BalanceInfo(BaseModel):
    gold: int
    energy: int
    energy_cap: int
    energy_updated_at: datetime


class HeroInfo(BaseModel):
    id: int
    hero_class: HeroClass
    name: str
    level: int
    xp: int
    unspent_points: dict
    base_stats: dict


class MeResponse(BaseModel):
    profile: ProfileInfo
    balance: BalanceInfo
    hero: HeroInfo | None = None


def _regen_energy(balance: Balance) -> None:
    """Lazy energy регенерация на стороне Python (без SQL-функции).

    1 unit / 6 минут, кап = energy_cap.
    Прошедшее дробное время сохраняется в energy_updated_at,
    чтобы не терять регенерацию при чтениях.
    """
    if balance.energy >= balance.energy_cap:
        return
    now = datetime.now(balance.energy_updated_at.tzinfo)
    elapsed_seconds = (now - balance.energy_updated_at).total_seconds()
    full_ticks = int(elapsed_seconds // (6 * 60))
    if full_ticks <= 0:
        return
    balance.energy = min(balance.energy_cap, balance.energy + full_ticks)
    # Carry-over дробного времени:
    from datetime import timedelta

    balance.energy_updated_at = balance.energy_updated_at + timedelta(
        minutes=6 * full_ticks
    )


@router.get("/me", response_model=MeResponse)
async def get_me(
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
) -> MeResponse:
    balance = await session.get(Balance, profile.id)
    if balance is None:
        # Защита: если по какой-то причине баланса нет — создаём
        balance = Balance(profile_id=profile.id)
        session.add(balance)
        await session.flush()
    _regen_energy(balance)

    hero = await session.scalar(
        select(Hero)
        .where(Hero.profile_id == profile.id, Hero.deleted_at.is_(None))
        .limit(1)
    )

    hero_info: HeroInfo | None = None
    if hero is not None:
        hero_info = HeroInfo(
            id=hero.id,
            hero_class=hero.hero_class,
            name=hero.name,
            level=hero.level,
            xp=hero.xp,
            unspent_points=hero.unspent_points,
            base_stats=hero.base_stats,
        )

    return MeResponse(
        profile=ProfileInfo(
            id=profile.id,
            locale=profile.locale,
            telegram_username=profile.telegram_username,
            is_admin=profile.is_admin,
            withdrawal_2fa_enabled=profile.withdrawal_2fa_enabled,
            created_at=profile.created_at,
        ),
        balance=BalanceInfo(
            gold=balance.gold,
            energy=balance.energy,
            energy_cap=balance.energy_cap,
            energy_updated_at=balance.energy_updated_at,
        ),
        hero=hero_info,
    )

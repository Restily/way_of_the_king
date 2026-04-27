"""GET /api/v1/me — текущий профиль + баланс + основной hero."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.api.deps import current_profile
from wotk.core.db import get_session
from wotk.domain.enums import HeroClass
from wotk.domain.models import Balance, Hero, Profile
from wotk.game.energy import compute_regenerated
from wotk.schemas.profile import ProfileFull

log = structlog.get_logger()
router = APIRouter(tags=["profile"])


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
    profile: ProfileFull
    balance: BalanceInfo
    hero: HeroInfo | None = None


@router.get("/me", response_model=MeResponse)
async def get_me(
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
) -> MeResponse:
    # Один JOIN-запрос вместо двух последовательных. Outer join на Hero
    # покрывает случай "Hero ещё не создан" — получаем (Balance, None).
    stmt = (
        select(Balance, Hero)
        .outerjoin(
            Hero,
            (Hero.profile_id == Balance.profile_id) & (Hero.deleted_at.is_(None)),
        )
        .where(Balance.profile_id == profile.id)
        .order_by(Hero.id.asc().nulls_last())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        # Инвариант: Balance создаётся вместе с Profile в /auth/login.
        # Отсутствие = баг или ручное удаление, не лечим лениво.
        log.error("balance_missing_for_profile", profile_id=profile.id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="balance_missing"
        )
    balance, hero = row

    # Lazy regen — read-only. Запись в БД только при spend.
    energy_state = compute_regenerated(
        energy=balance.energy,
        energy_cap=balance.energy_cap,
        energy_updated_at=balance.energy_updated_at,
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
        profile=ProfileFull.model_validate(profile),
        balance=BalanceInfo(
            gold=balance.gold,
            energy=energy_state.energy,
            energy_cap=balance.energy_cap,
            energy_updated_at=energy_state.energy_updated_at,
        ),
        hero=hero_info,
    )

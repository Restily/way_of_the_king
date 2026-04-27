"""POST /api/v1/heroes — создание Knight в MVP."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.api.deps import current_profile
from wotk.core.db import get_session
from wotk.domain.enums import HeroClass
from wotk.domain.models import Hero, Profile

log = structlog.get_logger()
router = APIRouter(prefix="/heroes", tags=["hero"])


# Дефолтные знания Knight на старте — 4 скилла в hotbar
KNIGHT_DEFAULT_SKILLS = ["cleave", "shield_bash", "whirlwind", "charge"]
KNIGHT_DEFAULT_BASE_STATS = {"str": 10, "dex": 5, "int": 3}


class CreateHeroRequest(BaseModel):
    name: str = Field(min_length=3, max_length=20)


class HeroCreated(BaseModel):
    id: int
    hero_class: HeroClass
    name: str
    level: int
    xp: int
    unspent_points: dict
    base_stats: dict
    active_skills: list[str]


@router.post("", response_model=HeroCreated, status_code=status.HTTP_201_CREATED)
async def create_hero(
    body: CreateHeroRequest,
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,  # noqa: ARG001
) -> HeroCreated:
    """В MVP создаётся только Knight, max 1 на профиль."""
    # Проверка существующего hero (для понятной 409 вместо IntegrityError)
    existing = await session.scalar(
        select(Hero).where(
            Hero.profile_id == profile.id,
            Hero.hero_class == HeroClass.KNIGHT,
            Hero.deleted_at.is_(None),
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="HERO_ALREADY_EXISTS"
        )

    hero = Hero(
        profile_id=profile.id,
        hero_class=HeroClass.KNIGHT,
        name=body.name,
        base_stats=dict(KNIGHT_DEFAULT_BASE_STATS),
        active_skills=list(KNIGHT_DEFAULT_SKILLS),
    )
    session.add(hero)
    try:
        await session.flush()
    except IntegrityError as e:
        # Race-condition: параллельный запрос успел создать
        await session.rollback()
        log.info("hero_create_race", profile_id=profile.id)
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="HERO_ALREADY_EXISTS"
        ) from e

    log.info("hero_created", profile_id=profile.id, hero_id=hero.id, name=hero.name)
    return HeroCreated(
        id=hero.id,
        hero_class=hero.hero_class,
        name=hero.name,
        level=hero.level,
        xp=hero.xp,
        unspent_points=hero.unspent_points,
        base_stats=hero.base_stats,
        active_skills=hero.active_skills,
    )

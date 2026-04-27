"""POST /api/v1/heroes — создание Knight в MVP."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.api.deps import current_profile
from wotk.core.db import get_session
from wotk.domain.enums import HeroClass
from wotk.domain.models import Hero, Profile

log = structlog.get_logger()
router = APIRouter(prefix="/heroes", tags=["hero"])


# Дефолтные знания Knight на старте — 4 скилла в hotbar.
# base_stats / unspent_points = server_default из Hero модели.
KNIGHT_DEFAULT_SKILLS = ("cleave", "shield_bash", "whirlwind", "charge")

ERROR_HERO_EXISTS = "HERO_ALREADY_EXISTS"


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
    idempotency_key: Annotated[  # noqa: ARG001 — wired для logger context на W2
        str | None, Header(alias="Idempotency-Key")
    ] = None,
) -> HeroCreated:
    """В MVP создаётся только Knight, max 1 на профиль (uq_hero_profile_class)."""
    hero = Hero(
        profile_id=profile.id,
        hero_class=HeroClass.KNIGHT,
        name=body.name,
        active_skills=list(KNIGHT_DEFAULT_SKILLS),
    )
    session.add(hero)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=ERROR_HERO_EXISTS
        ) from e

    log.info(
        "hero_created", profile_id=profile.id, hero_id=hero.id, name=hero.name
    )
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

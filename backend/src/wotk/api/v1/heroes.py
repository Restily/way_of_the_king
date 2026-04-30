"""POST /api/v1/heroes — создание hero (Knight в MVP)."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.api.deps import current_profile
from wotk.api.idempotency import CachedHttpResponse, begin_idempotent
from wotk.core.db import get_session
from wotk.domain.enums import HeroClass
from wotk.domain.models import Hero, Profile

log = structlog.get_logger()
router = APIRouter(prefix="/heroes", tags=["hero"])


#: Дефолтные знания Knight на старте — 4 скилла в hotbar.
#: ``base_stats`` / ``unspent_points`` берутся из ``server_default`` в Hero модели.
KNIGHT_DEFAULT_SKILLS = ("cleave", "shield_bash", "whirlwind", "charge")

#: Код ошибки 409 при попытке создать второго hero на профиль.
ERROR_HERO_EXISTS = "HERO_ALREADY_EXISTS"


class CreateHeroRequest(BaseModel):
    """Тело запроса POST /heroes.

    :cvar name: Имя персонажа, 3..20 символов. Совпадает с
        ``ck_hero_name_len`` CHECK constraint.
    """

    name: str = Field(min_length=3, max_length=20)


class HeroCreated(BaseModel):
    """Ответ на успешное создание hero.

    :cvar id: PK созданного персонажа.
    :cvar hero_class: Класс (всегда KNIGHT в MVP).
    :cvar name: Подтверждённое имя.
    :cvar level: 1 (стартовый).
    :cvar xp: 0.
    :cvar unspent_points: ``{"stat": 0, "skill": 0}``.
    :cvar base_stats: ``{"str": 10, "dex": 5, "int": 3}``.
    :cvar active_skills: Список 4 default-скиллов.
    """

    id: int
    hero_class: HeroClass
    name: str
    level: int
    xp: int
    unspent_points: dict
    base_stats: dict
    active_skills: list[str]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_hero(
    body: CreateHeroRequest,
    request: Request,
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
    idempotency_key: Annotated[
        str | None,
        # max_length 128 защищает от DoS через гигантский header.
        # UUID = 36 chars, ULID = 26 — 128 c запасом.
        Header(alias="Idempotency-Key", max_length=128),
    ] = None,
) -> JSONResponse:
    """В MVP создаётся только Knight, max 1 на профиль.

    Уникальность гарантируется partial unique index ``uq_hero_profile_class``.
    Race-condition обрабатывается ловлей ``IntegrityError`` (TOCTOU-safe).

    Idempotency: при наличии ``Idempotency-Key`` header — повторный запрос с
    тем же ключом и тем же body вернёт закэшированный ответ (TTL 2h). Запрос
    с тем же ключом и ДРУГИМ body отвергается 422 — клиентская ошибка.

    :param body: :class:`CreateHeroRequest` с именем.
    :param request: Starlette Request — нужен для idempotency body hash.
    :param profile: Авторизованный профиль (через :func:`current_profile`).
    :param session: Async DB session.
    :param idempotency_key: ``Idempotency-Key`` header, опциональный UUID v4.
    :returns: :class:`JSONResponse` со status 201 и :class:`HeroCreated` body.
    :raises HTTPException: 409 ``HERO_ALREADY_EXISTS`` если hero уже есть,
        400 при невалидном формате idempotency-key,
        422 при несовпадении body для уже использованного key.
    """
    idem = await begin_idempotent(
        request=request,
        session=session,
        profile=profile,
        raw_key=idempotency_key,
    )
    if idem.cached_response is not None:
        return JSONResponse(
            status_code=idem.cached_response.status_code,
            content=idem.cached_response.content,
        )

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

    response_body = HeroCreated(
        id=hero.id,
        hero_class=hero.hero_class,
        name=hero.name,
        level=hero.level,
        xp=hero.xp,
        unspent_points=hero.unspent_points,
        base_stats=hero.base_stats,
        active_skills=hero.active_skills,
    ).model_dump(mode="json")

    response = CachedHttpResponse(
        status_code=status.HTTP_201_CREATED, content=response_body
    )
    await idem.store(session, response=response)

    log.info(
        "hero_created", profile_id=profile.id, hero_id=hero.id, name=hero.name
    )
    return JSONResponse(status_code=response.status_code, content=response.content)

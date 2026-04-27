"""POST /api/v1/auth/login + /refresh."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.api.deps import ensure_not_blocked
from wotk.core.config import get_settings
from wotk.core.db import get_session
from wotk.core.geo import get_country_from_request, is_country_blocked
from wotk.core.jwt_auth import (
    JwtError,
    issue_access_token,
    issue_refresh_token,
    verify_token,
)
from wotk.core.limiter import limiter
from wotk.core.telegram_auth import (
    InitDataError,
    InvalidSignature,
    StaleInitData,
    TelegramUser,
    verify_init_data,
)
from wotk.domain.models import Balance, Profile
from wotk.schemas.profile import ProfileSummary

log = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])


SUPPORTED_LOCALES = frozenset({"ru", "en", "es", "pt", "zh", "ar"})


class LoginRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str


class LoginResponse(TokenPair):
    user: ProfileSummary


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


def _default_locale_for(tg: TelegramUser) -> str:
    if tg.language_code in SUPPORTED_LOCALES:
        return tg.language_code
    return "ru"


def _refresh_denormalized_fields(
    profile: Profile, tg: TelegramUser, country: str | None
) -> None:
    """Обновляет profile.* только если значение реально изменилось.

    Защищает от write amplification: 100k DAU × login каждые 5–10 мин =
    десятки UPDATE/sec на абсолютно идентичные значения. SQLA dirty-tracking
    помечает атрибут изменённым на сам факт set-attr, поэтому conditional set.
    """
    if profile.telegram_username != tg.username:
        profile.telegram_username = tg.username
    if profile.telegram_first_name != tg.first_name:
        profile.telegram_first_name = tg.first_name
    if profile.ip_country != country:
        profile.ip_country = country
    profile.last_seen_at = datetime.now(UTC)


@router.post("/login", response_model=LoginResponse)
@limiter.limit("20/minute")
async def login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> LoginResponse:
    settings = get_settings()

    country = get_country_from_request(request)
    if is_country_blocked(country):
        log.info(
            "login_geo_blocked",
            country=country,
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="geo_blocked")

    try:
        verified = verify_init_data(
            body.init_data,
            settings.telegram_bot_token.get_secret_value(),
            ttl_seconds=settings.telegram_initdata_ttl_seconds,
        )
    except (InvalidSignature, StaleInitData) as e:
        log.info("login_init_data_invalid", reason=str(e))
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="invalid_init_data"
        ) from e
    except InitDataError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"malformed_init_data: {e}"
        ) from e

    tg = verified.user

    profile = await session.scalar(
        select(Profile).where(Profile.telegram_id == tg.id)
    )

    if profile is None:
        new_profile = Profile(
            telegram_id=tg.id,
            telegram_username=tg.username,
            telegram_first_name=tg.first_name,
            locale=_default_locale_for(tg),
            ip_country=country,
            last_seen_at=datetime.now(UTC),
        )
        session.add(new_profile)
        try:
            await session.flush()
            session.add(Balance(profile_id=new_profile.id))
            await session.flush()
            profile = new_profile
            log.info("profile_created", profile_id=profile.id, country=country)
        except IntegrityError:
            # Гонка: параллельный login для того же telegram_id успел
            # создать профиль. Откатываем и подтягиваем существующий.
            await session.rollback()
            profile = await session.scalar(
                select(Profile).where(Profile.telegram_id == tg.id)
            )
            if profile is None:
                log.error("profile_race_recovery_failed", telegram_id=tg.id)
                raise HTTPException(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="profile_race_recovery_failed",
                )
            _refresh_denormalized_fields(profile, tg, country)
    else:
        _refresh_denormalized_fields(profile, tg, country)

    ensure_not_blocked(profile)

    return LoginResponse(
        access_token=issue_access_token(profile.id),
        refresh_token=issue_refresh_token(profile.id),
        user=ProfileSummary.model_validate(profile),
    )


@router.post("/refresh", response_model=TokenPair)
@limiter.limit("60/minute")
async def refresh(
    request: Request,  # noqa: ARG001 — нужен для slowapi key_func
    body: RefreshRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenPair:
    try:
        claims = verify_token(body.refresh_token, expected_type="refresh")
    except JwtError as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="invalid_refresh"
        ) from e

    profile = await session.get(Profile, claims.profile_id)
    if profile is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="profile_not_found"
        )
    ensure_not_blocked(profile)

    return TokenPair(
        access_token=issue_access_token(profile.id),
        refresh_token=issue_refresh_token(profile.id),
    )

"""POST /api/v1/auth/login + /refresh."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    verify_init_data,
)
from wotk.domain.models import Balance, Profile

log = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])


SUPPORTED_LOCALES = {"ru", "en", "es", "pt", "zh", "ar"}


class LoginRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str


class UserInfo(BaseModel):
    id: int
    locale: str
    telegram_username: str | None
    is_admin: bool
    withdrawal_2fa_enabled: bool


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserInfo


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


@router.post("/login", response_model=LoginResponse)
@limiter.limit("20/minute")
async def login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> LoginResponse:
    settings = get_settings()

    # 1. Geo-блок
    country = get_country_from_request(request)
    if is_country_blocked(country):
        log.info(
            "login_geo_blocked",
            country=country,
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="geo_blocked"
        )

    # 2. Валидация initData
    try:
        verified = verify_init_data(
            body.init_data,
            settings.telegram_bot_token,
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

    # 3. Найти / создать Profile
    profile = await session.scalar(
        select(Profile).where(Profile.telegram_id == tg.id)
    )

    if profile is None:
        # Дефолтный locale = telegram language_code если в whitelist, иначе 'ru'
        default_locale = (
            tg.language_code
            if tg.language_code in SUPPORTED_LOCALES
            else "ru"
        )
        profile = Profile(
            telegram_id=tg.id,
            telegram_username=tg.username,
            telegram_first_name=tg.first_name,
            locale=default_locale,
            ip_country=country,
            last_seen_at=datetime.now(UTC),
        )
        session.add(profile)
        await session.flush()  # получаем profile.id

        # Дефолтный баланс при первом логине
        session.add(Balance(profile_id=profile.id))
        await session.flush()

        log.info("profile_created", profile_id=profile.id, country=country)
    else:
        # Обновляем denormalized данные с каждым логином
        profile.telegram_username = tg.username
        profile.telegram_first_name = tg.first_name
        profile.ip_country = country
        profile.last_seen_at = datetime.now(UTC)

    if profile.is_blocked:
        log.info("login_blocked_profile", profile_id=profile.id)
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="account_blocked"
        )

    return LoginResponse(
        access_token=issue_access_token(profile.id),
        refresh_token=issue_refresh_token(profile.id),
        user=UserInfo(
            id=profile.id,
            locale=profile.locale,
            telegram_username=profile.telegram_username,
            is_admin=profile.is_admin,
            withdrawal_2fa_enabled=profile.withdrawal_2fa_enabled,
        ),
    )


@router.post("/refresh", response_model=TokenPair)
@limiter.limit("60/minute")
async def refresh(
    request: Request,  # noqa: ARG001 — нужен для slowapi
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
    if profile.is_blocked:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="account_blocked"
        )

    return TokenPair(
        access_token=issue_access_token(profile.id),
        refresh_token=issue_refresh_token(profile.id),
    )

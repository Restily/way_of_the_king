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
from wotk.core.db import get_session
from wotk.core.geo import get_country_from_request, is_country_blocked
from wotk.core.jwt_auth import JwtError, JwtService, get_jwt_service
from wotk.core.limiter import limiter
from wotk.core.telegram_auth import (
    InitDataError,
    InvalidSignature,
    StaleInitData,
    TelegramInitDataValidator,
    TelegramUser,
    get_telegram_validator,
)
from wotk.domain.models import Balance, Profile
from wotk.schemas.profile import ProfileSummary

log = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])


#: Языки, поддерживаемые игрой. Совпадает с CHECK constraint на ``profile.locale``.
SUPPORTED_LOCALES = frozenset({"ru", "en", "es", "pt", "zh", "ar"})


class LoginRequest(BaseModel):
    """Тело запроса POST /auth/login.

    :cvar init_data: Сырой ``Telegram.WebApp.initData`` querystring.
        Длина ограничена 8 KB — Telegram гарантирует укладывание в это.
    """

    init_data: str = Field(min_length=1, max_length=8192)


class TokenPair(BaseModel):
    """Пара access + refresh токенов.

    :cvar access_token: Короткоживущий JWT (~1ч).
    :cvar refresh_token: Долгоживущий JWT (~30 дней).
    """

    access_token: str
    refresh_token: str


class LoginResponse(TokenPair):
    """Ответ на /login: пара токенов + минимальная инфа о юзере.

    :cvar user: :class:`ProfileSummary` для немедленного отображения в UI.
    """

    user: ProfileSummary


class RefreshRequest(BaseModel):
    """Тело запроса POST /auth/refresh.

    :cvar refresh_token: Refresh-JWT, выданный ранее в /login или /refresh.
    """

    refresh_token: str = Field(min_length=1, max_length=4096)


def _default_locale_for(tg: TelegramUser) -> str:
    """Выбрать стартовый locale нового профиля.

    Если ``language_code`` от Telegram входит в :data:`SUPPORTED_LOCALES` —
    используется он. Иначе fallback на ``ru``.

    :param tg: Распарсенный пользователь Telegram.
    :returns: ISO-код языка (один из :data:`SUPPORTED_LOCALES`).
    """
    if tg.language_code in SUPPORTED_LOCALES:
        return tg.language_code
    return "ru"


def _refresh_denormalized_fields(
    profile: Profile, tg: TelegramUser, country: str | None
) -> None:
    """Обновляет ``profile.*`` только если значение реально изменилось.

    Защищает от write amplification: 100k DAU × login каждые 5–10 мин =
    десятки UPDATE/sec на абсолютно идентичные значения. SQLA dirty-tracking
    помечает атрибут изменённым при любом ``set-attr``, поэтому conditional
    set критичен.

    Поле ``last_seen_at`` обновляется всегда — это и есть назначение
    каждого login'а.

    :param profile: Существующий профиль из БД.
    :param tg: Свежие данные пользователя из initData.
    :param country: Страна по ip (или None если не определилась).
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
    validator: TelegramInitDataValidator = Depends(get_telegram_validator),
    jwt_service: JwtService = Depends(get_jwt_service),
) -> LoginResponse:
    """Принять ``initData``, создать/обновить профиль, выдать токены.

    Поток:

    1. Geo-block по IP-стране (CF header → MaxMind в v1+).
    2. HMAC-валидация initData через :class:`TelegramInitDataValidator`.
    3. ``SELECT profile WHERE telegram_id = …``.
    4. Если профиль отсутствует → создаём + Balance.
       При concurrent-login race (IntegrityError) → rollback и
       подтягиваем существующий.
    5. Если есть → обновляем denormalized поля (только при изменении).
    6. Проверка ``is_blocked`` → 403.
    7. Issue access + refresh JWT.

    Rate-limit: 20 req/min на IP.

    :param request: Starlette Request (нужен slowapi key_func).
    :param body: Распарсенный :class:`LoginRequest`.
    :param session: Async DB session.
    :param validator: Telegram initData validator (через DI).
    :param jwt_service: JWT issuer (через DI).
    :returns: :class:`LoginResponse` с парой токенов + summary.
    :raises HTTPException: 403 при geo-block / blocked-account,
        401 при невалидной initData,
        400 при malformed init_data,
        500 при потере profile race recovery.
    """
    country = get_country_from_request(request)
    if is_country_blocked(country):
        log.info(
            "login_geo_blocked",
            country=country,
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="geo_blocked")

    try:
        verified = validator.verify(body.init_data)
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
        access_token=jwt_service.issue_access(profile.id),
        refresh_token=jwt_service.issue_refresh(profile.id),
        user=ProfileSummary.model_validate(profile),
    )


@router.post("/refresh", response_model=TokenPair)
@limiter.limit("60/minute")
async def refresh(
    request: Request,  # noqa: ARG001 — нужен для slowapi key_func
    body: RefreshRequest,
    session: AsyncSession = Depends(get_session),
    jwt_service: JwtService = Depends(get_jwt_service),
) -> TokenPair:
    """Обменять refresh-JWT на новую пару (access + refresh).

    Не делает revocation/rotation в MVP — refresh-токен переиспользуем
    до его истечения (30 дней). Rate-limit: 60 req/min на IP.

    :param request: Starlette Request (slowapi key_func).
    :param body: :class:`RefreshRequest` с refresh-токеном.
    :param session: Async DB session.
    :param jwt_service: JWT verifier + issuer.
    :returns: Новая :class:`TokenPair`.
    :raises HTTPException: 401 при невалидном/истёкшем refresh,
        403 при заблокированном профиле.
    """
    try:
        claims = jwt_service.verify(body.refresh_token, expected_type="refresh")
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
        access_token=jwt_service.issue_access(profile.id),
        refresh_token=jwt_service.issue_refresh(profile.id),
    )

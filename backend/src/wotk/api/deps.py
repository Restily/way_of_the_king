"""FastAPI-зависимости: :func:`current_profile`, :func:`current_admin`,
helpers.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.core.db import get_session
from wotk.core.jwt_auth import (
    JwtExpired,
    JwtInvalid,
    JwtService,
    get_jwt_service,
)
from wotk.domain.models import Profile

log = structlog.get_logger()

# ``auto_error=False`` — отдаём свой JSON-формат ошибок
# (Starlette default возвращает обычный 403/401 без полезного detail).
_bearer = HTTPBearer(auto_error=False, scheme_name="JWT")


def ensure_not_blocked(profile: Profile) -> None:
    """Бросает 403 если аккаунт заблокирован.

    Вызывается из всех auth-флоу — :func:`current_profile`, login, refresh.

    :param profile: Профиль из БД.
    :raises HTTPException: 403 ``account_blocked``.
    """
    if profile.is_blocked:
        log.info("auth_blocked_account_access", profile_id=profile.id)
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="account_blocked"
        )


async def current_profile(
    creds: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
    session: AsyncSession = Depends(get_session),
    jwt_service: JwtService = Depends(get_jwt_service),
) -> Profile:
    """Извлекает :class:`Profile` из JWT в Authorization header.

    Используется как зависимость на защищённых эндпоинтах::

        @router.get("/me")
        async def get_me(profile: Profile = Depends(current_profile)):
            ...

    :param creds: Bearer-credentials, парсится FastAPI-механизмом
        :class:`HTTPBearer`.
    :param session: Async DB session.
    :param jwt_service: Сервис верификации JWT.
    :returns: Загруженный :class:`Profile`.
    :raises HTTPException: 401 при отсутствующем/невалидном токене,
        403 при заблокированном профиле.
    """
    if creds is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="missing_auth_header"
        )

    try:
        claims = jwt_service.verify(creds.credentials, expected_type="access")
    except JwtExpired as e:
        log.info("auth_token_expired")
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="expired_token"
        ) from e
    except JwtInvalid as e:
        log.info("auth_token_invalid", reason=str(e))
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="invalid_token"
        ) from e

    profile = await session.get(Profile, claims.profile_id)
    if profile is None:
        log.warning("auth_token_profile_not_found", profile_id=claims.profile_id)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="profile_not_found"
        )
    ensure_not_blocked(profile)
    return profile


async def current_admin(
    profile: Profile = Depends(current_profile),
) -> Profile:
    """Дополнительная проверка ``is_admin=true`` поверх :func:`current_profile`.

    :param profile: Профиль авторизованного юзера.
    :returns: Тот же профиль (для chained Depends).
    :raises HTTPException: 403 ``admin_required`` если юзер не админ.
    """
    if not profile.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="admin_required"
        )
    return profile

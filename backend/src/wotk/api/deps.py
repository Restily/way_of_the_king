"""FastAPI dependencies: current_profile, current_admin, helpers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.core.db import get_session
from wotk.core.jwt_auth import JwtExpired, JwtInvalid, verify_token
from wotk.domain.models import Profile

# auto_error=False, чтобы вернуть наш JSON-формат ошибок (а не Starlette default)
_bearer = HTTPBearer(auto_error=False, scheme_name="JWT")


def ensure_not_blocked(profile: Profile) -> None:
    """Бросает 403 если аккаунт заблокирован. Используется во всех auth-флоу."""
    if profile.is_blocked:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="account_blocked"
        )


async def current_profile(
    creds: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
    session: AsyncSession = Depends(get_session),
) -> Profile:
    """Извлекает Profile из JWT в Authorization header."""
    if creds is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="missing_auth_header"
        )

    try:
        claims = verify_token(creds.credentials, expected_type="access")
    except JwtExpired as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="expired_token"
        ) from e
    except JwtInvalid as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="invalid_token"
        ) from e

    profile = await session.get(Profile, claims.profile_id)
    if profile is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="profile_not_found"
        )
    ensure_not_blocked(profile)
    return profile


async def current_admin(
    profile: Profile = Depends(current_profile),
) -> Profile:
    """Дополнительная проверка is_admin=true."""
    if not profile.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="admin_required"
        )
    return profile

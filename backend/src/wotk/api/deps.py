"""FastAPI dependencies: current_profile, current_admin."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.core.db import get_session
from wotk.core.jwt_auth import JwtError, verify_token
from wotk.domain.models import Profile


async def current_profile(
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
) -> Profile:
    """Извлекает Profile из JWT в Authorization header."""
    if not authorization:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="missing_auth_header"
        )
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="malformed_auth_header"
        )
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="empty_token"
        )

    try:
        claims = verify_token(token, expected_type="access")
    except JwtError as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail=f"invalid_token: {e}"
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

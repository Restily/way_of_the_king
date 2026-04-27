"""Pydantic-схемы профиля. Используются в auth и me роутерах."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProfileSummary(BaseModel):
    """Минимальная инфа о профиле — возвращается в auth/login response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    locale: str
    telegram_username: str | None
    is_admin: bool
    withdrawal_2fa_enabled: bool


class ProfileFull(ProfileSummary):
    """Полная инфа — возвращается в GET /me."""

    created_at: datetime

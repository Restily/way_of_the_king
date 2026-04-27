"""Pydantic-схемы профиля для API responses.

Используются в ``api/v1/auth`` (login response) и ``api/v1/me``
(GET /me response). Конструируются из ORM-модели :class:`Profile`
через ``ProfileSummary.model_validate(profile)``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProfileSummary(BaseModel):
    """Минимальная инфа о профиле — возвращается в ``/auth/login`` response.

    Только поля нужные клиенту сразу после логина. Не содержит
    серверных служебных полей (block_reason, last_seen_at, и т.д.).

    :cvar id: Внутренний PK профиля.
    :cvar locale: Код языка (``ru``, ``en``, ``es``, ``pt``, ``zh``, ``ar``).
    :cvar telegram_username: ``@username`` из Telegram (может быть ``None``).
    :cvar is_admin: Признак админ-доступа.
    :cvar withdrawal_2fa_enabled: 2FA-флаг для вывода средств.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    locale: str
    telegram_username: str | None
    is_admin: bool
    withdrawal_2fa_enabled: bool


class ProfileFull(ProfileSummary):
    """Полная инфа — возвращается в ``GET /me``.

    Расширяет :class:`ProfileSummary` полем ``created_at``.

    :cvar created_at: Время регистрации профиля (UTC).
    """

    created_at: datetime

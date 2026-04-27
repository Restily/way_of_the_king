"""HMAC-валидация Telegram Mini App initData через :class:`TelegramInitDataValidator`.

Спецификация:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

Алгоритм:

1. Распарсить ``initData`` как querystring.
2. Извлечь и убрать ``hash``.
3. Собрать ``data_check_string``: отсортированные ``key=value`` через ``\\n``.
4. ``secret_key = HMAC-SHA256(message=bot_token, key=b"WebAppData")``.
5. ``expected_hash = HMAC-SHA256(message=data_check_string, key=secret_key).hexdigest()``.
6. Сравнить с переданным ``hash`` (constant-time через :func:`hmac.compare_digest`).
7. Проверить, что ``auth_date`` не старше TTL.

Сервис инжектируется в FastAPI-эндпоинты через
``Depends(get_telegram_validator)``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qsl

from wotk.core.config import get_settings


# ============================================================================
# Exceptions
# ============================================================================


class InitDataError(Exception):
    """Базовый класс ошибок валидации initData."""


class InvalidSignature(InitDataError):
    """HMAC-подпись не сходится."""


class StaleInitData(InitDataError):
    """``auth_date`` старше TTL."""


class MalformedInitData(InitDataError):
    """``initData`` не парсится или нет обязательных полей."""


# ============================================================================
# Data classes
# ============================================================================


@dataclass(frozen=True, slots=True)
class TelegramUser:
    """Данные пользователя из ``initData.user`` (распарсенный JSON).

    :ivar id: Telegram user ID (int64).
    :ivar first_name: Имя пользователя (может быть ``None``).
    :ivar last_name: Фамилия (может быть ``None``).
    :ivar username: ``@username`` без префикса (может быть ``None``).
    :ivar language_code: ISO-код языка от Telegram (``ru``, ``en``, …).
    :ivar is_premium: Признак Telegram Premium.
    :ivar raw: Полный raw dict от Telegram — на случай если нужны
        нестандартные поля.
    """

    id: int
    first_name: str | None
    last_name: str | None
    username: str | None
    language_code: str | None
    is_premium: bool
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VerifiedInitData:
    """Результат успешной валидации initData.

    :ivar user: Распарсенный :class:`TelegramUser`.
    :ivar auth_date: Unix-timestamp подписи initData.
    :ivar raw_params: Все параметры initData кроме ``hash``
        (для отладки/аудита).
    """

    user: TelegramUser
    auth_date: int
    raw_params: dict[str, str]


# ============================================================================
# TelegramInitDataValidator
# ============================================================================


class TelegramInitDataValidator:
    """Валидатор Telegram initData по официальной спеке.

    Хранит ``bot_token`` и pre-computed ``secret_key`` (HMAC от
    ``WebAppData`` с ключом ``bot_token``) — экономит один HMAC-вызов
    на каждую валидацию.

    :ivar _bot_token: Токен бота.
    :ivar _ttl_seconds: Допустимая давность ``auth_date``.
    :ivar _secret_key: Производный ключ для HMAC проверки.
    """

    def __init__(self, *, bot_token: str, ttl_seconds: int = 86400) -> None:
        """Создать валидатор для конкретного бота.

        :param bot_token: Telegram bot token (из BotFather).
        :param ttl_seconds: Максимальная давность ``auth_date``.
            Telegram официально рекомендует 24 часа (86400).
        :raises ValueError: Если ``bot_token`` пустой.
        """
        if not bot_token:
            raise ValueError("bot_token must not be empty")
        self._bot_token = bot_token
        self._ttl_seconds = ttl_seconds
        self._secret_key = hmac.new(
            b"WebAppData", bot_token.encode(), hashlib.sha256
        ).digest()

    def verify(
        self, init_data: str, *, now: int | None = None
    ) -> VerifiedInitData:
        """Валидирует initData и возвращает распарсенные данные.

        :param init_data: Querystring из ``Telegram.WebApp.initData``.
        :param now: Override Unix-timestamp для проверки TTL (для тестов).
        :returns: :class:`VerifiedInitData` с распарсенным user и auth_date.
        :raises MalformedInitData: Формат не валиден или нет
            ``hash``/``user``/``auth_date``.
        :raises InvalidSignature: HMAC не сходится.
        :raises StaleInitData: ``auth_date`` старше TTL.
        """
        if not init_data:
            raise MalformedInitData("init_data is empty")

        params = dict(parse_qsl(init_data, keep_blank_values=True))

        received_hash = params.pop("hash", None)
        if not received_hash:
            raise MalformedInitData("hash is missing")
        if "user" not in params:
            raise MalformedInitData("user is missing")
        if "auth_date" not in params:
            raise MalformedInitData("auth_date is missing")

        try:
            auth_date = int(params["auth_date"])
        except ValueError as e:
            raise MalformedInitData(
                f"auth_date not int: {params['auth_date']}"
            ) from e

        current = now if now is not None else int(time.time())
        if current - auth_date > self._ttl_seconds:
            raise StaleInitData(
                f"auth_date is {current - auth_date}s old (max {self._ttl_seconds})"
            )

        data_check_string = "\n".join(
            f"{k}={params[k]}" for k in sorted(params.keys())
        )
        expected_hash = hmac.new(
            self._secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_hash, received_hash):
            raise InvalidSignature("HMAC mismatch")

        try:
            user_raw = json.loads(params["user"])
        except json.JSONDecodeError as e:
            raise MalformedInitData(f"user is not valid JSON: {e}") from e

        if "id" not in user_raw or user_raw["id"] is None:
            raise MalformedInitData("user.id is missing")

        user = TelegramUser(
            id=int(user_raw["id"]),
            first_name=user_raw.get("first_name"),
            last_name=user_raw.get("last_name"),
            username=user_raw.get("username"),
            language_code=user_raw.get("language_code"),
            is_premium=bool(user_raw.get("is_premium", False)),
            raw=user_raw,
        )

        return VerifiedInitData(
            user=user, auth_date=auth_date, raw_params=params
        )


# ============================================================================
# DI factory
# ============================================================================


@lru_cache(maxsize=1)
def get_telegram_validator() -> TelegramInitDataValidator:
    """Возвращает синглтон-инстанс :class:`TelegramInitDataValidator`.

    Предполагает что ``settings.telegram_bot_token`` непустой —
    в dev допускается, в staging/production падает на старте через
    Pydantic-валидатор в :mod:`wotk.core.config`.

    :returns: Валидатор с pre-computed ``secret_key``.
    :raises ValueError: Если ``telegram_bot_token`` пуст.
    """
    settings = get_settings()
    return TelegramInitDataValidator(
        bot_token=settings.telegram_bot_token.get_secret_value(),
        ttl_seconds=settings.telegram_initdata_ttl_seconds,
    )

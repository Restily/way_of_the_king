"""HMAC-валидация Telegram Mini App initData.

Спецификация:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

Алгоритм:
1. Распарсить initData как querystring
2. Извлечь и убрать `hash`
3. Собрать data_check_string: отсортированные `key=value` через `\n`
4. secret_key = HMAC-SHA256(message=bot_token, key=b"WebAppData")
5. expected_hash = HMAC-SHA256(message=data_check_string, key=secret_key).hexdigest()
6. Сравнить с переданным `hash` (constant-time)
7. Проверить, что `auth_date` не старше TTL
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl


class InitDataError(Exception):
    """Базовый класс ошибок валидации initData."""


class InvalidSignature(InitDataError):
    """HMAC-подпись не сходится."""


class StaleInitData(InitDataError):
    """auth_date слишком стар (> TTL)."""


class MalformedInitData(InitDataError):
    """initData не парсится или нет обязательных полей."""


@dataclass(frozen=True, slots=True)
class TelegramUser:
    """Данные пользователя из initData.user (распарсенный JSON)."""

    id: int
    first_name: str | None
    last_name: str | None
    username: str | None
    language_code: str | None
    is_premium: bool
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VerifiedInitData:
    user: TelegramUser
    auth_date: int  # unix timestamp
    raw_params: dict[str, str]


def verify_init_data(
    init_data: str,
    bot_token: str,
    *,
    ttl_seconds: int = 86400,
    now: int | None = None,
) -> VerifiedInitData:
    """Валидирует initData и возвращает распарсенные данные.

    Raises:
        MalformedInitData: формат не валиден или нет user/hash/auth_date
        InvalidSignature: HMAC не сходится
        StaleInitData: auth_date старше TTL
    """
    if not init_data:
        raise MalformedInitData("init_data is empty")

    if not bot_token:
        raise MalformedInitData("bot_token is empty")

    # parse_qsl сохраняет порядок и URL-декодирует значения
    params = dict(parse_qsl(init_data, keep_blank_values=True))

    received_hash = params.pop("hash", None)
    if not received_hash:
        raise MalformedInitData("hash is missing")

    if "user" not in params:
        raise MalformedInitData("user is missing")

    if "auth_date" not in params:
        raise MalformedInitData("auth_date is missing")

    # Проверка свежести
    try:
        auth_date = int(params["auth_date"])
    except ValueError as e:
        raise MalformedInitData(f"auth_date not int: {params['auth_date']}") from e

    current = now if now is not None else int(time.time())
    if current - auth_date > ttl_seconds:
        raise StaleInitData(
            f"auth_date is {current - auth_date}s old (max {ttl_seconds})"
        )

    # data_check_string: sorted key=value через \n
    data_check_string = "\n".join(
        f"{k}={params[k]}" for k in sorted(params.keys())
    )

    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise InvalidSignature("HMAC mismatch")

    # Парсим user
    try:
        user_raw = json.loads(params["user"])
    except json.JSONDecodeError as e:
        raise MalformedInitData(f"user is not valid JSON: {e}") from e

    if "id" not in user_raw:
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

    return VerifiedInitData(user=user, auth_date=auth_date, raw_params=params)

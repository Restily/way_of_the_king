"""Общие утилиты для тестов."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import quote


def build_init_data(
    *,
    bot_token: str,
    telegram_id: int = 12345,
    user_extra: dict | None = None,
    auth_date: int | None = None,
    extra_params: dict | None = None,
    bad_hash: bool = False,
) -> str:
    """Строит валидную (или с заведомо плохим hash) Telegram initData querystring.

    Используется в test_telegram_auth и e2e test_api_flow — единая реализация
    защищает от рассинхрона если HMAC-схема Telegram изменится.
    """
    user = {
        "id": telegram_id,
        "first_name": "Test",
        "username": f"user{telegram_id}",
        "language_code": "en",
        **(user_extra or {}),
    }
    if auth_date is None:
        auth_date = int(time.time())

    params: dict[str, str] = {
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(auth_date),
        "query_id": f"AAH{telegram_id}",
        **(extra_params or {}),
    }

    data_check_string = "\n".join(
        f"{k}={params[k]}" for k in sorted(params.keys())
    )
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()
    h = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if bad_hash:
        h = "deadbeef" * 8

    parts = [f"{quote(k)}={quote(params[k])}" for k in params]
    parts.append(f"hash={h}")
    return "&".join(parts)

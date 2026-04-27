"""Sentry initialization с обязательной редакцией secrets/PII.

Это критически важно: mnemonic горячего кошелька, JWT secrets, токены —
никогда не должны попадать в внешний сервис. Лучше потерять отчёт об ошибке,
чем утечь секрет.
"""

from __future__ import annotations

import re
from typing import Any

import sentry_sdk
import structlog

from wotk.core.config import Settings

log = structlog.get_logger()

# Поля по имени, значения которых редактируются всегда
SENSITIVE_FIELD_NAMES = frozenset({
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "x-csrf-token",
    "jwt",
    "jwt_secret",
    "internal_hmac_secret",
    "internal_hmac_realtime_to_api",
    "internal_hmac_api_to_realtime",
    "telegram_bot_token",
    "tfa_code",
    "tfa_code_hash",
    "mnemonic",
    "hot_wallet_mnemonic",
    "seed",
    "private_key",
    "api_key",
    "ton_rpc_api_key",
    "init_data",
    "initdata",
    "ws_token",
    "access_token",
    "refresh_token",
    "idempotency_key",
})

# Mnemonic-подобная строка: 12-24 lowercase английских слова через пробел
MNEMONIC_PATTERN = re.compile(r"^[a-z]+(?:\s+[a-z]+){11,23}$")

# JWT-подобная строка: три base64url секции через точку
JWT_PATTERN = re.compile(r"^eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")

REDACTED = "***REDACTED***"
MAX_RECURSION_DEPTH = 20


def _looks_sensitive(value: str) -> bool:
    """Эвристика: похоже ли значение на секрет, даже если ключ не подозрительный."""
    stripped = value.strip()
    if MNEMONIC_PATTERN.match(stripped.lower()):
        return True
    if JWT_PATTERN.match(stripped):
        return True
    return False


def _redact(obj: Any, depth: int = 0) -> Any:
    if depth > MAX_RECURSION_DEPTH:
        return REDACTED  # подозрительная глубина — лучше схлопнуть
    if isinstance(obj, dict):
        result: dict[Any, Any] = {}
        for k, v in obj.items():
            key_lower = k.lower() if isinstance(k, str) else ""
            if key_lower in SENSITIVE_FIELD_NAMES:
                result[k] = REDACTED
            else:
                result[k] = _redact(v, depth + 1)
        return result
    if isinstance(obj, list):
        return [_redact(v, depth + 1) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_redact(v, depth + 1) for v in obj)
    if isinstance(obj, str) and _looks_sensitive(obj):
        return REDACTED
    return obj


def _before_send(event: dict, _hint: dict) -> dict | None:
    """Sentry before_send hook. При любой ошибке внутри — drop event целиком."""
    try:
        return _redact(event)
    except Exception:
        log.exception("sentry_redaction_failed_dropping_event")
        return None


def init_sentry(settings: Settings) -> None:
    dsn = settings.sentry_dsn.get_secret_value()
    if not dsn:
        return

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=settings.app_env,
            before_send=_before_send,
            send_default_pii=False,
            traces_sample_rate=0.1 if settings.app_env == "production" else 1.0,
            max_request_body_size="never",
            attach_stacktrace=True,
            include_local_variables=False,  # local vars могут содержать секреты
        )
        log.info("sentry_initialized", env=settings.app_env)
    except Exception:
        log.exception("sentry_init_failed")

"""Общие утилиты для тестов."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from urllib.parse import quote

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

#: Bot-токен под которым подписываются initData во всех e2e-тестах.
#: Зеркально определён в conftest.py — оба должны совпадать.
E2E_BOT_TOKEN = "test:bot_token_for_e2e_tests_1234567890"

#: Internal HMAC-секрет для подписи /api/v1/internal/* запросов.
#: Зеркало conftest.py monkeypatch.setenv("INTERNAL_HMAC_REALTIME_TO_API", ...).
E2E_INTERNAL_HMAC_SECRET = b"test_internal_hmac_realtime_to_api_e2e"


async def login_e2e(client: AsyncClient, *, telegram_id: int) -> str:
    """Залогинить юзера через POST /auth/login и вернуть access_token.

    Используется в любом e2e-тесте для setup'а авторизованной сессии.
    """
    init_data = build_init_data(bot_token=E2E_BOT_TOKEN, telegram_id=telegram_id)
    r = await client.post("/api/v1/auth/login", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


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


def sign_internal_body(body_bytes: bytes) -> str:
    """HMAC-SHA256 hex над raw body — для /api/v1/internal/* тестов.

    Use case::

        body_bytes = json.dumps(payload, separators=(",", ":")).encode()
        sig = sign_internal_body(body_bytes)
        await client.post(url, content=body_bytes,
                          headers={"X-Internal-Sig": sig, ...})
    """
    return hmac.new(
        E2E_INTERNAL_HMAC_SECRET, body_bytes, hashlib.sha256
    ).hexdigest()


@dataclass(frozen=True)
class SetupResult:
    """Результат :func:`setup_user_with_funds`."""

    access_token: str
    profile_id: int
    hero_id: int


async def setup_user_with_funds(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    telegram_id: int,
    name: str = "TestKnight",
    gold: int | None = None,
    energy: int | None = None,
) -> SetupResult:
    """Залогинить юзера, создать hero, опционально пополнить балансы.

    Используется в любом e2e-тесте который требует authenticated user с hero
    и (опционально) деньгами для платных операций (dungeon /enter и т.п.).

    Импортируется поздно (внутри функции) чтобы избежать circular imports
    при загрузке pytest-фикстур.
    """
    from wotk.domain.models import Balance, Hero, Profile

    access = await login_e2e(client, telegram_id=telegram_id)
    headers = {"Authorization": f"Bearer {access}"}
    r = await client.post(
        "/api/v1/heroes",
        json={"name": name},
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201, r.text

    profile = await db_session.scalar(
        select(Profile).where(Profile.telegram_id == telegram_id)
    )
    assert profile is not None
    hero = await db_session.scalar(
        select(Hero).where(Hero.profile_id == profile.id)
    )
    assert hero is not None

    if gold is not None or energy is not None:
        balance = await db_session.scalar(
            select(Balance).where(Balance.profile_id == profile.id)
        )
        assert balance is not None
        if gold is not None:
            balance.gold = gold
        if energy is not None:
            balance.energy = energy
        await db_session.commit()

    return SetupResult(access_token=access, profile_id=profile.id, hero_id=hero.id)

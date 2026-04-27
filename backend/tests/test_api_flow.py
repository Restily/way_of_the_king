"""End-to-end тесты auth → hero creation → /me."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import AsyncIterator
from urllib.parse import quote

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from wotk.api.main import app
from wotk.core.config import get_settings
from wotk.core.db import get_session


def _build_init_data(telegram_id: int) -> str:
    """Строит валидную initData с current bot_token из settings."""
    settings = get_settings()
    user = {
        "id": telegram_id,
        "first_name": "Test",
        "username": f"user{telegram_id}",
        "language_code": "ru",
    }
    params = {
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(int(time.time())),
        "query_id": "AAH" + str(telegram_id),
    }
    data_check_string = "\n".join(
        f"{k}={params[k]}" for k in sorted(params.keys())
    )
    secret_key = hmac.new(
        b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256
    ).digest()
    h = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    parts = [f"{quote(k)}={quote(params[k])}" for k in params]
    parts.append(f"hash={h}")
    return "&".join(parts)


@pytest_asyncio.fixture
async def client(test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:  # noqa: ARG001
    """HTTP-клиент с подменённой DB session на test_engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    test_factory = async_sessionmaker(
        bind=test_engine, expire_on_commit=False, autoflush=False
    )

    async def override_get_session():
        async with test_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    # Telegram token — нужен для initData валидации в login
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test:bot_token_for_e2e_tests_1234567890")
    # Очищаем кэш get_settings чтобы взять новый token
    get_settings.cache_clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_full_flow_login_create_hero_get_me(client: AsyncClient) -> None:
    """Сценарий: новый юзер → login → POST /heroes → GET /me показывает hero."""
    init_data = _build_init_data(telegram_id=11111)

    # 1. Login
    r = await client.post("/api/v1/auth/login", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["telegram_username"] == "user11111"
    assert data["user"]["is_admin"] is False

    access = data["access_token"]
    auth_headers = {"Authorization": f"Bearer {access}"}

    # 2. /me — нет ещё hero
    r = await client.get("/api/v1/me", headers=auth_headers)
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["hero"] is None
    assert me["balance"]["gold"] == 0
    assert me["balance"]["energy"] == 100

    # 3. Create hero
    r = await client.post(
        "/api/v1/heroes",
        json={"name": "Galahad"},
        headers={**auth_headers, "Idempotency-Key": "test-key-1"},
    )
    assert r.status_code == 201, r.text
    hero = r.json()
    assert hero["name"] == "Galahad"
    assert hero["hero_class"] == 0  # KNIGHT
    assert hero["level"] == 1
    assert hero["base_stats"] == {"str": 10, "dex": 5, "int": 3}
    assert hero["unspent_points"] == {"stat": 0, "skill": 0}
    assert "cleave" in hero["active_skills"]

    # 4. Повторное создание → 409
    r = await client.post(
        "/api/v1/heroes",
        json={"name": "Mordred"},
        headers={**auth_headers, "Idempotency-Key": "test-key-2"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "HERO_ALREADY_EXISTS"

    # 5. /me теперь показывает hero
    r = await client.get("/api/v1/me", headers=auth_headers)
    assert r.status_code == 200
    me = r.json()
    assert me["hero"] is not None
    assert me["hero"]["name"] == "Galahad"


@pytest.mark.asyncio
async def test_login_invalid_init_data(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/login",
        json={"init_data": "user=%7B%22id%22%3A1%7D&hash=deadbeef&auth_date=1"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/api/v1/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_with_invalid_token(client: AsyncClient) -> None:
    r = await client.get(
        "/api/v1/me", headers={"Authorization": "Bearer not.a.real.jwt"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_hero_name_too_short(client: AsyncClient) -> None:
    init_data = _build_init_data(telegram_id=22222)
    r = await client.post("/api/v1/auth/login", json={"init_data": init_data})
    access = r.json()["access_token"]

    r = await client.post(
        "/api/v1/heroes",
        json={"name": "X"},  # < 3 chars
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 422  # Pydantic validation

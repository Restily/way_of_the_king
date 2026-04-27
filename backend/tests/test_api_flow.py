"""End-to-end тесты auth → hero creation → /me."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from wotk.api.main import app
from wotk.core.config import get_settings
from wotk.core.db import get_session

from ._helpers import build_init_data

BOT_TOKEN = "test:bot_token_for_e2e_tests_1234567890"


@pytest_asyncio.fixture
async def client(
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ARG001 — нужен для get_settings reset
) -> AsyncIterator[AsyncClient]:
    """HTTP-клиент с подменённой DB session на test_engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    test_factory = async_sessionmaker(
        bind=test_engine, expire_on_commit=False, autoflush=False
    )

    async def override_get_session():
        async with test_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    get_settings.cache_clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_full_flow_login_create_hero_get_me(client: AsyncClient) -> None:
    init_data = build_init_data(bot_token=BOT_TOKEN, telegram_id=11111)

    r = await client.post("/api/v1/auth/login", json={"init_data": init_data})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["telegram_username"] == "user11111"
    assert data["user"]["is_admin"] is False

    auth_headers = {"Authorization": f"Bearer {data['access_token']}"}

    r = await client.get("/api/v1/me", headers=auth_headers)
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["hero"] is None
    assert me["balance"]["gold"] == 0
    assert me["balance"]["energy"] == 100

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

    r = await client.post(
        "/api/v1/heroes",
        json={"name": "Mordred"},
        headers={**auth_headers, "Idempotency-Key": "test-key-2"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "HERO_ALREADY_EXISTS"

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
    # Generic detail (не raw exception message)
    assert r.json()["detail"] == "invalid_token"


@pytest.mark.asyncio
async def test_create_hero_name_too_short(client: AsyncClient) -> None:
    init_data = build_init_data(bot_token=BOT_TOKEN, telegram_id=22222)
    r = await client.post("/api/v1/auth/login", json={"init_data": init_data})
    access = r.json()["access_token"]

    r = await client.post(
        "/api/v1/heroes",
        json={"name": "X"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 422  # Pydantic validation

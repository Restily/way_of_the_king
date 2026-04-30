"""End-to-end тесты auth → hero creation → /me."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from ._helpers import E2E_BOT_TOKEN, build_init_data, login_e2e


@pytest.mark.asyncio
async def test_full_flow_login_create_hero_get_me(client: AsyncClient) -> None:
    init_data = build_init_data(bot_token=E2E_BOT_TOKEN, telegram_id=11111)

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
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
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
        headers={**auth_headers, "Idempotency-Key": str(uuid.uuid4())},
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
    access = await login_e2e(client, telegram_id=22222)
    r = await client.post(
        "/api/v1/heroes",
        json={"name": "X"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 422  # Pydantic validation

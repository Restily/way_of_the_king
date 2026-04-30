"""Smoke-тесты /health эндпоинта и security defaults."""

import pytest
from httpx import ASGITransport, AsyncClient

from wotk.api.main import app


@pytest.mark.asyncio
async def test_health_returns_ok() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_does_not_leak_version() -> None:
    """Публичный health не должен раскрывать версию (помогает таргетить CVE)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    data = response.json()
    assert "version" not in data
    assert "build" not in data


@pytest.mark.asyncio
async def test_health_ready_returns_alembic_version(client: AsyncClient) -> None:
    """/health/ready должен подтверждать миграции и postgres ping.

    Использует ``client`` fixture — там test_engine с применёнными миграциями,
    значит alembic_version должен быть != null.
    """
    r = await client.get("/health/ready")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ready"
    assert data["checks"]["postgres"] == "ok"
    # Не пинимся к конкретной ревизии — иначе assert ломается на каждой миграции.
    assert data["checks"]["migrations"]
    assert data["checks"]["migrations"] != "no alembic_version row"
    # Redis + Arq (W3-052) — Redis должен быть поднят в test compose.
    assert data["checks"]["redis"] == "ok"
    assert isinstance(data["checks"]["arq_queue"], int)


@pytest.mark.asyncio
async def test_cors_does_not_allow_wildcard() -> None:
    """CORS никогда не должен возвращать allow-origin: * — даже в dev."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    # Либо 400, либо без allow-origin для неизвестного origin
    allow_origin = response.headers.get("access-control-allow-origin")
    assert allow_origin != "*"
    assert allow_origin != "https://evil.example.com"

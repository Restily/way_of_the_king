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

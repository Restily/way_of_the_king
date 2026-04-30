"""Тесты idempotency middleware на POST /api/v1/heroes.

Покрытие:

* Cache hit: повторный запрос с тем же ключом и body → закэшированный 201.
* Body mismatch: тот же ключ + другое body → 422.
* Невалидный UUID в header → 400.
* Без header вообще — обычный flow.
* Один UUID разных юзеров не конфликтует (PK = key + profile_id).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from ._helpers import login_e2e


@pytest.mark.asyncio
async def test_idempotent_replay_returns_cached_response(
    client: AsyncClient,
) -> None:
    """Тот же UUID + то же body → точно тот же ответ, второго hero не создаётся."""
    access = await login_e2e(client, telegram_id=30001)
    headers_base = {"Authorization": f"Bearer {access}"}
    idem = str(uuid.uuid4())

    r1 = await client.post(
        "/api/v1/heroes",
        json={"name": "Lancelot"},
        headers={**headers_base, "Idempotency-Key": idem},
    )
    assert r1.status_code == 201
    body1 = r1.json()

    # Повтор → должно вернуться то же самое (закэшировано), не 409
    r2 = await client.post(
        "/api/v1/heroes",
        json={"name": "Lancelot"},
        headers={**headers_base, "Idempotency-Key": idem},
    )
    assert r2.status_code == 201
    assert r2.json() == body1


@pytest.mark.asyncio
async def test_idempotent_body_mismatch_returns_422(client: AsyncClient) -> None:
    """Тот же UUID + другое body → 422, hero не создаётся."""
    access = await login_e2e(client, telegram_id=30002)
    headers_base = {"Authorization": f"Bearer {access}"}
    idem = str(uuid.uuid4())

    r1 = await client.post(
        "/api/v1/heroes",
        json={"name": "Percival"},
        headers={**headers_base, "Idempotency-Key": idem},
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/api/v1/heroes",
        json={"name": "Tristan"},
        headers={**headers_base, "Idempotency-Key": idem},
    )
    assert r2.status_code == 422
    assert r2.json()["detail"] == "idempotency_key_body_mismatch"


@pytest.mark.asyncio
async def test_invalid_uuid_format_returns_400(client: AsyncClient) -> None:
    """Не-UUID строка в Idempotency-Key → 400, hero не создаётся."""
    access = await login_e2e(client, telegram_id=30003)

    r = await client.post(
        "/api/v1/heroes",
        json={"name": "Gawain"},
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": "not-a-uuid-at-all",
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_idempotency_key_format"


@pytest.mark.asyncio
async def test_no_idempotency_header_works_as_before(client: AsyncClient) -> None:
    """Без header — обычный create, никакой идемпотентности."""
    access = await login_e2e(client, telegram_id=30004)

    r = await client.post(
        "/api/v1/heroes",
        json={"name": "Bedivere"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Bedivere"


@pytest.mark.asyncio
async def test_different_users_can_use_same_uuid(client: AsyncClient) -> None:
    """PK = (key, profile_id) — один UUID разных юзеров не конфликтует."""
    shared_idem = str(uuid.uuid4())

    access_a = await login_e2e(client, telegram_id=30005)
    access_b = await login_e2e(client, telegram_id=30006)

    r_a = await client.post(
        "/api/v1/heroes",
        json={"name": "Arthur"},
        headers={
            "Authorization": f"Bearer {access_a}",
            "Idempotency-Key": shared_idem,
        },
    )
    assert r_a.status_code == 201

    r_b = await client.post(
        "/api/v1/heroes",
        json={"name": "Merlin"},
        headers={
            "Authorization": f"Bearer {access_b}",
            "Idempotency-Key": shared_idem,
        },
    )
    assert r_b.status_code == 201
    assert r_a.json()["id"] != r_b.json()["id"]

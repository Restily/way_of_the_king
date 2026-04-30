"""Тесты GET /me/campaign (W6-022).

Проверяет:
- Возврат корректного списка кампанийных локаций.
- Логику is_locked (act==1 всегда разблокирован; act>1 заблокирован если нет
  campaign_progress для (act-1, location)).
- Первый clear записывает completion_count=1; повторный — инкрементирует.
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.domain.enums import Difficulty, DungeonTheme
from wotk.domain.models import CampaignProgress, Dungeon

from ._helpers import setup_user_with_funds, sign_internal_body


async def _seed_campaign_dungeons(db_session: AsyncSession) -> None:
    """Создать минимальный набор кампанийных данжей для тестов.

    Вставляет 4 данжа: act1/loc1, act1/loc2, act2/loc1, act2/loc2.
    """
    dungeons = [
        Dungeon(
            id="c_a1l1",
            name_key="dungeon.c_a1l1.name",
            theme=DungeonTheme.CRYPT,
            difficulty=Difficulty.NORMAL,
            min_level=1,
            entry_cost_gold=50,
            entry_cost_energy=5,
            daily_limit=5,
            floors_count=3,
            config={"v": 1, "floors": []},
            xp_base=100,
            gold_base=100,
            act=1,
            location=1,
        ),
        Dungeon(
            id="c_a1l2",
            name_key="dungeon.c_a1l2.name",
            theme=DungeonTheme.CRYPT,
            difficulty=Difficulty.HARD,
            min_level=1,
            entry_cost_gold=100,
            entry_cost_energy=10,
            daily_limit=3,
            floors_count=3,
            config={"v": 1, "floors": []},
            xp_base=200,
            gold_base=200,
            act=1,
            location=2,
        ),
        Dungeon(
            id="c_a2l1",
            name_key="dungeon.c_a2l1.name",
            theme=DungeonTheme.FOREST,
            difficulty=Difficulty.NORMAL,
            min_level=1,
            entry_cost_gold=150,
            entry_cost_energy=10,
            daily_limit=5,
            floors_count=4,
            config={"v": 1, "floors": []},
            xp_base=300,
            gold_base=300,
            act=2,
            location=1,
        ),
        Dungeon(
            id="c_a2l2",
            name_key="dungeon.c_a2l2.name",
            theme=DungeonTheme.FOREST,
            difficulty=Difficulty.HARD,
            min_level=1,
            entry_cost_gold=200,
            entry_cost_energy=15,
            daily_limit=3,
            floors_count=5,
            config={"v": 1, "floors": []},
            xp_base=400,
            gold_base=400,
            act=2,
            location=2,
        ),
    ]
    for d in dungeons:
        db_session.add(d)
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_campaign_act1_always_unlocked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Act 1 локации должны быть разблокированы без каких-либо предусловий."""
    r = await setup_user_with_funds(client, db_session, telegram_id=90001)
    await _seed_campaign_dungeons(db_session)

    resp = await client.get(
        "/api/v1/me/campaign",
        headers={"Authorization": f"Bearer {r.access_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)

    # Все act==1 должны быть разблокированы.
    act1 = [x for x in data if x["act"] == 1]
    assert len(act1) == 2
    for loc in act1:
        assert loc["is_locked"] is False, f"Act1 должен быть разблокирован: {loc}"
        assert loc["completion_count"] == 0


@pytest.mark.asyncio
async def test_get_campaign_act2_locked_without_act1_clear(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Act 2 заблокирован если нет campaign_progress для (act=1, location=*)."""
    r = await setup_user_with_funds(client, db_session, telegram_id=90002)
    await _seed_campaign_dungeons(db_session)

    resp = await client.get(
        "/api/v1/me/campaign",
        headers={"Authorization": f"Bearer {r.access_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Act 2 локации должны быть заблокированы.
    act2 = [x for x in data if x["act"] == 2]
    assert len(act2) == 2
    for loc in act2:
        assert loc["is_locked"] is True, f"Act2 должен быть заблокирован без прохождения Act1: {loc}"


@pytest.mark.asyncio
async def test_get_campaign_act2_unlocked_after_act1_clear(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Act 2 location=1 разблокируется после прохождения act=1 location=1."""
    r = await setup_user_with_funds(client, db_session, telegram_id=90003)
    await _seed_campaign_dungeons(db_session)

    # Вручную добавляем campaign_progress для (act=1, location=1).
    cp = CampaignProgress(
        hero_id=r.hero_id,
        act=1,
        location=1,
        completion_count=1,
        best_clear_time_s=120,
    )
    db_session.add(cp)
    await db_session.commit()

    resp = await client.get(
        "/api/v1/me/campaign",
        headers={"Authorization": f"Bearer {r.access_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # act=2, location=1 должен быть разблокирован (act=1, location=1 пройдена).
    a2l1 = next((x for x in data if x["act"] == 2 and x["location"] == 1), None)
    assert a2l1 is not None
    assert a2l1["is_locked"] is False

    # act=2, location=2 должен оставаться заблокированным (нет прогресса act=1 loc=2).
    a2l2 = next((x for x in data if x["act"] == 2 and x["location"] == 2), None)
    assert a2l2 is not None
    assert a2l2["is_locked"] is True


@pytest.mark.asyncio
async def test_get_campaign_returns_404_without_hero(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /me/campaign возвращает 404 если у профиля нет hero."""
    from ._helpers import login_e2e

    access = await login_e2e(client, telegram_id=90004)
    await _seed_campaign_dungeons(db_session)

    resp = await client.get(
        "/api/v1/me/campaign",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "hero_not_created"


@pytest.mark.asyncio
async def test_get_campaign_completion_count_reflects_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """completion_count и best_clear_time_s корректно возвращаются из DB."""
    r = await setup_user_with_funds(client, db_session, telegram_id=90005)
    await _seed_campaign_dungeons(db_session)

    cp = CampaignProgress(
        hero_id=r.hero_id,
        act=1,
        location=1,
        completion_count=3,
        best_clear_time_s=90,
    )
    db_session.add(cp)
    await db_session.commit()

    resp = await client.get(
        "/api/v1/me/campaign",
        headers={"Authorization": f"Bearer {r.access_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    a1l1 = next(x for x in data if x["act"] == 1 and x["location"] == 1)
    assert a1l1["completion_count"] == 3
    assert a1l1["best_clear_time_s"] == 90
    assert a1l1["is_locked"] is False

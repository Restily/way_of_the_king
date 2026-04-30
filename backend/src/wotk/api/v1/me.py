"""GET /api/v1/me — текущий профиль + баланс + основной hero + прогресс кампании."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.api.deps import current_profile, load_active_hero
from wotk.core.db import get_session
from wotk.domain.enums import HeroClass
from wotk.domain.models import Balance, CampaignProgress, Dungeon, Hero, Item, ItemBase, Profile
from wotk.game.energy import compute_regenerated
from wotk.game.hero_stats import EquippedItemSnapshot, compute_hero_combat_stats
from wotk.schemas.profile import ProfileFull

log = structlog.get_logger()
router = APIRouter(tags=["profile"])


class BalanceInfo(BaseModel):
    """Баланс юзера для UI.

    :cvar gold: Целое количество gold (1:1 с UI).
    :cvar energy: Текущая энергия с уже применённой lazy regen.
    :cvar energy_cap: Максимум энергии (растёт от пассивок в v1+).
    :cvar energy_updated_at: Время последнего тика регена.
    """

    gold: int
    energy: int
    energy_cap: int
    energy_updated_at: datetime


class HeroInfo(BaseModel):
    """Краткая инфа о hero для главного экрана.

    :cvar id: PK персонажа.
    :cvar hero_class: Класс (knight в MVP).
    :cvar name: Имя игрока.
    :cvar level: Текущий уровень (1..100).
    :cvar xp: Накопленный опыт.
    :cvar unspent_points: ``{"stat": int, "skill": int}``.
    :cvar base_stats: Распределённые ``{"str", "dex", "int"}``.
    """

    id: int
    hero_class: HeroClass
    name: str
    level: int
    xp: int
    unspent_points: dict
    base_stats: dict


class MeResponse(BaseModel):
    """Композит-ответ для GET /me.

    :cvar profile: Полная инфа профиля.
    :cvar balance: Текущий баланс с актуальной энергией.
    :cvar hero: Основной hero, либо ``None`` если не создан.
    """

    profile: ProfileFull
    balance: BalanceInfo
    hero: HeroInfo | None = None


@router.get("/me", response_model=MeResponse)
async def get_me(
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
) -> MeResponse:
    """Возвращает данные текущего юзера: профиль, баланс, основной hero.

    Использует один JOIN-запрос для получения Balance + Hero (вместо
    двух последовательных). Energy регенерируется read-only через
    :func:`compute_regenerated` — никаких UPDATE на каждый poll.

    :param profile: Профиль из JWT (через :func:`current_profile`).
    :param session: Async DB session.
    :returns: :class:`MeResponse` с профилем, балансом и (опционально) hero.
    :raises HTTPException: 500 если ``Balance`` отсутствует
        (баг или ручное удаление — инвариант: создаётся с Profile).
    """
    # Один JOIN-запрос вместо двух последовательных. Outer join на Hero
    # покрывает случай "Hero ещё не создан" — получаем (Balance, None).
    stmt = (
        select(Balance, Hero)
        .outerjoin(
            Hero,
            (Hero.profile_id == Balance.profile_id) & (Hero.deleted_at.is_(None)),
        )
        .where(Balance.profile_id == profile.id)
        .order_by(Hero.id.asc().nulls_last())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        # Инвариант: Balance создаётся вместе с Profile в /auth/login.
        # Отсутствие = баг или ручное удаление, не лечим лениво.
        log.error("balance_missing_for_profile", profile_id=profile.id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="balance_missing"
        )
    balance, hero = row

    # Lazy regen — read-only. Запись в БД только при spend.
    energy_state = compute_regenerated(
        energy=balance.energy,
        energy_cap=balance.energy_cap,
        energy_updated_at=balance.energy_updated_at,
    )

    hero_info: HeroInfo | None = None
    if hero is not None:
        hero_info = HeroInfo(
            id=hero.id,
            hero_class=hero.hero_class,
            name=hero.name,
            level=hero.level,
            xp=hero.xp,
            unspent_points=hero.unspent_points,
            base_stats=hero.base_stats,
        )

    return MeResponse(
        profile=ProfileFull.model_validate(profile),
        balance=BalanceInfo(
            gold=balance.gold,
            energy=energy_state.energy,
            energy_cap=balance.energy_cap,
            energy_updated_at=energy_state.energy_updated_at,
        ),
        hero=hero_info,
    )


# ---------------------------------------------------------------------------
# GET /me/combat-stats
# ---------------------------------------------------------------------------


class CombatStatsResponse(BaseModel):
    """Финальные combat stats hero с учётом equipped items."""

    hp: int
    mana: int
    atk: int
    def_: int
    crit_chance_pct: float
    crit_damage_pct: float
    attack_speed_mult: float
    movement_speed_mult: float
    resist_fire_pct: int
    resist_cold_pct: int
    resist_lightning_pct: int


@router.get("/me/combat-stats", response_model=CombatStatsResponse)
async def get_combat_stats(
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
) -> CombatStatsResponse:
    """Combat stats hero с применёнными бонусами от equipped items.

    Используется UI'ем для показа в "Stats" panel (City экран).
    Также значения попадают в hero_state при /enter.

    :raises HTTPException: 404 hero_not_created.
    """
    # Один outer-join roundtrip: hero + (опционально) equipped items с base'ом.
    # Если у hero нет equipped — outerjoin вернёт одну строку (Hero, None, None).
    rows = (
        await session.execute(
            select(Hero, Item, ItemBase)
            .outerjoin(Item, Item.equipped_on == Hero.id)
            .outerjoin(ItemBase, Item.base_id == ItemBase.id)
            .where(Hero.profile_id == profile.id, Hero.deleted_at.is_(None))
            .order_by(Hero.id.asc())
        )
    ).all()
    if not rows:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="hero_not_created"
        )

    hero = rows[0][0]
    equipped: list[EquippedItemSnapshot] = [
        EquippedItemSnapshot(
            slot=int(base.slot),
            base_stats=dict(base.base_stats),
            affixes=list(item.affixes),
        )
        for _, item, base in rows
        if item is not None and base is not None
    ]

    derived = compute_hero_combat_stats(
        base_stats={
            "str": hero.base_stats.get("str", 0),
            "dex": hero.base_stats.get("dex", 0),
            "int": hero.base_stats.get("int", 0),
        },
        level=hero.level,
        equipped=equipped,
    )

    return CombatStatsResponse(
        hp=derived.hp,
        mana=derived.mana,
        atk=derived.atk,
        def_=derived.def_,
        crit_chance_pct=derived.crit_chance_pct,
        crit_damage_pct=derived.crit_damage_pct,
        attack_speed_mult=derived.attack_speed_mult,
        movement_speed_mult=derived.movement_speed_mult,
        resist_fire_pct=derived.resist_fire_pct,
        resist_cold_pct=derived.resist_cold_pct,
        resist_lightning_pct=derived.resist_lightning_pct,
    )


# ---------------------------------------------------------------------------
# GET /me/campaign
# ---------------------------------------------------------------------------


class CampaignLocationInfo(BaseModel):
    """Один элемент списка кампании — локация в акте.

    :cvar act: Номер акта (1..5).
    :cvar location: Номер локации (1..10).
    :cvar dungeon_id: Stable ID данжа (``crypt_normal``).
    :cvar name_key: i18n якорь для UI.
    :cvar completion_count: Число успешных clear'ов (0 = ни разу).
    :cvar best_clear_time_s: Лучшее время в секундах (None = не пройден).
    :cvar is_locked: True если локация заблокирована (предыдущий акт не пройден).
    """

    act: int
    location: int
    dungeon_id: str
    name_key: str
    completion_count: int
    best_clear_time_s: int | None
    is_locked: bool


@router.get("/me/campaign", response_model=list[CampaignLocationInfo])
async def get_campaign(
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
) -> list[CampaignLocationInfo]:
    """Список всех кампанийных локаций с прогрессом активного героя.

    Возвращает все ``dungeons`` где ``act IS NOT NULL``, отсортированные по
    ``(act, location)``. Для каждой локации делает LEFT JOIN с
    ``campaign_progress`` героя, чтобы заполнить ``completion_count`` и
    ``best_clear_time_s``.

    Логика ``is_locked``:

    * ``act == 1`` — всегда разблокирован (tutorial/начало игры).
    * ``act > 1`` — заблокирован если нет записи в ``campaign_progress``
      для ``(act-1, location)`` для текущего героя.

    :param profile: Авторизованный профиль.
    :param session: Async DB session.
    :returns: Список :class:`CampaignLocationInfo`, отсортированный по act, location.
    :raises HTTPException: 404 если у профиля нет активного героя.
    """
    hero = await load_active_hero(session, profile_id=profile.id)
    if hero is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="hero_not_created")

    # Загружаем все кампанийные данжи.
    dungeons_stmt = (
        select(Dungeon)
        .where(Dungeon.act.is_not(None), Dungeon.location.is_not(None))
        .order_by(Dungeon.act.asc(), Dungeon.location.asc())
    )
    dungeons = (await session.scalars(dungeons_stmt)).all()

    if not dungeons:
        return []

    # Загружаем все campaign_progress записи героя одним запросом.
    cp_rows = (
        await session.scalars(
            select(CampaignProgress).where(CampaignProgress.hero_id == hero.id)
        )
    ).all()
    # Индексируем по (act, location) для быстрого lookup'а.
    cp_index: dict[tuple[int, int], CampaignProgress] = {
        (row.act, row.location): row for row in cp_rows
    }

    result: list[CampaignLocationInfo] = []
    for d in dungeons:
        act = d.act
        loc = d.location
        # Инвариант: act/location не NULL (WHERE выше гарантирует).
        assert act is not None and loc is not None

        cp = cp_index.get((act, loc))
        completion_count = cp.completion_count if cp is not None else 0
        best_clear_time_s = cp.best_clear_time_s if cp is not None else None

        # Логика блокировки: act==1 всегда открыт. act>1 заблокирован
        # если предыдущий акт+та же локация не пройдена.
        if act == 1:
            is_locked = False
        else:
            prev_cp = cp_index.get((act - 1, loc))
            is_locked = prev_cp is None

        result.append(
            CampaignLocationInfo(
                act=act,
                location=loc,
                dungeon_id=d.id,
                name_key=d.name_key,
                completion_count=completion_count,
                best_clear_time_s=best_clear_time_s,
                is_locked=is_locked,
            )
        )

    return result

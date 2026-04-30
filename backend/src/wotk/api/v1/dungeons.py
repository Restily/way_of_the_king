"""GET /api/v1/dungeons + POST /api/v1/dungeons/{id}/enter + POST /api/v1/runs/{id}/flee.

Главные gameplay endpoints W3+W5. Управляют жизненным циклом dungeon_run:

* List enabled dungeons фильтрованных по hero level (в client'е будут показаны
  как карточки в City).
* /enter — payment-critical operation: списание gold/energy, INSERT
  ``dungeon_run`` + ``transaction`` + ``daily_dungeon_entries`` UPSERT,
  выпуск ws_token JWT (короткий 60s TTL) для последующего connect к Colyseus.
* /flee — добровольный выход с возвратом ``pending_gold`` (но не entry cost).
* /internal/finalize — HMAC-protected callback от Colyseus: материализует loot,
  начисляет XP/gold, auto-claim items в inventory, записывает RunEncounter.

Concurrency: /enter под пессимистичной блокировкой ``balance`` row + partial
unique index ``uq_runs_one_active_per_hero`` (status=IN_PROGRESS) гарантирует
что concurrent /enter не создадут два активных run'а на одного героя.
"""

from __future__ import annotations

import random
import secrets
import time
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import jwt as _jwt
import sentry_sdk
import structlog
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wotk.api.deps import current_admin, current_profile, load_active_hero
from wotk.api.idempotency import CachedHttpResponse, begin_idempotent
from wotk.core.config import Settings, get_settings
from wotk.core.db import get_session
from wotk.core.internal_hmac import verify_internal_hmac
from wotk.core.metrics import inc as metrics_inc
from wotk.domain.enums import EncounterResult, Rarity, RunStatus, TransactionType
from wotk.domain.models import (
    Balance,
    CampaignProgress,
    DailyDungeonEntry,
    Dungeon,
    DungeonRun,
    Item,
    ItemBase,
    Profile,
    RunEncounter,
    Transaction,
)
from wotk.game.loot import generate_item
from wotk.game.loot_db import load_affix_pool, materialize_item

log = structlog.get_logger()
router = APIRouter(tags=["dungeon"])


#: TTL ws_token'а (для подключения к Colyseus после /enter). 60 секунд —
#: запас на медленный network handshake между REST response и WS connect.
WS_TOKEN_TTL_SECONDS = 60


# ===========================================================================
# Response schemas
# ===========================================================================


class DungeonInfo(BaseModel):
    """Карточка данжа для UI-списка.

    :cvar id: Stable ID (``crypt_normal``).
    :cvar name_key: i18n якорь.
    :cvar theme: enum (0=CRYPT..4=SWAMP).
    :cvar difficulty: enum (0=NORMAL..2=MYTHIC).
    :cvar min_level: Минимальный hero.level для входа.
    :cvar entry_cost_gold: Стоимость в gold (целое, без sub-units).
    :cvar entry_cost_energy: Стоимость энергии.
    :cvar daily_limit: Максимум входов в сутки.
    :cvar floors_count: Количество этажей.
    """

    id: str
    name_key: str
    theme: int
    difficulty: int
    min_level: int
    entry_cost_gold: int
    entry_cost_energy: int
    daily_limit: int
    floors_count: int


class DungeonListResponse(BaseModel):
    """Список данжей доступных hero'ю (по level)."""

    dungeons: list[DungeonInfo]


class EnterResponse(BaseModel):
    """Результат успешного enter'а — клиент connectit'ся к Colyseus с этим ws_token.

    :cvar run_id: UUID созданного :class:`DungeonRun`.
    :cvar ws_url: URL Colyseus-комнаты (placeholder в W3 без realtime).
    :cvar ws_token: JWT с ``run_id``+``profile_id``+``hero_id``+``seed_hex``,
        TTL :data:`WS_TOKEN_TTL_SECONDS`.
    :cvar dungeon: Карточка данжа для отображения в loading screen.
    """

    run_id: UUID
    ws_url: str
    ws_token: str
    dungeon: DungeonInfo


class FleeResponse(BaseModel):
    """Результат /flee — финализирует run в FLED + возвращает pending_gold.

    :cvar run_id: UUID завершённого run'а.
    :cvar pending_gold_returned: Сколько gold вернулось на balance.
    :cvar status: Финальный status (``"FLED"`` всегда).
    """

    run_id: UUID
    pending_gold_returned: int
    status: str


class ItemSummaryDTO(BaseModel):
    """Краткое описание материализованного предмета для RunSummaryDTO.

    :cvar id: PK предмета в inventory.
    :cvar base_kind: Строковый kind базы (``"test_sword"`` и т.п.).
    :cvar rarity: Rarity enum value (0=COMMON..4=LEGENDARY).
    :cvar ilvl: Item level.
    """

    id: int
    base_kind: str
    rarity: int
    ilvl: int


class RunSummaryDTO(BaseModel):
    """Полный итог run'а — возвращается /internal/finalize и GET /runs/{id}/summary.

    :cvar run_id: UUID run'а.
    :cvar status: Финальный статус (``COMPLETED`` / ``FAILED`` / ``ABANDONED`` / ``FLED``).
    :cvar gold_earned: Суммарный gold начисленный за run (из RunEncounter rows).
    :cvar xp_earned: Суммарный XP начисленный за run (из RunEncounter rows).
    :cvar items: Список материализованных предметов.
    :cvar floors_cleared: Количество завершённых этажей (COUNT RunEncounter rows).
    :cvar duration_s: Продолжительность run'а в секундах (finished_at - started_at).
    :cvar boss_killed: True если status == COMPLETED и dungeon.floors_count достигнут.
    """

    run_id: UUID
    status: str
    gold_earned: int
    xp_earned: int
    items: list[ItemSummaryDTO]
    floors_cleared: int
    duration_s: int
    boss_killed: bool


# ===========================================================================
# Error codes
# ===========================================================================

ERR_DUNGEON_NOT_FOUND = "dungeon_not_found"
ERR_DUNGEON_DISABLED = "dungeon_disabled"
ERR_NO_HERO = "hero_not_created"
ERR_LEVEL_TOO_LOW = "level_too_low"
ERR_INSUFFICIENT_GOLD = "insufficient_gold"
ERR_INSUFFICIENT_ENERGY = "insufficient_energy"
ERR_DAILY_LIMIT_REACHED = "daily_limit_reached"
ERR_RUN_ALREADY_ACTIVE = "run_already_active"
ERR_RUN_NOT_FOUND = "run_not_found"
ERR_RUN_NOT_OWNER = "run_not_owner"
ERR_RUN_NOT_ACTIVE = "run_not_active"


# ===========================================================================
# GET /dungeons
# ===========================================================================


@router.get("/dungeons", response_model=DungeonListResponse)
async def list_dungeons(
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
) -> DungeonListResponse:
    """Список enabled данжей доступных hero'ю (по level).

    Если у profile ещё нет hero — возвращает пустой список (нечего играть
    без героя). Сортировка: по difficulty ASC, потом по min_level ASC.

    :param profile: Авторизованный профиль.
    :param session: DB session.
    :returns: :class:`DungeonListResponse` со списком карточек.
    """
    hero = await load_active_hero(session, profile_id=profile.id)
    if hero is None:
        return DungeonListResponse(dungeons=[])

    stmt = (
        select(Dungeon)
        .where(Dungeon.is_enabled.is_(True), Dungeon.min_level <= hero.level)
        .order_by(Dungeon.difficulty.asc(), Dungeon.min_level.asc())
    )
    rows = (await session.scalars(stmt)).all()
    return DungeonListResponse(
        dungeons=[
            DungeonInfo(
                id=d.id,
                name_key=d.name_key,
                theme=int(d.theme),
                difficulty=int(d.difficulty),
                min_level=d.min_level,
                entry_cost_gold=d.entry_cost_gold,
                entry_cost_energy=d.entry_cost_energy,
                daily_limit=d.daily_limit,
                floors_count=d.floors_count,
            )
            for d in rows
        ]
    )


# ===========================================================================
# POST /dungeons/{id}/enter
# ===========================================================================


def _today_utc() -> datetime:
    """UTC date snapped в datetime.min.time для PK ``daily_dungeon_entries.date_utc``.

    :returns: datetime сегодняшнего дня UTC в 00:00:00.
    """
    return datetime.combine(datetime.now(UTC).date(), datetime.min.time())


def _build_ws_token(
    *,
    settings: Settings,
    run_id: UUID,
    profile_id: int,
    hero_id: int,
    dungeon_id: str,
    seed_hex: str,
    floors: list[Any] | None = None,
) -> str:
    """Сформировать ws_token JWT для Colyseus connect.

    Использует тот же JWT secret что и access_token (для interop). Payload
    содержит всё для Colyseus.onAuth без DB-чтения; короткий TTL покрывает
    REST→WS handshake gap, не более.

    ``floors`` — список :class:`~wotk.game.dungeon_config.FloorConfig` из
    ``dungeon.config.floors``. Встраивается в JWT чтобы Colyseus не делал
    DB round-trip при onJoin. Типичный 5-floor config < 2 KB приемлем.

    :param floors: Список floor-конфигов из ``dungeon.config["floors"]``;
        если ``None`` — поле не добавляется в payload (backward compat).
    :returns: signed JWT строка.
    """
    iat = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(profile_id),
        "type": "ws",
        "jti": _uuid.uuid4().hex,
        "iat": iat,
        "exp": iat + WS_TOKEN_TTL_SECONDS,
        "run_id": str(run_id),
        "hero_id": hero_id,
        "dungeon_id": dungeon_id,
        "seed_hex": seed_hex,
    }
    if floors is not None:
        payload["floors"] = floors
    return _jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


@router.post(
    "/dungeons/{dungeon_id}/enter", status_code=status.HTTP_201_CREATED
)
async def enter_dungeon(
    dungeon_id: str,
    request: Request,
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> JSONResponse:
    """Главный gameplay endpoint: войти в данж.

    В одной DB транзакции:

    1. Lock balance + load hero + dungeon
    2. Validate level/gold/energy/daily_limit/no_active_run
    3. Debit balance.gold + balance.energy
    4. INSERT transaction (DUNGEON_ENTRY, -amount, balance_after, ref={"dungeon_id": ...})
    5. UPSERT daily_dungeon_entries.count += 1
    6. INSERT dungeon_run (status=IN_PROGRESS, seed=secrets.token_bytes(32), expires_at=now()+24h)
    7. Issue ws_token JWT
    8. Return EnterResponse

    Idempotency: payment-critical (TTL 24h). Повторный запрос с тем же
    Idempotency-Key возвращает кэшированный response (тот же run_id).

    :raises HTTPException: 404 dungeon_not_found, 403 dungeon_disabled /
        level_too_low, 402 insufficient_gold / insufficient_energy, 429
        daily_limit_reached, 409 run_already_active.
    """
    idem = await begin_idempotent(
        request=request,
        session=session,
        profile=profile,
        raw_key=idempotency_key,
        is_payment_critical=True,
    )
    if idem.cached_response is not None:
        return JSONResponse(
            status_code=idem.cached_response.status_code,
            content=idem.cached_response.content,
        )

    # Load dungeon (FK существует, но проверяем наличие отдельно для красивого 404).
    dungeon = await session.get(Dungeon, dungeon_id)
    if dungeon is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=ERR_DUNGEON_NOT_FOUND
        )
    if not dungeon.is_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ERR_DUNGEON_DISABLED)

    # Load hero (берём первого active).
    hero = await load_active_hero(session, profile_id=profile.id)
    if hero is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ERR_NO_HERO)
    if hero.level < dungeon.min_level:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ERR_LEVEL_TOO_LOW)

    # Lock balance + check funds.
    balance = await session.scalar(
        select(Balance)
        .where(Balance.profile_id == profile.id)
        .with_for_update()
    )
    if balance is None:
        # Инвариант: Balance создаётся с Profile в /auth/login.
        log.error("balance_missing_for_enter", profile_id=profile.id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="balance_missing"
        )
    if balance.gold < dungeon.entry_cost_gold:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, detail=ERR_INSUFFICIENT_GOLD
        )
    if balance.energy < dungeon.entry_cost_energy:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, detail=ERR_INSUFFICIENT_ENERGY
        )

    # Daily limit check (UPSERT после).
    today = _today_utc()
    daily = await session.scalar(
        select(DailyDungeonEntry).where(
            DailyDungeonEntry.profile_id == profile.id,
            DailyDungeonEntry.dungeon_id == dungeon_id,
            DailyDungeonEntry.date_utc == today,
        )
    )
    current_count = daily.count if daily is not None else 0
    if current_count >= dungeon.daily_limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail=ERR_DAILY_LIMIT_REACHED
        )

    # Debit balance + create transaction.
    balance.gold -= dungeon.entry_cost_gold
    balance.energy -= dungeon.entry_cost_energy

    tx = Transaction(
        profile_id=profile.id,
        type=TransactionType.DUNGEON_ENTRY,
        amount=-dungeon.entry_cost_gold,
        balance_after=balance.gold,
        ref={"dungeon_id": dungeon_id},
    )
    session.add(tx)

    # UPSERT daily_dungeon_entries.
    upsert_stmt = (
        pg_insert(DailyDungeonEntry)
        .values(
            profile_id=profile.id,
            dungeon_id=dungeon_id,
            date_utc=today,
            count=1,
        )
        .on_conflict_do_update(
            index_elements=["profile_id", "dungeon_id", "date_utc"],
            set_={"count": DailyDungeonEntry.count + 1},
        )
    )
    await session.execute(upsert_stmt)

    # Create dungeon_run. uq_runs_one_active_per_hero ловит race.
    seed_bytes = secrets.token_bytes(32)
    run = DungeonRun(
        profile_id=profile.id,
        hero_id=hero.id,
        dungeon_id=dungeon_id,
        seed=seed_bytes,
        hero_state={
            "hp": 100,  # placeholder — в W4 заполнится из compute_derived_stats
            "mana": 50,
            "level": hero.level,
        },
        entry_paid_gold=dungeon.entry_cost_gold,
        entry_paid_energy=dungeon.entry_cost_energy,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    session.add(run)
    try:
        await session.flush()
    except IntegrityError as e:
        # Скорее всего uq_runs_one_active_per_hero — уже есть IN_PROGRESS run.
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=ERR_RUN_ALREADY_ACTIVE
        ) from e

    # Issue ws_token + build response.
    settings = get_settings()
    # Embed floors config from dungeon.config so Colyseus onJoin can read floor
    # geometry and spawn tables without a DB round-trip.
    dungeon_floors: list[Any] | None = None
    if isinstance(dungeon.config, dict):
        raw_floors = dungeon.config.get("floors")
        if isinstance(raw_floors, list):
            dungeon_floors = raw_floors
    ws_token = _build_ws_token(
        settings=settings,
        run_id=run.id,
        profile_id=profile.id,
        hero_id=hero.id,
        dungeon_id=dungeon_id,
        seed_hex=seed_bytes.hex(),
        floors=dungeon_floors,
    )
    ws_url = settings.realtime_ws_url

    response_body: dict[str, Any] = {
        "run_id": str(run.id),
        "ws_url": ws_url,
        "ws_token": ws_token,
        "dungeon": {
            "id": dungeon.id,
            "name_key": dungeon.name_key,
            "theme": int(dungeon.theme),
            "difficulty": int(dungeon.difficulty),
            "min_level": dungeon.min_level,
            "entry_cost_gold": dungeon.entry_cost_gold,
            "entry_cost_energy": dungeon.entry_cost_energy,
            "daily_limit": dungeon.daily_limit,
            "floors_count": dungeon.floors_count,
        },
    }

    response = CachedHttpResponse(
        status_code=status.HTTP_201_CREATED, content=response_body
    )
    await idem.store(session, response=response)

    log.info(
        "dungeon_entered",
        profile_id=profile.id,
        hero_id=hero.id,
        run_id=str(run.id),
        dungeon_id=dungeon_id,
        gold_debited=dungeon.entry_cost_gold,
        energy_debited=dungeon.entry_cost_energy,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED, content=response_body
    )


# ===========================================================================
# POST /runs/{id}/flee
# ===========================================================================


@router.post("/runs/{run_id}/flee", response_model=FleeResponse)
async def flee_run(
    run_id: UUID,
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
) -> FleeResponse:
    """Добровольный выход из run'а с возвратом ``pending_gold``.

    Не возвращает entry cost (player потерял эти gold). Лут в run escrow
    остаётся; передача в инвентарь — отдельным /claim в W4.

    Под FOR UPDATE на run — concurrent flee + finalize не race'ятся.

    :raises HTTPException: 404 run_not_found, 403 run_not_owner, 409 run_not_active.
    """
    run = await session.scalar(
        select(DungeonRun).where(DungeonRun.id == run_id).with_for_update()
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=ERR_RUN_NOT_FOUND)
    if run.profile_id != profile.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail=ERR_RUN_NOT_OWNER
        )
    if run.status != RunStatus.IN_PROGRESS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=ERR_RUN_NOT_ACTIVE
        )

    pending = run.pending_gold

    # Lock balance + credit pending_gold.
    if pending > 0:
        balance = await session.scalar(
            select(Balance)
            .where(Balance.profile_id == profile.id)
            .with_for_update()
        )
        # balance гарантированно есть — invariant из /auth/login.
        assert balance is not None
        balance.gold += pending

        tx = Transaction(
            profile_id=profile.id,
            type=TransactionType.DUNGEON_REWARD,
            amount=pending,
            balance_after=balance.gold,
            ref={"run_id": str(run_id), "reason": "flee"},
        )
        session.add(tx)

    run.status = RunStatus.FLED
    run.finished_at = datetime.now(UTC)
    await session.flush()

    log.info(
        "dungeon_fled",
        profile_id=profile.id,
        run_id=str(run_id),
        pending_gold_returned=pending,
    )
    return FleeResponse(
        run_id=run_id, pending_gold_returned=pending, status=RunStatus.FLED.name
    )


# ===========================================================================
# POST /internal/runs/{id}/finalize (HMAC, для Colyseus)
# ===========================================================================


#: Абсолютный потолок строк лута в одном finalize body — отклоняем гигантские
#: payload'ы до DB-работы. Дополнительно к dungeon-relative cap в хендлере.
_FINALIZE_MAX_ITEMS_HARD_CAP = 100

#: Абсолютные верхние границы для gold/xp в одном finalize body. Защита
#: от очевидно невозможных значений (overflow / numeric attacks). Тонкая
#: dungeon-relative проверка делается в хендлере после загрузки конфига.
_FINALIZE_MAX_GOLD_HARD_CAP = 10_000_000
_FINALIZE_MAX_XP_HARD_CAP = 10_000_000

#: Множитель допустимого превышения dungeon-config baseline (gold_base /
#: xp_base / floors_count). 10× даёт запас на legendary boss-runs, но
#: бьёт по тревоге если HMAC-secret leak'нул и атакер пытается mint-ить.
_FINALIZE_DUNGEON_BASELINE_MULTIPLIER = 10

#: Максимум item drops на один floor — защита от item-flood при компрометации.
_FINALIZE_MAX_ITEMS_PER_FLOOR = 5


class ItemRollSpec(BaseModel):
    """Спецификация предмета для материализации при финализации run'а.

    Colyseus отправляет только rarity — FastAPI выбирает base_id и роллит аффиксы.

    :cvar rarity: Rarity enum value (0=COMMON..4=LEGENDARY).
    """

    rarity: int = Field(default=0, ge=0, le=4)


class InternalFinalizeBody(BaseModel):
    """Body для /internal/runs/{id}/finalize.

    :cvar status: "COMPLETED" | "FAILED" | "ABANDONED"
    :cvar hero_state: Финальный snapshot героя (HP/mana/equipped state).
    :cvar gold_earned: Total gold собранный в ране (включая pending_gold).
    :cvar xp_earned: XP начисляемый hero. 0 если не передан (backward compat).
    :cvar items_rolled: Список предметов для материализации (только rarity от
        Colyseus; base_id и аффиксы роллятся в FastAPI).
    :cvar combat_summary: JSONB summary от CombatLog.toSummary() (v=1 format).
        None если не передан (backward compat).
    """

    status: str
    hero_state: dict[str, Any]
    gold_earned: int = Field(default=0, ge=0, le=_FINALIZE_MAX_GOLD_HARD_CAP)
    xp_earned: int = Field(default=0, ge=0, le=_FINALIZE_MAX_XP_HARD_CAP)
    items_rolled: list[ItemRollSpec] = Field(
        default_factory=list, max_length=_FINALIZE_MAX_ITEMS_HARD_CAP
    )
    combat_summary: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_default_combat_summary() -> dict[str, Any]:
    """Синтезировать минимальный v=1 combat_summary если Colyseus не прислал.

    Используется когда ``body.combat_summary is None`` чтобы удовлетворить
    DB CHECK ``combat_summary ? 'v'``.

    :returns: Минимальный совместимый словарь.
    """
    return {
        "v": 1,
        "damage_dealt": 0,
        "damage_taken": 0,
        "duration_s": 0,
        "deaths": 0,
        "events": [],
    }


@router.post(
    "/internal/runs/{run_id}/finalize",
    dependencies=[Depends(verify_internal_hmac)],
)
async def internal_finalize_run(
    run_id: UUID,
    body: InternalFinalizeBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Internal callback от Colyseus при завершении run'а (W5-031..034).

    Подпись проверяется через :func:`wotk.core.internal_hmac.verify_internal_hmac`
    (HMAC-SHA256 над raw body, секрет — ``INTERNAL_HMAC_REALTIME_TO_API``).

    Идемпотентность через status check: если run уже не IN_PROGRESS — 409.

    При ``status=COMPLETED``:

    1. Credits ``gold_earned`` в balance + Transaction(DUNGEON_REWARD).
    2. Начисляет ``xp_earned`` в hero.xp (placeholder; level-up в W6).
    3. Материализует ``items_rolled`` через :func:`wotk.game.loot_db.materialize_item`
       (base_id = random ``ItemBase``; affixes роллятся в FastAPI).
    4. Auto-claim: items с ``escrow_run_id == run.id`` переходят в первую
       свободную ячейку inventory. Если inventory full — items остаются в
       escrow для future ``/claim`` endpoint (W6).
    5. INSERT ``RunEncounter`` с combat_summary.

    :raises HTTPException: 404 run_not_found, 409 run_not_active, 422 invalid_status.
    """
    run = await session.scalar(
        select(DungeonRun).where(DungeonRun.id == run_id).with_for_update()
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=ERR_RUN_NOT_FOUND)
    if run.status != RunStatus.IN_PROGRESS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=ERR_RUN_NOT_ACTIVE
        )

    # Только terminal-statuses разрешены для finalize. IN_PROGRESS/SETTLED/FLED
    # обрабатываются другими путями (state-guard через RunStatus[...] lookup).
    allowed = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.ABANDONED}
    try:
        new_status = RunStatus[body.status]
    except KeyError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid_status:{body.status}",
        ) from e
    if new_status not in allowed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid_status:{body.status}",
        )

    # Defense-in-depth: даже под валидной HMAC-подписью не доверяем
    # значениям вслепую. Bound'им gold/xp/items по конфигу данжа — если
    # HMAC-секрет утёк или Colyseus-нода скомпрометирована, ущерб
    # ограничен правдоподобным rewards-окном.
    dungeon = await session.get(Dungeon, run.dungeon_id)
    if dungeon is not None:
        max_gold = (
            dungeon.gold_base
            * dungeon.floors_count
            * _FINALIZE_DUNGEON_BASELINE_MULTIPLIER
        )
        max_xp = (
            dungeon.xp_base
            * dungeon.floors_count
            * _FINALIZE_DUNGEON_BASELINE_MULTIPLIER
        )
        max_items = dungeon.floors_count * _FINALIZE_MAX_ITEMS_PER_FLOOR
        if (
            body.gold_earned > max_gold
            or body.xp_earned > max_xp
            or len(body.items_rolled) > max_items
        ):
            log.warning(
                "finalize_rewards_exceed_cap",
                run_id=str(run_id),
                dungeon_id=run.dungeon_id,
                gold=body.gold_earned,
                gold_cap=max_gold,
                xp=body.xp_earned,
                xp_cap=max_xp,
                items=len(body.items_rolled),
                items_cap=max_items,
            )
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="rewards_exceed_dungeon_cap",
            )

    run.status = new_status
    run.hero_state = body.hero_state
    run.finished_at = datetime.now(UTC)

    items_materialized_count = 0

    if new_status == RunStatus.COMPLETED:
        # ── W5-032: Credit gold ─────────────────────────────────────────────
        balance = await session.scalar(
            select(Balance)
            .where(Balance.profile_id == run.profile_id)
            .with_for_update()
        )
        assert balance is not None

        if body.gold_earned > 0:
            balance.gold += body.gold_earned
            session.add(
                Transaction(
                    profile_id=run.profile_id,
                    type=TransactionType.DUNGEON_REWARD,
                    amount=body.gold_earned,
                    balance_after=balance.gold,
                    ref={"run_id": str(run_id), "reason": "completion"},
                )
            )

        # ── W5-032: XP grant (placeholder — W6 adds level-up logic) ────────
        # Hero загружается единожды, переиспользуется и для XP, и для ilvl
        # дропа.
        hero = (
            await load_active_hero(session, profile_id=run.profile_id)
            if (body.xp_earned > 0 or body.items_rolled)
            else None
        )
        if body.xp_earned > 0 and hero is not None:
            hero.xp += body.xp_earned

        # ── W5-031: Materialize items ───────────────────────────────────────
        if body.items_rolled:
            hero_level = hero.level if hero is not None else 1
            seed_int = int.from_bytes(run.seed, "big")
            # Pre-fetch all bases один раз; per-item random.choice вместо
            # ORDER BY RANDOM() round-trip на каждый дроп.
            bases = (await session.scalars(select(ItemBase))).all()

            for item_idx, spec in enumerate(body.items_rolled):
                rng = random.Random(seed_int ^ hash((run_id, item_idx)))  # noqa: S311
                if not bases:
                    log.warning(
                        "finalize_no_item_base",
                        run_id=str(run_id),
                        item_idx=item_idx,
                    )
                    continue
                base = rng.choice(bases)
                ilvl = max(1, hero_level)
                slot = int(base.slot)
                rarity_val = max(0, min(4, spec.rarity))
                pool = await load_affix_pool(session, slot=slot, ilvl=ilvl)

                generated = generate_item(
                    rng,
                    base_id=base.id,
                    slot=slot,
                    ilvl=ilvl,
                    rarity=Rarity(rarity_val),
                    base_tags=[],
                    affix_pool=pool,
                )
                await materialize_item(
                    session,
                    generated=generated,
                    pool=pool,
                    owner_profile_id=run.profile_id,
                    escrow_run_id=run.id,
                )
                items_materialized_count += 1

            await session.flush()

        # ── W5-034: Auto-claim escrow → inventory ───────────────────────────
        # Items c escrow_run_id == run.id переходят в свободные ячейки
        # inventory. Если inventory full — остаются в escrow для будущего
        # /claim endpoint (W6).
        escrow_items = (
            await session.scalars(
                select(Item).where(Item.escrow_run_id == run.id)
            )
        ).all()
        if escrow_items:
            used_positions = set(
                (
                    await session.scalars(
                        select(Item.inventory_position).where(
                            Item.owner_profile_id == run.profile_id,
                            Item.inventory_position.is_not(None),
                        )
                    )
                ).all()
            )
            free_iter = (p for p in range(48) if p not in used_positions)
            for item in escrow_items:
                free_pos = next(free_iter, None)
                if free_pos is None:
                    log.info(
                        "finalize_inventory_full_item_kept_in_escrow",
                        run_id=str(run_id),
                        item_id=item.id,
                    )
                    break
                # Must clear escrow_run_id BEFORE setting inventory_position to
                # satisfy CHECK ck_item_state_exclusive.
                item.escrow_run_id = None
                item.inventory_position = free_pos

        await session.flush()

        # ── W6-021: UPSERT campaign_progress ────────────────────────────────
        # Пропускаем если dungeon не привязан к кампании (act/location = NULL).
        if dungeon is not None and dungeon.act is not None and dungeon.location is not None:
            finished_ts = run.finished_at or datetime.now(UTC)
            started_ts = run.started_at
            duration_s = max(1, int((finished_ts - started_ts).total_seconds()))
            cp_upsert = (
                pg_insert(CampaignProgress)
                .values(
                    hero_id=run.hero_id,
                    act=dungeon.act,
                    location=dungeon.location,
                    completion_count=1,
                    best_clear_time_s=duration_s,
                )
                .on_conflict_do_update(
                    index_elements=["hero_id", "act", "location"],
                    set_={
                        "completion_count": CampaignProgress.completion_count + 1,
                        "best_clear_time_s": case(
                            (CampaignProgress.best_clear_time_s.is_(None), duration_s),
                            (duration_s < CampaignProgress.best_clear_time_s, duration_s),
                            else_=CampaignProgress.best_clear_time_s,
                        ),
                    },
                )
            )
            await session.execute(cp_upsert)
            log.info(
                "campaign_progress_upserted",
                run_id=str(run_id),
                hero_id=run.hero_id,
                act=dungeon.act,
                location=dungeon.location,
                duration_s=duration_s,
            )

        # ── W5-032: Record RunEncounter ─────────────────────────────────────
        combat_summary = body.combat_summary or _make_default_combat_summary()
        loot_rolled_summary = [{"rarity": s.rarity} for s in body.items_rolled]
        session.add(
            RunEncounter(
                run_id=run.id,
                floor=run.current_floor,
                encounter_idx=0,
                enemies_spawned=[],
                combat_summary=combat_summary,
                loot_rolled=loot_rolled_summary,
                gold_rolled=body.gold_earned,
                result=EncounterResult.WIN,
            )
        )

    await session.flush()

    # ── W6-050: floors_breakdown from RunEncounter rows ──────────────────────
    # Derive per-floor summary from DB rows for structured logging.
    encounter_rows = (
        await session.scalars(
            select(RunEncounter)
            .where(RunEncounter.run_id == run.id)
            .order_by(RunEncounter.floor.asc())
        )
    ).all()
    floors_breakdown = [
        {
            "floor": enc.floor,
            "gold": enc.gold_rolled,
            "xp": enc.combat_summary.get("xp_earned", 0),
            "items_count": len(enc.loot_rolled),
            "duration_s": enc.combat_summary.get("duration_s", 0),
        }
        for enc in encounter_rows
    ]
    boss_killed = new_status == RunStatus.COMPLETED

    # ── W6-052: Prometheus counters ──────────────────────────────────────────
    dungeon_id_label = run.dungeon_id
    difficulty_label = str(int(dungeon.difficulty)) if dungeon is not None else "0"
    if new_status == RunStatus.COMPLETED:
        metrics_inc(
            "dungeon_completed_total",
            dungeon_id=dungeon_id_label,
            difficulty=difficulty_label,
        )
        if boss_killed:
            # W6-052: boss_killed_total — use dungeon_id as proxy for boss_id
            # until Day 2 adds explicit boss_id to finalize body.
            metrics_inc("boss_killed_total", boss_id=dungeon_id_label)
    elif new_status == RunStatus.ABANDONED:
        metrics_inc("dungeon_abandoned_total", dungeon_id=dungeon_id_label)
    elif new_status == RunStatus.FAILED:
        metrics_inc("dungeon_failed_total", dungeon_id=dungeon_id_label)
        # ── W6-051: Sentry breadcrumb on critical death ───────────────────
        sentry_sdk.add_breadcrumb(
            category="dungeon",
            message="hero_died_run_failed",
            level="warning",
            data={
                "run_id": str(run_id),
                "dungeon_id": dungeon_id_label,
                "floor": run.current_floor,
            },
        )

    log.info(
        "run_finalized",
        run_id=str(run_id),
        status=body.status,
        gold_earned=body.gold_earned,
        xp_earned=body.xp_earned,
        items_materialized=items_materialized_count,
        boss_killed=boss_killed,
        floors_breakdown=floors_breakdown,
    )
    # ── W6-030: Build and return RunSummaryDTO ──────────────────────────────
    summary = await _build_run_summary(session, run=run, dungeon=dungeon)
    return summary.model_dump(mode="json")


# ===========================================================================
# POST /internal/runs/{id}/floor-cleared (HMAC, для Colyseus — W6-003/004)
# ===========================================================================


class InternalFloorClearedBody(BaseModel):
    """Body для /internal/runs/{id}/floor-cleared.

    Вызывается Colyseus при переходе hero на следующий этаж.  Создаёт
    RunEncounter для завершённого этажа и инкрементирует current_floor.
    Обновляет last_checkpoint_at в той же транзакции (W6-004).

    :cvar floor: 0-based индекс завершённого этажа.
    :cvar gold_earned: Gold, собранный на этом этаже.
    :cvar xp_earned: XP, заработанный на этом этаже.
    :cvar items_rolled: Предметы, дропнутые на этом этаже.
    :cvar combat_summary: CombatLog.flushFloor() summary для этого этажа.
    :cvar advance_to_floor: Новое значение current_floor (= floor + 1).
    """

    floor: int = Field(default=0, ge=0)
    gold_earned: int = Field(default=0, ge=0, le=_FINALIZE_MAX_GOLD_HARD_CAP)
    xp_earned: int = Field(default=0, ge=0, le=_FINALIZE_MAX_XP_HARD_CAP)
    items_rolled: list[ItemRollSpec] = Field(
        default_factory=list, max_length=_FINALIZE_MAX_ITEMS_HARD_CAP
    )
    combat_summary: dict[str, Any] | None = None
    advance_to_floor: int = Field(default=1, ge=1)


@router.post(
    "/internal/runs/{run_id}/floor-cleared",
    dependencies=[Depends(verify_internal_hmac)],
)
async def internal_floor_cleared(
    run_id: UUID,
    body: InternalFloorClearedBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Internal callback от Colyseus при переходе на следующий этаж (W6-002..004).

    Подпись проверяется через :func:`wotk.core.internal_hmac.verify_internal_hmac`.

    В одной транзакции:

    1. Validates run is IN_PROGRESS + body.advance_to_floor == run.current_floor + 1.
    2. Defense-in-depth: bound-ирует gold/xp/items по dungeon-конфигу (per-floor cap).
    3. Credits gold_earned / xp_earned.
    4. Materializes items_rolled (как в finalize, но per-floor cap).
    5. Auto-claim escrow items → inventory.
    6. INSERT RunEncounter (floor = body.floor).
    7. UPDATE dungeon_run.current_floor = body.advance_to_floor,
       last_checkpoint_at = now() (W6-004).

    :raises HTTPException: 404 run_not_found, 409 run_not_active / bad_floor_advance,
        422 rewards_exceed_dungeon_cap.
    """
    run = await session.scalar(
        select(DungeonRun).where(DungeonRun.id == run_id).with_for_update()
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=ERR_RUN_NOT_FOUND)
    if run.status != RunStatus.IN_PROGRESS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=ERR_RUN_NOT_ACTIVE
        )

    # Validate floor transition is sequential.
    expected_advance = run.current_floor + 1
    if body.advance_to_floor != expected_advance:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"bad_floor_advance:expected_{expected_advance}_got_{body.advance_to_floor}",
        )

    # Defense-in-depth: bound-ируем rewards по dungeon конфигу (per-floor cap).
    dungeon = await session.get(Dungeon, run.dungeon_id)
    if dungeon is not None:
        max_gold = dungeon.gold_base * _FINALIZE_DUNGEON_BASELINE_MULTIPLIER
        max_xp = dungeon.xp_base * _FINALIZE_DUNGEON_BASELINE_MULTIPLIER
        max_items = _FINALIZE_MAX_ITEMS_PER_FLOOR
        if (
            body.gold_earned > max_gold
            or body.xp_earned > max_xp
            or len(body.items_rolled) > max_items
        ):
            log.warning(
                "floor_cleared_rewards_exceed_cap",
                run_id=str(run_id),
                floor=body.floor,
                gold=body.gold_earned,
                gold_cap=max_gold,
                xp=body.xp_earned,
                xp_cap=max_xp,
                items=len(body.items_rolled),
                items_cap=max_items,
            )
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="rewards_exceed_dungeon_cap",
            )

    items_materialized_count = 0

    # ── Credit gold ─────────────────────────────────────────────────────────
    balance = await session.scalar(
        select(Balance)
        .where(Balance.profile_id == run.profile_id)
        .with_for_update()
    )
    assert balance is not None

    if body.gold_earned > 0:
        balance.gold += body.gold_earned
        session.add(
            Transaction(
                profile_id=run.profile_id,
                type=TransactionType.DUNGEON_REWARD,
                amount=body.gold_earned,
                balance_after=balance.gold,
                ref={"run_id": str(run_id), "floor": body.floor, "reason": "floor_clear"},
            )
        )

    # ── XP grant ────────────────────────────────────────────────────────────
    hero = (
        await load_active_hero(session, profile_id=run.profile_id)
        if (body.xp_earned > 0 or body.items_rolled)
        else None
    )
    if body.xp_earned > 0 and hero is not None:
        hero.xp += body.xp_earned

    # ── Materialize items ────────────────────────────────────────────────────
    if body.items_rolled:
        hero_level = hero.level if hero is not None else 1
        seed_int = int.from_bytes(run.seed, "big")
        bases = (await session.scalars(select(ItemBase))).all()

        for item_idx, spec in enumerate(body.items_rolled):
            rng = random.Random(  # noqa: S311
                seed_int ^ hash((run_id, body.floor, item_idx))
            )
            if not bases:
                log.warning(
                    "floor_cleared_no_item_base",
                    run_id=str(run_id),
                    floor=body.floor,
                    item_idx=item_idx,
                )
                continue
            base = rng.choice(bases)
            ilvl = max(1, hero_level)
            slot = int(base.slot)
            rarity_val = max(0, min(4, spec.rarity))
            pool = await load_affix_pool(session, slot=slot, ilvl=ilvl)

            generated = generate_item(
                rng,
                base_id=base.id,
                slot=slot,
                ilvl=ilvl,
                rarity=Rarity(rarity_val),
                base_tags=[],
                affix_pool=pool,
            )
            await materialize_item(
                session,
                generated=generated,
                pool=pool,
                owner_profile_id=run.profile_id,
                escrow_run_id=run.id,
            )
            items_materialized_count += 1

        await session.flush()

    # ── Auto-claim escrow → inventory ────────────────────────────────────────
    escrow_items = (
        await session.scalars(
            select(Item).where(Item.escrow_run_id == run.id)
        )
    ).all()
    if escrow_items:
        used_positions = set(
            (
                await session.scalars(
                    select(Item.inventory_position).where(
                        Item.owner_profile_id == run.profile_id,
                        Item.inventory_position.is_not(None),
                    )
                )
            ).all()
        )
        free_iter = (p for p in range(48) if p not in used_positions)
        for item in escrow_items:
            free_pos = next(free_iter, None)
            if free_pos is None:
                log.info(
                    "floor_cleared_inventory_full_item_kept_in_escrow",
                    run_id=str(run_id),
                    floor=body.floor,
                    item_id=item.id,
                )
                break
            item.escrow_run_id = None
            item.inventory_position = free_pos

    await session.flush()

    # ── Record RunEncounter (scoped to this floor) ───────────────────────────
    combat_summary = body.combat_summary or _make_default_combat_summary()
    loot_rolled_summary = [{"rarity": s.rarity} for s in body.items_rolled]
    session.add(
        RunEncounter(
            run_id=run.id,
            floor=body.floor,
            encounter_idx=0,
            enemies_spawned=[],
            combat_summary=combat_summary,
            loot_rolled=loot_rolled_summary,
            gold_rolled=body.gold_earned,
            result=EncounterResult.WIN,
        )
    )

    # ── Advance floor + checkpoint (W6-004) ──────────────────────────────────
    prev_floor = run.current_floor
    run.current_floor = body.advance_to_floor
    run.last_checkpoint_at = datetime.now(UTC)

    # ── W6-051: Sentry breadcrumb on floor advance ───────────────────────────
    sentry_sdk.add_breadcrumb(
        category="dungeon",
        message="floor_advanced",
        level="info",
        data={
            "run_id": str(run_id),
            "from_floor": prev_floor,
            "to_floor": body.advance_to_floor,
        },
    )

    await session.flush()
    log.info(
        "floor_cleared",
        run_id=str(run_id),
        floor=body.floor,
        advance_to=body.advance_to_floor,
        gold_earned=body.gold_earned,
        xp_earned=body.xp_earned,
        items_materialized=items_materialized_count,
    )
    return {
        "run_id": str(run_id),
        "floor": body.floor,
        "current_floor": body.advance_to_floor,
    }


# ===========================================================================
# Helpers — RunSummaryDTO construction
# ===========================================================================


async def _build_run_summary(
    session: AsyncSession,
    *,
    run: DungeonRun,
    dungeon: Dungeon | None,
) -> RunSummaryDTO:
    """Собрать RunSummaryDTO из завершённого run'а.

    Агрегирует gold/xp из RunEncounter rows (SUM), загружает материализованные
    items (owner_profile_id + один из: escrow_run_id или inventory_position),
    считает floors_cleared как COUNT(RunEncounter). Если run ещё не завершён
    (finished_at is None) — duration_s вычисляется как 0.

    :param session: Async DB session.
    :param run: Экземпляр :class:`DungeonRun` (уже в session identity map).
    :param dungeon: Экземпляр :class:`Dungeon` или ``None`` (нет данжа в DB).
    :returns: Populated :class:`RunSummaryDTO`.
    """
    # Aggregate gold + xp + floor count from RunEncounter rows.
    agg = await session.execute(
        select(
            func.count(RunEncounter.id).label("floors_cleared"),
            func.coalesce(func.sum(RunEncounter.gold_rolled), 0).label("gold_earned"),
        ).where(RunEncounter.run_id == run.id)
    )
    agg_row = agg.one()
    floors_cleared: int = int(agg_row.floors_cleared)
    gold_earned: int = int(agg_row.gold_earned)

    # XP: sum from combat_summary.xp_earned is unreliable; use hero delta is
    # not available here. Best source is encounter rows' xp via body — but
    # since RunEncounter doesn't store xp_earned directly, we store it in
    # combat_summary->xp_earned. Fall back to 0 if not present.
    # For FLED runs there may be no encounters; we rely on the sum over encounters.
    xp_rows = (
        await session.scalars(
            select(RunEncounter.combat_summary).where(RunEncounter.run_id == run.id)
        )
    ).all()
    xp_earned = sum(
        int(cs.get("xp_earned", 0)) if isinstance(cs, dict) else 0
        for cs in xp_rows
    )

    # Materialized items for this run — either still in escrow or already claimed.
    # We join ItemBase to get base_kind.
    item_rows = (
        await session.execute(
            select(Item, ItemBase)
            .join(ItemBase, Item.base_id == ItemBase.id)
            .where(
                Item.owner_profile_id == run.profile_id,
                # Items that were part of this run: either in escrow or recently claimed
                # (escrow cleared at finalize time). We track by matching the run.
                # Since escrow_run_id is cleared on claim, we rely on a time window:
                # items created between run.started_at and run.finished_at + 5s.
                Item.created_at >= run.started_at,
            )
        )
    ).all()

    # Filter to items created during this run window.
    finished = run.finished_at or datetime.now(UTC)
    window_end = finished + timedelta(seconds=5)
    items = [
        ItemSummaryDTO(
            id=item_row.id,
            base_kind=base_row.kind,
            rarity=int(item_row.rarity),
            ilvl=item_row.ilvl,
        )
        for item_row, base_row in item_rows
        if item_row.created_at <= window_end
    ]

    # Duration.
    started = run.started_at
    duration_s = max(0, int((finished - started).total_seconds()))

    # boss_killed: COMPLETED + dungeon.floors_count encountered on last floor.
    status_val = run.status
    boss_killed = status_val == RunStatus.COMPLETED and (
        dungeon is None or floors_cleared >= dungeon.floors_count
    )

    return RunSummaryDTO(
        run_id=run.id,
        status=status_val.name,
        gold_earned=gold_earned,
        xp_earned=xp_earned,
        items=items,
        floors_cleared=floors_cleared,
        duration_s=duration_s,
        boss_killed=boss_killed,
    )


# ===========================================================================
# GET /runs/{run_id}/summary (W6-030 — fallback для клиентов потерявших WS)
# ===========================================================================

ERR_RUN_NOT_TERMINAL = "run_not_terminal"


@router.get("/runs/{run_id}/summary", response_model=RunSummaryDTO)
async def get_run_summary(
    run_id: UUID,
    profile: Annotated[Profile, Depends(current_profile)],
    session: AsyncSession = Depends(get_session),
) -> RunSummaryDTO:
    """Получить итог завершённого run'а (W6-030).

    Canonical fallback для клиентов которые потеряли WS-сообщение ``run_summary``
    (refresh, network drop). Возвращает :class:`RunSummaryDTO` если run в
    terminal-статусе. Ownership check: run.profile_id == profile.id.

    :param run_id: UUID dungeon_run'а.
    :param profile: Авторизованный профиль.
    :param session: DB session.
    :returns: :class:`RunSummaryDTO` с агрегированными данными.
    :raises HTTPException: 404 run_not_found, 403 run_not_owner,
        409 run_not_terminal (если run ещё IN_PROGRESS).
    """
    run = await session.get(DungeonRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=ERR_RUN_NOT_FOUND)
    if run.profile_id != profile.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ERR_RUN_NOT_OWNER)

    terminal = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.ABANDONED, RunStatus.FLED}
    if run.status not in terminal:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=ERR_RUN_NOT_TERMINAL)

    dungeon = await session.get(Dungeon, run.dungeon_id)
    summary = await _build_run_summary(session, run=run, dungeon=dungeon)

    log.info(
        "run_summary_fetched",
        run_id=str(run_id),
        profile_id=profile.id,
        status=run.status.name,
    )
    return summary


# ===========================================================================
# GET /api/v1/admin/runs/{run_id}/encounters (admin-only — W6-053)
# ===========================================================================


class EncounterReplayDTO(BaseModel):
    """Snapshot одного RunEncounter для replay / audit.

    :cvar id: PK.
    :cvar floor: Номер этажа (0-based).
    :cvar encounter_idx: Порядковый индекс энкаунтера на этаже.
    :cvar enemies_spawned: JSON список заспауненных мобов.
    :cvar combat_summary: CombatLog summary (v=1 format).
    :cvar loot_rolled: Список роллов лута.
    :cvar gold_rolled: Gold за этот энкаунтер.
    :cvar result: EncounterResult enum value.
    :cvar created_at: Timestamp создания.
    """

    id: int
    floor: int
    encounter_idx: int
    enemies_spawned: list[Any]
    combat_summary: dict[str, Any]
    loot_rolled: list[Any]
    gold_rolled: int
    result: int
    created_at: datetime


@router.get(
    "/admin/runs/{run_id}/encounters",
    response_model=list[EncounterReplayDTO],
)
async def admin_get_run_encounters(
    run_id: UUID,
    _admin: Annotated[Profile, Depends(current_admin)],
    session: AsyncSession = Depends(get_session),
) -> list[EncounterReplayDTO]:
    """Получить все RunEncounter для run'а (admin replay / audit, W6-053).

    Ownership-agnostic — доступно только admin-профилям. Возвращает строки
    упорядоченные по ``floor ASC, encounter_idx ASC`` для детерминированного
    replay.

    :param run_id: UUID dungeon_run'а.
    :param _admin: Admin-профиль (из :func:`wotk.api.deps.current_admin`).
    :param session: DB session.
    :returns: Список :class:`EncounterReplayDTO`.
    :raises HTTPException: 404 если run не найден.
    """
    run = await session.get(DungeonRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=ERR_RUN_NOT_FOUND)

    rows = (
        await session.scalars(
            select(RunEncounter)
            .where(RunEncounter.run_id == run_id)
            .order_by(RunEncounter.floor.asc(), RunEncounter.encounter_idx.asc())
        )
    ).all()

    return [
        EncounterReplayDTO(
            id=enc.id,
            floor=enc.floor,
            encounter_idx=enc.encounter_idx,
            enemies_spawned=enc.enemies_spawned,
            combat_summary=enc.combat_summary,
            loot_rolled=enc.loot_rolled,
            gold_rolled=enc.gold_rolled,
            result=int(enc.result),
            created_at=enc.created_at,
        )
        for enc in rows
    ]

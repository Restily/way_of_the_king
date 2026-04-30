# Week 3 — Тикеты

Версия: 0.1 (создано 2026-04-28)
Период: 7 дней, ~60 рабочих часов
Цель недели:
1. **§6 + §8 DB foundation** — таблицы предметов, аффиксов и данжей в схеме (loot.py наконец-то получит persistence; dungeon_runs нужен для ws_token).
2. **Первый gameplay endpoint** — `POST /dungeons/{id}/enter` со списанием gold/energy + созданием DungeonRun + выпуском ws_token.
3. **Realtime layer (Colyseus skeleton)** — DungeonRoom с JWT-onAuth, server tick 20Hz, position broadcast. **Без AI/боя/мобов** — только player перемещается через сервер.
4. **Frontend Colyseus integration** — Mini App подключается к WS-комнате после `/enter`, рендерит server-driven state, делает client prediction для своего player'а.

Каждый тикет:
- **Acceptance criteria** — что считается «готово»
- **Estimate** — оценка (часы)
- **Dependencies** — что должно быть готово до старта
- **Status** — `TODO` / `PARTIAL` / `DONE`

## Что уже сделано к концу W2 (фундамент для W3)

- ✅ §1-§5 + §11.2 миграции (profile/balance/referral/hero/transaction/idempotency_keys + триггеры + functions)
- ✅ Idempotency middleware (применяется к новым POST endpoints)
- ✅ Arq worker с cron-инфраструктурой (cleanup задачи)
- ✅ Pixi placeholder сцена с движением + коллизиями + 5 комнатами + camera follow
- ✅ structlog JSON в prod, Sentry request_id tag, /health/ready
- ✅ loot.py готов как pure functions (27 тестов), нужен только адаптер к БД

## Что НЕ делается на 3-й неделе (защита скоупа)

- AI мобов / боёвка (Phase 4, W8-10)
- Real LPC sprites / Tiled JSON loader (нет assets)
- Production deploy (W2-001..014 carried over)
- TON интеграция (Phase 7, W15+)
- Маркет, PvP (постMVP)
- Леденящий рендер мобов в realtime — только player position в W3

---

## День 1 (Пн) — §6 items + affixes DB (~8ч)

### W3-001 — Миграция 0007 — item_base + affix_definition + item `TODO`
Реализация DATABASE.md §6 со всеми best-practice полями:
- **item_base**: BIGSERIAL id, kind UNIQUE, slot SMALLINT, min_ilvl, base_stats JSONB, is_two_handed BOOLEAN
- **affix_definition**: BIGSERIAL id, affix_type SMALLINT, mod_group, min_ilvl, tier, weight, applicable_slots JSONB, tags JSONB GIN, spawn_weights JSONB nullable, mod_type, value_min/max
- **item**: BIGSERIAL id, owner_profile_id FK, base_id FK, rarity SMALLINT, ilvl, **affixes JSONB со snapshot** (`{id,value,t,vmin,vmax}` per §6.3.1), equipped_on FK hero, equipped_slot SMALLINT, inventory_position INT, is_in_market_escrow, escrow_run_id (FK добавится после §8), updated_at + триггер
- Все CHECK / partial unique indexes / GIN из §6
- **AC:** миграция применяется на чистой БД; все индексы созданы; downgrade работает
- **Estimate:** 2.5ч
- **Dependencies:** W2-030 (idempotency) — не блокер

### W3-002 — SQLAlchemy модели §6 `TODO`
- `ItemBase`, `AffixDefinition`, `Item` в `wotk/domain/models.py`
- `Item.affixes` типизировать как `list[dict[str, int]]` (snapshot shape)
- Mapped enum'ы через существующий `IntEnumColumn` (Slot, Rarity, AffixType — добавить в `domain/enums.py`)
- **AC:** модели импортируются, mypy strict проходит, все enum-колонки типизированы
- **Estimate:** 1.5ч
- **Dependencies:** W3-001

### W3-003 — Seed script для reference-data `TODO`
- `backend/scripts/seed_reference.py` — идемпотентный (проверяет `kind` UNIQUE)
- ~10 базовых: `sword_short_iron`, `sword_2h_iron`, `helm_leather`, `helm_iron`, `chest_leather`, `chest_iron`, `boots_leather`, `bow_short_oak`, `ring_bronze`, `offhand_buckler_iron`
- ~30 аффиксов: `flat_str/dex/int` (3 tier), `flat_hp/mana` (3 tier), `pct_atk/def/crit` (3 tier), `flat_phys/fire/cold_dmg` (3 tier), `pct_resist_*` (3 tier)
- **AC:** `uv run python -m scripts.seed_reference` на чистой БД создаёт ~10 base + ~30 affix; повторный запуск — no-op (нет ошибок UNIQUE)
- **Estimate:** 2ч
- **Dependencies:** W3-002

### W3-004 — Адаптер loot.py → БД `TODO`
- `wotk/game/loot_db.py` — функции:
  - `async load_affix_pool(session, slot, ilvl) -> tuple[AffixDefinition, ...]` — JOIN по applicable_slots GIN + min_ilvl filter
  - `async materialize_item(session, generated: GeneratedItem, owner_profile_id, escrow_run_id) -> Item` — INSERT в `item` table со snapshot affixes
- **AC:** unit-тест: load → generate → materialize → SELECT возвращает item с правильным snapshot
- **Estimate:** 1.5ч
- **Dependencies:** W3-002, W3-003, существующий [loot.py](../backend/src/wotk/game/loot.py)

### W3-005 — Интеграционные тесты §6 моделей `TODO`
- `tests/test_models_items.py` — CHECK constraints (rarity range, equipped_slot only when equipped_on set, inventory_position uniqueness per owner)
- `tests/test_loot_db.py` — adapter end-to-end через test_engine
- **AC:** ≥10 тестов, все зелёные, edge cases (попытка equip двух items в один слот → IntegrityError)
- **Estimate:** 1.5ч
- **Dependencies:** W3-004

---

## День 2 (Вт) — §8 dungeons DB (~8ч)

### W3-010 — Миграция 0008 — dungeons + dungeon_runs + run_encounters + daily_dungeon_entries + campaign_progress `TODO`
Реализация DATABASE.md §8 в одной миграции:
- **dungeons**: TEXT id PK, name_key, theme SMALLINT, difficulty, min_level, entry_cost_gold/energy, daily_limit, floors_count, config JSONB, xp_base, gold_base, is_enabled
- **dungeon_runs**: UUID PK gen_random_uuid(), profile_id FK, hero_id FK, dungeon_id FK TEXT, seed BYTEA(32), status SMALLINT, current_floor, hero_state JSONB, pending_gold, entry_paid_gold/energy, revives_used, realtime_node_id TEXT, started_at/last_activity_at/last_checkpoint_at/finished_at/expires_at
- Partial unique `uq_runs_one_active_per_hero` (status=0)
- **run_encounters**: BIGSERIAL id, run_id FK, floor, encounter_idx, enemies_spawned JSONB, combat_summary JSONB (с `"v": 1` версией), loot_rolled JSONB, gold_rolled, result SMALLINT
- **daily_dungeon_entries**: PK (profile_id, dungeon_id, date_utc), count
- **campaign_progress**: PK (hero_id, act, location), first_completed_at, best_clear_time_s, completion_count
- Триггер `trg_run_seed_immutable` (BEFORE UPDATE) — seed/dungeon_id immutable
- Триггер `trg_run_activity` (BEFORE UPDATE WHEN status=0)
- Item.escrow_run_id → FK к dungeon_runs(id) (отложенная FK из 0007)
- **AC:** миграция применяется, все CHECK работают, попытка изменить seed → exception
- **Estimate:** 3ч

### W3-011 — SQLAlchemy модели §8 `TODO`
- `Dungeon`, `DungeonRun`, `RunEncounter`, `DailyDungeonEntry`, `CampaignProgress`
- Enum'ы в `domain/enums.py`: `DungeonTheme`, `Difficulty`, `RunStatus`, `EncounterResult`
- **AC:** модели импортируются, mypy strict проходит
- **Estimate:** 1.5ч
- **Dependencies:** W3-010

### W3-012 — Seed script для dungeons `TODO`
- 6 dungeons минимум для MVP: Crypt {Normal/Hard}, Forest {Normal/Hard}, Castle Mythic-only
- Конфиг floors с placeholder loot tables (~3 affix groups per dungeon)
- entry_cost_gold/energy балансные значения из SPEC.md (если есть, иначе примерные)
- **AC:** `uv run python -m scripts.seed_dungeons` создаёт 6 enabled dungeons
- **Estimate:** 1.5ч
- **Dependencies:** W3-011

### W3-013 — DB-уровень триггеры в миграции 0008 (audit) `TODO`
- Уже включены в W3-010 на уровне SQL — вынести в отдельный тикет если нужна верификация
- Тест на attempt-to-modify-seed (must raise IntegrityError)
- **AC:** dedicated test проходит, попытка `UPDATE dungeon_runs SET seed = ...` → exception
- **Estimate:** 0.5ч (тест)
- **Dependencies:** W3-011

### W3-014 — Интеграционные тесты §8 моделей `TODO`
- `tests/test_models_dungeons.py`: создание run, нельзя 2 active на hero, status transitions, FK к hero/profile
- **AC:** ≥8 тестов, все зелёные
- **Estimate:** 1.5ч
- **Dependencies:** W3-013

---

## День 3 (Ср) — Backend gameplay endpoints (~10ч)

### W3-020 — Wire `current_energy()` в GET /me `TODO`
- `wotk/api/v1/me.py` — заменить чтение `balance.energy` на вызов SQL функции `current_energy(profile_id)` (read-only, lazy regen)
- Returns текущее значение БЕЗ записи в БД (только spend-операции вызывают `regen_energy_for_profile`)
- **AC:** /me возвращает energy = ((`now - energy_updated_at`) / 6 мин) + stored, capped at energy_cap
- **Estimate:** 1ч
- **Dependencies:** Migration 0005 (already applied)

### W3-021 — GET /api/v1/dungeons — список доступных `TODO`
- Возвращает enabled dungeons с фильтром по `min_level <= hero.level`
- Поля: `id, name_key, theme, difficulty, min_level, entry_cost_gold, entry_cost_energy, daily_limit, floors_count`
- **AC:** список всегда отсортирован по (difficulty, min_level); закрытые дунжи не возвращаются
- **Estimate:** 1ч
- **Dependencies:** W3-011

### W3-022 — POST /api/v1/dungeons/{id}/enter `TODO`
Главный endpoint W3. В одной DB транзакции:
1. SELECT hero (FOR UPDATE) — проверка level/energy/gold
2. `regen_energy_for_profile(uid)` — материализуем регенерацию перед списанием
3. Проверка no active run (partial unique catches race)
4. Проверка `daily_dungeon_entries.count < daily_limit`
5. UPDATE balance: gold -= entry_cost, energy -= entry_cost_energy
6. INSERT transaction (DUNGEON_ENTRY type, -amount, balance_after, ref={"dungeon_id": ...})
7. UPSERT daily_dungeon_entries
8. INSERT dungeon_runs (status=IN_PROGRESS, seed=secrets.token_bytes(32), expires_at=now()+24h)
9. Сгенерировать ws_token (JWT с 30s TTL): `{run_id, profile_id, hero_id, dungeon_id, seed: hex, exp}`
10. Return `{run_id, ws_url, ws_token, dungeon: {...}}`
- **Idempotency:** обязательный `Idempotency-Key` header (payment-critical TTL=24h)
- **AC:** успешный enter возвращает 200 с ws_token; повторный запрос с тем же idem-key возвращает тот же run_id; insufficient gold → 402; insufficient energy → 402; daily limit reached → 429 + retry-after; level too low → 403
- **Estimate:** 3.5ч
- **Dependencies:** W3-020, W3-021

### W3-023 — Tests для enter flow `TODO`
- e2e: login → create hero → seed dungeon в test fixture → enter → assert balance debited + transaction created + run row exists
- Idempotency: тот же key возвращает тот же run_id
- Concurrent enter (asyncio.gather) — только один создаёт run, остальные 409
- Daily limit: 5 успешных enter'ов потом 429
- **AC:** ≥6 тестов, race condition тест проходит
- **Estimate:** 2.5ч
- **Dependencies:** W3-022

### W3-024 — POST /api/v1/runs/{id}/flee — добровольный выход `TODO`
- Только своих run'ов (404 если не owner, 409 если status != IN_PROGRESS)
- В транзакции: UPDATE status=FLED, finished_at=now(); INSERT transaction (DUNGEON_REWARD, +pending_gold)
- Не возвращает entry_cost (player потерял)
- Лут в run escrow остаётся; передача в инвентарь — отдельным /claim endpoint в W4
- **AC:** flee из IN_PROGRESS работает; флеш-аут балансы корректны; повторный flee → 409
- **Estimate:** 1.5ч
- **Dependencies:** W3-022

### W3-025 — POST /api/v1/internal/runs/{id}/finalize (HMAC, для Colyseus → backend) `TODO`
- Endpoint только для realtime-ноды; auth через HMAC-SHA256 header (`X-Internal-Sig`)
- Body: `{run_id, status: COMPLETED|FAILED|ABANDONED, hero_state: {...}, encounters: [...]}`
- В транзакции: UPDATE dungeon_runs, INSERT run_encounters batch, INSERT transaction (DUNGEON_REWARD если COMPLETED)
- **AC:** валидный HMAC проходит; невалидный → 401; повторный finalize → 409 (already settled)
- **Estimate:** 0.5ч (полная имплементация в Phase 4 — здесь только skeleton)
- **Dependencies:** W3-022

---

## День 4 (Чт) — Colyseus realtime skeleton (~10ч)

### W3-030 — Colyseus 0.16 проект готов `TODO`
- ✅ scaffold уже есть в `realtime/`
- Установить deps если не установлены: `cd realtime && npm install`
- Проверить что `npm run dev` поднимает empty Colyseus server на :2567
- Подключить TS strict mode + ESLint config (если ещё нет)
- **AC:** WS connection к ws://localhost:2567/ — handshake OK; monitor открывается на :2567/colyseus
- **Estimate:** 1ч

### W3-031 — DungeonRoom class с onAuth `TODO`
- `realtime/src/rooms/DungeonRoom.ts` — extends `Room<WorldState>`
- `onAuth(client, options)`: верифицировать ws_token (JWT HS256, тот же secret что и в FastAPI)
- Проверки: claims.run_id matches room name, exp > now, hero_id matches
- Если invalid → reject (Colyseus throw → close 1011)
- Сохранить parsed claims в `client.userData` для последующего использования в onJoin
- **AC:** валидный ws_token → onAuth resolves; невалидный/expired → connection rejected с информативным сообщением
- **Estimate:** 2ч
- **Dependencies:** W3-022 (issuer), W3-030

### W3-032 — WorldState Schema (Colyseus Schema sync) `TODO`
- `realtime/src/schemas/WorldState.ts` — `WorldState extends Schema`
- Поля: `players: MapSchema<Player>`, `currentFloor: number`
- `Player` schema: `id, x, y, hp, maxHp, facing` (string union)
- Schema diff broadcast — Colyseus делает автоматически на каждый tick
- **AC:** state виден в monitor (:2567/colyseus); подключённый client получает full state на join
- **Estimate:** 1.5ч
- **Dependencies:** W3-031

### W3-033 — Server tick 20Hz + applyInputs `TODO`
- `setSimulationInterval(this.tick.bind(this), 50)` (20Hz = 50ms)
- `tick(deltaMs)`:
  - Читает inputs из `client.lastInput` (set'ится в onMessage)
  - Применяет к Player.x/y с проверкой против walls (TODO: пока без walls — пустая комната)
  - Schema автоматически diffit'ит изменения
- Input-message handler: `this.onMessage("input", (client, msg) => {...})`
- **AC:** клиент шлёт `{x: 0.5, y: 0}` → через 50ms на схеме увидим player.x смещён; latency локально <20ms
- **Estimate:** 2.5ч
- **Dependencies:** W3-032

### W3-034 — HMAC client → POST /internal/runs/{id}/finalize `TODO`
- `realtime/src/internal/api.ts` — async function `finalizeRun(runId, payload)`
- Подписывает body через `INTERNAL_HMAC_REALTIME_TO_API` секрет
- Header: `X-Internal-Sig: <hex>`
- Retry с exponential backoff (3 попытки)
- Триггерится при room dispose (все клиенты ушли) или явный finish
- **AC:** при `room.disconnect()` backend получает callback и переводит run в SETTLED статус
- **Estimate:** 1.5ч
- **Dependencies:** W3-033, W3-025

### W3-035 — Internal HMAC validation на FastAPI стороне `TODO`
- Middleware/dependency `verify_internal_hmac` для `/api/v1/internal/*` routes
- Использует `INTERNAL_HMAC_REALTIME_TO_API` (raw body + secret → HMAC-SHA256)
- Constant-time comparison (`hmac.compare_digest`)
- Logging при mismatch (audit_events добавим в W4)
- **AC:** unit-тест — валидный sig проходит, mismatch → 401, missing header → 401
- **Estimate:** 1.5ч
- **Dependencies:** W3-025

---

## День 5 (Пт) — Frontend Colyseus integration (~10ч)

### W3-040 — colyseus.js client install `TODO`
- `cd frontend && npm install colyseus.js`
- TS types из package included
- **AC:** `import { Client } from 'colyseus.js'` works
- **Estimate:** 0.5ч

### W3-041 — POST /dungeons/{id}/enter → connect to room `TODO`
- `frontend/src/api/dungeons.ts` — typed wrapper для `/dungeons/{id}/enter` (с idempotency-key generation)
- В Playground заменить debug-room-selector на список реальных dungeons из `/api/v1/dungeons`
- При выборе → POST /enter → получить ws_token + ws_url
- `colyseus.Client(ws_url).joinOrCreate('dungeon', { token: ws_token })` — Colyseus передаст token в onAuth
- **AC:** клик "Crypt Normal" → debit gold/energy → подключение к room → onJoin срабатывает → видим player в schema state
- **Estimate:** 3ч
- **Dependencies:** W3-022, W3-031

### W3-042 — Render server-driven state в Pixi `TODO`
- В scene.ts добавить `applyServerState(state: WorldState)`:
  - Для каждого Player в state: создать или обновить Pixi sprite (placeholder circle всё ещё)
  - Удалить sprites которых больше нет в state
- Listen `room.onStateChange` → call applyServerState
- Свой player НЕ обновляем напрямую (см. W3-043)
- **AC:** другие players (если зайдут одновременно — multi-tab тест) видны на канвасе
- **Estimate:** 2.5ч
- **Dependencies:** W3-041

### W3-043 — Client prediction для своего player'а `TODO`
- Свой player двигается локально по input (как уже сделано в W2)
- Шлём input на сервер через `room.send("input", {x, y, seq: counter++})`
- При получении server state с обновлённой позицией СВОЕГО player'а:
  - Если drift < 30px → smooth lerp за ~200ms
  - Если drift > 30px → snap (rubber-band, server authoritative)
- **AC:** на нормальной latency движение плавное; при искусственной задержке (Chrome DevTools throttle) видна reconciliation rubber-band
- **Estimate:** 3ч
- **Dependencies:** W3-042

### W3-044 — Dev overlay с метриками `TODO`
- В углу Playground (только при `import.meta.env.DEV`): latency (ping/pong), packets/sec, server tick rate
- Простой `Stats` компонент через requestAnimationFrame
- **AC:** в dev сборке цифры обновляются, в prod build (когда будет) скрыто
- **Estimate:** 1ч
- **Dependencies:** W3-041

---

## День 6 (Сб) — Reconciliation + observability (~8ч)

### W3-050 — Reconciliation cron в Arq worker `TODO`
- `wotk/worker/main.py` — добавить cron `reconcile_balances` каждые 5 мин
- Запрос: `SELECT b.profile_id, b.gold, t.balance_after FROM balance b LEFT JOIN LATERAL (SELECT balance_after FROM transaction WHERE profile_id=b.profile_id ORDER BY id DESC LIMIT 1) t ON true WHERE t.balance_after IS NOT NULL AND b.gold != t.balance_after`
- При наличии расхождений: log CRITICAL + Sentry alert + (TODO в W4 — INSERT audit_events)
- **AC:** unit-тест: создать profile с balance.gold=100 + последняя transaction.balance_after=200 → cron находит drift и логирует
- **Estimate:** 2ч
- **Dependencies:** W2-032 (Arq infra)

### W3-051 — Реальная имплементация cleanup_expired_runs `TODO`
- Заменить W2-stub на вызов `UPDATE dungeon_runs SET status=ABANDONED, finished_at=now() WHERE status=0 AND expires_at < now() RETURNING id`
- Для каждого ABANDONED — обработать escrow items (политика: 50% delete, 50% инвентарь — но это W4)
- Пока: только status update + лог
- **AC:** интеграционный тест проверяет, что expired run переходит в ABANDONED через cron
- **Estimate:** 1.5ч
- **Dependencies:** W3-010 (dungeon_runs table)

### W3-052 — Расширить /health/ready `TODO`
- Добавить проверки: Redis ping (через async redis client), Arq queue length (через `ArqRedis.queued_jobs`)
- Возвращать в `checks: {postgres, migrations, redis, arq_queue}`
- **AC:** падает с 503 если Redis down или Arq queue > 1000 (заглушка для прод-алертинга)
- **Estimate:** 1.5ч
- **Dependencies:** W2-034

### W3-053 — Request duration / status в structlog `TODO`
- В `RequestIdMiddleware`: измерить duration_ms (`time.perf_counter`), залогить вместе с status_code на success/failure
- **AC:** в prod-JSON логе каждый запрос → одна структурированная строка с `duration_ms`, `status_code`
- **Estimate:** 1ч
- **Dependencies:** W2-033

### W3-054 — Логирование внутри Colyseus (структурированное) `TODO`
- `realtime/src/logger.ts` — pino с redaction (mirror того что в backend `sentry_setup.py`)
- Логи на onAuth/onJoin/onLeave/dispose с run_id + profile_id
- **AC:** логи Colyseus в JSON-формате, секреты замаскированы
- **Estimate:** 1ч
- **Dependencies:** W3-031

---

## День 7 (Вс) — E2E playable loop + W4 plan (~6ч)

### W3-060 — End-to-end test playable loop `TODO`
Полный сценарий локально:
1. Login через ngrok-Mini App
2. Create Knight (если новый)
3. City экран → list dungeons (видим Crypt Normal с stats)
4. Click Crypt Normal → дебит gold + energy → переход в Pixi сцену
5. Connect to Colyseus room → видим своего player'а (server-driven position)
6. Двигаться через джойстик — видим движение через server tick (20Hz updates)
7. Open second browser tab под другим test user → second player виден в первом tab
8. Click "Flee" → возврат в City → balance корректно отрезан / pending_gold вернулся

- **AC:** все 8 шагов проходят без exceptions; observable in console / Sentry
- **Estimate:** 2.5ч
- **Dependencies:** W3-043, W3-024

### W3-061 — Bug fixes из W3-060 `TODO`
Резерв на «всё пошло не так» при e2e сборке. Типичные: rubber-band слишком резкий, ws_token expires до connect (увеличить TTL до 60s), Pydantic строгая schema vs реальный TG initData.
- **Estimate:** 1.5ч

### W3-062 — Update WEEK-3-TICKETS статус + WEEK-4-PLAN.md outline `TODO`
- Отметить готовое в этом документе
- Создать `docs/WEEK-4-PLAN.md` outline:
  - Phase 4 start: моба (Skeleton Warrior как первый), AI states, server-side combat, encounter spawn, item materialization при kill
  - Inventory UI (внутри City) — equip/unequip, рендер snapshot affixes из item.affixes JSONB
  - Skill rotation (4 active skills hotbar)
- **AC:** WEEK-4-PLAN.md существует и содержит ≥10 тикетов outline
- **Estimate:** 1ч

### W3-063 — Buffer `TODO`
1ч резерв.

---

## Итого по неделе

- Всего тикетов: **31** (тот же объём что W1/W2)
- Суммарная оценка: ~62 часа
- Critical path: W3-001 → W3-002 → W3-010 → W3-022 → W3-031 → W3-041 → W3-043 → W3-060
- **Phase 2 deferred items** (нужны assets): swap procedural rooms на Tiled JSON, swap circle Knight на LPC sprite — это **не блокер для W3**, делаем параллельно когда assets появятся

## Acceptance criteria недели

- ✅ Player может ВОЙТИ в данж (списание gold/energy + создание run + ws_token)
- ✅ Player в Pixi сцене двигается **через сервер** (20Hz tick, schema sync)
- ✅ Multiple players в одной комнате видят друг друга (multi-tab тест)
- ✅ Flee возвращает в City с корректной финализацией баланса
- ✅ Reconciliation cron активен и алертит на drift
- ✅ HMAC между FastAPI ↔ Colyseus работает (internal callback)
- ✅ §6 + §8 миграции применены, ~10 base + ~30 affixes + 6 dungeons засеяны
- ✅ Backend tests: ≥150 (было 125, +20-25 на §6+§8+enter+flee+HMAC)

## Что НЕ должно сломаться (regression-защита)

- W1: auth + hero create + /me — все 124 W2-теста зелёные
- W2: idempotency на /heroes остаётся работать
- Pixi: переход City → Playground (теперь это «выбор данжа → enter»), city экран не ломается

## Риски недели

| Риск | Митигация |
|---|---|
| Colyseus 0.16 + Pixi v8 + Vite HMR конфликтуют | Deps уже в package.json, Vite HMR для realtime не используется (отдельный процесс) |
| Schema sync медленный (>50ms) на mid-range Android | Снизить tick до 10Hz, использовать ParticleContainer для других players |
| HMAC между сервисами — путаница с двумя секретами (RT→API vs API→RT) | Они уже определены отдельно в config.py, тесты должны catch'ить swap |
| Client prediction rubber-band ужасный feel | Tune lerp duration; в W3 принимаем «жёсткий snap» если drift > 30px, smooth refinement в W4 |
| §6 миграция большая, autogenerate не справится | Писать вручную через `op.execute(sa.DDL(...))` как в 0004/0005/0006 |
| Daily limit race condition | UPSERT с `ON CONFLICT DO UPDATE` + WHERE clause проверки в той же транзакции |
| Concurrent enter (одновременные клики) | partial unique `uq_runs_one_active_per_hero` уже catches; idempotency key — second layer |
| Flee timing — «нажал Flee когда уже finalize пришёл от Colyseus» | Idempotent finalize handler; flee проверяет status=IN_PROGRESS и 409 если нет |

## Что готово к началу W4

- DB foundation полная (§1-§8 + §11.2 в схеме)
- Realtime каркас работает, можно добавлять game logic
- Client prediction proof-of-concept — следующий шаг полноценный input replay
- Dungeon entry как референсная гoodbye payment-critical idempotent operation — все будущие withdrawal/transactions делаются по этому паттерну

---

## Что W3 НЕ покрывает (и где они будут)

- **AI мобов** — W4 (Phase 4 start)
- **Real combat** (атаки, скиллы, урон) — W4-W5 (Phase 4 mid)
- **Inventory UI** (фронтенд экран с предметами) — W4
- **Equip/unequip endpoints** — W4
- **Real LPC sprites** — когда появятся assets, swap-in без архитектурных изменений
- **Tiled JSON loader** — когда появятся .tmx файлы, замена `room.ts` builders
- **TON wallet** — Phase 7, W15+

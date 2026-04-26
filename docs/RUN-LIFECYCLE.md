# Жизненный цикл прохождения данжа (Dungeon Run Lifecycle)

Версия: 0.1
Последнее обновление: 2026-04-27

Документ описывает где живёт состояние во время рана, как происходят переходы, что делать при сбоях, и почему выбран именно такой подход.

---

## 1. TL;DR

- **Persistent state** (выживает падение процессов): `dungeon_runs` + `items` (с `escrow_run_id`) в PostgreSQL.
- **Volatile state** (живёт пока Colyseus Room в памяти): позиции, HP, AI, кулдауны, бафы, снаряды, лут на полу.
- **Persistence happens** на: enter, **pickup** (sync), **floor transition** (atomic with ack), completion/death/flee.
- **Persistence НЕ happens** на: каждый tick, каждое движение, каждая атака, дроп лута на пол.
- **Worst-case потеря** при сбое: текущий этаж — мобы респаунятся, золото с этажа теряется. Лут, поднятый до сбоя, сохранён.

---

## 2. Где что живёт

### 2.1 PostgreSQL (persistent)

| Сущность | Когда пишется | Когда читается |
|---|---|---|
| `dungeon_runs` row | INSERT на enter, UPDATE на каждый floor transition + completion | На enter (validate), resume, claim, audit |
| `items` row (с `escrow_run_id`) | INSERT при pickup игроком (sync HMAC-callback от Colyseus) | На claim (release escrow), на recovery |
| `transactions` row (DUNGEON_ENTRY) | INSERT в момент enter (списание gold/energy) | Для аудита |
| `transactions` row (DUNGEON_REWARD) | INSERT в момент claim (зачисление pending_gold) | Для аудита |
| `daily_dungeon_entries` row | UPSERT на enter (инкремент) | На enter (validate лимита) |
| `run_encounters` row | INSERT в конце каждого этажа (combat summary, для replay/аналитики) | Для анти-чит арбитража |

### 2.2 Colyseus Room memory (volatile)

| Данные | Размер (примерно) | Что произойдёт при потере |
|---|---|---|
| Позиция игрока + HP/mana/buffs/cooldowns | ~500B | Игрок респаунится в начале этажа |
| Все мобы текущего этажа (10–15 шт) | ~2KB | Респаунятся при resume (детерминированно из seed) |
| AI state мобов (target, path, cooldowns) | ~1KB | Сбросится |
| Активные снаряды | ~200B на снаряд | Исчезнут (для ARPG нормально) |
| Лежащий лут (ещё не поднят) | ~500B на дроп | **Может быть восстановлен** через тот же seed при resume |
| Tick counter | 8B | Сбрасывается |
| Очередь events текущего тика | ~1KB | Не успеет долететь до клиента — клиент не увидит этих эффектов |

**Итого один Room ≈ 5–50 KB в памяти Node-процесса.**

### 2.3 Telegram CloudStorage клиента (для resume)

- `ws_token` (короткоживущий JWT) — для re-attach к Room
- Текущий `run_id`
- Persisted, чтобы при перезапуске Mini App знать «у тебя есть незавершённый ран»

---

## 3. State machine рана

```
                  POST /enter
        ┌─────────────────────────►
        │
   ┌────┴────┐
   │ ABSENT  │  (нет активного рана)
   └────┬────┘
        │
        │ FastAPI валидирует, списывает entry cost,
        │ создаёт dungeon_runs row, выпускает ws_token
        │
        ▼
   ┌─────────────┐
   │ IN_PROGRESS │ ◄────────────── reconnect within grace
   └──┬───┬──┬───┘
      │   │  │
      │   │  └─── floor cleared → atomic checkpoint → next floor (status stays IN_PROGRESS)
      │   │
      │   │ boss defeated
      │   ▼
      │   ┌───────────┐  POST /claim
      │   │ COMPLETED ├─────────────►┌─────────┐
      │   └───────────┘              │ SETTLED │
      │                              └─────────┘
      │ player died, no revive
      │
      ▼
   ┌────────┐  POST /claim (partial loot)
   │ FAILED ├──────────────────────►┌─────────┐
   └────────┘                       │ SETTLED │
      │                             └─────────┘
      │  POST /flee
      ▼
   ┌─────┐  POST /claim
   │ FLED├────────────────────────►┌─────────┐
   └─────┘                         │ SETTLED │
                                   └─────────┘

   ┌───────────┐ cron: expires_at < now() AND no activity
   │ ABANDONED │ ←──────────────────────────────────
   └───────────┘
```

---

## 4. Поток: успешный ран

```
═══════════════ ENTER ═══════════════

[Client] → POST /api/v1/dungeons/crypt_normal/enter
           Idempotency-Key: <uuid>
           Body: { character_id }

[FastAPI] (в одной БД-транзакции):
  - SELECT character (FOR UPDATE)
  - проверка level/energy/gold
  - проверка daily_dungeon_entries.count < dungeon.daily_limit
  - проверка no active run on character
  - UPDATE balances: gold -= entry_cost, energy -= 10
  - INSERT transactions (DUNGEON_ENTRY, -entry_cost)
  - UPSERT daily_dungeon_entries (count + 1)
  - INSERT dungeon_runs (status=IN_PROGRESS, current_floor=0,
                         seed=random_bytes(32), character_state=snapshot,
                         expires_at=now()+24h)
  - сгенерировать ws_token (JWT, exp=30s):
    {
      run_id, user_id, character_snapshot (HP/mana/stats/skills),
      seed, dungeon_config (floors, encounters, loot_tables),
      callback_secret_id  // для HMAC при callback
    }

[FastAPI] → 200 OK { run_id, ws_url, ws_token, dungeon }

═══════════════ WS CONNECT ═══════════════

[Client] → wss://realtime.example.com/runs/<run_id>/ws
           Subprotocol: token=<ws_token>

[Colyseus.onAuth]: jwt.verify(ws_token, SHARED_SECRET)
[Colyseus.onCreate]: создаёт World из payload (без DB-чтения!)
                     спавнит floor 0
[Colyseus.onJoin]: client attached

═══════════════ FLOOR 0 GAMEPLAY ═══════════════

20Hz tick loop:
  - applyInputs() — валидация и обработка input от клиента
  - updateAI() — мобы выбирают действия
  - move() — позиции с коллизиями
  - resolveCombat() — урон, смерти
  - spawnLootOnGround() — при death моба, в Colyseus state (не в БД!)
  - syncToClient() — Colyseus Schema diff broadcast

[Player tap on loot drop]:
  [Client] → WS message { pickup: lootId }
  [Colyseus]:
    - validate radius (player близко к лут-точке)
    - HMAC-callback POST /api/v1/internal/runs/<id>/loot-pickup
      Body: { item_roll: {base_id, rarity, ilvl, affixes}, idempotency_key }
    - await response (timeout 5s, retry на 5xx)
    - on success (FastAPI вернул item_id):
      - INSERT items (owner_user_id, escrow_run_id=run_id, ...)
      - удалить loot из Colyseus state
      - broadcast { event: 'loot_picked', loot_id, item_id }
    - on failure: rollback — лут остаётся на полу

═══════════════ FLOOR CLEARED ═══════════════

Все мобы убиты:
  [Colyseus]:
    - HMAC-callback POST /api/v1/internal/runs/<id>/checkpoint
      Body: {
        current_floor: 1,                    // следующий этаж
        character_state: {hp, mana, buffs}, // snapshot для recovery
        pending_gold_delta: 250              // золото за этот этаж
      }
    - await ack от FastAPI:
      - UPDATE dungeon_runs SET current_floor=1, character_state=...,
                                 pending_gold = pending_gold + 250,
                                 last_checkpoint_at = now()
      - INSERT run_encounters (combat summary, для replay)
      - 200 OK
    - ТОЛЬКО ПОСЛЕ ack: Colyseus спавнит floor 1
    - спавн портала (визуально)
    - игрок проходит в портал → loading screen → новый floor

═══════════════ ... повторяется для floors 1, 2, 3, 4 ═══════════════

═══════════════ BOSS DEFEATED ═══════════════

[Colyseus]:
  - HMAC-callback POST /api/v1/internal/runs/<id>/checkpoint
    Body: {
      current_floor: 5,
      character_state: ...,
      pending_gold_delta: 1000,
      status: 'COMPLETED'  // финальный
    }
  - await ack:
    - UPDATE dungeon_runs SET status=COMPLETED, finished_at=now()
    - 200 OK
  - Colyseus broadcast { event: 'run_complete' }
  - Colyseus закрывает Room через ~5 сек (даём клиенту прочитать events)

[Client] видит «Complete!» экран с лутом

═══════════════ CLAIM ═══════════════

[Client] → POST /api/v1/runs/<run_id>/claim

[FastAPI] (в БД-транзакции):
  - SELECT dungeon_runs (FOR UPDATE)
  - проверка status IN (COMPLETED, FAILED, FLED)
  - SELECT items WHERE escrow_run_id = run_id
  - проверка inventory has space (или auto-sell legacy items?)
  - UPDATE items SET escrow_run_id=NULL, inventory_position=<next_free>
  - UPDATE balances SET gold = gold + pending_gold
  - INSERT transactions (DUNGEON_REWARD, +pending_gold)
  - UPDATE dungeon_runs SET status=SETTLED
  - 200 OK { items, gold_received }

[Client] видит обновлённый инвентарь
```

---

## 5. Failure-сценарии

### 5.1 Кратковременный disconnect клиента (< 60s)

**Что происходит:**
- Colyseus детектит close → клиент detached, Room остаётся живой
- Запускается grace timer на 60–90 сек
- Tick loop продолжается (мобы атакуют пустоту, опционально — pause AI на grace period)

**При reconnect:**
- Client → WS connect с тем же `ws_token`
- Colyseus.onAuth verifies JWT (если ещё не expired)
- Если expired — клиент сначала идёт в `POST /runs/:id/refresh-token` → новый ws_token
- onJoin → attach к существующей Room → отправить full snapshot world
- Tick loop продолжается, ничего не потеряно

**Что НЕ работает:**
- Если игрок умер во время disconnect → status=FAILED, надо начинать заново или ревайвить

### 5.2 Disconnect > grace (Room уничтожена)

**Что происходит:**
- Grace timer истёк → Colyseus close Room
- В БД: `dungeon_runs.status = IN_PROGRESS` (не меняется автоматически)
- Player при возврате в Mini App видит «У вас прерванный ран в <dungeon>»

**Опции игрока:**
1. **Resume:** POST `/api/v1/runs/<run_id>/resume`
   - FastAPI валидирует: run.status = IN_PROGRESS, expires_at > now()
   - выпускает новый ws_token с теми же данными (run_id, character_state из last_checkpoint, seed)
   - Client → WS connect → новая Room создаётся
   - Colyseus.onCreate инициализирует World из payload, спавнит **тот же** этаж заново (тот же seed → те же мобы и лут)
   - **Что сохранилось:** все items с escrow_run_id=run_id (поднятые на пройденных этажах), pending_gold с пройденных этажей
   - **Что потеряно:** прогресс на текущем этаже (мобы респаунятся), золото и лут текущего этажа (если что-то успели поднять — сохранено в items)

2. **Flee:** POST `/api/v1/runs/<run_id>/flee`
   - status → FLED, finished_at = now()
   - Дальше → POST /claim → забирает накопленное (items + pending_gold)

3. **Ничего:** через 24 часа cron `cleanup_expired_runs()` пометит status=ABANDONED. Items с escrow_run_id остаются, ABANDONED policy решает судьбу (см. DATABASE.md §6.3).

### 5.3 Падение Colyseus процесса (целиком)

**Что происходит:**
- Все Rooms на ноде потеряны
- В БД множество `dungeon_runs` висят в `IN_PROGRESS`
- Клиенты получают WS error/close

**Recovery:**
- Colyseus процесс рестартует (Docker restart policy / k8s)
- На startup НЕ восстанавливает Rooms автоматически (anti-pattern, см. §7)
- Каждый клиент идёт по сценарию 5.2 (Resume / Flee)
- При scale-out `dungeon_runs.realtime_node_id` помогает понять, какие раны были на упавшей ноде, и метрики покажут масштаб

### 5.4 Failure callback Colyseus → FastAPI

**Loot pickup callback failed:**
- HTTP 5xx или timeout → Colyseus retry с тем же `idempotency_key`
- 3 retries с exponential backoff (200ms, 1s, 5s)
- Если всё ещё fail → лут остаётся на полу, игрок может попробовать снова tap
- Логируется WARN, метрика `loot_pickup_failures_total`

**Floor transition checkpoint failed:**
- Colyseus НЕ переходит на следующий этаж
- Retry в фоне (5 попыток × 1s)
- Игроку показывается «Saving progress...» индикатор
- Если за 30 сек не получили ack → клиенту показать «Connection issue, please retry» + возможность ручного retry
- Worst case: игрок снова зачищает уже зачищенный этаж (idempotency_key защитит от двойной записи)

### 5.5 Падение FastAPI

**Что происходит:**
- Colyseus callbacks начинают фейлить
- Активные раны продолжают играть (state в Colyseus памяти)
- Pickup и checkpoint калбэки кладутся в retry-очередь Colyseus
- Когда FastAPI поднимется — retries проходят, всё догоняется

**Worst case:**
- FastAPI лежал > grace period reconnect → клиенты, которые попытались reconnect, не смогли (FastAPI не выдаёт ws_token)
- После recovery — Resume сценарий

### 5.6 Падение PostgreSQL

**Что происходит:**
- FastAPI отвечает 5xx на всё
- Colyseus не может делать checkpoints
- Активные раны продолжают играть в памяти Colyseus, но их state «отрывается» от persistent

**Recovery:**
- При восстановлении Postgres — Colyseus retry callbacks → checkpoints проходят
- Если FastAPI был в downtime > N минут — некоторые ws_token expired → клиенты должны refresh

---

## 6. Anti-patterns (что НЕ делаем) — с обоснованием из ресёрча

### 6.1 ❌ Snapshot всего state в Redis каждый tick
- 20Hz × 1000 rooms = 20K writes/sec для околунулевой выгоды
- Игрок не различает 50ms vs 30s loss в восприятии
- CPU node-процесса страдает на serialize

### 6.2 ❌ Использовать Colyseus `devMode` с `onCacheRoom` в проде
- Документация Colyseus прямо запрещает: «not optimized for a large amount of rooms»
- На restart все rooms одновременно регидрируются → death spiral

### 6.3 ❌ Сохранять полный state в Postgres каждые N секунд
- WAL-нагрузка убьёт прод
- Postgres не для эфемерного state

### 6.4 ❌ Лут commit'ить только на claim (предыдущая версия плана)
- Last Epoch-сценарий: краш между «complete» и материализацией = потеря эпиков
- Жалобы валом на форумах
- Решение: pickup = sync write, claim = только release escrow

### 6.5 ❌ Полный event sourcing с replay
- Сложность операций × 3, отладка × 5, recovery latency × 10
- Используется когда audit trail / replay — продуктовое требование (анти-чит арбитраж в турнирах)
- Для MVP — overkill

### 6.6 ❌ Hot standby Colyseus процессов
- State divergence, leader election, sync overhead
- Используется только в AAA с строгим SLA
- Нерелевантно до 100k+ DAU

### 6.7 ❌ Грейс-период 30 секунд
- Mobile network reality: смена вышек, реконнект Wi-Fi, тоннели метро регулярно занимают 30+ сек
- Цена «лишних» 30 сек висящей Room — околонулевая
- 60–90 сек — best practice для mobile-first

---

## 7. Что делает индустрия (контекст)

| Игра | Стратегия | Источник |
|---|---|---|
| **Path of Exile** | Map instances эфемерны, persist только cross-instance state | GGG dev на HN |
| **Diablo 4** | Micro-checkpoints на key events; HC-смерть при дисконнекте — норма | Multiple postmortems |
| **TrinityCore (WoW emu)** | `PlayerSaveInterval = 15 минут` дефолт + per-event saves | worldserver.conf.dist |
| **Albion Online** | In-memory primary + async Cassandra writes (hybrid) | GDC 2016 talk |
| **EVE Online** | In-memory state, persist по событиям | High Scalability article |
| **Last Epoch** | Echo runs persist на complete → жалобы на crash mid-complete | Forum complaints |

Наша стратегия = **PoE + улучшение из урока Last Epoch (sync loot pickup)**.

---

## 8. Метрики мониторинга

### Prometheus метрики:
- `wotk_runs_started_total{dungeon_id, difficulty}` — counter
- `wotk_runs_completed_total{dungeon_id, status}` — counter (status: COMPLETED/FAILED/FLED/ABANDONED)
- `wotk_run_duration_seconds{dungeon_id, status}` — histogram
- `wotk_floor_transitions_total{dungeon_id}` — counter
- `wotk_floor_checkpoint_duration_seconds` — histogram (от send до ack)
- `wotk_floor_checkpoint_retries_total` — counter
- `wotk_loot_pickup_duration_seconds` — histogram
- `wotk_loot_pickup_failures_total` — counter
- `wotk_active_rooms` — gauge (текущее число активных Colyseus Rooms)
- `wotk_room_tick_duration_seconds{percentile="p99"}` — histogram
- `wotk_grace_reconnects_total` — counter (успешные reconnect within grace)
- `wotk_grace_expired_total` — counter (Room закрыта по grace timeout)
- `wotk_runs_resumed_total` — counter
- `wotk_runs_abandoned_total` — counter (cron пометил)

### Grafana алерты:
- `wotk_floor_checkpoint_retries_total` rate > 1/sec (постоянные retry → проблемы)
- `wotk_loot_pickup_failures_total` rate > 0.1/sec (теряем pickup'ы)
- `wotk_room_tick_duration_seconds` p99 > 30ms (приближаемся к budget)
- `wotk_runs_abandoned_total / wotk_runs_started_total` > 5% за день (что-то не так)

### Триггер для пересмотра стратегии:
**Если support-обращения «потерял прогресс из-за дисконнекта» > 2% от run completions** → добавляем intra-floor Redis snapshots каждые 15 секунд:
```typescript
// В DungeonRoom.onCreate:
this.snapshotInterval = setInterval(async () => {
  const snapshot = msgpack.encode(this.state.toJSON());
  await redis.set(`run:${this.runId}:snapshot`, snapshot, 'EX', 300);
}, 15000);

// В DungeonRoom.onCreate (recovery path):
const snapshot = await redis.get(`run:${runId}:snapshot`);
if (snapshot) {
  this.state.fromJSON(msgpack.decode(snapshot));
}
```

---

## 9. Open questions

- [ ] Auto-sell при полном инвентаре на claim — или блок claim'а с просьбой освободить место?
- [ ] Pause AI мобов в течение grace-window когда client disconnected — играть честнее или сохранять challenge?
- [ ] Лимит на resume-попытки одного рана (анти-абуз против фарма стартового лута)
- [ ] Длина grace: 60s или 90s? Замерить на staging реальные mobile-disconnect'ы и калибровать
- [ ] FAILED → claim policy: 50% брошенный или 50% по броску? Влияет на ощущение «нечестно повезло» vs «обидно»

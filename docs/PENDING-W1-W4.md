# Невыполненные тикеты W1–W6

Версия: 0.4 (обновлено 2026-04-30 после полного W6 implementation: multi-floor + boss + campaign + run summary + telemetry + WEEK-7-PLAN.md)
Источник: аудит [WEEK-1-TICKETS.md](WEEK-1-TICKETS.md), [WEEK-2-TICKETS.md](WEEK-2-TICKETS.md), [WEEK-3-TICKETS.md](WEEK-3-TICKETS.md), [WEEK-4-TICKETS.md](WEEK-4-TICKETS.md), [WEEK-5-PLAN.md](WEEK-5-PLAN.md), [WEEK-6-PLAN.md](WEEK-6-PLAN.md).

ROADMAP.md ведёт прогресс **на уровне фаз**, не тикетов. Этот документ — единый перечень того, что осталось из W1–W6 (с указанием причины блокировки).

**Изменения v0.4:** W6 Days 1-6 закрыты полностью (multi-floor + boss + campaign progression + run summary UX + telemetry + admin endpoints + 50% escrow policy). Day 7 W6-063 ([WEEK-7-PLAN.md](WEEK-7-PLAN.md)) сделан. Не закрыты только W6-060/061/062 — все блокируются Блоком 2 (real TG) / Блоком 4 (real device). Метрики: backend 331/331 ✅, realtime 139/139 ✅, frontend tsc clean ✅, 9 миграций (включая 0009 dungeon_campaign_meta).

**Изменения v0.3 (для истории):** W5 Days 1-6 закрыты, W5-060/061/062 заблокированы внешним.

**Изменения v0.2 (для истории):** все локально-доступные тикеты W1-W4 закрыты.

---

## 🚫 Блок 1 — Production deploy (нужен Hetzner + домен)

Вся инфра-цепочка карри-овер'ится с W1 в W2 и до сих пор не сделана. Распаковка ~24h работы:

| ID | Тикет | Источник |
|---|---|---|
| W1-006 / W2-001 | GitHub repo + push (сейчас `git remote` указывает на placeholder) | W1, W2 |
| W1-007 | Прогон CI локально через `act` | W1 |
| W1-050 / W2-002 | Hetzner CCX23: создать сервер, ufw + fail2ban + non-root юзер + Docker | W1, W2 |
| W1-051 / W2-003 | Зарегистрировать домен + DNS + Cloudflare proxy | W1, W2 |
| W2-004 | `.env.production.example` + сгенерировать prod-секреты | W2 |
| W2-005 | Postgres + Redis в prod compose (без публичных портов, persistent volumes) | W2 |
| W2-006 | Smoke-тест prod после миграций | W2 |
| W1-052 / W2-010 | Caddy + auto-TLS (Let's Encrypt через DNS-validated) | W1, W2 |
| W1-053 / W2-011 | GitHub Actions deploy workflow (push в main → ssh-action → docker compose up -d --build → `/health` smoke check) | W1, W2 |
| W2-012 | Production secrets через Docker secrets (chmod 600 + owner=wotk) | W2 |
| W2-013 | Sentry проект для production (DSN + APP_ENV=production + проверка PII redaction) | W2 |
| W2-014 | Backup стратегия — pg_dump → Backblaze B2 cron + 7d/4w/3m retention + restore-smoke | W2 |
| W1-054 | Прогон миграций на prod БД + smoke-тест | W1 |

**Выходной milestone:** `https://wayoftheking.app/health` отвечает 200 с валидным TLS, push в main → автодеплой ≤ 3 мин.

---

## 🚫 Блок 2 — Real Telegram (нужен prod URL для BotFather)

| ID | Тикет | Источник |
|---|---|---|
| W1-060 / W2-020 | BotFather: `/setdomain` + `/newapp` с prod URL + иконки 640×360, 192×192 | W1, W2 |
| W1-061 / W2-023 | E2E smoke в реальном Telegram (iOS + Android, попросить друга) | W1, W2 |
| W2-024 | Bug fixes из W2-023 (typical: viewport mismatch, safe-area iOS, theme-params) | W2 |
| W2-062 | Phase 2 milestone smoke в реальном TG: feel mobile-Diablo + 2 friends feedback | W2 |
| W3-060 | E2E playable loop: login → enter dungeon → multi-tab → flee | W3 |
| W3-061 | Bug fixes из W3-060 (rubber-band, ws_token TTL, Pydantic schema mismatches) | W3 |
| W4-053 | E2E equip → stats change → ready (ручной + screenshot evidence) | W4 |
| W5-060 | E2E smoke W5: enter Crypt Normal → kill 5 mobs → settle → equip best drop → re-enter с буст stats | W5 |
| W5-062 | Bug fixes из W5-060 (типичные: cast latency, mob HP-bar drift, damage-number flood) | W5 |
| W6-060 | E2E smoke W6: clear floor-1 → advance → clear floor-2 → boss kill → finalize → check campaign_progress UPSERT + RunSummary + новый item в inventory + level-up animation | W6 |
| W6-062 | Bug fixes из W6-060 | W6 |

> Локально часть проверяется через ngrok ([LOCAL-TELEGRAM-TESTING.md](LOCAL-TELEGRAM-TESTING.md)) — но финальный sign-off без prod URL невозможен.

---

## 🎨 Блок 3 — Assets-blocked (нужны LPC sprite pack + Tiled tilesets)

| ID | Тикет | Источник |
|---|---|---|
| W2-041 | Скачать LPC sprite pack (Knight idle + walk × 4 направления) + license-файл | W2 |
| W2-042 | Tiled Map Editor: создать первую комнату 20×15 + tile layers + collision objects | W2 |
| W2-043 | Pixi-loader Tiled JSON (`game/render/TiledMap.ts`) — заменит процедурный `room.ts` | W2 |
| W2-044 | Knight idle/walk анимация через PIXI.AnimatedSprite (заменит placeholder circle) | W2 |

> Сейчас работает placeholder-версия: процедурные комнаты (5 layouts) + circle Knight с chevron-индикатором facing. Свап на real assets — drop-in без архитектурных изменений (контракт `room.ts` + `Player.ts` сохранён).

---

## 📱 Блок 4 — Performance (нужен реальный mid-range Android / iPhone)

| ID | Тикет | Источник |
|---|---|---|
| W2-060 | Performance pass: Pixi-рендер на Pixel 5 эмуляторе, цель 60 FPS | W2 |
| W4-060 | Combat math benchmark (1000 mob kills + 10000 damage calcs < 100ms) — частично можно сделать через cProfile, но измерение target-platform требует устройства | W4 |
| W5-061 | Performance pass W5: 60 FPS при 5+ mobs + AoE skill effects + damage-number spam — Pixi profiler на реальном mid-range Android | W5 |
| W6-061 | Performance pass W6: 60 FPS при boss + 4 minion'а + AOE telegraph + damage-number spam — Pixi profiler | W6 |

---

## ✅ Блок 5 — Локальная observability (CLOSED v0.2)

| ID | Тикет | Источник | Status |
|---|---|---|---|
| W3-052 | Расширить `/health/ready`: Redis ping + Arq queue length | W3 | ✅ done — [main.py](../backend/src/wotk/api/main.py), test в [test_health.py](../backend/tests/test_health.py) |
| W3-053 | Request duration / status в structlog | W3 | ✅ done — [middleware.py](../backend/src/wotk/core/middleware.py) логирует `request_completed` с `duration_ms` + `status_code`; health-эндпоинты заглушены |
| W3-054 | Colyseus structured логи (run_id + profile_id) | W3 | ✅ done — extracted shared [logger.ts](../realtime/src/logger.ts), DungeonRoom child'компонент логирует `ws_auth_ok`/`ws_join`/`ws_leave`/etc |
| W2-063 | `WEEK-3-PLAN.md` outline | W2 | ✅ done — [WEEK-3-TICKETS.md](WEEK-3-TICKETS.md) — полный 31-тикет файл вместо outline |
| W3-062 | `WEEK-4-PLAN.md` outline | W3 | ✅ done — [WEEK-4-TICKETS.md](WEEK-4-TICKETS.md) |
| W4-062 | `WEEK-5-PLAN.md` outline | W4 | ✅ done — [WEEK-5-PLAN.md](WEEK-5-PLAN.md) (31 outline-тикет) |

**Только осталось:** W4-061 (bug fixes резерв из manual testing) — зависит от W4-053 e2e в реальном Telegram, разблокируется после Блока 2.

---

## ✅ Блок 6 — Realtime client prediction + server collision (CLOSED v0.2)

| ID | Тикет | Источник | Status |
|---|---|---|---|
| W3-043 | Полноценная client prediction для своего player'а (drift < 30px → smooth lerp; drift ≥ 30px → snap) | W3 | ✅ done — [scene.ts](../frontend/src/game/scene.ts) `reconcileOwnPlayer(serverX, serverY)`; lerp-rate 0.18 (≈80% drift убирается за 167ms); snap при drift ≥ 30px (rubber-band). Wired в [Playground.tsx](../frontend/src/screens/Playground.tsx) — own sessionId на onPlayerUpdate теперь reconcile, не ignore. |
| W3-044 | Dev overlay с latency (ping/pong) + packets/sec | W3 | ✅ done — [realtime.ts](../frontend/src/game/realtime.ts) `getMetrics()` + ping/pong с 2s интервалом; `<DevOverlay>` в Playground под `import.meta.env.DEV` + online mode |
| (gap) | Server-side collision в Colyseus против walls | W3 | ✅ done — [DungeonRoom.ts](../realtime/src/rooms/DungeonRoom.ts) добавлен `ROOM_WALLS` placeholder geometry (40×30 arena с периметром) + `collidesAt()` + slide-along-wall в tick. В W5 геометрия будет передаваться из `/enter` response. |

---

## 🟡 Блок 7 — Документация и polish

| ID | Тикет | Источник | Notes |
|---|---|---|---|
| W1-063 | RUNBOOK.md production sections (`[WHEN-PROD]` маркеры) | W1 | Skeleton есть, заполнить после Hetzner-деплоя |
| W2-064 / W3-063 / W4-063 / W5-063-buf | Buffer-тикеты на bug fixes | W2/W3/W4/W5 | Не самостоятельные задачи |

---

## 🟢 W5 follow-ups — переехали в WEEK-6-PLAN.md

Эти пункты родились в процессе реализации W5 (sub-agent reports + simplify-review + security-review). Вместо отдельного списка — все вошли в [WEEK-6-PLAN.md](WEEK-6-PLAN.md) Day 5 (W6-040..045) и Day 6 (W6-050..054). Ничего не потеряно.

| Источник | Что переехало |
|---|---|
| Day 5 sub-agent | CSS pass для всех новых BEM-классов (`playground__hotbar*`, `playground__death-screen`, `playground__damage-number`) → W6-042 |
| Day 6 sub-agent | Per-skill SFX дифференциация + gore-particle на смерти моба → W6-043, W6-044 |
| simplify-review | Optimistic CD без server-rejection recovery — known limitation, ждёт W6 |
| simplify-review | Loot icon click → real backend pickup endpoint (сейчас visual-only) → W6-041 |
| security-review | Defense-in-depth caps на /internal/finalize (gold/xp/items relative to dungeon config) — ✅ закрыто в этом сеансе ([dungeons.py](../backend/src/wotk/api/v1/dungeons.py), 2 regression теста) |

---

## ✅ Что НЕ в этом списке (сделано)

- W1-001..005 (env, postgres, backend, alembic, structlog) ✅
- W1-009..013 (enums, models, миграции, db session, integration tests) ✅
- W1-020..024 (initData HMAC, JWT, /auth/login, current_user, /me) ✅
- W1-030..034 (POST /heroes, stats, leveling, bot, hero tests) ✅
- W1-040..045 (Vite, Telegram SDK, auth flow, i18n, CreateHero, City) ✅
- W1-062 (bug fixes, ongoing) ✅
- W2-021/022 (bot /start deeplink + /help/wallet — сделаны ещё в W1) ✅
- W2-030/031/034 (idempotency_keys + middleware + /health/ready) ✅
- W2-032 (Arq cron + cleanup_expired_idempotency_keys) ✅
- W2-033 (structlog JSON + Sentry request_id tag) ✅
- W2-040/042-alt/043/044-alt (Pixi v8 + процедурные комнаты + placeholder Knight) ✅
- W2-050..054-alt (joystick + movement + collision + camera + 5 layouts) ✅
- W2-061 (resize + orientationchange listener) ✅
- W3-001..005 (§6 миграция + модели + seed reference + loot_db adapter + 17 тестов) ✅
- W3-010..014 (§8 миграция + модели + seed dungeons + триггеры + 14 тестов) ✅
- W3-020..025 (GET /dungeons + POST /enter + POST /flee + POST /internal/finalize + HMAC) ✅
- W3-030..035 (Colyseus DungeonRoom + WorldState + onAuth JWT + 20Hz tick + HMAC client) ✅
- W3-040..042 (colyseus.js client + connect-on-enter + render server-state) ✅ *(W3-043 client prediction только partial — см. Блок 6)*
- W3-050 (reconciliation cron) ✅
- W3-051 (real cleanup_expired_runs) ✅
- W4-001..005 (combat formulas + cooldowns + Knight skills + 45 тестов) ✅
- W4-010..014 (3 mobs + AI FSM + A* + spawn + 22 тестов) ✅
- W4-020..023 (skill_cast + status_effects + drops + combat_log) ✅
- W4-030..034 (inventory backend + tests) ✅
- W4-040..044 (Inventory React grid + tooltip + rarity colors + i18n) ✅
- W4-050..052 (hero_stats + GET /me/combat-stats + City stats panel) ✅
- W5-001..005 (mobs в WorldState + spawn + frontend render + tests) ✅
- W5-010..014 (AI FSM в realtime tick + A* pathfinding + integration tests) ✅
- W5-020..025 (skill cast + mob attack + status effects + cooldowns + 75 тестов) ✅
- W5-030..035 (drops + materialize_item + HMAC finalize callback + escrow auto-claim + integration tests) ✅
- W5-040..045 (frontend combat UX: Hotbar + tap-to-cast + damage numbers + HP bars + DeathScreen + i18n) ✅
- W5-050..054 (inventory polish + drop UX: loot icons + LongPressMenu + CompareTooltip + new-item badge + sfx placeholders) ✅
- W5-063 ([WEEK-6-PLAN.md](WEEK-6-PLAN.md) — 31 outline-тикет: multi-floor + boss + campaign progression) ✅
- W5-security ([dungeons.py](../backend/src/wotk/api/v1/dungeons.py) — Pydantic Field bounds + dungeon-config-relative caps на /internal/finalize, 2 regression теста) ✅
- W6-001..005 (multi-floor server logic: FloorConfig в JWT + next_floor handler + per-floor RunEncounter + auto-checkpoint + 4 интегр. теста) ✅
- W6-010..015 (boss encounter: crypt_lich mob + telegraph/enrage/summon AI + boss-floor spawn + boss death = COMPLETED + 9 boss tests) ✅
- W6-020..025 (campaign progression: миграция 0009 + dungeon.act/location + UPSERT campaign_progress + GET /me/campaign + Campaign.tsx + i18n) ✅
- W6-030..035 (post-run summary: RunSummaryDTO + GET /runs/{id}/summary + RunSummaryScreen + DeathScreen v2 + FloorClearedToast + LevelUpSparkle + i18n) ✅
- W6-040..045 (W5 follow-ups: CSS pass для всех BEM-классов + per-skill SFX + gore-particles + W6-040 уже сделан в /simplify pass) ✅
- W6-050..054 (reliability+telemetry: floors_breakdown logging + Sentry breadcrumbs + /metrics endpoint + admin /encounters + cleanup 50% escrow policy) ✅
- W6-063 ([WEEK-7-PLAN.md](WEEK-7-PLAN.md) — 31 outline-тикет: TON wallet + deposit/withdraw + testnet jetton) ✅

**Метрики:** 331/331 backend тестов зелёные (288 baseline + W6 additions), 139/139 realtime тестов зелёные (124 baseline + boss+drops), frontend typecheck green, 9 миграций применены.

---

## Приоритизация (после v0.4)

**Все локально-доступные тикеты W1-W6 закрыты.** Что осталось — всё ждёт внешних разблокировок:

**HIGH (анлокит реальное тестирование):**
1. Блок 1 (Hetzner-деплой целиком) — 24h
2. Блок 2 (BotFather + e2e в TG, включая W5-060 + W5-062 + W6-060 + W6-062) — 6h после Блока 1

**MEDIUM (улучшает MVP до играбельности):**
3. Блок 3 (assets) — нужен художник или ~10h на покупку готовых паков

**LOW (нет нужды до prod):**
4. Блок 4 (perf на устройстве, включая W5-061 + W6-061) — после первого playable build
5. Блок 7 (RUNBOOK production sections) — после Блока 1

W7 ([WEEK-7-PLAN.md](WEEK-7-PLAN.md)) — TON wallet integration на testnet — можно стартовать сейчас, Hetzner deploy не блокирует (testnet работает локально через TON HTTP API).

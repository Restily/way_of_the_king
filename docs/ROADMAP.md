# Way Of The King — Roadmap

Версия: 0.1 (черновик)
Последнее обновление: 2026-04-27

Документ разбит на две части: путь до MVP (~16 недель) и путь до 1M DAU (~24 месяца).

---

# ЧАСТЬ I. Roadmap до MVP

**Цель MVP:** играбельная Knight-кампания с базовым лутом и работающим вводом/выводом TON. Без маркета, без PvP, без других классов.

**Срок:** 16 недель / ~4 месяца при 60ч/нед

**Бюджет до MVP:** ~3–8k$ (юр.лицо + ассеты + хостинг + ликвидность)

## Phase 0. Pre-development (1 неделя, параллельно с кодом)

### Юридическое

- День 1–3: консультация с крипто-юристом (200–500$, asynchronously по email)
- День 3–7: подача документов на Individual Entrepreneur в Грузии (через TBC/BoG, ~300$, оформление ~2 недели)
- ToS + Privacy Policy (Termly или iubenda шаблон + правка)
- Регистрация торговой марки WOTK (опционально, 200$ в Грузии)

### Инфраструктура

- Регистрация домена (`wayoftheking.app` или `.io`, ~30$)
- Hetzner аккаунт + первый CCX23 (~30€/мес)
- GitHub Organization (private)
- Cloudflare аккаунт (Free)
- BotFather: создать `@WayOfTheKingBot`, привязать домен
- Sentry account (Free tier)

### Контент

- GDD v0.1 (5–10 страниц): формулы статов, скиллов, дроп-таблиц
- Стиль-гид: палитра, шрифты (Cinzel, IM Fell English), референсы
- Покупка ассет-паков на itch.io ($50–100): dungeon tilesets (Crypt, Forest, Castle), character spritesheets (LPC Knight), monster pack, UI kit фэнтези
- Game-icons.net — все иконки скиллов/предметов (CC BY 3.0, бесплатно)

## Phase 1. Скелет (Недели 1–2) ✅ DONE *(production deploy отложен)*

### Backend ✅

- ✅ Monorepo (`backend/` Python + `realtime/` Node + `frontend/` TS + `shared/`)
- ✅ `pyproject.toml` (uv), Docker Compose (postgres + redis + caddy)
- ✅ FastAPI app: `/health` + `/health/ready`, structlog (JSON в prod), Sentry с PII-редакцией + request_id tag
- ✅ SQLAlchemy 2.0 async + Alembic 6 миграций (profile/balance/referral/hero/transaction + best-practices delta + idempotency)
- ✅ `initData` HMAC валидация + JWT issue/verify (HS256/384/512 only)
- ✅ POST `/auth/login`, GET `/me`, POST `/heroes` с idempotency middleware
- ✅ Arq worker с cron-задачами (cleanup_expired_idempotency_keys)
- ❌ **Деплой на Hetzner — отложен** (требует prod-инфраструктуры; W2-001..014)

### Frontend ✅

- ✅ Vite + React 19 + TS + i18next (ru, en)
- ✅ Telegram WebApp SDK интеграция
- ✅ Авторизация по `initData` → JWT в memory + Telegram CloudStorage
- ✅ Welcome screen, character creation (Knight only)
- ✅ City UI с активной кнопкой Campaign → Playground
- ✅ Pixi v8 placeholder сцена: процедурные комнаты + circle Knight + nipplejs джойстик + WASD + collision + camera follow + room selector

### Bot ✅

- ✅ aiogram skeleton: `/start` с deeplink + referral parsing, `/help`, `/wallet` placeholder

**Конец Phase 1:** Mini App работает локально (через ngrok для тестирования в TG). Production-деплой ждёт W3+.

## Phase 2. Рендер и движение (Недели 3–4)

### Frontend (PixiJS) — частично сделано в W2 с placeholder-графикой

- ✅ Pixi v8 канвас + Application
- ❌ `@pixi/tilemap`, рендер первой комнаты из Tiled JSON (нет assets)
- ❌ Спрайт Knight (idle + walk × 4 направления) — из LPC pack (нет assets)
- ✅ nipplejs виртуальный джойстик
- ✅ Local-only движение с коллизиями (без сервера) — на placeholder-circle
- ✅ Camera follow player
- ✅ Resize handling (orientation change)

### Tiled — отложено

- 5 тестовых комнат уже сделано **процедурно** (см. `frontend/src/game/room.ts`)
- Tiled JSON loader + LPC tileset — когда появятся assets

**Конец Phase 2:** клиент-only, перс ходит по комнате, чувствуется feel mobile-Diablo. Placeholder-версия уже работает; остаётся swap geometry → Tiled и circle → animated sprite.

## Phase 3. Realtime layer (Недели 5–7)

### Realtime (Colyseus)

- Init Node проект, TypeScript, Colyseus 0.16
- DungeonRoom с onAuth (JWT verify), onJoin
- Schema: WorldState, Entity, Player
- Server tick 20Hz, applyInput → move → broadcast state
- Internal HMAC client для callback в FastAPI

### Backend

- POST `/dungeons/{id}/enter`: создаёт DungeonRun, выдаёт ws_token (короткий JWT)
- POST `/internal/runs/{id}/finalize`: HMAC-signed callback от Colyseus

### Frontend

- Colyseus.js client
- Подключение к WS после `enter` запроса
- Client prediction для движения, reconciliation от server state
- Render entities из Schema (player + другие в будущем)
- Metrics в console: latency, packet rate

### Tooling

- Shared schemas: первые 2 (JWT payload, RunFinish payload)
- Codegen: `datamodel-code-generator` (Python), `json-schema-to-typescript`

**Конец Phase 3:** Knight движется по комнате через сервер, latency < 100ms locally

## Phase 4. Бой: мобы и атаки (Недели 8–10)

### Мобы

- 3 типа в MVP: Skeleton Warrior (melee), Skeleton Archer (ranged), Zombie (melee tank)
- A* pathfinding по grid (или flow field)
- AI states: idle → patrol → detect → chase → attack → return
- Server-side spawn по encounter config

### Combat

- Auto-attack: tap враг → подбежать → бить с интервалом
- Damage formula на сервере, hp updates broadcast
- 2 скилла в первой итерации: Cleave + Shield Bash
- Cooldowns, mana, validation
- Damage popups (client-only, из server events)
- Death анимация моба, despawn

### Frontend

- React HUD: HP/Mana orbs (Diablo style), skill bar (4 buttons)
- Touch handling: tap-to-attack (auto-target), skill buttons
- Knight attack animations (LPC has those)
- Particle effects для скиллов (PixiJS particles)

**Конец Phase 4:** можно зайти в комнату с мобами, убить их используя 2 скилла

## Phase 5. Скиллы, лут, инвентарь (Недели 11–12)

### Скиллы (все 6)

- Whirlwind, Charge, Battle Shout, Last Stand
- Skill picker UI (выбор 4 в hotbar)
- Базовая балансировка

### Лут

- Loot table в config данжа
- Drop rolls на server при death моба
- Loot entity на полу с tap-pickup
- Affixes generation (5 префиксов + 5 суффиксов в первой итерации)
- 5 baseTypes на старте: помогать собирать билд

### Inventory

- React grid 6×8
- Equipment screen: 6 слотов
- Equip/unequip с пересчётом статов
- Item tooltip с rarity-coded цветами
- Сортировка/фильтры

**Конец Phase 5:** полный gameplay loop: вошёл → убил мобов → собрал лут → одел → стал сильнее

## Phase 6. Многокомнатные данжи + кампания (Недели 13–14)

### Multi-room dungeon

- Колесёус: room state с `current_room_idx`, `rooms: RoomDef[]`
- Триггер «всё убито» → spawn портала → переход в следующую комнату
- Boss room (5-я комната): уникальный моб с 3× HP и спец-механикой
- Run lifecycle: enter → 5 floors → boss → claim screen

### Campaign

- 1 акт (5 локаций) в MVP, остальные — после
- Campaign screen с прогрессом
- Локации: Outskirts → Crypt Entrance → Crypt Depths → Throne Hall → Boss

### Daily/Energy

- Восстановление энергии (cron каждые 6 минут)
- Daily reset (UTC midnight) — лимиты данжей

### Bot push

- «Энергия восстановлена», «Daily reset»

**Конец Phase 6:** играбельная кампания на 5 локаций

## Phase 7. TON интеграция (Недели 15–16)

### Smart contract

- Деплой Jetton WOTK в **testnet** через Blueprint
- 1 неделя тестов вводов/выводов в testnet

### Backend

- HD-wallet: master mnemonic в env, sub-address generation per user
- TON-listener: singleton с Redis lock, опрос каждые 10s
- Deposit flow: detect tx → confirm → credit gold (atomic transaction)
- Withdrawal flow: API → 2FA через бота → Arq queue → подпись и отправка
- Reconciliation cron каждые 5 минут
- Лимиты, кулдауны

### Frontend

- Wallet screen: deposit address + QR, withdrawal form
- TonConnect для привязки внешнего адреса
- История транзакций
- Курс gold ↔ WOTK (отображение)

### Mainnet deploy

- Финальный деплой Jetton mainnet
- Минимальная ликвидность на STON.fi (~500–1500$ в TON + WOTK)
- Smoke-тест: 5 ручных вводов и выводов

**Конец Phase 7:** работает ввод и вывод реальных TON

## Phase 8. Polish + Closed Beta (Недели 17–18, бонусные)

> Если 16 недель не хватит — откладываем PvP и дополнительные фичи v1, оставляем только то, что строго в MVP.

- Bug-fix marathon
- Производительность (memory leaks в Pixi, оптимизация tilemap)
- Touch UX полишинг
- Tutorial: 3 экрана + первый бой за руку
- Loading screens, transitions, sound effects (бесплатные с opengameart)
- Closed beta: 50 человек из инсайдеров (TG-чат)
- Сбор фидбэка через in-app form
- 1 неделя на критичные правки

## Pre-launch marketing (параллельно с Phase 4–7)

- Twitter/X аккаунт `@WayOfTheKingApp`, build-in-public посты 3×/нед
- TG-канал EN + RU, цель 1000+ подписчиков до релиза
- Лендинг (одностраничник на Vercel, бесплатно): описание, скриншоты, форма подписки на бету
- TON Foundation grant — заявка (10–50k$ возможно)
- Подача в каталоги: tapps.bot, tonapp.io, TON Society
- Контакт с Tonkeeper и Wallet про dApps directory
- Тизер-видео 30 сек (геймплей PvE)

## Soft Launch (после Phase 8)

- Mini App доступна публично в Telegram
- Aнонс в TG-каналах
- Первые 1000 юзеров получают starter pack
- Реферальная программа: invite получает 100 gold, +10% earnings от реферала первые 30 дней
- Ежедневный мониторинг метрик: D1, conversion to first dungeon, errors
- Patches каждую неделю

### Целевые KPI после soft launch (1 месяц)

- 5 000 регистраций
- 500 DAU
- D1 30%, D7 15%
- 50 успешных withdraw'ов

---

# ЧАСТЬ II. Roadmap до 1M DAU

**Реалистичный таймлайн:** ~24 месяца от старта (≈20 месяцев после MVP). Не быстрее.

**Бюджет общий:** до 1M DAU суммарно ~500k–2M$ (большая часть — маркетинг и команда), окупаемая выручкой при достижении ~50k DAU.

## Этап A. Post-MVP стабилизация (Месяцы 5–6)

**Цели:** 5k DAU, D7 25%, первые $1k MRR

### Технология

- Production hardening: бэкапы, мониторинг, alerts
- Performance: PgBouncer, query optimization, индексы
- Vertical scale: CCX23 → CCX33 (8 vCPU, 32GB RAM)

### Контент

- Закончить кампанию: ещё 2 акта (10 локаций)
- 10 новых типов мобов
- 2 элитных босса
- Расширить аффиксы (15 → 30)
- 10 Legendary предметов

### Game design

- Балансировка по реальным данным: drop rates, XP кривая, HP мобов
- Tutorial improvements (по фидбэку)
- Daily quests system

### Маркетинг

- Сезонный ивент к запуску (например, Halloween — нежить-themed)
- 5–10 KOL'ов TON сегмента (бартер: ранний доступ + WOTK)
- Reddit r/TonCoin, r/Telegram, r/MMORPG посты

### Команда

- Найм 1 фриланс-художника на icons/UI (200–500$/мес projects)
- Community manager part-time (RU+EN, ~500$/мес)

### Юридическое

- Бухгалтерия по Грузинской IE настроена
- Compliance review: лимиты выводов, KYC-light для крупных сумм

## Этап B. Расширение классов (Месяцы 7–9)

**Цели:** 15k DAU, D7 30%, $5k MRR

### Технология

- Postgres read replica добавлена
- Redis cluster (3-node)
- Колесёус scale-out: 2 процесса с sticky routing

### Контент

- **Archer класс**: 6 скиллов, 20 пассивок, дерево, балансировка против Knight
- **Necromancer класс**: 6 скиллов с миньонами (challenge — миньоны как entities в Colyseus state, надо оптимизировать)
- 2 новые тематики данжей: Forest Spirits, Frozen Caverns
- Кросс-класс баланс (особенно важно перед PvP)

### Game design

- Class pick screen, возможность иметь 3 персонажей на аккаунте
- Stash (общее хранилище предметов между персами)

### Маркетинг

- Анонс «Update 1: The Ranger» с трейлером
- Airdrop WOTK для топ-100 игроков предыдущего месяца
- Twitter рекламная кампания (~1000$, тестово)

## Этап C. Маркетплейс (Месяцы 10–11)

**Цели:** 30k DAU, $15k MRR, P2P маркет с объёмом 100k+ gold/день

### Технология

- Маркет endpoints + escrow логика
- Search-индекс: Meilisearch (легче чем Elasticsearch для соло)
- Анти-фрод правила: лимиты, скоринг сделок
- ClickHouse для market analytics

### Game

- Market UI с filters/search
- Listing flow, expiration, auto-cancel
- Notifications через бота

### Команда

- Найм middle backend dev (~3000$/мес remote, СНГ) — критично, соло уже не вытягиваешь по объёму
- Передача части задач: маркет, аналитика, infra

### Юридическое

- Anti-fraud процедуры формализованы
- Sanctions screening (OFAC list проверка по адресам выводов)

## Этап D. PvP (Месяцы 12–14)

**Цели:** 50k DAU, $30k MRR, активное PvP комьюнити

### Технология

- PvP Room в Colyseus
- ELO matchmaking в Redis ZSET
- Сезоны: cron на закрытие/открытие, leaderboard в ClickHouse
- Anti-cheat усиленный: replay validation, behavior scoring

### Game

- PvP UI: queue, leaderboard, history
- Награды за топ-100 (uniques, gold, WOTK airdrop)
- Сезонная косметика

### Team & ops

- Community moderators (волонтёры из топ-игроков, перки)
- 24/7 monitoring rotation (или PagerDuty alerts)

### Маркетинг

- PvP турниры с призовым фондом (1000$ TON)
- Стримы топ-игроков (WOTK promotion + бонусы)

## Этап E. Internationalization (Месяцы 15–17)

**Цели:** 150k DAU, $75k MRR, выход на LATAM

### Локализация

- Перевод на ES (испанский) и PT-BR (бразильский португальский) — главные TON-рынки за СНГ
- Native QA на каждый язык (фрилансер $300/lang)
- Локальные TG-каналы и комьюнити

### Game design

- Региональные ивенты (например, Карнавал в Бразилии)
- Локальные платёжные методы (где возможно через Stars)

### Маркетинг

- KOL'ы LATAM crypto/gaming (3–5 в каждой стране, ~5k$/мес)
- Локальные пресс-релизы
- Реклама в TG Ads (Mini Apps категория) с гео-таргетингом

### Юридическое

- Юр.консультация по Бразилии и Мексике (крипто-регулирование)
- Если высокий объём — открытие entity в одной из юрисдикций

### Команда

- 2 community managers (по одному на регион)
- Marketing manager (полный рабочий день, 2–4k$/мес)

## Этап F. Major content + endgame (Месяцы 18–20)

**Цели:** 300k DAU, $200k MRR

### Контент

- Endgame system: бесконечный режим (Path of Exile-style maps, Diablo Rifts)
- Гильдии/кланы (joins, chat, гильдейский банк)
- Гильдейские ивенты (raid bosses)
- Расширенный crafting (рецепты)
- 3-й класс (если ещё не добавили): Mage / Berserker / Paladin (выбор по фидбэку)

### Технология

- Шардинг Postgres (по user_id) — это Rubicon
- Multi-region: EU + APAC nodes
- Custodial wallet sub-pool: тысячи sub-address'ов, batched withdrawals
- Dedicated TON-нода
- Мониторинг: полный Grafana stack, OpenTelemetry tracing

### Команда (~7–10 человек)

- 2 backend devs
- 1 frontend dev
- 1 game designer / balance
- 1 artist (full-time)
- 1 community lead
- 1 marketing/biz
- DevOps (part-time или contractor)

## Этап G. Hyper-growth (Месяцы 21–24)

**Цели:** 1M DAU, $1M+ MRR

### Технология

- Functional split: separate auth-service, market-service, wallet-service
- Event-driven: Kafka/Redpanda для cross-service events
- Edge compute: Cloudflare Workers для read paths
- Своё железо в colocation (кратно дешевле облака на этом масштабе)
- DDoS protection enterprise tier

### Game

- Major expansions каждые 3 месяца
- New game modes: Boss Rush, Survival, Co-op (2-3 player party)
- Mobile native apps опционально (PWA wrapper)

### Бизнес

- Listing WOTK на Tier-1 биржах (KuCoin, Gate.io, MEXC)
- Венчурный раунд если нужен (или органический рост)
- Партнёрства с другими TON-играми и сервисами
- Опциональная DAO-модель управления (governance token)

### Команда (~25–40 человек)

- 5–7 backend devs (split по сервисам)
- 3–4 frontend devs
- 2 game designers
- 3 artists
- 1 sound designer
- 1 narrative designer
- DevOps team (3 человека)
- QA team (2–3 человека)
- Marketing team (5+)
- Community team (5+ по регионам)
- Legal counsel (in-house или retainer)
- CEO/CTO/CMO leadership

### Инфраструктура расходы

- ~50–200k€/мес на хостинг и сервисы
- Customer support: ticket system, ~5+ агентов

## Сквозные блоки (на всём пути)

### Финансовая модель (грубо)

- ARPU $0.5–2/мес (стандарт TG-игр)
- При 1M DAU и $1 ARPU = $1M MRR = $12M ARR
- Чистая маржа после расходов ~30–40% = $4–5M EBITDA год при 1M DAU
- Точка безубыточности: ~5–10k DAU при правильной экономике

### Юридическая эволюция

- Месяц 0: Грузинская IE (старт)
- Месяц 6: апгрейд если объёмы > $50k/мес: Грузинский LLC
- Месяц 12: открытие entity в EU (Мальта/Кипр) для европейского рынка
- Месяц 18: VARA license в ОАЭ для глобальной операции
- Месяц 24: full compliance — KYC/AML procedures, transaction monitoring, tax reporting в N юрисдикциях

### Маркетинговая эволюция

- 0–10k DAU: build-in-public, organic, KOLs за бартер
- 10–50k DAU: paid TG Ads, KOL платный, ивенты, аирдропы
- 50k–200k: Twitter Ads, Reddit Ads, influencer programs, PR-агентство retainer
- 200k–1M: TV/streaming реклама в крупных рынках, partnerships, tournaments с большими призами, esports-формат

### Безопасность по этапам

- MVP: базовый чек-лист, ручной мониторинг
- v1: bug bounty (Immunefi или своя), внешний security audit
- 100k+ DAU: SOC 2 (если хочешь enterprise партнёрства), pentest каждый квартал
- 1M DAU: полная security team, 24/7 SOC, formal incident response

### Tokenomics эволюция

- MVP: запуск Jetton, базовая ликвидность ($1k)
- v1: листинг на STON.fi и DeDust, ликвидность $10k
- 100k DAU: листинг на CMC/CoinGecko, тиер-2 биржи, ликвидность $100k+
- 500k+ DAU: тиер-1 биржи, governance proposals, staking, vesting прозрачен онлайн

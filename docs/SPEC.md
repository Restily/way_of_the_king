# Way Of The King — Техническое задание

Версия: 0.1 (черновик)
Последнее обновление: 2026-04-27

---

## 1. Общее описание

**Название:** Way Of The King (WOTK)
**Тип:** Real-time Action RPG в Telegram Mini App с интеграцией TON
**Сеттинг:** Тёмная средневековая фэнтези. Референсы визуала: Darkest Dungeon, Diablo II, Hammerwatch, Berserk
**Жанр-референсы:** Diablo Immortal (mobile UX), Path of Exile (билды/лут), Diablo II (классы/атмосфера)
**Платформа:** Telegram Mini App (TMA), web-fallback опционально позже
**Бизнес-модель:** F2P + косметика + комиссии маркета/PvP. Никакого pay-to-win.
**Целевая аудитория:** 18–35, СНГ + глобальный TON-рынок (LATAM, SEA, MENA)

---

## 2. Функциональные требования

### 2.1 Аккаунт и аутентификация

- Регистрация автоматическая через Telegram `initData` (HMAC SHA-256 валидация)
- Одна Telegram-учётка = один игровой аккаунт
- Device fingerprint при первом логине (anti-fraud)
- Привязка TON-кошелька через TonConnect — опциональна, обязательна для вывода
- Geo-блок US/UK/санкционных юрисдикций (MaxMind GeoLite2)
- Soft KYC: телеграм + поведенческий профиль; жёсткий KYC при выводе > N USDT эквивалента (когда дойдём до порогов регулятора)

### 2.2 Система персонажей

**MVP:** только **Knight**
**v1.x (постMVP):** добавляются Archer и Necromancer

#### Knight — архетип

- Роль: melee tank/bruiser
- Основной стат: Strength (STR)
- Производные: высокий HP, средний ATK, высокий DEF, низкий MOV SPD, низкая Mana
- Вооружение: 1H Sword/Mace/Axe + Shield, либо 2H Sword/Maul (выше DPS, без блока)
- Уникальная механика: блок щитом (chance, снижает урон на N%), passive «Knight's Honor» (+def при низком HP)

#### Слоты статов

- Базовые: STR / DEX / INT — растут от уровня + распределяются вручную (3 очка на level up)
- Производные (формулы):
  - HP = 50 + STR × 5 + level × 10 + bonuses
  - Mana = 20 + INT × 3 + bonuses
  - ATK = weapon_dmg × (1 + STR × 0.02) + bonuses
  - DEF = armor + STR × 0.5 + bonuses
  - Crit Chance % = 5 + DEX × 0.2 + bonuses
  - Crit Damage % = 150 + DEX × 0.5 + bonuses
  - Attack Speed = base × (1 + DEX × 0.005) + bonuses
  - Movement Speed = base × (1 + 0.005 × DEX) + bonuses
  - Resistances (Fire/Cold/Lightning) — только от снаряжения

#### Уровни

- 1–60 в MVP. XP-кривая: `xp(n) = round(100 × n^1.7)`

#### Активные скиллы Knight (MVP)

1. **Cleave** — melee AoE, frontal cone, базовый, без cooldown
2. **Shield Bash** — single target, stun, cooldown 4s
3. **Whirlwind** — PBAOE, channeled, cooldown 8s, mana cost
4. **Charge** — dash to target, knockdown, cooldown 12s
5. **Battle Shout** — self-buff, +ATK/+DEF area, cooldown 30s
6. **Last Stand** — ультимейт: invulnerable 3s, regen, cooldown 90s

В hotbar помещается 4 одновременно. Игрок выбирает в меню перед боем.

#### Дерево пассивок

- 20 узлов (MVP), открываются по 1 за level up
- Простая ветвистая структура (не Path of Exile mega-tree)
- На v1 — расширение до 30+ узлов и опциональные ультимейт-узлы

### 2.3 Система предметов

#### Слоты экипировки (6)

- Helmet
- Chest (Body Armor)
- Weapon (1H или 2H)
- Off-hand (Shield для 1H; пустой для 2H)
- Boots
- Ring

#### MVP типы баз

- Helmets: 4 (cap, helm, great helm, hood)
- Chests: 4 (leather, mail, plate, robes)
- Weapons: 6 (1H sword, 2H sword, 1H mace, 1H axe, 2H axe, dagger)
- Shields: 3 (buckler, kite, tower)
- Boots: 3 (leather, mail, plate)
- Rings: 3 (silver, gold, platinum)
- Итого: ~23 base items

#### Рарность и аффиксы

| Рарность | Префиксы | Суффиксы | Спец |
|---|---|---|---|
| Common (white) | 0 | 0 | — |
| Magic (blue) | 1 | 1 | — |
| Rare (yellow) | до 2 | до 2 | — |
| Epic (purple) | до 3 | до 3 | unique implicit |
| Legendary (orange) | fixed | fixed | unique passive |

#### MVP-аффиксы

- 15 префиксов (`+X to Max HP`, `+Y% Increased ATK`, `+Z to STR`, `+W% Crit Chance`, etc.)
- 15 суффиксов (`+X% Resistance`, `Life Leech +Y%`, `+Z% Movement Speed`, etc.)
- 5 уникальных Legendary в MVP (например, "Crown of Lions" — +50 HP, +20% damage to undead, set bonus)

#### Item level (ilvl)

- ilvl = level моба, который дропнул
- Влияет на пул возможных аффиксов

#### Действия с предметами

- Equip / Unequip
- Sell to NPC (за gold)
- Salvage (разобрать → 1–N осколков по рарности)
- Reroll affixes (за осколки + gold)
- Listing на маркете (v1)

#### Инвентарь

- Grid 6×8 (48 ячеек), позже расширяется покупкой за «Корону»

### 2.4 Боевая система

- **Тип:** real-time top-down ARPG
- **Tick rate сервера:** 20Hz (50ms / тик)
- **Server-authoritative:** все расчёты на сервере, клиент только рендерит
- **Управление:** виртуальный джойстик (движение) + 4 кнопки скиллов + tap-to-attack
- **Auto-target:** ближайший враг в радиусе оружия

#### Combat math

- Damage = (weapon_dmg + ATK_bonus) × stat_mod × skill_mod × (1 - target_DEF / (target_DEF + 100)) × (1 - resist%)
- Crit roll: `random < crit_chance%` → damage × crit_damage_multiplier
- Block roll (только Knight с щитом): `random < block_chance%` → damage × (1 - block_value%)
- Hit detection: AABB / circle vs circle, с проверкой line-of-sight для ranged

#### Death

- Player умирает → возрождение в начале текущей комнаты данжа OR полный fail рана (по уровню сложности)
- Mob умирает → loot drop, XP начисление

#### Бафы/дебафы

- Stack-based, длительность в секундах, серверный TTL

### 2.5 Данжи и кампания

#### Кампания (MVP)

- 1 акт × 5 локаций = 5 уровней кампании в MVP (расширение до 3 актов в v1)
- Прогрессия: открываются последовательно
- Награды: золото, лут, XP, осколки

#### Данжи (MVP)

- 3 типа: Crypt, Forest, Castle (визуальные + тематические тайлсеты)
- 3 сложности: Normal / Hard / Mythic
- Стоимость входа: 100 / 500 / 2000 gold + 10 энергии
- Дневной лимит входов: 5 / 3 / 1 на сложность
- Длительность рана: 5–15 минут (5 комнат + boss)
- Drop boost: Hard = ×1.5 lootroll, Mythic = ×2.5 + гарантированный rare+

#### Структура рана

1. Player входит → spawn в стартовой комнате
2. Зачищает комнату → активируется портал
3. Переход в следующую комнату (loading screen)
4. Повтор для 5 комнат
5. Boss room → boss fight
6. Победа → claim screen → лут в инвентарь
7. ИЛИ death → optional revive за gold/Корону → или fail → частичный лут (50%)

#### Жизненный цикл рана и устойчивость

Подробности — в отдельном документе [docs/RUN-LIFECYCLE.md](RUN-LIFECYCLE.md). Ключевые принципы:

- **Per-floor checkpoint модель**: in-memory state в Colyseus Room, persistence в Postgres только на floor transition и при завершении. Внутри этажа — только in-memory.
- **Atomic floor transition**: переход на следующий этаж блокируется до подтверждения записи checkpoint в БД (HMAC-callback Colyseus → FastAPI с idempotency_key). При failure — retry. Гарантия: «комната зачищена, но прогресс не сохранён» невозможна.
- **Sync loot pickup**: при поднятии предмета игроком — синхронная запись в `items` (escrow_run_id = run_id). Поднял = твоё, что бы дальше ни произошло. Лут на полу не материализован, материализуется при pickup.
- **Reconnect grace 60–90 секунд**: Room переживает дисконнект клиента это время, при возврате с тем же `ws_token` — full snapshot world state и продолжение с того же тика.
- **Recovery после grace**: Room закрывается, но `dungeon_runs.status = IN_PROGRESS`. Игрок может POST `/runs/:id/resume` → новый Room создаётся из `character_state` (start of current floor) + seed. Тот же этаж генерируется детерминированно. Лут с пройденных этажей сохранён в `items`.
- **NO intra-floor snapshots в MVP**: индустриальный стандарт (PoE, Diablo, TrinityCore) — checkpoint per-instance/per-zone достаточен. Метрика-триггер для пересмотра: support-обращения «потерял прогресс из-за дисконнекта» > 2% от run completions.

#### Энергия

- Кап 100, восстановление 1 ед / 6 минут
- Покупка восстановления за Корону

### 2.6 Маркетплейс (постMVP, v1.0)

- Листинг: ставится цена в gold, длительность 24/72/168ч
- Поиск: фильтр по slot, rarity, статам, цене
- Покупка: gold списывается, item переходит в инвентарь
- Эскроу: при листинге item уходит в системный hold
- Комиссия: 7% (sink)
- Лимиты: max 10 активных лотов на юзера (расширяется за Корону)
- Анти-абуз: мин.цена по рарности, лимит на сделки между связанными аккаунтами

### 2.7 PvP арена (постMVP, v1.1)

- Формат: 1×1, ставка в gold (банк = 2× ставка − 5% комиссия)
- Матчмейкинг: ELO в Redis ZSET
- Ставки: 100, 500, 2000, 10000 gold (тиры)
- Сезоны: 4 недели, награды для топ-100
- Anti-cheat: лимит боёв в день, проверка повторных матчей с одним юзером, server-authoritative

### 2.8 Кастодиальный кошелёк и TON

#### Архитектура

- HD-wallet (BIP-39/BIP-44), один master mnemonic в env vars
- Каждый юзер получает уникальный sub-address (deterministic derivation)
- Hot wallet: оперативный остаток (≤ 20% резерва)
- Cold wallet: 80%+, multi-sig 2-of-3 (на v1, на MVP — single-sig hardware)

#### Депозит

1. Юзер видит свой адрес + QR в Mini App
2. TON-listener (singleton) опрашивает TON Center каждые 10s
3. При входящей jetton-tx → проверка → зачисление gold по курсу
4. Push в бота: «Зачислено X gold»

#### Вывод

1. Юзер вводит TON-адрес и сумму (минимум 1000 gold = 1 WOTK)
2. Лимиты: max 50 WOTK/день на юзера, кулдаун 24h на новый адрес
3. 2FA через бота (one-time code)
4. Задача в Arq queue → воркер подписывает и шлёт jetton
5. Push в бота: статус выполнения

#### Reconciliation

- Cron каждые 5 мин сверяет sum(user_balances * rate) vs onchain
- Расхождение > 1% → пауза + алерт

#### WOTK Jetton

- Total supply: 1 000 000 000
- Деплой через готовый шаблон `@ton-community/jetton`
- Распределение: 40% game economy, 20% team (vesting 24m, cliff 6m), 15% DEX liquidity, 10% marketing, 10% reserve, 5% airdrop

### 2.9 Telegram Bot

- Команды: `/start`, `/help`, `/wallet`, `/notifications`
- Push-уведомления:
  - «Энергия восстановлена»
  - «Daily quest available»
  - «Withdrawal completed: X WOTK to your wallet»
  - «Your item sold for X gold» (v1)
  - «PvP opponent found» (v1.1)
- Deeplinks: открытие конкретного экрана Mini App из бота

### 2.10 Локализация

- MVP: RU + EN
- v1.x: + ES, PT-BR (Brazil — большой TON-рынок)
- v2.x: + ZH, AR
- Все строки только через i18next ключи (lint-rule запрещает литералы)
- Числа/даты через Intl
- Названия предметов собираются процедурно: `${prefix} ${base} ${suffix}`

---

## 3. Нефункциональные требования

### 3.1 Производительность

- API p95 latency < 200ms
- WS server-tick budget < 30ms (60% от 50ms tick)
- Время загрузки Mini App < 3s на 4G
- Размер бандла Mini App < 5MB initial, остальное lazy-load

### 3.2 Доступность

- Uptime SLA 99.5% на MVP, 99.9% на v1+
- RTO (recovery time) < 30 мин
- RPO (recovery point) < 5 мин (бэкапы каждые 5 мин на v1+)

### 3.3 Безопасность

- HTTPS only
- HMAC-валидация `initData` на каждом запросе (TTL 24h)
- JWT для сессий (короткоживущие 1h, refresh)
- Rate limit: 60 RPS на IP, 30 RPS на юзера
- Все суммы в БД bigint (целочисленный gold, без sub-units)
- Все балансовые операции — в DB транзакциях
- `idempotency_key` на каждый POST с фронта
- Hot wallet seed только в env vars + бумажная backup
- Cold wallet — hardware wallet (Ledger/Tonkeeper Pro)

### 3.4 Анти-чит

- Серверный расчёт всего combat
- Валидация всех client inputs (max speed, sequence, timestamp drift)
- Rate limiting inputs per WS-connection
- Periodic state snapshots для replay-аудита
- Behavioral fingerprinting (slow patterns, outlier metrics → flag)
- Honeypot loot/stats для детекта memory edit'еров

### 3.5 Масштабируемость (заложить с MVP)

- Stateless API (любой инстанс отвечает на любой запрос)
- Все запросы к user data — через `user_id` (sharding-ready)
- Pure-function game logic (separable в worker pool)
- Outbox pattern для интеграций
- API versioning (`/api/v1/...`)
- Migrations only-forward

---

## 4. Технический стек

| Слой | Технология | Версия |
|---|---|---|
| Backend REST | FastAPI | 0.115+ |
| ORM | SQLAlchemy 2.0 async | latest |
| Driver | asyncpg | latest |
| Migrations | Alembic | latest |
| Validation | Pydantic v2 | latest |
| Realtime | Colyseus | 0.16+ |
| Realtime runtime | Node.js LTS | 22+ |
| Queue | Arq | latest |
| Bot | aiogram | 3.x |
| TON | pytoniq + tonsdk | latest |
| Mini App framework | React + Vite + TypeScript | React 19, Vite 6 |
| Game renderer | PixiJS | 8.x |
| Tilemap | @pixi/tilemap | latest |
| Map editor | Tiled | latest |
| Joystick | nipplejs | latest |
| TonConnect | @tonconnect/ui-react | latest |
| i18n | i18next + react-i18next | latest |
| DB | PostgreSQL | 16 |
| Cache/PubSub | Redis | 7.4 |
| Reverse proxy | Caddy | 2.x |
| Containers | Docker + Docker Compose | latest |
| Hosting | Hetzner CCX23 (MVP) → CCX33+ | — |
| CI/CD | GitHub Actions | — |
| Monitoring | Prometheus + Grafana + Sentry + Uptime Kuma | latest |
| Logging | structlog (Python) + pino (Node) | latest |
| Smart contract | готовый Jetton от @ton-community | — |

---

## 5. Архитектура (high-level)

```
[Telegram Client]
  ├─ Mini App (React + Pixi)
  │    ├─ REST → /api/* → FastAPI
  │    ├─ WS   → /game/* → Colyseus
  │    └─ TonConnect → TON Wallet
  │
  └─ Bot deeplinks ────► aiogram

[Caddy reverse proxy]
  ├─ /api/*    → fastapi:8000
  ├─ /game/*   → colyseus:2567
  └─ /         → miniapp static (Vite build)

[Backend services]
  ├─ fastapi      (REST, 4 uvicorn workers)
  ├─ colyseus     (WS, game rooms, 1 process MVP)
  ├─ arq-worker   (background jobs: loot, payouts, daily reset)
  ├─ aiogram-bot  (singleton)
  └─ ton-listener (singleton, leader-lock в Redis)

[Data layer]
  ├─ PostgreSQL 16 (с asyncpg pool, PgBouncer на v1)
  └─ Redis 7      (cache, queues, pub/sub)

[External]
  ├─ TON RPC (TON Center / getblock)
  └─ TonConnect bridge
```

---

## 6. Модель данных (ключевые таблицы)

```sql
users (
  id bigserial PK,
  telegram_id bigint UNIQUE NOT NULL,
  telegram_username text,
  locale text DEFAULT 'ru',
  ip_country text,
  device_fingerprint text,
  is_blocked bool DEFAULT false,
  created_at timestamptz,
  last_seen_at timestamptz
)

characters (
  id bigserial PK,
  user_id bigint FK,
  class text NOT NULL,           -- 'knight' (только в MVP)
  name text,
  level int DEFAULT 1,
  xp bigint DEFAULT 0,
  unspent_stat_points int DEFAULT 0,
  unspent_skill_points int DEFAULT 0,
  base_stats jsonb,              -- {str, dex, int}
  passives jsonb,                -- список ID выбранных пассивок
  active_skills jsonb,           -- список 4 скиллов в hotbar
  created_at timestamptz
)

items (
  id bigserial PK,
  owner_user_id bigint FK,
  base_id text NOT NULL,         -- 'sword_2h_01'
  rarity text NOT NULL,          -- common/magic/rare/epic/legendary
  ilvl int NOT NULL,
  affixes jsonb NOT NULL,        -- [{type, value, tier}, ...]
  socket text,                   -- если в equipment: helmet/chest/...
  socket_character_id bigint,    -- если equipped
  inventory_position int,        -- если в bag (0..47), null если equipped
  market_listing_id bigint,      -- если в эскроу маркета
  created_at timestamptz
)

balances (
  user_id bigint PK FK,
  gold bigint DEFAULT 0,         -- целочисленный gold (1:1 с UI)
  energy int DEFAULT 100,
  energy_updated_at timestamptz,
  shards bigint DEFAULT 0,
  korona int DEFAULT 0           -- премиум-валюта
)

wallets (
  user_id bigint PK FK,
  internal_ton_address text UNIQUE,    -- кастодиальный адрес для депозитов
  external_ton_address text,           -- куда юзер выводит
  external_address_set_at timestamptz, -- кулдаун на смену
  created_at timestamptz
)

transactions (
  id bigserial PK,
  user_id bigint FK,
  type text NOT NULL,            -- DUNGEON_ENTRY, DUNGEON_REWARD, MARKET_BUY, WITHDRAWAL, etc.
  amount bigint NOT NULL,        -- может быть отрицательным
  currency text NOT NULL,        -- GOLD, WOTK, KORONA, SHARDS, ENERGY
  balance_after bigint,
  ref jsonb,                     -- {run_id, item_id, tx_hash, ...}
  idempotency_key text UNIQUE,
  created_at timestamptz
)

dungeons (
  id text PK,
  name_key text NOT NULL,
  difficulty text NOT NULL,
  min_level int,
  entry_cost bigint,
  energy_cost int,
  daily_limit int,
  config jsonb                   -- floors, encounters, loot tables, boss
)

dungeon_runs (
  id uuid PK,
  user_id bigint FK,
  character_id bigint FK,
  dungeon_id text FK,
  seed bytea NOT NULL,
  status text NOT NULL,          -- IN_PROGRESS, COMPLETED, FAILED, FLED, ABANDONED, SETTLED
  current_floor int DEFAULT 0,
  character_state jsonb,
  pending_loot jsonb DEFAULT '[]',
  pending_gold bigint DEFAULT 0,
  entry_paid bigint,
  started_at timestamptz,
  finished_at timestamptz,
  expires_at timestamptz
)

run_encounters (
  id bigserial PK,
  run_id uuid FK,
  floor int,
  encounter_idx int,
  enemies jsonb,
  combat_summary jsonb,          -- damage dealt/taken, time, deaths
  loot_rolled jsonb,
  result text,
  created_at timestamptz,
  UNIQUE(run_id, floor, encounter_idx)
)

dungeon_entries_daily (
  user_id bigint,
  dungeon_id text,
  date_utc date,
  count int DEFAULT 0,
  PRIMARY KEY (user_id, dungeon_id, date_utc)
)

withdrawals (
  id bigserial PK,
  user_id bigint FK,
  amount_wotk bigint,
  to_address text,
  status text,                   -- PENDING, PROCESSING, SENT, CONFIRMED, FAILED
  tx_hash text,
  retry_count int DEFAULT 0,
  created_at timestamptz,
  updated_at timestamptz
)

deposits (
  id bigserial PK,
  user_id bigint FK,
  amount_wotk bigint,
  from_address text,
  tx_hash text UNIQUE,
  block_seqno bigint,
  credited_gold bigint,
  status text,                   -- DETECTED, CONFIRMED, CREDITED
  detected_at timestamptz,
  credited_at timestamptz
)

treasury_log (
  id bigserial PK,
  action text,                   -- HOT_TO_COLD, REBALANCE, MANUAL, etc.
  amount_wotk bigint,
  hot_balance_after bigint,
  cold_balance_after bigint,
  initiated_by text,
  tx_hash text,
  created_at timestamptz
)

audit_events (
  id bigserial PK,
  user_id bigint,
  event_type text,
  payload jsonb,
  ip text,
  created_at timestamptz
)

-- Маркет (v1)
market_listings (
  id bigserial PK,
  seller_user_id bigint FK,
  item_id bigint FK,
  price_gold bigint,
  expires_at timestamptz,
  status text,                   -- ACTIVE, SOLD, EXPIRED, CANCELLED
  listed_at timestamptz
)

market_sales (
  id bigserial PK,
  listing_id bigint FK,
  buyer_user_id bigint FK,
  seller_user_id bigint FK,
  price bigint,
  fee bigint,
  sold_at timestamptz
)

-- PvP (v1.1)
pvp_matches (
  id uuid PK,
  player1_id bigint,
  player2_id bigint,
  bet_amount bigint,
  fee bigint,
  winner_id bigint,
  duration_s int,
  combat_summary jsonb,
  season int,
  played_at timestamptz
)

pvp_seasons (
  id int PK,
  starts_at timestamptz,
  ends_at timestamptz,
  status text                    -- ACTIVE, ENDED
)
```

Индексы под основные паттерны: `user_id` везде, `(status, expires_at)` для очистки runs, `(rarity, slot, price_gold)` для search маркета.

---

## 7. API surface (REST, FastAPI)

```
# Auth
POST /api/v1/auth/login                 (initData → JWT)
POST /api/v1/auth/refresh               (refresh JWT)

# User
GET  /api/v1/me
PATCH /api/v1/me/locale

# Characters
GET  /api/v1/characters
POST /api/v1/characters                 (create knight)
GET  /api/v1/characters/{id}
POST /api/v1/characters/{id}/allocate-stats
POST /api/v1/characters/{id}/learn-passive
POST /api/v1/characters/{id}/set-skills

# Inventory & Equipment
GET  /api/v1/inventory
POST /api/v1/inventory/equip            (item_id, slot)
POST /api/v1/inventory/unequip
POST /api/v1/inventory/sell             (item_id)
POST /api/v1/inventory/salvage
POST /api/v1/inventory/reroll           (item_id)

# Campaign & Dungeons
GET  /api/v1/campaign
GET  /api/v1/dungeons
GET  /api/v1/dungeons/{id}
POST /api/v1/dungeons/{id}/enter        (creates run, returns ws_token)
GET  /api/v1/runs/{run_id}
POST /api/v1/runs/{run_id}/claim
POST /api/v1/runs/{run_id}/flee
POST /api/v1/runs/{run_id}/revive       (за korona)

# Wallet & TON
GET  /api/v1/wallet
POST /api/v1/wallet/connect             (TonConnect proof)
POST /api/v1/wallet/withdraw            (request)
POST /api/v1/wallet/withdraw/confirm    (2FA code)
GET  /api/v1/wallet/transactions
GET  /api/v1/rates                      (gold/WOTK/USD)

# Market (v1)
GET  /api/v1/market/listings            (?slot, rarity, min_price, max_price)
POST /api/v1/market/listings            (item_id, price, duration)
DELETE /api/v1/market/listings/{id}
POST /api/v1/market/listings/{id}/buy
GET  /api/v1/market/my-listings
GET  /api/v1/market/my-sales

# PvP (v1.1)
POST /api/v1/pvp/queue                  (bet_tier)
DELETE /api/v1/pvp/queue
GET  /api/v1/pvp/leaderboard
GET  /api/v1/pvp/my-stats

# Internal (HMAC-signed, для Colyseus → FastAPI)
POST /api/v1/internal/runs/{id}/finalize
POST /api/v1/internal/pvp/{id}/finalize

# Admin (JWT с admin claim)
GET  /api/v1/admin/users
POST /api/v1/admin/users/{id}/block
GET  /api/v1/admin/treasury
POST /api/v1/admin/treasury/rebalance
```

---

## 8. WebSocket контракт (Colyseus)

### Подключение

```ts
const room = await client.joinOrCreate("dungeon", { token: ws_token });
```

### Client → Server messages

```ts
type ClientInput = {
  seq: number;             // монотонная последовательность
  t: number;               // client timestamp (ms)
  move?: { dx: number; dy: number };  // -1..1
  target?: number;         // entity id
  skill?: number;          // skill slot 0..3
  skill_pos?: { x: number; y: number };  // для targeted spells
  pickup?: number;         // loot id
}
```

### Server → Client (через Colyseus Schema, авто-delta)

```ts
class WorldState extends Schema {
  @type("number") tick: number;
  @type({ map: Entity }) entities: MapSchema<Entity>;
  @type({ map: LootDrop }) loots: MapSchema<LootDrop>;
  @type([Event]) events: ArraySchema<Event>;  // damage, death, drop — очищается каждый тик
  @type("number") current_room: number;
  @type("string") room_state: string;  // 'fighting', 'cleared', 'transition'
}

class Entity extends Schema {
  @type("number") id: number;
  @type("string") kind: string;     // 'player', 'mob_zombie', etc.
  @type("number") x: number;
  @type("number") y: number;
  @type("number") dir: number;      // 0=down, 1=left, 2=right, 3=up
  @type("string") anim: string;     // 'idle', 'walk', 'attack', 'die'
  @type("number") hp: number;
  @type("number") hp_max: number;
}
```

### Lifecycle messages

- `room_cleared` → portal активен
- `room_transition` → loading screen, новая комната
- `boss_appeared`, `boss_defeated`
- `player_died` → respawn / game over
- `loot_dropped`, `loot_picked`

---

## 9. Безопасность и анти-чит

1. HMAC валидация `initData` + JWT
2. CORS на свой домен, никаких wildcards
3. Rate limit на REST + WS
4. Server-authoritative combat
5. Input validation: rate, sequence, timestamp drift, bounds
6. `idempotency_key` на write operations
7. DB транзакции на всё, что меняет балансы
8. HD wallet с hot/cold split
9. 2FA на withdraw через бот
10. Reconciliation cron
11. Геоблок US/UK/санкций
12. Periodic snapshots для replay-аудита
13. Behavioral fraud detection (на v1+)
14. Bug bounty (на v1+)

---

## 10. Метрики и аналитика

### Технические (Prometheus)

- API: requests/sec, p50/p95/p99 latency, error rate per endpoint
- WS: active connections, rooms count, tick duration histogram, inbox/outbox depth, dropped messages
- DB: connection pool usage, slow queries, replication lag (на v1+)
- Redis: ops/sec, memory, keyspace
- Custom: gold flow (faucets/sinks), TON balance hot/cold, withdrawal queue depth

### Продуктовые (PostHog или собственная таблица events → ClickHouse на v1)

- DAU / WAU / MAU
- D1 / D7 / D30 retention
- Sessions per user
- Avg session length
- Funnel: install → tutorial → first dungeon → first death → first revive → first purchase → first withdraw
- ARPU, ARPPU, Conversion to payer
- Dungeon completion rate by difficulty
- Combat death heatmap (which mobs/bosses kill most)
- Item rarity distribution
- Market volume, avg sale price by rarity
- PvP match rate, win rate by class (когда добавим классы)

### Алерты (на Slack/Telegram)

- Error rate > 1%
- p99 latency > 500ms
- Tick budget violation > 10% rooms
- Reconciliation diff > 1%
- Withdrawal queue > 100 pending
- Hot wallet balance < daily payout estimate

---

## 11. Constraints (Telegram-специфичные)

- Размер Mini App < 5MB initial bundle (Telegram грузит из CDN)
- Нельзя использовать `localStorage` для критичных данных (TMA может очищать) — использовать `Telegram.WebApp.CloudStorage` или сервер
- Touch input only, без hover-состояний
- Безопасная зона: `Telegram.WebApp.viewportHeight` (учитывает swipe-down area)
- Theme: учитывать `Telegram.WebApp.themeParams` (light/dark)
- Haptic feedback через `Telegram.WebApp.HapticFeedback`
- Кнопка "Back" → перехват и навигация в Mini App
- Платежи: Telegram Stars обязательны для покупки премиума (Apple/Google требуют), TON — только для крипто-операций

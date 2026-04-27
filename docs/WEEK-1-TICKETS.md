# Week 1 — Тикеты

Версия: 0.2 (обновлено 2026-04-27 после schema simplification + security review)
Период: 7 дней, ~60 рабочих часов
Цель недели: рабочий скелет в Telegram — Mini App открывается, юзер логинится, создаёт Knight, попадает на City экран. Деплой на Hetzner с CI/CD.

Каждый тикет имеет:
- **Acceptance criteria** — что считается «готово»
- **Estimate** — реалистичная оценка (часы)
- **Dependencies** — что должно быть готово до старта
- **Status** — `TODO` / `PARTIAL` (уже частично сделано в скаффолдинге) / `DONE`

## Уже сделано в фазе 0 (scaffolding + security review)

При инициализации проекта закрыты:
- ✅ Структура монорепо (backend/realtime/frontend/shared/maps + docker-compose + Caddyfile)
- ✅ Git-репо с двумя коммитами (`a424087` security hardening, `45cfdbc` initial scaffold)
- ✅ FastAPI каркас с `/health`, structlog, Sentry redaction (`sentry_setup.py`), Pydantic validator с production-чеками, slowapi limiter, жёсткий CORS allowlist
- ✅ Realtime каркас с Colyseus 0.16, безопасными дефолтами env, basic-auth на monitor, pino redact
- ✅ Frontend каркас (React 19 + Vite 6 + PixiJS 8 deps + Telegram WebApp в index.html)
- ✅ CI workflow (lint+test+build для трёх сервисов) + Dependabot (weekly pip+npm+actions+docker)
- ✅ Docs: SPEC.md, ROADMAP.md, DATABASE.md (с smallint enums и упрощённой схемой), RUN-LIFECYCLE.md, SECURITY.md
- ✅ Тесты: test_health, test_config_security, test_sentry_redaction (15 кейсов суммарно)

Поэтому многие тикеты ниже либо `PARTIAL` (доделать оставшееся), либо `TODO` (новые, не пересекаются).

---

## День 1 (Пн) — локальная среда + dev tools (~8ч)

### W1-001 — Локальная среда разработки `TODO`
- Установить: Python 3.13, uv, Node.js 22, Docker Desktop, Tiled Editor, ngrok
- Активировать GitHub Copilot или Cursor (опционально, в дополнение к Claude Code)
- Настроить IDE (VS Code/Cursor): Python ext, Pylance, ESLint, Prettier, EditorConfig
- **AC:** все CLI работают, `python --version`, `node --version`, `docker --version` отвечают
- **Estimate:** 1.5ч

### W1-002 — Поднять postgres + redis локально `TODO`
- `docker compose up -d postgres redis` — должно подняться
- Проверить подключение через psql / redis-cli
- **AC:** `psql -h localhost -U wotk -d wotk -c "SELECT 1"` возвращает 1
- **Estimate:** 0.5ч
- **Dependencies:** docker-compose.yml уже создан

### W1-003 — Backend: установка зависимостей и базовый запуск `PARTIAL`
- ✅ Уже сделано: pyproject.toml с зависимостями, FastAPI app с /health, тест на health
- Осталось: запустить `cd backend && uv sync` → сгенерируется `uv.lock` → `uv run uvicorn wotk.api.main:app --reload`
- Запустить тесты: `uv run pytest` — все 3 файла тестов должны пройти (health, config_security, sentry_redaction)
- **AC:** /health возвращает 200, все тесты зелёные, `uv.lock` закоммичен
- **Estimate:** 0.5ч
- **Dependencies:** W1-001

### W1-004 — Alembic init + первая пустая миграция `PARTIAL`
- ✅ Уже сделано: alembic.ini, alembic/env.py, script.py.mako template
- Осталось: `cd backend && uv run alembic revision -m "0001_baseline_empty"` (пустая placeholder-миграция перед W1-011)
- Проверить: `uv run alembic upgrade head` создаёт `alembic_version`
- **AC:** в БД появляется таблица `alembic_version`, downgrade работает
- **Estimate:** 0.5ч
- **Dependencies:** W1-002, W1-003

### W1-005 — Структурное логирование + Sentry `PARTIAL`
- ✅ Уже сделано: `sentry_setup.py` с PII/secret redaction, structlog import в main.py
- Осталось: middleware с `request_id` для каждого запроса (FastAPI dependency или Starlette middleware), биндинг в structlog context
- structlog: JSON-формат в проде, человекочитаемый в dev (по `app_env`)
- **AC:** ошибка в эндпоинте → структурированный JSON-лог с request_id + entry в Sentry (если SENTRY_DSN задан)
- **Estimate:** 1ч
- **Dependencies:** W1-003

### W1-006 — GitHub репозиторий + push `PARTIAL`
- ✅ Уже сделано: локальный git-репо инициализирован, 2 коммита на main (`45cfdbc`, `a424087`, плюс docs `6403993`)
- Осталось: создать private repo в GitHub Org → `git remote add origin ...` → `git push -u origin main`
- Проверить, что Dependabot активировался (PRs появятся через ~неделю)
- **AC:** код в GitHub, CI зелёный на главной, `/security-review` slash-команда теперь работает
- **Estimate:** 0.5ч

### W1-007 — Прогон CI локально (act) для отладки `TODO`
- Опционально: установить `act` для локального прогона GitHub Actions
- Поправить если есть проблемы с CI workflow (uv.lock missing, npm lock missing — после первого `uv sync` / `npm install`)
- **AC:** `git push` → CI зелёный (lint+test+build для всех трёх сервисов)
- **Estimate:** 1ч

---

## День 2 (Вт) — enums + модели + миграции (~8ч)

### W1-009 — `wotk/domain/enums.py` (smallint enum классы) `TODO`

**Новый тикет.** Источник истины — `docs/DATABASE.md` §1.5.

**Скоуп MVP (§1-§5)** — только enum'ы для таблиц этих секций:
- `HeroClass` (KNIGHT=0, ARCHER=1, NECROMANCER=2) — из §4 hero
- `TransactionType` (DUNGEON_ENTRY=0..ADMIN_ADJUST=22) — из §5 transaction

Остальные enum'ы из §1.5 (item.rarity, dungeon_runs.status, deposit.status, etc.) — добавим когда будем работать над их таблицами в следующих фазах.

- Создать `backend/src/wotk/domain/enums.py` с двумя `IntEnum` классами выше
- Каждое значение задаётся явно (`KNIGHT = 0`, не `KNIGHT = auto()`) — чтобы случайно не сдвинуть после удаления.
- Unit-тест `tests/test_enums.py`: парсит §1.5 из DATABASE.md и сверяет name+value, падает при расхождении (anti-drift защита). Для MVP — проверять только реализованные enum'ы.
- **AC:** оба enum'а определены, тест синхронизации проходит
- **Estimate:** 1ч (раньше было 1.5ч на 16 enum'ов)
- **Dependencies:** W1-003

### W1-010 — SQLAlchemy Base + модели MVP `TODO`

Источник истины — `docs/DATABASE.md` §1-§5. Используем DeclarativeBase 2.0 + `Mapped[T]`.

**Скоуп MVP (только §1-§5):**

`backend/src/wotk/domain/models.py`:
- **`Profile`** (§3.1): id, telegram_id, telegram_username, telegram_first_name, locale, ip_country, is_blocked, block_reason, blocked_at, is_admin, withdrawal_2fa_enabled, created_at, updated_at, last_seen_at
- **`Referral`** (§3.2): id, referrer_profile_id (FK), referred_profile_id (FK), confirmed_at, bonus_paid_gold, expires_at, created_at
- **`Hero`** (§4.1): id, profile_id (FK), class (smallint, mapped to `HeroClass`), name, level, xp, unspent_points (JSONB `{stat,skill}`), base_stats (JSONB), passives (JSONB), active_skills (JSONB), is_blocked, created_at, updated_at, deleted_at
- **`Balance`** (§5.1): profile_id (PK+FK), gold, energy, energy_cap, energy_updated_at, updated_at
- **`Transaction`** (§5.2): id, profile_id (FK), type (smallint, mapped to `TransactionType`), amount, balance_after, ref (JSONB), idempotency_key, created_at

**НЕ включаем в MVP** (за рамками §1-§5):
- §6: ItemBase, AffixDefinition, Item — добавим в Phase 5 (loot/inventory)
- §7: Wallet, Deposit, Withdrawal, TreasuryLog — Phase 7 (TON integration)
- §8+: dungeons, runs, market, pvp, audit_events и т.д. — соответствующие фазы

Mapping smallint enum'ов: `Mapped[HeroClass] = mapped_column(SmallInteger, ...)` с конвертацией через кастомный `TypeDecorator` (`IntEnumColumn[E]`).

- **AC:** модели импортируются, mypy strict проходит, все enum-колонки типизированы как `Mapped[<EnumClass>]`
- **Estimate:** 2.5ч (раньше было 3ч на 6 моделей; теперь 5)
- **Dependencies:** W1-004, W1-009

### W1-011 — Alembic миграции (по плану §16 DATABASE.md) `TODO`

Создать миграции согласно `docs/DATABASE.md` §16. **Скоуп MVP §1-§5:**
- **0001** — profile, balance + триггер `trg_set_updated_at` (wallet отложен до Phase 7)
- **0002** — referral
- **0003** — hero
- **0004** — transaction (партиционирование с дня 1: `PARTITION BY RANGE (created_at)`, стартовые партиции на 3 месяца вперёд) + триггер `trg_profile_block_audit` (хотя audit_events ещё нет — триггер можно отложить до миграции 0007)

Способ: НЕ `--autogenerate` (он может пропускать партиционирование, CHECK с BETWEEN). Писать вручную через Alembic op. Партиционирование — через `op.execute("CREATE TABLE ... PARTITION BY RANGE ...")`.

Все CHECK constraints из DATABASE.md §3-§5 обязательны.

- **AC:** все миграции применяются на пустой БД, downgrade работает, схема визуально совпадает с DATABASE.md (`\d profile`, `\d hero`, `\d balance`, `\d "transaction"` и т.д.)
- **Estimate:** 3ч
- **Dependencies:** W1-010

### W1-012 — DB session helper для FastAPI `TODO`
- `wotk/core/db.py`: async engine с asyncpg, sessionmaker, dependency `get_session()` для FastAPI
- Pool size в конфиге (дефолт 20)
- Lifecycle: graceful close в `lifespan`
- **AC:** в эндпоинтах через `Depends(get_session)` доступна `AsyncSession`, в тестах есть фикстура с rollback
- **Estimate:** 1.5ч
- **Dependencies:** W1-010

### W1-013 — Первый интеграционный тест с БД `TODO`
- pytest fixture: тестовая БД (отдельный namespace или transaction-rollback wrapper)
- Тест: создать Profile → создать Balance → прочитать через session → assert поля совпали
- Тест: попытка вставить Hero с class=99 → должна упасть на CHECK constraint
- Тест: попытка двух Hero одного класса для одного profile → должна упасть на partial unique index
- **AC:** тесты зелёные в CI, БД-фикстура переиспользуется между тестами
- **Estimate:** 1.5ч
- **Dependencies:** W1-012

---

## День 3 (Ср) — Telegram авторизация (~10ч)

### W1-020 — initData HMAC-валидация
- `wotk/core/telegram_auth.py`: функция `verify_init_data(init_data: str, bot_token: str) -> dict`
- Реализация по официальной спеке Telegram (HMAC SHA-256, проверка auth_date)
- Unit-тесты на валидную и невалидную initData
- **AC:** валидная initData распарсилась, невалидная вызвала исключение
- **Estimate:** 2.5ч

### W1-021 — JWT issue / verify
- `wotk/core/jwt_auth.py`: `issue_access_token(user_id) -> str`, `verify_token(token) -> Claims`
- HS256, TTL из конфига
- Unit-тесты
- **AC:** access token issue/verify работают, expired token rejected
- **Estimate:** 1.5ч

### W1-022 — POST /api/v1/auth/login `TODO`
- Принимает `{init_data: str}` в body
- Валидирует initData → находит/создаёт Profile → создаёт Balance (default `gold=0, energy=100`) если новый юзер → выдаёт JWT (access + refresh). Wallet создаётся в Phase 7 (TON integration).
- При первом логине: `locale` берётся из `initData.user.language_code` (если в whitelist `ru/en/es/pt/zh/ar`, иначе `ru`); telegram_username и first_name обновляются на каждом login
- Сохраняет `ip_country` (из `CF-IPCountry` header / MaxMind GeoLite2)
- Geo-блок: если country в `GEO_BLOCK_COUNTRIES` → 403 + INSERT audit_events с event_type=2 (LOGIN_GEO_BLOCKED)
- Защита rate-limit: `@limiter.limit(f"{settings.rate_limit_login_per_ip_per_min}/minute")` на эндпоинт
- Возвращает `{access_token, refresh_token, user: {id, locale, telegram_username, is_admin}}`
- **AC:** валидная initData → 200 с JWT, невалидная → 401, заблокированная страна → 403, rate-limit срабатывает после 20 запросов/мин с одного IP
- **Estimate:** 3ч
- **Dependencies:** W1-020, W1-021, W1-012

### W1-023 — Auth middleware / Depends `TODO`
- `Depends(current_user)` для защищённых эндпоинтов: извлекает JWT из `Authorization: Bearer ...`, валидирует, грузит User из БД, кэширует на запрос
- Проверки: токен валиден → юзер существует → не заблокирован
- На 401 — структурированный лог с request_id (без leakage токена)
- Дополнительно: `Depends(current_admin)` — проверяет `is_admin=true`
- **AC:** защищённые эндпоинты доступны только с валидным JWT, заблокированные юзеры получают 403
- **Estimate:** 1.5ч
- **Dependencies:** W1-021, W1-005

### W1-024 — GET /api/v1/me `TODO`
- Возвращает структуру `{profile, balance, hero?}`
- `profile`: id, locale, telegram_username, is_admin, withdrawal_2fa_enabled, created_at
- `balance`: gold, energy (lazy regen через `regen_energy_for_profile`), energy_cap, energy_updated_at — после регена
- `hero`: первый Knight профиля (или null если не создан)
- **AC:** с валидным JWT → 200 с актуальными данными, energy инкрементировался если прошло > 6 минут
- **Estimate:** 2ч
- **Dependencies:** W1-023, W1-013

---

## День 4 (Чт) — Knight creation + бот (~10ч)

### W1-030 — POST /api/v1/heroes (Knight only) `TODO`
- Body: `{name: str}` (3–20 chars, валидация Pydantic)
- Header: `Idempotency-Key: <uuid>` (защита от двойного создания)
- Валидация: `class = HeroClass.KNIGHT` (0) принудительно в MVP, max 1 hero на profile (см. partial unique index `uq_hero_profile_class`)
- Создаёт Hero со значениями:
  - `class = 0`, `level = 1`, `xp = 0`
  - `base_stats = {"str":10,"dex":5,"int":3}` (knight defaults)
  - `unspent_points = {"stat":0,"skill":0}`
  - `passives = []`, `active_skills = ["cleave","shield_bash","whirlwind","charge"]` (4 default skills)
- **AC:** создание возвращает 201 с hero, повторное (другая Idempotency-Key) → 409 c кодом `HERO_ALREADY_EXISTS`
- **Estimate:** 2ч
- **Dependencies:** W1-023, W1-009

### W1-031 — Формулы статов (pure functions) `TODO`
- `wotk/game/stats.py`: `compute_derived_stats(base_stats, equipment, passives) -> DerivedStats`
- Формулы из `docs/SPEC.md` §2.2: HP, Mana, ATK, DEF, Crit Chance, Crit Damage, Attack Speed, Movement Speed, Resistances
- Pure function — без I/O, без random, детерминирована
- Полное покрытие pytest: каждая формула, edge cases (level 1 с дефолтным снаряжением, level 60 с full epic, нулевые/максимальные статы)
- **AC:** все формулы из SPEC реализованы, ≥ 90% test coverage модуля
- **Estimate:** 3ч

### W1-032 — XP кривая + level up + поддержка денормализованного `level` `TODO`
- `wotk/game/leveling.py`:
  - `compute_level(xp: int) -> int` — pure, единственный источник истины
  - `xp_for_level(level: int) -> int` — обратная функция (граница для UI)
  - `apply_xp(hero, gained_xp) -> LevelUpResult` — мутирует hero.xp + hero.level **в одной транзакции**
- Level up даёт +3 stat points → инкремент `unspent_points.stat`
- Корректная обработка multi-level (зашёл lvl 5, получил много XP, стал lvl 8 одним вызовом — даёт 9 stat points)
- Unit-тесты: формула, multi-level, нет потери XP, level всегда == compute_level(xp)
- **AC:** все edge cases покрыты, инвариант `level == compute_level(xp)` всегда верен
- **Estimate:** 2ч

### W1-033 — Bot init (aiogram) `TODO`
- `wotk/bot/main.py`: aiogram 3 bot, единичный процесс (entrypoint `python -m wotk.bot`)
- Команды:
  - `/start [referral_code]` — приветствие + кнопка с `web_app` в Mini App. Если `referral_code` — записать в `referral` table (если новый юзер)
  - `/help` — текст помощи
  - `/wallet` — placeholder, будет в Phase 7
- Все строки через i18n (структура с RU/EN на bot-стороне)
- **AC:** `/start` → текст + кнопка, кнопка открывает Mini App, deeplink `?startapp=ref_<code>` подхватывается
- **Estimate:** 2.5ч

### W1-034 — Тесты для hero creation `TODO`
- Integration: автологин (mock initData) → POST /heroes {name:"Sir Lancelot"} → GET /me → assert hero присутствует с правильными статами
- Тест на повторное создание (idempotency)
- Тест на класс отличный от knight → 422
- **AC:** end-to-end сценарий зелёный, regression-защита от багов в base_stats / unspent_points структуре
- **Estimate:** 1ч
- **Dependencies:** W1-030, W1-024

---

## День 5 (Пт) — Frontend skeleton (~12ч)

### W1-040 — Vite + React + TypeScript setup
- `frontend/package.json` со всеми deps
- `vite.config.ts`, `tsconfig.json`
- Запуск `npm run dev` → http://localhost:5173 показывает hello
- **AC:** dev server поднимается без ошибок
- **Estimate:** 1.5ч

### W1-041 — Telegram WebApp SDK интеграция
- Установить `@telegram-apps/sdk-react`
- `Telegram.WebApp.ready()`, `Telegram.WebApp.expand()`
- Доступ к initData в коде
- **AC:** при открытии в TG, initData доступен в JS, theme params применяются
- **Estimate:** 1.5ч

### W1-042 — Auth flow на фронте
- API client (axios или fetch wrapper) с JWT в headers
- На старте: вызов `/api/v1/auth/login` с initData → сохранить JWT
- Сохранение JWT в memory + Telegram CloudStorage для persistence
- Refresh token логика (на 401 → попробовать refresh → если не получилось → re-login)
- **AC:** при открытии Mini App — автологин происходит за < 1 сек
- **Estimate:** 3ч
- **Dependencies:** W1-022

### W1-043 — i18next setup (RU + EN)
- `i18n/ru.json`, `i18n/en.json` с базовыми ключами
- Provider в App.tsx, hooks для использования
- Авто-выбор по `user.locale` или Telegram language
- ESLint правило: запрет литералов в JSX (через eslint-plugin-i18next)
- **AC:** переключение языка работает, литералов в коде нет
- **Estimate:** 2ч

### W1-044 — Welcome / Character creation экран
- Если у юзера нет персонажа → форма создания (только name input, класс предзадан Knight)
- POST на `/api/v1/characters` → переход на City экран
- **AC:** новый юзер видит экран создания, после ввода имени попадает на City
- **Estimate:** 2ч
- **Dependencies:** W1-042, W1-030

### W1-045 — City экран (placeholder)
- Главное меню: 4 кнопки — Campaign, Inventory, Wallet, Settings
- Хедер с именем персонажа, уровнем, золотом
- На MVP-этапе все кнопки ведут на placeholder-экраны «Coming soon»
- **AC:** после логина видно City, кнопки кликабельны
- **Estimate:** 2ч

---

## День 6 (Сб) — Деплой (~8ч)

### W1-050 — Hetzner CCX23 готов
- Создать сервер (Ubuntu 24.04 или Debian 12)
- SSH-ключи, fail2ban, ufw firewall (открыть только 80, 443, SSH на нестандартном порту)
- Установить Docker + Docker Compose
- **AC:** SSH работает, docker запущен
- **Estimate:** 1.5ч

### W1-051 — Domain + DNS
- Зарегистрировать домен (если ещё нет)
- A-запись на IP сервера, опц. CNAME для api.* / game.*
- Cloudflare proxy включён (опц., но даёт CDN/DDoS бесплатно)
- **AC:** `nslookup` возвращает правильный IP
- **Estimate:** 1ч

### W1-052 — Production-конфиг Caddy + TLS
- Раскомментировать prod-блок в Caddyfile, прописать домен
- При первом запуске Caddy получит Let's Encrypt сертификат автоматически
- **AC:** https://yourdomain.app/health → 200
- **Estimate:** 1.5ч

### W1-053 — Деплой через GitHub Actions
- Workflow `.github/workflows/deploy.yml`:
  - Trigger: push в main после успешного CI
  - Steps: SSH в Hetzner, `git pull`, `docker compose pull`, `docker compose up -d --build`
  - Secrets: SSH_PRIVATE_KEY, SSH_HOST, SSH_USER
- **AC:** push в main → автодеплой → новая версия доступна через 2-3 минуты
- **Estimate:** 3ч

### W1-054 — Проверка production env
- Скопировать `.env.example` → `.env` на сервере, заполнить prod значениями (BOT_TOKEN, JWT_SECRET, DB credentials)
- Прогнать миграции на prod БД
- Smoke-тест: открыть https://yourdomain.app/health
- **AC:** health возвращает 200 на prod URL
- **Estimate:** 1ч

---

## День 7 (Вс) — End-to-end тест в Telegram + добивка (~6ч)

### W1-060 — Регистрация бота в BotFather
- Создать `@WayOfTheKingDevBot` через @BotFather
- Привязать домен через `/setdomain`
- Создать Mini App через `/newapp`, указать prod URL
- **AC:** в Telegram бот работает, кнопка Mini App открывает приложение
- **Estimate:** 1ч

### W1-061 — End-to-end smoke-тест в реальном TG
- Открыть бота → нажать кнопку → Mini App открылся
- Проверить: автологин → форма создания персонажа → создание → City экран
- Проверить i18n (открыть с разными языками)
- Проверить на iOS и Android (попросить друга)
- **AC:** полный сценарий работает на iOS + Android в реальном Telegram
- **Estimate:** 2ч

### W1-062 — Bug fixes и полировка
- Исправление того, что нашёл в W1-061
- Резерв времени на «всё пошло не так»
- **AC:** критичных багов нет, флоу работает чисто
- **Estimate:** 2ч

### W1-063 — Документирование
- Обновить README.md под актуальное состояние (как локально поднять, как тестить в TG)
- Создать `docs/RUNBOOK.md` с операционными процедурами (как смотреть логи, как откатить деплой, как зайти на сервер)
- **AC:** другой человек может склонировать репо и поднять локально по README
- **Estimate:** 1ч

---

## Итого по неделе

- Всего тикетов: 31 (добавлен W1-009 для enums.py)
- Суммарная оценка: ~62 часа (точно в недельный бюджет 60ч с буфером)
- Critical path: W1-001 → W1-003 → W1-009 → W1-010 → W1-011 → W1-022 → W1-042 → W1-053
- **PARTIAL** тикеты: W1-003, W1-004, W1-005, W1-006 — суммарно сэкономлено ~5 часов работы (фундамент сделан в фазе scaffolding)

## Acceptance criteria недели

- ✅ Mini App открывается в Telegram через бота
- ✅ Юзер автоматически логинится
- ✅ Создаёт Knight'а
- ✅ Попадает на City экран
- ✅ Всё это работает на prod URL (Hetzner)
- ✅ CI/CD: push в main → автодеплой
- ✅ Тесты зелёные

## Что НЕ делается на 1-й неделе (защита скоупа)

- Pixi/canvas рендер (это W2)
- Любая боёвая механика (W4+)
- Реальные стат-распределения через UI (W5+)
- TON интеграция (W15+)
- Маркет, PvP (постMVP)

## Риски недели

| Риск | Митигация |
|---|---|
| HMAC валидация initData оказалась сложнее | Готовая референс-реализация на GitHub (несколько примеров) |
| Hetzner setup затянулся | Иметь backup план — Vultr/DigitalOcean (~$20 за месяц) |
| BotFather бесит с доменом | Использовать ngrok временно, поменять позже |
| CI/CD не работает с первого раза | Тестировать через `act` локально, иначе уйдут часы на debug |
| Затык на Frontend (не сильная сторона) | Просить Claude Code сразу с шаблонными компонентами и ESLint конфигом |

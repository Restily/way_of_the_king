# Week 1 — Тикеты

Версия: 0.1
Период: 7 дней, ~60 рабочих часов
Цель недели: рабочий скелет в Telegram — Mini App открывается, юзер логинится, создаёт Knight, попадает на City экран. Деплой на Hetzner с CI/CD.

Каждый тикет имеет:
- **Acceptance criteria** — что считается «готово»
- **Estimate** — реалистичная оценка (часы)
- **Dependencies** — что должно быть готово до старта

---

## День 1 (Пн) — локальная среда + dev tools (~8ч)

### W1-001 — Локальная среда разработки
- Установить: Python 3.13, uv, Node.js 22, Docker Desktop, Tiled Editor, ngrok
- Активировать GitHub Copilot или Cursor (опционально, в дополнение к Claude Code)
- Настроить IDE (VS Code/Cursor): Python ext, Pylance, ESLint, Prettier, EditorConfig
- **AC:** все CLI работают, `python --version`, `node --version`, `docker --version` отвечают
- **Estimate:** 1.5ч

### W1-002 — Поднять postgres + redis локально
- `docker compose up -d postgres redis` — должно подняться
- Проверить подключение через psql / redis-cli
- **AC:** `psql -h localhost -U wotk -d wotk -c "SELECT 1"` возвращает 1
- **Estimate:** 0.5ч
- **Dependencies:** docker-compose.yml уже создан

### W1-003 — Backend: установка зависимостей и базовый запуск
- `cd backend && uv sync` — подтянуть deps
- Запустить локально: `uv run uvicorn wotk.api.main:app --reload`
- Открыть http://localhost:8000/health → `{"status": "ok"}`
- Запустить тесты: `uv run pytest` — health-test проходит
- **AC:** /health возвращает 200, тест зелёный
- **Estimate:** 1ч
- **Dependencies:** W1-001

### W1-004 — Alembic init + первая пустая миграция
- Создать `alembic/versions/0001_init.py` (пустая миграция-плейсхолдер)
- Проверить: `uv run alembic upgrade head` отрабатывает на пустой БД
- **AC:** в БД появляется таблица `alembic_version`
- **Estimate:** 1ч
- **Dependencies:** W1-002, W1-003

### W1-005 — Структурное логирование + Sentry
- Конфиг structlog (JSON-формат для prod, читаемый для dev)
- Sentry init (если SENTRY_DSN задан)
- Middleware: добавление request_id в каждый запрос
- **AC:** ошибка в эндпоинте → структурированный JSON-лог + entry в Sentry (если включён)
- **Estimate:** 2ч
- **Dependencies:** W1-003

### W1-006 — GitHub репозиторий + первый коммит
- Создать private repo в GitHub Org
- `git init`, добавить remote, первый коммит «initial scaffold»
- Push в main
- **AC:** код в GitHub, CI запустился (даже если упал)
- **Estimate:** 1ч

### W1-007 — Прогон CI локально (acted) для отладки
- Опционально: установить `act` для локального прогона GitHub Actions
- Поправить если есть проблемы с CI workflow
- **AC:** `git push` → CI зелёный (lint+test+build)
- **Estimate:** 1ч

---

## День 2 (Вт) — модели и миграции (~8ч)

### W1-010 — SQLAlchemy Base + первые модели
- `wotk/domain/models.py`:
  - `User` (id, telegram_id, username, locale, ip_country, device_fingerprint, is_blocked, created_at, last_seen_at)
  - `Character` (id, user_id, class, name, level, xp, base_stats jsonb, passives jsonb, active_skills jsonb)
  - `Balance` (user_id PK, gold, energy, energy_updated_at, shards, korona)
  - `Wallet` (user_id PK, internal_ton_address, external_ton_address, external_address_set_at)
  - `Transaction` (id, user_id, type, amount, currency, balance_after, ref jsonb, idempotency_key)
- Использовать DeclarativeBase v2 синтаксис
- **AC:** модели импортируются без ошибок, типизированы (mypy strict проходит)
- **Estimate:** 3ч
- **Dependencies:** W1-004

### W1-011 — Alembic миграция: первые таблицы
- `alembic revision --autogenerate -m "init core tables"`
- Проверить сгенерированную миграцию, поправить (индексы, constraints, defaults)
- Прогнать `alembic upgrade head` на чистой БД
- Проверить downgrade тоже работает
- **AC:** все таблицы созданы, индексы стоят, downgrade откатывает чисто
- **Estimate:** 2ч
- **Dependencies:** W1-010

### W1-012 — DB session helper для FastAPI
- `wotk/core/db.py`: async engine, sessionmaker, dependency `get_session()` для FastAPI
- Lifecycle: открытие/закрытие при старте/остановке app
- **AC:** в эндпоинтах можно через `Depends(get_session)` получить async сессию
- **Estimate:** 1.5ч
- **Dependencies:** W1-010

### W1-013 — Первый интеграционный тест с БД
- pytest fixture: тестовая БД (отдельная schema или transaction-rollback)
- Тест: создать User, прочитать обратно
- **AC:** тест зелёный в CI
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

### W1-022 — POST /api/v1/auth/login
- Принимает `{init_data: str}` в body
- Валидирует initData → находит/создаёт User → выдаёт JWT
- Сохраняет ip_country (из Cloudflare header или MaxMind), device_fingerprint
- Возвращает `{access_token, refresh_token, user: {...}}`
- Geo-блок: если country в `GEO_BLOCK_COUNTRIES` → 403
- **AC:** валидная initData → 200 с JWT, невалидная → 401, заблокированная страна → 403
- **Estimate:** 3ч
- **Dependencies:** W1-020, W1-021, W1-012

### W1-023 — Auth middleware / Depends
- `Depends(current_user)` для защищённых эндпоинтов
- Извлекает JWT из `Authorization: Bearer ...`
- Проверяет, не заблокирован ли пользователь
- **AC:** защищённые эндпоинты доступны только с валидным JWT
- **Estimate:** 1.5ч
- **Dependencies:** W1-021

### W1-024 — GET /api/v1/me
- Возвращает текущего юзера + его балансы + список персонажей
- **AC:** с валидным JWT → 200 с данными юзера
- **Estimate:** 1.5ч
- **Dependencies:** W1-023

---

## День 4 (Чт) — Knight creation + бот (~10ч)

### W1-030 — POST /api/v1/characters (Knight only)
- Body: `{name: str}`
- Валидация: только класс knight в MVP, max 1 персонаж на user в MVP
- Создаёт Character с базовыми статами (`{str: 10, dex: 5, int: 3}`), level 1, default skills
- **AC:** создание возвращает 201 с character, повторное → 409
- **Estimate:** 2ч
- **Dependencies:** W1-023

### W1-031 — Формулы статов (pure functions)
- `wotk/game/stats.py`: `compute_derived_stats(base, equipment, passives) -> DerivedStats`
- HP, Mana, ATK, DEF, Crit, AS, MS, Resistances
- Полное покрытие unit-тестами
- **AC:** формулы из SPEC.md реализованы и протестированы
- **Estimate:** 3ч

### W1-032 — XP кривая + level up
- `wotk/game/leveling.py`: `xp_for_level(n)`, `apply_xp(character, gained_xp) -> LevelUpResult`
- Распределение нерастраченных stat points (3 на каждый level up)
- Unit-тесты
- **AC:** level up корректен, переходы XP-границ работают, нет потери XP при множественном level up
- **Estimate:** 1.5ч

### W1-033 — Bot init (aiogram)
- `wotk/bot/main.py`: aiogram bot, единичный процесс
- Команда `/start`: приветствие + кнопка с deeplink в Mini App
- Команда `/help`
- Запускается отдельным entry-point
- **AC:** `/start` в боте → текст + кнопка, кнопка открывает Mini App URL
- **Estimate:** 2.5ч

### W1-034 — Тесты для character creation
- Integration: создать юзера через login → создать персонажа → проверить через /me
- **AC:** end-to-end сценарий зелёный
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

- Всего тикетов: 30
- Суммарная оценка: ~62 часа (точно в недельный бюджет 60ч с буфером)
- Critical path: W1-001 → W1-003 → W1-010 → W1-022 → W1-042 → W1-053

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

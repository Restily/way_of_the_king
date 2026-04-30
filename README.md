# Way Of The King

Real-time top-down ARPG в Telegram Mini App с интеграцией TON.

## Структура проекта

```
way_of_the_king/
├── backend/      # FastAPI (Python) — REST API, bot, TON, queue workers
├── realtime/     # Colyseus (Node.js) — игровые комнаты, бой в реальном времени
├── frontend/     # React + Vite + PixiJS — Telegram Mini App
├── shared/       # JSON-схемы для синхронизации типов между сервисами
├── maps/         # Tiled .tmx файлы (карты данжей)
├── docs/         # SPEC.md, ROADMAP.md, тикеты
└── docker-compose.yml
```

## Документация

- [Техническое задание](docs/SPEC.md)
- [Roadmap до MVP и 1M DAU](docs/ROADMAP.md)
- [Схема базы данных](docs/DATABASE.md) — таблицы, индексы, триггеры, партиционирование
- [Жизненный цикл прохождения данжа](docs/RUN-LIFECYCLE.md) — где живёт state, recovery-сценарии
- [Security policy](docs/SECURITY.md) — threat model, операционные процедуры, accepted risks
- [Operational runbook](docs/RUNBOOK.md) — как смотреть логи, запускать миграции, делать ротации
- [Тикеты на 1-ю неделю](docs/WEEK-1-TICKETS.md)
- [Локальное тестирование Mini App в Telegram](docs/LOCAL-TELEGRAM-TESTING.md)

## Стек

| Слой | Технология |
|---|---|
| REST API | FastAPI 0.115+ / Python 3.13 |
| Realtime | Colyseus 0.16 / Node.js 22 |
| Frontend | React 19 + Vite 6 + PixiJS 8 |
| БД | PostgreSQL 16 + Redis 7 |
| Reverse proxy | Caddy 2 |
| Hosting | Hetzner CCX23 (MVP) |

## Локальный запуск

### Требования

- Docker Desktop (Windows/Mac) или Docker Engine + Compose plugin (Linux)
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (быстрый Python package manager)
- Node.js 22+

### Шаги

```bash
# 1. Скопировать env-файл и заполнить как минимум TELEGRAM_BOT_TOKEN
#    (для локала — любой не-пустой placeholder, для теста в реальном TG — реальный токен от @BotFather)
cp backend/.env.example backend/.env

# 2. Поднять Postgres + Redis (только инфра, без приложения — backend
#    запускается отдельно с --reload для удобной разработки)
docker compose up -d postgres redis

# 3. Backend: deps + миграции + запуск
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn wotk.api.main:app --reload --host 0.0.0.0 --port 8000

# 4. Frontend (в отдельном терминале)
cd frontend
npm install
npm run dev
```

После старта:

| Сервис | URL |
|---|---|
| Backend REST API | http://localhost:8000 |
| Healthcheck | http://localhost:8000/health |
| OpenAPI docs | http://localhost:8000/docs |
| Frontend dev | http://localhost:5173 |

> **Важно**: в `backend/.env` после копирования `.env.example` хост Postgres надо поменять с `postgres` на `localhost`, потому что backend запускается на хосте, а не в контейнере. То же самое для Redis. (Если запускать backend через `docker compose up backend` — оставить как есть.)

### Прогон тестов

```bash
cd backend
uv run pytest                 # все тесты (118 на текущий момент)
uv run pytest -k loot         # только loot.py тесты
uv run pytest --co            # collect-only, проверить что pytest всё видит
```

Тестовая БД создаётся автоматически (`<DATABASE_URL>_test`), миграции применяются один раз на сессию, между тестами таблицы чистятся через TRUNCATE.

### Линт + типы

```bash
cd backend
uv run ruff check .
uv run mypy src
```

## Mini App в Telegram

См. подробный гайд: [docs/LOCAL-TELEGRAM-TESTING.md](docs/LOCAL-TELEGRAM-TESTING.md). Краткая последовательность:

1. `ngrok http 5173` (публикуем frontend dev-сервер)
2. В [@BotFather](https://t.me/BotFather): `/newapp` → указать ngrok URL
3. Открыть бот, нажать кнопку Mini App → автологин → создание Knight'а → City экран

## Как сделать новую миграцию

```bash
cd backend
uv run alembic revision -m "0006_short_description"
# отредактировать сгенерированный файл в backend/alembic/versions/
uv run alembic upgrade head           # применить
uv run alembic downgrade -1           # откатить на одну
uv run alembic current                # показать текущую head
```

Миграции пишутся **вручную**, не через `--autogenerate` — autogen пропускает CHECK-constraints, partial indexes, триггеры и партиции. См. примеры в [backend/alembic/versions/](backend/alembic/versions/).

## Лицензия

Пока приватный проект, лицензия не определена.

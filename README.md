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
- [Тикеты на 1-ю неделю](docs/WEEK-1-TICKETS.md)

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

Требования: Docker, Docker Compose, Node.js 22+, Python 3.13+, [uv](https://docs.astral.sh/uv/).

```bash
cp backend/.env.example backend/.env
docker compose up -d postgres redis
cd backend && uv sync && uv run alembic upgrade head
docker compose up
```

После старта:
- Backend API: http://localhost:8000
- Realtime: ws://localhost:2567
- Frontend dev: http://localhost:5173
- Caddy proxy: http://localhost

## Mini App в Telegram

Для тестирования в Telegram нужен туннель:
1. `ngrok http 80` (или cloudflared)
2. В BotFather: `/newapp` → указать ngrok URL
3. Открыть бот, нажать кнопку Mini App

# Operational Runbook

Версия: 0.1
Последнее обновление: 2026-04-28

Этот документ — **операционный playbook**: пошаговые процедуры для типовых задач (смотреть логи, прогонять миграции, ротация секретов, откат деплоя). Когда что-то горит, сюда заходишь и копируешь команду; не сюда — за объяснением «почему» (это в [SECURITY.md](SECURITY.md), [DATABASE.md](DATABASE.md), [SPEC.md](SPEC.md)).

> **Статус production**: на момент 2026-04-28 prod ещё не развёрнут (W1-050..054 из [WEEK-1-TICKETS.md](WEEK-1-TICKETS.md) не выполнены). Секции про Hetzner/Caddy/деплой помечены `[WHEN-PROD]` — заполнятся после первого раскатывания.

---

## 1. Локальная разработка

### 1.1 Поднять/положить инфраструктуру

```bash
# Старт постгреса + редиса (без приложения, для удобной разработки backend через --reload)
docker compose up -d postgres redis

# Проверить статус
docker compose ps

# Положить
docker compose down                    # сохранит volumes
docker compose down -v                 # ВНИМАНИЕ: снесёт volumes (БД + redis data)
```

### 1.2 Полный стек в Docker (когда не нужен hot-reload)

```bash
docker compose up -d                   # все сервисы: postgres, redis, backend, bot, realtime, caddy
docker compose logs -f backend         # tail логов одного сервиса
docker compose logs -f --tail=100      # tail всех с последних 100 строк
docker compose restart backend         # перезапуск без пересборки
docker compose up -d --build backend   # с пересборкой образа
```

### 1.3 Backend локально (рекомендуется для активной разработки)

```bash
cd backend
uv run uvicorn wotk.api.main:app --reload --host 0.0.0.0 --port 8000
```

`--reload` следит за изменениями файлов в `src/` и автоматически перезапускает воркер. Логи идут в stdout (structlog в человекочитаемом формате при `APP_ENV=development`, JSON — иначе).

### 1.4 Bot отдельно

```bash
cd backend
uv run python -m wotk.bot
```

Не нужно при разработке REST API — бот трогать только когда работаешь с командами `/start`/`/wallet`.

---

## 2. База данных

### 2.1 Подключиться к локальной БД

```bash
docker compose exec postgres psql -U wotk -d wotk
# или с хоста, если установлен psql
psql -h localhost -U wotk -d wotk
```

Полезные команды psql:
```
\dt                  -- список таблиц
\d profile           -- описание таблицы (колонки, индексы, FK, CHECK)
\df                  -- список функций
\sf current_energy   -- show function definition
\timing on           -- показывать время запроса
\x                   -- expanded output (по строкам, не по столбцам)
```

### 2.2 Миграции

```bash
cd backend

# Текущее состояние
uv run alembic current
uv run alembic history --verbose

# Применить всё до head
uv run alembic upgrade head

# Откатить
uv run alembic downgrade -1            # на одну вниз
uv run alembic downgrade 0003_hero     # до конкретной ревизии
uv run alembic downgrade base          # снести всё (очень аккуратно)

# Создать новую миграцию (пустую — заполнить вручную)
uv run alembic revision -m "0006_short_name"

# Сгенерировать SQL без применения (для review перед prod)
uv run alembic upgrade head --sql > /tmp/migration.sql
```

### 2.3 Сбросить локальную БД с нуля

```bash
docker compose down -v                 # снести volumes
docker compose up -d postgres redis    # поднять заново
cd backend && uv run alembic upgrade head
```

### 2.4 Сбросить только тестовую БД

Тестовая БД создаётся автоматически conftest'ом (имя = `<dev_db>_test`). Если что-то залипло:

```bash
docker compose exec postgres psql -U wotk -d postgres -c 'DROP DATABASE wotk_test;'
docker compose exec postgres psql -U wotk -d postgres -c 'CREATE DATABASE wotk_test OWNER wotk;'
# следующий запуск pytest применит миграции на чистую БД
```

### 2.5 Reconciliation: проверить, что баланс == последняя транзакция

```sql
-- На каждый профиль: balance.gold должен совпадать с balance_after последней транзакции.
SELECT
  b.profile_id,
  b.gold,
  t.balance_after AS last_tx_balance,
  b.gold - t.balance_after AS drift
FROM balance b
LEFT JOIN LATERAL (
  SELECT balance_after FROM transaction
  WHERE profile_id = b.profile_id
  ORDER BY id DESC LIMIT 1
) t ON true
WHERE t.balance_after IS NOT NULL
  AND b.gold != t.balance_after;
```

Если что-то нашлось — это инцидент. См. §6.3 Compromise response в [SECURITY.md](SECURITY.md).

---

## 3. Логи и наблюдение

### 3.1 Локально

```bash
# Tail всех сервисов
docker compose logs -f

# Конкретный сервис, последние 200 строк
docker compose logs -f --tail=200 backend

# Только ошибки за последний час
docker compose logs --since 1h backend | grep -E '"level":\s*"error"'
```

При запуске backend без Docker (`uv run uvicorn ...`) логи идут просто в stdout текущего терминала.

### 3.2 Sentry

DSN задаётся в `.env` (`SENTRY_DSN=`). При пустом DSN в development — OK, в staging/production — startup-warning. Все ошибки идут в Sentry с автоматической редакцией PII/секретов через `wotk/core/sentry_setup.py` (JWT, mnemonic, токены маскируются перед отправкой).

### 3.3 [WHEN-PROD] Production логи

TODO: после деплоя на Hetzner — `journalctl -u wotk-backend`, либо Loki/Grafana stack.

---

## 4. Тесты

```bash
cd backend
uv run pytest                          # всё (118 тестов, ~10 сек)
uv run pytest -x                       # стоп на первом упавшем
uv run pytest -k loot                  # только тесты из test_loot.py
uv run pytest tests/test_models_db.py::test_create_hero -vv
uv run pytest --co -q                  # collect-only, посмотреть что pytest видит
```

### 4.1 Если тесты валятся на DB connection

1. Проверить что Postgres поднят: `docker compose ps`
2. Проверить что в `.env` хост корректен (если backend локально — `localhost`, если в compose — `postgres`)
3. Снести тест-БД (см. §2.4) и прогнать ещё раз

### 4.2 Frontend тесты

TODO: jest/vitest конфиг ещё не настроен (W1 не покрывает фронт-тесты).

---

## 5. Секреты и .env

### 5.1 Сгенерировать новый секрет

```bash
# JWT_SECRET, INTERNAL_HMAC_*, TFA_PEPPER (когда появится)
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Минимум 32 байта. Pydantic-валидатор в `backend/src/wotk/core/config.py` блокирует startup в staging/production, если секреты содержат `change_me` / `dev` / `example` или короче минимума.

### 5.2 [WHEN-PROD] Ротация JWT_SECRET

См. [SECURITY.md §3.3](SECURITY.md). Краткая последовательность:
1. Сгенерировать новый.
2. Подменить в env / Docker secret.
3. `docker compose restart backend`.
4. Все existing JWT станут невалидными → юзеры перелогинятся через initData (для них незаметно).

### 5.3 [WHEN-PROD] Ротация HOT_WALLET_MNEMONIC

См. [SECURITY.md §3.2](SECURITY.md). Делается планово или при подозрении на компрометацию. Требует maintenance mode + перевод баланса.

---

## 6. Инциденты

### 6.1 Backend не стартует с ошибкой про секрет

```
ValidationError: ... JWT_SECRET must be at least 32 bytes ...
```

→ Проверить `backend/.env`. В development можно поставить заглушку (`JWT_SECRET=dev_secret_at_least_32_bytes_long_____` — конфиг разрешит при `APP_ENV=development`). В staging/prod — сгенерировать настоящий (см. §5.1).

### 6.2 alembic upgrade падает

```
sqlalchemy.exc.IntegrityError: ... constraint ... already exists
```

→ Скорее всего БД в промежуточном состоянии. Проверить `alembic_version` таблицу (`SELECT * FROM alembic_version`), сравнить с историей `uv run alembic history`. Если совсем застрял — снести БД (см. §2.3).

### 6.3 Postgres контейнер unhealthy

```bash
docker compose logs postgres
docker compose restart postgres
# если не помогло
docker compose down && docker compose up -d postgres redis
```

Если БД не поднимается из-за corrupted volume — данные локальной разработки нерелевантны, можно `docker compose down -v` (потеряются данные, но это dev).

### 6.4 [WHEN-PROD] Compromise response

См. полный playbook в [SECURITY.md §3.4](SECURITY.md). Базовые сценарии:
- **Hot wallet скомпрометирован** → пауза withdrawals, перевод на cold, аудит treasury_log, ротация mnemonic
- **JWT_SECRET утёк** → ротация (§5.2), аудит audit_events
- **БД read-only утечка** → ротация JWT_SECRET (содержимое БД больше не usable для подделки токенов)

---

## 7. Деплой [WHEN-PROD]

TODO: заполнится после W1-050..054. Планируемая схема:

- **Server**: Hetzner CCX23, Ubuntu 24.04, Docker + Docker Compose
- **Reverse proxy**: Caddy 2 (auto Let's Encrypt)
- **Deploy**: GitHub Actions → SSH → `git pull && docker compose pull && docker compose up -d --build`
- **Rollback**: `git checkout <prev-sha> && docker compose up -d --build`
- **DB backup**: continuous WAL archiving в Backblaze B2 + ежедневный pg_basebackup, см. [DATABASE.md §17](DATABASE.md)

---

## 8. Полезные shortcuts

```bash
# Полный reset локальной среды
docker compose down -v && docker compose up -d postgres redis && \
  cd backend && uv run alembic upgrade head && uv run pytest

# Open API docs
open http://localhost:8000/docs        # Mac
start http://localhost:8000/docs       # Windows

# Watch активные DB-соединения
watch -n 1 'docker compose exec -T postgres psql -U wotk -d wotk -c "SELECT count(*), state FROM pg_stat_activity WHERE datname=\"wotk\" GROUP BY state;"'

# Текущий размер всех таблиц
docker compose exec postgres psql -U wotk -d wotk -c "
  SELECT schemaname, relname, pg_size_pretty(pg_total_relation_size(relid)) AS size
  FROM pg_stat_user_tables
  ORDER BY pg_total_relation_size(relid) DESC;"
```

---

## 9. Контакты при инциденте

- Соло-разработчик: см. CLAUDE.md / git blame
- Telegram бот для алертов: TODO (W1-061+)
- Sentry проект: TODO (DSN в env)

В будущих фазах сюда добавится: 24/7 on-call, escalation policy, status page.

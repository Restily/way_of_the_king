# Week 2 — Тикеты

Версия: 0.2 (обновлено 2026-04-28 — production отложен, assets отложены)
Период: 7 дней, ~60 рабочих часов
Цель недели (ОРИГИНАЛЬНАЯ):
1. **Production live** — Mini App открывается с реального домена, push в main → автодеплой
2. **Telegram bot реально работает** — реальный @username через BotFather, e2e сценарий зелёный
3. **Phase 2 запущен** — Pixi v8 рендерит первую комнату, Knight ходит 4-directional, есть джойстик

**Реальный итог:** prod отложен (нет инфры), assets отложены (нет арта). Всё что доступно локально — сделано.

Каждый тикет имеет:
- **Acceptance criteria** — что считается «готово»
- **Estimate** — оценка (часы)
- **Dependencies** — что должно быть готово до старта
- **Status** — `TODO` / `PARTIAL` / `DONE`

## Уже сделано в W1 (фундамент для W2)

- ✅ Auth flow (initData → JWT → /me) полностью рабочий, 118 тестов зелёных
- ✅ Hero creation, City экран в React + i18n
- ✅ Все §1-§5 модели + миграции 0001-0005 (включая best-practices delta v0.2)
- ✅ Affix-генератор PoE-style ([loot.py](../backend/src/wotk/game/loot.py)) — забежали вперёд из Phase 5
- ✅ RUNBOOK.md + README с локальным setup'ом
- ✅ aiogram bot caркас ([bot/main.py](../backend/src/wotk/bot/main.py))

## Что НЕ делается на 2-й неделе (защита скоупа)

- Сервер-боёвка через Colyseus (это Phase 3, W5-7)
- Мобы, AI, атаки (Phase 4, W8-10)
- §6 item_base/affix_definition таблицы (Phase 5, W11-12 — пока loot.py живёт без БД)
- §8 dungeons/dungeon_runs (Phase 4, W8+)
- TON интеграция (Phase 7, W15+)
- Маркет, PvP (постMVP)

---

## День 1 (Пн) — Hetzner + GitHub push (~8ч)

### W2-001 — GitHub: создать private repo + push `TODO`
Carry-over из W1-006. Сейчас `git remote` указывает на placeholder.
- Создать private repo в GitHub Org (или personal). Имя `way_of_the_king`.
- `git remote set-url origin git@github.com:<org>/way_of_the_king.git`
- `git push -u origin main`
- Включить Dependabot alerts + security updates в Settings → Code security
- Проверить, что workflow `.github/workflows/ci.yml` запустился и зелёный
- **AC:** код на GitHub, CI зелёный, Dependabot активен, `/security-review` skill теперь видит remote
- **Estimate:** 0.5ч

### W2-002 — Hetzner CCX23 готов `TODO`
Carry-over из W1-050.
- Создать сервер CCX23 (Ubuntu 24.04, дата-центр Helsinki/Falkenstein), $8.5/мес
- SSH-ключи: добавить публичный ключ при создании; root login ban в `/etc/ssh/sshd_config` (`PermitRootLogin no`, `PasswordAuthentication no`); SSH на нестандартном порту (например 22022)
- `apt update && apt upgrade -y && apt install -y ufw fail2ban`
- ufw: `ufw default deny incoming; ufw allow 22022/tcp; ufw allow 80/tcp; ufw allow 443/tcp; ufw enable`
- fail2ban: дефолтная конфигурация для sshd достаточна
- Создать non-root юзера `wotk` с sudo, логиниться им
- Установить Docker + Compose plugin (`apt install -y docker.io docker-compose-plugin`), добавить юзера в группу docker
- **AC:** ssh от non-root юзера работает, `docker ps` отвечает, ufw status active, fail2ban active
- **Estimate:** 2ч

### W2-003 — Domain + DNS `TODO`
Carry-over из W1-051.
- Зарегистрировать домен (например через Porkbun/Namecheap, ~$10/год для `.app`)
- A-запись `wayoftheking.app` → IP сервера; CNAME `www` → `wayoftheking.app`
- Cloudflare proxy включён (бесплатно, даёт CDN + DDoS protection). **Важно:** SSL/TLS mode = "Full (strict)" чтобы Caddy сам управлял сертификатом
- **AC:** `dig wayoftheking.app` возвращает Cloudflare IP, `dig +short wayoftheking.app @1.1.1.1` стабилен
- **Estimate:** 1.5ч

### W2-004 — Каркас prod конфигурации `TODO`
- Создать `.env.production.example` (без секретов, только placeholder + комментарии откуда брать значения)
- Сгенерировать prod секреты на локале: `python -c "import secrets; print(secrets.token_urlsafe(48))"` → `JWT_SECRET`, `INTERNAL_HMAC_REALTIME_TO_API`, `INTERNAL_HMAC_API_TO_REALTIME`. **Не коммитить.**
- На сервере: `mkdir -p /opt/wotk && cd /opt/wotk && git clone git@github.com:<org>/way_of_the_king.git .` (deploy key для read-only)
- `cp backend/.env.production.example backend/.env`, заполнить prod значениями (БД пароль уникальный для prod)
- **AC:** `.env` на сервере с уникальными секретами, Pydantic-валидатор не отвергает (проверить `cd backend && uv run python -c "from wotk.core.config import get_settings; print(get_settings().app_env)"`)
- **Estimate:** 1ч

### W2-005 — Постгрес + редис в prod compose `TODO`
- Скопировать docker-compose.yml → docker-compose.prod.yml. В prod-варианте:
  - `postgres`: НЕ публиковать порт 5432 наружу (убрать `ports:`)
  - `redis`: то же самое
  - `restart: always` вместо `unless-stopped`
  - persistent volumes на отдельный disk path (`/opt/wotk/data/postgres`)
- `docker compose -f docker-compose.prod.yml up -d postgres redis` → проверить healthy
- Прогнать миграции: `docker compose -f docker-compose.prod.yml run --rm backend uv run alembic upgrade head`
- **AC:** psql на prod БД работает (через `docker compose exec`), `\dt` показывает все 5 таблиц, `alembic current` = `0005_best_practices`
- **Estimate:** 2ч
- **Dependencies:** W2-002, W2-004

### W2-006 — Прогон тестов в проде с пустой БД `TODO`
- Только smoke: backend стартует без ошибок, /health 200
- НЕ прогонять интеграционные тесты на prod — они TRUNCATE'ят таблицы. Локально достаточно.
- **AC:** `curl http://localhost:8000/health` на сервере возвращает 200, в логах нет startup errors
- **Estimate:** 1ч
- **Dependencies:** W2-005

---

## День 2 (Вт) — TLS, CI/CD, реальный домен (~8ч)

### W2-010 — Caddy + TLS `TODO`
Carry-over из W1-052.
- Caddyfile (root уровень): `wayoftheking.app { reverse_proxy backend:8000 }` плюс блок для realtime когда подключим
- Запустить caddy сервис: `docker compose -f docker-compose.prod.yml up -d caddy`
- Caddy автоматически получит Let's Encrypt сертификат (требует, чтобы 80/443 были доступны снаружи и DNS резолвился)
- **AC:** `https://wayoftheking.app/health` возвращает 200 с валидным TLS, `https://wayoftheking.app/docs` открывает OpenAPI Swagger
- **Estimate:** 1.5ч
- **Dependencies:** W2-003, W2-005

### W2-011 — GitHub Actions deploy workflow `TODO`
Carry-over из W1-053.
- `.github/workflows/deploy.yml`:
  - Trigger: `push` в `main` ПОСЛЕ успешного `ci.yml` (`workflow_run`, `conclusion: success`)
  - Steps: ssh-action → `cd /opt/wotk && git pull && docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d --build`
  - Финальный шаг: `curl -f https://wayoftheking.app/health` (smoke check, fail если не 200)
- Secrets в GitHub: `SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_USER`, `SSH_PORT`
- На сервере: добавить публичный ключ deploy-юзера в `~/.ssh/authorized_keys` с restrictive options (`command="..."`)
- **AC:** push в main → автодеплой → /health отвечает 200 в течение 3 минут
- **Estimate:** 3ч
- **Dependencies:** W2-001, W2-010

### W2-012 — Production secrets через Docker secrets / env_file `TODO`
- На MVP: `.env` файл с `chmod 600`, owner = wotk юзер
- Документировать в RUNBOOK.md §5 что для v1+ перейдём на Docker secrets / Vault (см. SECURITY.md §3.1)
- **AC:** `ls -l /opt/wotk/backend/.env` показывает `-rw------- 1 wotk wotk`
- **Estimate:** 0.5ч
- **Dependencies:** W2-004

### W2-013 — Sentry проект для production `TODO`
- Создать sentry.io аккаунт (free tier — 5k events/мес хватит для MVP)
- Создать проект `wotk-backend` (Python/FastAPI), скопировать DSN
- В prod `.env`: `SENTRY_DSN=<dsn>`, `APP_ENV=production` → редакция PII включена через `sentry_setup.py`
- Restart backend, спровоцировать тестовую ошибку (например GET /api/v1/heroes без auth → 401, проверить что Sentry это НЕ записал; ошибка 500 запишется)
- **AC:** реальная 500-ошибка появляется в Sentry dashboard, JWT/secrets отредактированы
- **Estimate:** 1.5ч
- **Dependencies:** W2-011

### W2-014 — Backup стратегия первой версии `TODO`
- На сервере: `apt install postgresql-client-16` (для pg_dump)
- Cron-скрипт `/opt/wotk/scripts/backup_db.sh` — `pg_dump`, gzip, upload в Backblaze B2 (`b2 sync` или `rclone`)
- Расписание: ежедневно в 03:00 UTC через `crontab -e`
- Retention: 7 дней дневных, 4 недельных (Sunday), 3 месячных (1-е число)
- **AC:** ручной прогон скрипта создаёт `.sql.gz` в B2, restore из бэкапа на отдельную БД проходит smoke-тест
- **Estimate:** 1.5ч
- **Dependencies:** W2-005

---

## День 3 (Ср) — Bot полировка + e2e в реальном TG (~8ч)

### W2-020 — BotFather setup для production `TODO`
Carry-over из W1-060.
- Создать `@WayOfTheKingBot` (или DevBot для dev environment отдельно). Получить токен.
- В BotFather: `/setdomain` → `wayoftheking.app`
- `/newapp` → название "Way Of The King", описание, иконка 640×360 + 192×192, URL `https://wayoftheking.app`
- Прописать токен в prod `.env` (`TELEGRAM_BOT_TOKEN`), restart backend + bot service
- **AC:** в Telegram бот находится по `@username`, кнопка Mini App открывает приложение с prod URL
- **Estimate:** 1.5ч
- **Dependencies:** W2-011

### W2-021 — `/start` с referral deeplink `TODO`
- Когда юзер открывает бот через `https://t.me/WayOfTheKingBot?start=ref_<base62>`, aiogram парсит payload
- Если `start_payload` начинается с `ref_` и юзер новый (нет в `profile`) — после login создать запись в `referral` с `referrer_profile_id` от owner'а кода (хранить mapping `ref_code → profile_id` в JWT или БД-таблице `referral_codes` — добавить простую таблицу)
- Если юзер уже зарегистрирован — игнорировать payload
- **AC:** перейти по deeplink → создать аккаунт → запись в `referral` появилась с правильным referrer
- **Estimate:** 2ч
- **Dependencies:** W2-020

### W2-022 — `/help` и `/wallet` команды `TODO`
- `/help` — статичный текст (i18n RU/EN), краткий обзор: что за игра, как играть, где взять помощь
- `/wallet` — placeholder "Coming in v1" пока нет TON интеграции
- **AC:** обе команды работают, отвечают на ru и en в зависимости от `language_code`
- **Estimate:** 1ч

### W2-023 — End-to-end smoke в реальном Telegram `TODO`
Carry-over из W1-061.
- iOS (личный девайс) + Android (попросить друга) — открыть бот, нажать Mini App
- Сценарий: автологин → форма Knight'а → ввод имени → создание → City экран
- Чек: i18n переключение работает по системной локали Telegram
- Чек: при reload Mini App auth не теряется (Telegram CloudStorage держит refresh token)
- **AC:** iOS + Android оба прошли сценарий, скриншоты в WEEK-2-TICKETS как evidence
- **Estimate:** 2ч
- **Dependencies:** W2-020

### W2-024 — Bug fixes из W2-023 `TODO`
Резерв на «всё пошло не так» при e2e в реальном TG. Типичные проблемы: viewport mismatch, safe area iOS, theme params (dark/light) не применились.
- **AC:** сценарий из W2-023 проходит чисто без visual glitches
- **Estimate:** 1.5ч
- **Dependencies:** W2-023

---

## День 4 (Чт) — Idempotency + observability (~10ч)

### W2-030 — `idempotency_keys` миграция `TODO`
Реализует [DATABASE.md §11.2](DATABASE.md) с применёнными best-practices: UUID PK, BYTEA(32) request_hash, size CHECK на response_body, tiered TTL.
- Миграция `0006_idempotency_keys.py` — таблица + индексы
- SQLAlchemy модель `IdempotencyKey` в `domain/models.py`
- **AC:** миграция применяется, тест на CHECK (>64KB body отвергается)
- **Estimate:** 1.5ч

### W2-031 — Idempotency middleware `TODO`
- `wotk/api/middleware_idempotency.py` или dependency `Depends(idempotent)`
- На POST с заголовком `Idempotency-Key: <uuid>` — посчитать `sha256(body)`, look up в `idempotency_keys`
- Если запись есть и `request_hash` совпал → вернуть закэшированный `response_status` + `response_body`
- Если запись есть и `request_hash` НЕ совпал → 422 (тот же ключ с другим телом — клиентская ошибка)
- Если записи нет → выполнить хендлер, потом INSERT с `expires_at = now() + (2h | 24h)` в зависимости от `is_payment_critical`
- Применить к: `POST /heroes`, `POST /auth/login` (last hour TTL для login достаточно)
- **AC:** unit-тесты на 3 кейса (cache hit, body mismatch, новый запрос); integration на /heroes — 2 раза с одним key возвращают одинаковый item
- **Estimate:** 3ч
- **Dependencies:** W2-030

### W2-032 — Cron infrastructure (Arq scheduler) `TODO`
- Установить `arq` (`uv add arq`)
- `wotk/worker/main.py` — Arq worker с задачами:
  - `cleanup_expired_idempotency_keys` — каждые 30 мин (вызывает функцию из миграции 0005)
  - `cleanup_expired_runs` — заглушка, активируется когда появятся dungeon_runs
- В docker-compose.prod.yml добавить сервис `worker`: `command: uv run arq wotk.worker.main.WorkerSettings`
- **AC:** worker стартует, в логах видно запуск задач по расписанию
- **Estimate:** 2ч

### W2-033 — Request_id + structlog в production JSON `TODO`
- ✅ middleware уже есть ([middleware.py](../backend/src/wotk/core/middleware.py))
- Дополнить: проверить, что в `APP_ENV=production` structlog выдаёт строго JSON (не human-readable)
- Sentry breadcrumb: автоматически прикладывать `request_id` к каждому event
- Документировать в RUNBOOK.md как искать ошибку по request_id (юзер репортит ID → grep в Loki/journalctl → стек ошибки)
- **AC:** в prod-логе одна строка = валидный JSON с `request_id`/`method`/`path`/`level`/`event`
- **Estimate:** 1.5ч

### W2-034 — Healthcheck + readiness endpoints `TODO`
- ✅ `/health` уже есть (liveness — backend жив)
- Добавить `/health/ready` — проверяет: postgres pingable + redis pingable + миграции применены (`alembic_version` существует и == head)
- Caddy/Cloudflare читают /health, GitHub Actions deploy после `up -d` ждёт /health/ready перед признанием успеха
- **AC:** /health/ready возвращает 200 когда всё ок, 503 + JSON `{checks: {...}}` если что-то не так
- **Estimate:** 1.5ч

---

## День 5 (Пт) — Pixi v8 setup + Tiled (~10ч)

### W2-040 — Pixi v8 в React `TODO`
Phase 2 старт.
- Установить `pixi.js@^8`, `@pixi/tilemap@^5` (или встроенный Container если @pixi/tilemap не готов под v8 — проверить)
- В `frontend/src/components/PixiCanvas.tsx`: создать React-компонент, монтирующий Pixi Application в div через `useEffect`
- В Mini App layout — вставить рядом с UI overlay (Pixi на 100% viewport, UI поверх через z-index)
- Cleanup на unmount (Application.destroy)
- **AC:** Pixi canvas рендерит цветной фон + один Sprite-плейсхолдер на координатах (100,100)
- **Estimate:** 2ч
- **Dependencies:** Phase 1 frontend (готов)

### W2-041 — Скачать LPC sprite pack + один Knight asset `TODO`
- LPC (Liberated Pixel Cup) — CC-BY-SA 3.0, бесплатно
- Скачать с opengameart.org один character pack: idle + walk × 4 направления (всего 9 frames idle + 9×4 walk = 45 кадров)
- Положить в `frontend/public/assets/sprites/knight/` (PNG sprite sheets) + `knight.json` Aseprite-style metadata (frames + animations)
- License-файл `LICENSE-LPC.md` рядом с asset'ами
- **AC:** в `frontend/public/assets/sprites/knight/` лежит spritesheet + metadata, license закоммичен
- **Estimate:** 1.5ч

### W2-042 — Tiled Map Editor: первая комната `TODO`
- Установить Tiled (бесплатно, opengameart-friendly)
- Скачать tileset (LPC dungeon tileset) — 32×32 tiles, terrain + walls
- Создать карту 20×15 tiles: пол + стены по периметру + одна внутренняя стенка для теста коллизий
- Layers: `terrain`, `walls`, `objects` (collision rectangles)
- Export: JSON в `frontend/public/maps/test_room_01.json`, PNG tileset рядом
- **AC:** JSON загружается в `pixi-tilemap` или вручную через Container, рендерится корректно (полы + стены видны)
- **Estimate:** 2.5ч

### W2-043 — Pixi: рендер Tiled JSON `TODO`
- `frontend/src/game/render/TiledMap.ts` — функция `loadTiledMap(json) -> Container`
- Парсит layers, для каждой ненулевой ячейки терёт `Sprite` с правильным `Texture` из tileset atlas
- Walls layer кладёт в отдельный Container с alpha=1, objects layer с collision rectangles НЕ рендерит, но возвращает массив `Rect[]` для коллизий
- **AC:** комната из W2-042 видна в Pixi canvas, FPS ≥ 60 на test устройстве
- **Estimate:** 2.5ч
- **Dependencies:** W2-040, W2-042

### W2-044 — Knight idle animation `TODO`
- `frontend/src/game/entities/Player.ts` — класс Player с PIXI.AnimatedSprite
- Загрузить spritesheet, разрезать на 4 idle-анимации (по направлениям) через PIXI.Spritesheet.parse
- Дефолтная анимация — idle south, FPS=8
- **AC:** Knight стоит в центре комнаты и анимирован (idle цикл)
- **Estimate:** 1.5ч
- **Dependencies:** W2-041, W2-043

---

## День 6 (Сб) — Joystick + движение + камера (~10ч)

### W2-050 — nipplejs виртуальный джойстик `TODO`
- `npm install nipplejs`
- React-компонент `Joystick.tsx`, рендерится в правом-нижнем углу UI overlay (touch-friendly, 120px diameter)
- onMove callback → передаёт `{angle, distance}` в Player через ref/zustand store
- Только на мобильных (детект через Telegram WebApp `platform`); на десктопе — WASD через keydown listener
- **AC:** на iOS Safari движение пальцем по nipplejs работает, события приходят в Player
- **Estimate:** 2.5ч

### W2-051 — Player movement (client-only) `TODO`
- В Player tick (PIXI.Ticker callback): `position.x += sin(angle) * speed * delta`, `position.y -= cos(angle) * speed * delta`
- Speed = 80 px/sec (тюнить по feel)
- 4-directional sprite switch: при движении — выбрать walk_<dir> анимацию по углу (north/south/east/west, 8-direction округление потом)
- При stop — вернуться к idle_<last_dir>
- **AC:** Knight ходит по экрану в 4 направления, спрайт меняется, в idle стоит
- **Estimate:** 2ч
- **Dependencies:** W2-044, W2-050

### W2-052 — Collision с walls layer `TODO`
- В Player tick перед `position +=`: проверить, что новая позиция не пересекается с любым `Rect` из walls (axis-aligned, простая AABB intersection)
- Если коллизия → попытаться двигаться только по X, потом только по Y (slide-along-wall)
- Player hitbox: 24×24 (меньше тайла, чтобы пролезал в дверные проёмы)
- **AC:** Knight упирается в стены, скользит вдоль них, не проходит сквозь
- **Estimate:** 2ч
- **Dependencies:** W2-051

### W2-053 — Camera follow player `TODO`
- World Container — родитель для tilemap + entities; UI overlay — отдельно (фиксирован)
- На каждом тике: `world.position.set(viewport.width/2 - player.x, viewport.height/2 - player.y)`
- Clamp: камера не уезжает за границы карты (если карта меньше viewport — не центрируем)
- **AC:** камера плавно следует за Knight'ом, при достижении края карты останавливается
- **Estimate:** 1.5ч
- **Dependencies:** W2-051

### W2-054 — 5 тестовых комнат разного layout `TODO`
- В Tiled нарисовать 5 .json файлов: маленькая (10×8), средняя (20×15), большая (40×30), узкие коридоры, комната с центральной колонной
- Кнопка-переключатель в City экране (debug menu — только в dev) → рендерит выбранную комнату
- **AC:** 5 карт, переключение работает, на всех Knight ходит без bug'ов с коллизиями
- **Estimate:** 2ч

---

## День 7 (Вс) — Polish + e2e + ROADMAP review (~6ч)

### W2-060 — Performance pass `TODO`
- Открыть Chrome DevTools Performance tab, профилировать Pixi-рендер на mid-range Android (Pixel 5 эмулятор или реальный девайс)
- Цель: 60 FPS на средней карте, < 16ms per frame
- Типичные оптимизации: ParticleContainer вместо Container для статичных тайлов, atlas mip-mapping, текстуры через `Assets.load` с preload
- **AC:** на Pixel 5 эмуляторе FPS не падает ниже 50 на самой большой карте
- **Estimate:** 1.5ч

### W2-061 — Mini App resize / orientation handling `TODO`
- Telegram WebApp meta: `Telegram.WebApp.expand()` уже есть; добавить listener на `viewportChanged` event
- Pixi Application.renderer.resize() при изменении viewport
- Поддержка landscape (когда Telegram пользователь повернёт девайс) — переключение layout: канвас остаётся 100%, joystick перепозиционируется
- **AC:** поворот девайса не ломает рендер, joystick всегда в touch-reachable зоне
- **Estimate:** 1ч

### W2-062 — Smoke в реальном Telegram (Phase 2 milestone) `TODO`
- iOS + Android: открыть Mini App → автологин → создать Knight (если не создан) → попасть на City → debug-кнопка "Test dungeon room" → Pixi сцена → ходить джойстиком 30 секунд
- Дёрнуть друзей пробежать тот же сценарий, собрать feedback (ощущение feel mobile-Diablo? joystick отзывчив?)
- **AC:** оба девайса прошли, нет крашей, FPS ≥ 50, friends дали ≥ 1 положительный отзыв на feel
- **Estimate:** 1.5ч
- **Dependencies:** W2-053, W2-054

### W2-063 — Документация + ROADMAP review `TODO`
- Обновить `docs/ROADMAP.md` — отметить Phase 1 как ✅ DONE, начало Phase 2
- Создать `docs/WEEK-3-PLAN.md` или briefly note в ROADMAP что готовить к W3 (продолжение Phase 2: client prediction, более сложные комнаты, base AI прототип на клиенте)
- Обновить README screenshot-секцию: добавить gif/png работающего Mini App
- **AC:** ROADMAP актуален, W3-план есть, README с актуальным screenshot
- **Estimate:** 1ч

### W2-064 — Резерв `TODO`
Buffer на «всё пошло не так». Типично использует production-инцидент или нерешённый Pixi-баг.
- **Estimate:** 1ч

---

## Итого по неделе

- Всего тикетов: 31 (как в W1, удобно)
- Суммарная оценка: ~62 часа (с буфером W2-064 = 1ч)
- Critical path: W2-001 → W2-002 → W2-005 → W2-010 → W2-011 → W2-020 → W2-040 → W2-051 → W2-062
- **Carry-over из W1:** W2-001 (push), W2-002 (Hetzner), W2-003 (DNS), W2-010 (Caddy), W2-011 (deploy), W2-020 (BotFather), W2-023 (e2e в TG)

## Фактический статус (2026-04-28)

**✅ Сделано (15 / 31):**
- W2-021, W2-022 (bot — уже было в W1)
- W2-030, W2-031 (idempotency_keys миграция + middleware + 5 тестов)
- W2-032 (Arq cron worker + cleanup_expired_idempotency_keys + тест)
- W2-033 (structlog JSON-config в prod + Sentry request_id tag через isolation_scope)
- W2-034 (/health/ready endpoint)
- W2-040 (Pixi v8 setup)
- W2-042-alt (5 процедурных комнат вместо Tiled — `frontend/src/game/room.ts`)
- W2-043 (рендер процедурных комнат через Graphics)
- W2-044-alt (placeholder Knight — circle + chevron вместо LPC sprite)
- W2-050 (nipplejs joystick)
- W2-051 (4-directional movement + sprite facing)
- W2-052 (collision с walls slide-along-wall)
- W2-053 (camera follow с clamp)
- W2-054-alt (5 layouts + dropdown selector)
- W2-061 (resize + orientationchange listener)

**❌ Отложено — production (12):** W2-001, W2-002..006, W2-010..014, W2-020, W2-023, W2-024, W2-062

**❌ Отложено — assets (3):** W2-041 (LPC sprite pack), W2-042 (Tiled JSON), W2-044 (real Knight animation)

**🟡 Не сделано — нужно реальное устройство (1):** W2-060 (Performance pass)

**Метрика покрытия скоупа:**
- Из 32h «локально-доступной» работы: ~30h освоено
- Backend tests: 125/125 green (was 124, +1 test_worker)
- Frontend typecheck + build: green
- Идём вровень с планом по Phase 1 завершению, Phase 2 запущена с placeholder-графикой

## Acceptance criteria недели

- ✅ Production live: `https://wayoftheking.app/health` 200 с валидным TLS
- ✅ Auto-deploy: push в main → < 3 мин до /health отвечает с новой версией
- ✅ Реальный Telegram bot: e2e сценарий проходит на iOS + Android
- ✅ Sentry получает реальные ошибки с production
- ✅ Idempotency middleware работает на POST /heroes
- ✅ Pixi: Knight ходит по комнате с джойстиком, FPS ≥ 50 на mid-range Android
- ✅ Backup БД настроен и протестирован restore'ом

## Риски недели

| Риск | Митигация |
|---|---|
| Hetzner сетап затянулся (firewall/SSH порт) | Готовый ansible playbook сэкономит 1ч; либо использовать Hetzner Cloud snapshot готового образа |
| Caddy не может получить cert (DNS не успел propagate) | Подождать 1ч после смены DNS, проверить через `dig +short` с разных резолверов |
| BotFather не принимает домен | Использовать `*.t.me/<bot>?startapp=...` deeplink временно, либо ngrok с существующим бот-токеном |
| GH Actions deploy валится на ssh-action | Pre-test через `act` локально; иметь fallback ручной деплой через ssh из терминала |
| LPC sprite pack оказался под несовместимой лицензией / отсутствует | Backup: itch.io free packs (Penzilla, kenney.nl); $0 за CC0 спрайты на kenney.nl |
| Pixi v8 + @pixi/tilemap несовместимы | Fallback: ручной рендер через Sprite-grid; чуть медленнее, но без библиотеки-специфики |
| Joystick lag на iOS Safari | Использовать Telegram WebApp HapticFeedback для тактильного фидбека → перекрывает визуальную задержку |
| Frontend (не сильная сторона) затягивает Pixi-задачи | Жёстко time-box каждый тикет; если W2-051 не вмещается за 2ч — упростить до WASD-only без animation switching |

## Что готово к началу W3

- Production environment стабильный, deploy автоматический → можно фокусироваться на коде
- Pixi-каркас работает → Phase 2 продолжение (W3-4): client prediction, server-driven movement, начало Phase 3 (Colyseus integration)
- Все W1+W2 тесты зелёные, regression-защита налажена

# Локальное тестирование через Telegram

Стек уже работает локально (`backend` на :8000, `frontend` на :5173,
`postgres+redis` в docker). Чтобы открыть Mini App **изнутри Telegram**
нужны:

1. **Реальный bot token** из @BotFather
2. **HTTPS-туннель** к фронтенду (Telegram не пускает Mini App на http://localhost)
3. Настроить Web App URL в BotFather

В качестве туннеля используем **cloudflared quick tunnel** — без регистрации,
без auth-token, без MITM-конфликтов с антивирусами (в отличие от ngrok-free,
у которого свежий домен `*.ngrok-free.dev` режется HTTPS-инспекцией некоторых AV
с ошибкой `ERR_SSL_PROTOCOL_ERROR` / `SEC_E_INVALID_TOKEN`).

---

## 1. Получить bot token (5 минут)

1. В Telegram открой чат с **@BotFather**
2. `/newbot` → введи display name (например `Way Of The King Local`) → введи username (должен заканчиваться на `bot`, например `wotk_dev_bot`)
3. BotFather пришлёт строку вида `1234567890:AAEa-fakefakeFAKE_xxxxxxxxxxxxxxxxxxxxxxx` — это **TELEGRAM_BOT_TOKEN**
4. Запомни username бота (без `@`) — это **TELEGRAM_BOT_USERNAME**

---

## 2. Установить cloudflared (один раз)

```bash
winget install Cloudflare.cloudflared
```

Бинарник ставится в `C:\Program Files (x86)\cloudflared\cloudflared.exe`. После
установки `cloudflared` доступен в новых терминалах (PATH обновляется).

Регистрация в Cloudflare **не нужна** для quick tunnel. Random URL вида
`https://<random-words>.trycloudflare.com` выдаётся каждый запуск.

---

## 3. Прописать переменные в `backend/.env`

```bash
# В backend/.env
TELEGRAM_BOT_TOKEN=1234567890:AAEa-...твой_токен_от_BotFather
TELEGRAM_BOT_USERNAME=wotk_dev_bot
# URL Mini App для кнопки в /start (заполнится после шага 4 — cloudflared URL)
TELEGRAM_MINIAPP_URL=
TELEGRAM_MINIAPP_SHORT_NAME=play
```

Pydantic Settings подхватит при следующем рестарте backend-процесса.

> ⚠️ `TELEGRAM_MINIAPP_URL` **обязательно** прямой HTTPS URL hosting'а
> (cloudflared/ngrok). Telegram отвечает `BUTTON_URL_INVALID` если в
> `WebAppInfo` подсунуть `t.me/...`-ссылку. Если поле пустое — бот сделает
> обычную URL-кнопку на `t.me/<bot>/<short_name>`, но это менее удобно
> (открывает Mini App через Telegram-deeplink вместо in-place WebApp).

---

## 4. Запустить cloudflared туннель к фронтенду

В **отдельном терминале**:

```bash
cloudflared tunnel --url http://localhost:5173
```

Получишь вывод вида:
```
2026-04-28T22:25:43Z INF Requesting new quick Tunnel on trycloudflare.com...
2026-04-28T22:25:47Z INF |  https://exclusion-usr-wisdom-cricket.trycloudflare.com  |
```

`https://exclusion-usr-wisdom-cricket.trycloudflare.com` — это **публичный HTTPS URL**
для Mini App.

> ⚠️ **Vite dev server должен быть запущен на :5173** (`npm run dev` в `frontend/`).
> Vite проксирует `/api/*` → backend :8000 и `/game` → Colyseus :2567, поэтому
> фронт+бэк+ws доступны через один туннель.

> ⚠️ Vite security: разрешённые hosts ограничены. `.trycloudflare.com` уже
> прописан в `vite.config.ts` → `allowedHosts`. Если меняешь туннель — добавь
> новый домен туда.

> ⚠️ URL **меняется каждый запуск** cloudflared. Если хочешь стабильный домен —
> зарегистрируй Cloudflare-аккаунт + named tunnel:
> ```bash
> cloudflared tunnel login
> cloudflared tunnel create wotk-dev
> cloudflared tunnel route dns wotk-dev wotk-dev.твой-домен.tld
> cloudflared tunnel --url http://localhost:5173 wotk-dev
> ```

---

## 5. Прописать Web App URL в BotFather

1. В чате с @BotFather: `/newapp` (или `/myapps` → выбрать бота → `Edit Web App URL`)
2. Выбрать своего бота
3. Заполнить:
   - **Title:** Way Of The King
   - **Description:** Medieval ARPG (any text)
   - **Photo:** любой PNG 640x360 (можно скип через `/empty`)
   - **GIF:** скип
   - **Web App URL:** `https://exclusion-usr-wisdom-cricket.trycloudflare.com` (твой trycloudflare URL)
   - **Short name:** `play` (для deep-link `t.me/wotk_dev_bot/play`)

При каждом перезапуске cloudflared URL меняется → **придётся обновлять Web App URL
в BotFather** (либо использовать named tunnel, см. шаг 4).

---

## 6. Перезапустить backend и запустить bot

После шага 4 (получили cloudflared URL) — впиши его в `backend/.env`:

```bash
TELEGRAM_MINIAPP_URL=https://exclusion-usr-wisdom-cricket.trycloudflare.com
```

Backend и **бот** нужно перезапустить чтобы подхватить новый
`TELEGRAM_BOT_TOKEN` и `TELEGRAM_MINIAPP_URL` из `.env`:

```bash
# Убить текущий backend (если бежит)
taskkill /F /IM python.exe

# В одном терминале — backend
cd backend
uv run uvicorn wotk.api.main:app --host 0.0.0.0 --port 8000

# В другом терминале — bot polling
cd backend
uv run python -m wotk.bot
```

Бот залогинится в Telegram и начнёт polling.

---

## 7. Открыть Mini App

В Telegram:

1. Найди своего бота по username (например `@wotk_dev_bot`)
2. Жми `/start`
3. Появится сообщение с кнопкой **«⚔️ Открыть игру»**
4. Жми кнопку → откроется Mini App

Или через deep link: `t.me/wotk_dev_bot/play`

---

## 8. Что должно работать

- ✅ Auto-login через `Telegram.WebApp.initData` (HMAC валидируется backend'ом)
- ✅ Создание Knight (форма с именем 3–20 символов)
- ✅ City экран с именем рыцаря, уровнем, золотом, энергией
- ✅ HapticFeedback на success/error в форме
- ✅ Локализация по `language_code` из Telegram

---

## 9. Логи и отладка

### Backend
```bash
# Уже логируется в stdout уvicorn'а
# Также в /tmp/wotk-backend2.log
```

Ключевые логи:
- `profile_created profile_id=...` — новый юзер
- `login_init_data_invalid` — HMAC не сошёлся (плохой токен в .env?)
- `login_geo_blocked` — страна в блоке
- `auth_token_expired` / `auth_token_invalid` — JWT проблемы

### Frontend
Открой DevTools в Telegram Desktop:
- ПКМ в Mini App → **Inspect Element** (только в Desktop версии Telegram)
- Network tab покажет запросы к `/api/v1/auth/login`, `/api/v1/me`, `/api/v1/heroes`

### Bot
```bash
# Логи polling в stdout
# /start обработка / referral parsing видны
```

### cloudflared
В stdout туннеля видны все входящие запросы (метод, путь, статус). Полноценного
inspector-UI как у ngrok нет — для глубокого debug используй DevTools браузера
или backend-логи.

---

## 10. Частые проблемы

| Симптом | Причина | Фикс |
|---|---|---|
| `invalid_init_data` 401 | TG токен не совпадает с тем, что был использован для подписи | Проверить TELEGRAM_BOT_TOKEN в `.env`, перезапустить backend |
| Кнопка Mini App не открывает ничего | Web App URL в BotFather не выставлен или сломан | `/myapps` в BotFather → Edit Web App URL |
| Vite "Blocked request" | hostname туннеля не в allowedHosts | В `vite.config.ts` уже есть `.trycloudflare.com`, `.ngrok-free.app`, `.ngrok-free.dev`. Если используешь другой провайдер — добавь его |
| `ERR_SSL_PROTOCOL_ERROR` / "сайт отправил недействительный ответ" на ngrok-free.dev | Антивирус с HTTPS-scanning ломает handshake к свежему домену `.ngrok-free.dev` (в Schannel логах — `SEC_E_INVALID_TOKEN`) | Перейти на cloudflared (`cloudflared tunnel --url http://localhost:5173`) либо отключить TLS-инспекцию AV для `*.ngrok-free.dev` |
| cloudflared URL "не открывается" | Старый URL — туннель перезапущен и выдал новый | Сверь URL в BotFather с текущим выводом cloudflared |
| `geo_blocked` 403 | Реальный IP попал в `GEO_BLOCK_COUNTRIES` | Закомментить себя через `GEO_BLOCK_COUNTRIES=` (пустая строка) в `.env` |
| `no_init_data` в браузере | Открываешь напрямую в браузере, не в TG | Это нормально — initData есть только в Telegram |
| Бот молчит на `/start` | Не запущен `python -m wotk.bot` | Запустить bot polling |
| `Bad Request: BUTTON_URL_INVALID` при `/start` | `TELEGRAM_MINIAPP_URL` пустой или это `t.me/...`-ссылка (Telegram её не принимает в `WebAppInfo`) | Прописать в `.env` прямой HTTPS URL cloudflared/ngrok туннеля и перезапустить bot |

# Локальное тестирование через Telegram

Стек уже работает локально (`backend` на :8000, `frontend` на :5173,
`postgres+redis` в docker). Чтобы открыть Mini App **изнутри Telegram**
нужны:

1. **Реальный bot token** из @BotFather
2. **HTTPS-туннель** к фронтенду (Telegram не пускает Mini App на http://localhost)
3. Настроить Web App URL в BotFather

ngrok уже установлен (через `winget install ngrok.ngrok`, версия 3+).

---

## 1. Получить bot token (5 минут)

1. В Telegram открой чат с **@BotFather**
2. `/newbot` → введи display name (например `Way Of The King Local`) → введи username (должен заканчиваться на `bot`, например `wotk_dev_bot`)
3. BotFather пришлёт строку вида `1234567890:AAEa-fakefakeFAKE_xxxxxxxxxxxxxxxxxxxxxxx` — это **TELEGRAM_BOT_TOKEN**
4. Запомни username бота (без `@`) — это **TELEGRAM_BOT_USERNAME**

---

## 2. Регистрация в ngrok (3 минуты, один раз)

Без auth-token бесплатные туннели работают, но дают случайный URL и
ограничения. С auth-token — более стабильно.

1. Зарегистрируйся на https://dashboard.ngrok.com/signup
2. Скопируй authtoken с https://dashboard.ngrok.com/get-started/your-authtoken
3. В терминале:
   ```bash
   ngrok config add-authtoken <твой_token>
   ```

(Можно пропустить — будет работать без auth, просто URL будет меняться при каждом перезапуске.)

---

## 3. Прописать переменные в `backend/.env`

```bash
# В backend/.env
TELEGRAM_BOT_TOKEN=1234567890:AAEa-...твой_токен_от_BotFather
TELEGRAM_BOT_USERNAME=wotk_dev_bot
```

Пересобрать backend конфиг не нужно — Pydantic Settings подхватит при следующем рестарте процесса.

---

## 4. Запустить ngrok туннель к фронтенду

В **отдельном терминале**:

```bash
ngrok http 5173
```

Получишь вывод вида:
```
Forwarding   https://abc-123-xyz.ngrok-free.app -> http://localhost:5173
```

`https://abc-123-xyz.ngrok-free.app` — это **публичный HTTPS URL** для Mini App.

> ⚠️ **Vite dev server должен быть запущен на :5173** (он уже работает, проверить
> можно открыв http://localhost:5173 в браузере). Vite проксирует `/api/*` к
> backend на :8000, поэтому фронт и бэк будут доступны через один туннель.

> ⚠️ Vite security: разрешённые hosts ограничены. Если ngrok URL отвергается —
> добавь `server.allowedHosts: ['.ngrok-free.app']` в `vite.config.ts` или
> запусти `npm run dev -- --host 0.0.0.0`.

---

## 5. Прописать Web App URL в BotFather

1. В чате с @BotFather: `/newapp` (или `/myapps` → выбрать бота → `Edit Web App URL`)
2. Выбрать своего бота
3. Заполнить:
   - **Title:** Way Of The King
   - **Description:** Medieval ARPG (any text)
   - **Photo:** любой PNG 640x360 (можно скип через `/empty`)
   - **GIF:** скип
   - **Web App URL:** `https://abc-123-xyz.ngrok-free.app` (твой ngrok URL)
   - **Short name:** `play` (для deep-link `t.me/wotk_dev_bot/play`)

---

## 6. Перезапустить backend и запустить bot

Backend нужно **перезапустить** чтобы он подхватил новый `TELEGRAM_BOT_TOKEN` из
`.env`:

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

### ngrok inspector
http://localhost:4040 — все запросы через туннель в реальном времени.

---

## 10. Частые проблемы

| Симптом | Причина | Фикс |
|---|---|---|
| `invalid_init_data` 401 | TG токен не совпадает с тем, что был использован для подписи | Проверить TELEGRAM_BOT_TOKEN в `.env`, перезапустить backend |
| Кнопка Mini App не открывает ничего | Web App URL в BotFather не выставлен или сломан | `/myapps` в BotFather → Edit Web App URL |
| Vite "Blocked request" | ngrok hostname не в allowedHosts | Добавить в `vite.config.ts`: `server: { allowedHosts: ['.ngrok-free.app'] }` |
| `geo_blocked` 403 | Реальный IP попал в `GEO_BLOCK_COUNTRIES` | Закомментить себя через `GEO_BLOCK_COUNTRIES=` (пустая строка) в `.env` |
| `no_init_data` в браузере | Открываешь напрямую в браузере, не в TG | Это нормально — initData есть только в Telegram |
| Бот молчит на `/start` | Не запущен `python -m wotk.bot` | Запустить bot polling |

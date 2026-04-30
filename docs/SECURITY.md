# Security Policy

Версия: 0.2
Последнее обновление: 2026-04-27

Документ описывает threat model, принципы secure development, операционные процедуры и accepted risks для Way Of The King.

---

## 1. Threat model (краткая)

### Главные активы
1. **Custodial hot wallet** — TON jetton'ы юзеров. Прямая монетизация любого взлома.
2. **Game economy integrity** — gold/items. Подделка = чёрный рынок дешёвого WOTK.
3. **User accounts** — Telegram identity, доступ к их wallet'у.
4. **Game state** — combat results, влияет на лидерборды и PvP-ставки.

### Главные threat actors
- **Опытные крипто-боты** — массово создают аккаунты, фармят, выводят
- **Memory editor / packet manipulation** — клиентский чит, обход combat правил
- **Insider** — кто-то с доступом к prod env (в нашем случае — соло-разработчик 😅)
- **Telegram-аккаунт hijack** — захват сессии через social engineering
- **Supply chain** — компрометация npm/pip пакета (Lottie, ua-parser-js прецеденты)
- **Внешний API compromise** — telegram.org, TON Center, RPC-провайдеры

### Что НЕ в model (out of scope)
- Государственные APT
- Физический доступ к серверу (предполагается, что hosting-провайдер защищён)
- Side-channel атаки на CPU

---

## 2. Принципы secure development

### Секреты
- **Никаких слабых дефолтов.** Pydantic-валидатор в `backend/src/wotk/core/config.py` отказывается стартовать в staging/production с дефолтными или короткими секретами.
- **Раздельные секреты для разных направлений.** HMAC между Colyseus↔FastAPI — два отдельных значения (если realtime-нода взломана, FastAPI→realtime канал всё ещё доверенный, и наоборот).
- **`.env` никогда не коммитится.** `.gitignore` блокирует `.env`, `secrets/`, `mnemonic*.txt`, `*.pem`, `*.key`.
- **Sentry с принудительной редакцией.** `wotk/core/sentry_setup.py` редактирует JWT, mnemonic, токены автоматически перед отправкой. Лучше потерять отчёт, чем утечь секрет.

### Authentication / Authorization
- HMAC-валидация Telegram `initData` на каждом login (TTL 24h по официальной рекомендации Telegram)
- JWT короткоживущие (1h access / 30d refresh / 30s ws_token)
- Algorithm — `Literal["HS256","HS384","HS512"]` (защита от `none`/RS256 confusion)
- 2FA через бота на withdrawal'ы

### Combat / Game logic
- **Server-authoritative всё.** Клиент шлёт inputs, не результаты.
- Server-side валидация input rate, sequence, timestamp drift, bounds
- Periodic snapshots для replay-аудита (см. RUN-LIFECYCLE.md)

### Custodial wallet
- HD-wallet (BIP-39/44), один master mnemonic
- **Derivation path не хранится в БД** — выводится детерминированно из `profile_id` (`m/44'/607'/<profile_id>'`). Снижает blast radius при компрометации БД: атакующий не получает прямую карту address ↔ HD slot. См. DATABASE.md §7.1.
- Hot wallet ≤ 20% резерва, остальное — cold (multi-sig 2-of-3 на v1+)
- Reconciliation cron каждые 5 мин (DB sum vs onchain) → расхождение > 1% = пауза
- Лимиты: max 50 WOTK/день/юзер, 24h cooldown на смену внешнего адреса
- Пороги для KYC при выводе > N USDT (когда регулятор применим)

### 2FA codes — HMAC + pepper, не bcrypt
6-значный код имеет 10⁶ entropy — любой password-hash (bcrypt/argon2/scrypt) перебирается за минуты на GPU. Поэтому:

- Хранится `HMAC-SHA256(pepper, code)` в `withdrawals.tfa_code_hash` (BYTEA, 32 байта).
- `pepper` — server-side секрет в env (`TFA_PEPPER`, минимум 32 байта random), **никогда не в БД**. Без pepper'а hash бесполезен.
- TTL кода — 10 минут (`tfa_expires_at`).
- Max 3 attempts (`tfa_attempts`), потом transition в `FAILED`.

```python
import hmac, hashlib
def hash_2fa_code(code: str, pepper: bytes) -> bytes:
    return hmac.new(pepper, code.encode(), hashlib.sha256).digest()

def verify_2fa_code(code: str, stored_hash: bytes, pepper: bytes) -> bool:
    return hmac.compare_digest(stored_hash, hash_2fa_code(code, pepper))
```

### Append-only ledger-таблицы (defence-in-depth)
Финансовые данные защищены **двумя** механизмами на уровне БД:

1. **БД-триггеры** (`BEFORE UPDATE/DELETE → RAISE EXCEPTION`) — основная защита. См. DATABASE.md §5.2, §7.4, §11.1.
2. **`REVOKE UPDATE, DELETE`** на app-роли (`wotk_app`) — defence-in-depth.

Покрытые таблицы: `transaction`, `treasury_log`, `audit_events`. Если один механизм пропустит (баг в Postgres, ошибочный GRANT) — второй сработает. Изменения в этих таблицах требуют DBA-доступа.

### Network / Infrastructure
- HTTPS only (HSTS + preload в Caddyfile)
- Жёсткий CORS allowlist (никаких "*")
- Strict CSP с `frame-ancestors` для Telegram, `script-src` ограничен
- Rate limiting через slowapi (Redis-backed) — per IP и per user
- Geo-блок US/UK/санкционные страны на уровне FastAPI middleware
- Все Docker-образы используют non-root user

### CI / CD
- Dependabot weekly (см. `.github/dependabot.yml`)
- pip-audit / npm audit в CI (TODO в W2 после генерации lockfile'ов)
- Никаких secrets в логах (структурное логирование с whitelist полей)

---

## 3. Операционные процедуры

### 3.1 Хранение mnemonic горячего кошелька

**MVP (acceptable):** env-переменная `HOT_WALLET_MNEMONIC` через Docker secrets:

```bash
# На сервере:
echo "twenty four words mnemonic phrase ..." | docker secret create wotk_hot_mnemonic -
```

И в `docker-compose.yml`:
```yaml
backend:
  secrets:
    - wotk_hot_mnemonic
  environment:
    HOT_WALLET_MNEMONIC_FILE: /run/secrets/wotk_hot_mnemonic

secrets:
  wotk_hot_mnemonic:
    external: true
```

(Адаптация к чтению `*_FILE` суффикса в `config.py` будет добавлена когда понадобится в Phase 7.)

**v1+ (recommended):** HashiCorp Vault или AWS Secrets Manager / Azure Key Vault с rotation policy.

**Backup:** бумажная копия в физическом сейфе (сейф в банке предпочтительнее домашнего).

### 3.2 Ротация mnemonic горячего кошелька

Делается при подозрении на утечку или раз в N месяцев планово.

1. Сгенерировать новый mnemonic offline (на air-gapped машине предпочтительно)
2. Создать новый HD wallet, дать ему testnet jetton'ов
3. Smoke-тест в testnet: deposit, withdraw, reconciliation
4. На проде:
   - Включить maintenance mode (запрет ввода/вывода)
   - Дождаться завершения всех PENDING withdrawal'ов
   - Перевести весь баланс старого hot wallet на новый адрес
   - Обновить Docker secret
   - Restart backend сервиса
   - Проверить deposit/withdraw в smoke-тесте
   - Снять maintenance mode
5. Старый mnemonic — destroy (sysrq sync + zero swap, или оффлайн физическое уничтожение бумаги)
6. Запись в `treasury_log` с action='ROTATION'

### 3.3 Ротация JWT_SECRET

JWT_SECRET ротируется при подозрении на утечку:

1. Сгенерировать новый: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. Поставить новый в env
3. Restart backend → все existing JWT станут невалидными
4. Юзеры будут вынуждены re-login (через initData → новый JWT) — для них незаметно

### 3.4 Compromise response

Если предположительно скомпрометирован:

**Hot wallet:**
1. Маркировать паузу в админке → ban на новые withdrawal'ы
2. **Немедленно** перевести весь баланс на cold wallet
3. Аудит treasury_log за последние 24 часа
4. Уведомить юзеров через бота
5. Ротация mnemonic (см. 3.2)

**JWT_SECRET:**
1. Ротация (см. 3.3) — все юзеры перелогинятся
2. Аудит audit_events: подозрительные login/withdraw

**Database:**
1. Если read-only утечка → ротация JWT_SECRET (содержимое БД больше не usable для подделки)
2. Если write — это уже incident response категория, нужен внешний аудит

### 3.5 Backup

- **Postgres**: continuous WAL archiving в S3 (Backblaze B2) + pg_basebackup ежедневно. См. DATABASE.md §17.
- **mnemonic**: бумажная копия в физическом сейфе (на 2 разных адресах для resilience)
- **Конфиг сервера**: terraform/ansible state в private GitHub repo

---

## 4. Accepted risks (известные, осознанные)

### A1. Telegram WebApp script без SRI
`<script src="https://telegram.org/js/telegram-web-app.js">` загружается без Subresource Integrity hash, потому что Telegram авто-апдейтит файл. Если telegram.org будет скомпрометирован — наш Mini App инкорпорирует malicious JS.

**Mitigation:** Strict CSP с `script-src 'self' https://telegram.org` ограничивает exfil каналы.

### A2. Соло-разработчик = единственная точка отказа
Если разработчик заболел/недоступен — никто не может ответить на инцидент быстро.

**Mitigation:**
- Документированные runbooks
- Бумажные копии всех критичных секретов в сейфе с procedure доступа доверенному лицу
- Автоматические алерты в Telegram бот соло-разработчика 24/7
- Long-term: найм 2-го разработчика как только бюджет позволит

### A3. Custodial wallet = регуляторный риск
В большинстве юрисдикций кастодиальное хранение крипты требует лицензии VASP/MSB.

**Mitigation:**
- Грузинская IE как первая юр.обёртка (1% налог, минимальные требования)
- Geo-блок US/UK/санкционные страны
- KYC для крупных выводов
- v1+: апгрейд до VARA/MiCA-compliant entity при росте

### A4. TON Center как единственный RPC-провайдер на старте
Если TON Center лежит — мы не видим депозитов и не можем отправлять выводы.

**Mitigation:**
- Резервный RPC (getblock.io) с автоматическим failover на v1+
- Своя TON-нода при достижении значимого объёма

### A5. Нет SOC 2 / pentest на MVP
**Mitigation:**
- Внешний security audit на v1 (после первой публики)
- Bug bounty программа на v1.x

---

## 5. Reporting vulnerabilities

**Если ты нашёл уязвимость в Way Of The King:**

- **НЕ публикуй её публично** до подтверждения фикса
- Напиши на security@wayoftheking.app (или @WOTK_security в Telegram)
- Опиши: затронутая компонента, шаги воспроизведения, потенциальный impact, твои контактные данные

**Bug bounty (после v1 launch):**
- Critical (RCE, wallet theft, mass account takeover): $1000–10000 в USDT
- High (single-account compromise, significant economy exploit): $200–1000
- Medium (logic bugs с monetary impact): $50–200
- Low (info leak без direct impact): $20–50

Acknowledgement: упоминание в Hall of Fame (если хочешь).

---

## 6. Security checklist по фазам

### Pre-MVP (now)
- [x] `.gitignore` блокирует все типы секретов
- [x] Pydantic validator для production secrets
- [x] Sentry с редакцией PII/secrets
- [x] CORS жёсткий allowlist
- [x] CSP в Caddyfile (production block)
- [x] Rate limiting infrastructure (slowapi)
- [x] HMAC с двумя секретами для Colyseus↔FastAPI
- [x] Dependabot
- [x] Non-root в Docker images
- [ ] HMAC-валидация Telegram initData (Phase 1, W1-020)
- [ ] JWT issue/verify (Phase 1, W1-021)

### Phase 7 (TON integration)
- [ ] HD wallet generator (derivation path computed from profile_id, not stored)
- [ ] Cold/hot split с reconciliation
- [ ] Withdrawal 2FA через бот (HMAC-SHA256 + pepper, BYTEA hash)
- [ ] Outbox pattern для TON-операций
- [ ] Treasury log + аудит cron + append-only triggers
- [ ] `TFA_PEPPER` в env / Docker secret, ротация при компрометации

### Pre-launch (Phase 8)
- [ ] External security review (фрилансер ~500$)
- [ ] Pentest hot wallet flow
- [ ] Геоблок проверен на реальных IP
- [ ] Бэкапы тестово восстановлены
- [ ] Runbook на инциденты написан и tested

### Post-MVP
- [ ] Bug bounty запущен
- [ ] pip-audit / npm audit в CI
- [ ] Cold wallet = hardware (Ledger)
- [ ] Multi-sig 2-of-3 для cold

---

## 7. References

- [OWASP Top 10 2023](https://owasp.org/Top10/)
- [OWASP API Security Top 10](https://owasp.org/API-Security/editions/2023/en/0x11-t10/)
- [Telegram Mini Apps — initData validation](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
- [TON Connect security](https://docs.ton.org/develop/dapps/ton-connect/overview)
- [Colyseus security best practices](https://docs.colyseus.io/server/room/#anti-cheat-and-security)

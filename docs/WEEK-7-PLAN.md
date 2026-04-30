# Week 7 — Outline

Версия: 0.1 (создано 2026-04-30)

Цель: **минимально жизнеспособная TON-интеграция на testnet** — пользователь может пополнить custodial wallet через TON deposit, и запросить withdraw обратно. Real money пока на testnet, mainnet — отдельно после security audit (Phase 8).

W7 — это первое касание реальных денег. **Любая ошибка здесь = потеря средств юзеров**, поэтому акцент на: server-side validation, idempotency, rate limits, audit logs, manual approval всех withdrawals в первую неделю.

## Что готово к старту W7

- ✅ Полный gameplay loop W6: campaign → enter → multi-floor → boss → drops → equip
- ✅ Internal HMAC infrastructure (Colyseus ↔ FastAPI) — может переиспользоваться для TON-listener ↔ FastAPI
- ✅ Idempotency middleware (payment-critical TTL 24h)
- ✅ `Balance` table + `Transaction` ledger с `balance_after` snapshot per row
- ✅ Reconciliation cron `reconcile_balances` (drift detection)
- ✅ Sentry + structlog + admin endpoints + metrics counter (W6)

## Что НЕ делается в W7

- Mainnet deploy (Phase 8 после security audit)
- Real liquidity на STON.fi (Phase 8)
- TonConnect для привязки внешних кошельков (Phase 8)
- 2FA через external authenticator app (используем простой TG-bot confirmation)
- Multi-currency (только TON + WOTK jetton, не USDT)
- DEX-интеграция / автоматические свопы

## Открытые вопросы (требуют решения до старта Day 1)

1. **HD wallet derivation path** — `m/44'/607'/account'/0/0` стандарт TON, но мы хотим per-profile sub-addresses. Решение: BIP44 с `account = profile.id` (uint32). Лимит 2^32 профилей (4B) — на ~10 лет хватит.
2. **Master mnemonic storage** — в `.env` в plain BIP39 24-word string, файл chmod 600, owner=wotk юзер. Для prod добавим Docker secrets (Phase 8). Семя backup'ится **офлайн на бумаге** — это критично, потеря = потеря всех средств юзеров.
3. **Jetton vs raw TON** — деплоим WOTK jetton (Blueprint в testnet) для будущей интеграции с DEX, но в первой итерации **принимаем только raw TON**, конвертация через в курс fix. Свой jetton как mint/burn только в W8+.
4. **Withdrawal manual approval** — в W7 каждый withdraw запрос блокируется в state `PENDING_APPROVAL` и ждёт ручного подтверждения через admin endpoint. Только после approval арr-задача отправляет TX. Auto-approve добавим после первой недели в проде.
5. **Минимальный/максимальный withdraw** — min 0.5 TON (gas + dust), max 100 TON в первый месяц (защита от sweep атаки если HD-key утечёт).

---

## День 1 (Пн ~10ч) — HD wallet + sub-address generation

* **W7-001** Установить TON SDK: `pytonlib` или `tonsdk` (питон) для derivation + signing. Версии — pinned в `pyproject.toml`. Изучить какой более активный (tonsdk последний релиз?).
* **W7-002** `backend/src/wotk/wallet/hd.py` (NEW) — `derive_address(profile_id: int) -> tuple[address: str, public_key: bytes]`. Pure function, master mnemonic из `Settings.ton_master_mnemonic`. Тестируется на known testnet seed.
* **W7-003** Migration `0010_wallet_addresses.py` (manual) — таблица `wallet_address`: `(profile_id PK, address TEXT UNIQUE, public_key BYTEA, derived_at TIMESTAMPTZ, last_seen_seqno BIGINT default 0)`. CHECK на формат TON address.
* **W7-004** `Wallet` SQLAlchemy model + `assign_wallet_to_profile(profile_id) -> WalletAddress` helper в `backend/src/wotk/wallet/service.py`. Идемпотентен — повторный вызов возвращает existing.
* **W7-005** Endpoint `GET /api/v1/me/wallet` — возвращает `{address, qr_url}`. Lazy creation при первом обращении (не на /auth/login — иначе дёргаем HD-derivation для всех юзеров включая ботов).
* **W7-006** Tests: derivation determinism (один seed + один profile_id → всегда тот же адрес), uniqueness (разные profile_id → разные адреса), assignment idempotency.
* **W7-007** Update `.env.example` + `docs/SECURITY.md` про master mnemonic backup procedure.

## День 2 (Вт ~10ч) — Testnet jetton + TON-listener skeleton

* **W7-010** Setup TON Blueprint workspace в `contracts/wotk-jetton/` — Tact или FunC скелет jetton minter. Деплой в testnet через `npx blueprint run`. Запись адреса в `.env`. *(Этот тикет blocking — всё последующее использует адрес.)*
* **W7-011** `backend/src/wotk/wallet/listener.py` — Redis-singleton с TTL-lock (5 min refresh). При старте — load `last_seen_seqno` из state, polled каждые 10s через TON HTTP API (testnet endpoint).
* **W7-012** Внутренний endpoint `POST /api/v1/internal/wallet/deposit-detected` — HMAC-protected (новый секрет `INTERNAL_HMAC_LISTENER_TO_API`), body `{profile_id, ton_amount_nanoton, tx_hash, lt}`. Валидирует tx_hash uniqueness, кредитит gold (по фикс-курсу `TON_TO_GOLD_RATE` из config), создаёт `Transaction(TON_DEPOSIT)` + `Wallet.last_seen_seqno`.
* **W7-013** `Transaction.type` enum: добавить `TON_DEPOSIT = 5`, `TON_WITHDRAW = 6`, `TON_FEE = 7`. Migration `0011_tx_types.py` обновляет CHECK constraint.
* **W7-014** `WithdrawalRequest` table + model: `(id UUID PK, profile_id, ton_amount_nanoton, destination_address, status PENDING_APPROVAL/APPROVED/SENT/FAILED, requested_at, approved_at NULL, sent_at NULL, tx_hash NULL, error TEXT NULL)`. Migration `0012_withdrawals.py`.
* **W7-015** Tests: HMAC verify deposit endpoint, duplicate tx_hash → 409, gold credited correctly, listener-singleton lock acquisition.

## День 3 (Ср ~10ч) — Withdrawal flow

* **W7-020** Endpoint `POST /api/v1/me/wallet/withdraw` — body `{ton_amount: int (nanoton), destination_address: str}`. Валидирует: `ton_amount >= MIN_WITHDRAW_NANOTON`, `<= MAX_WITHDRAW_NANOTON`, balance.gold >= equivalent gold (по `TON_TO_GOLD_RATE`), TON address format. INSERT WithdrawalRequest со status=PENDING_APPROVAL. Дебитит gold immediately (и создаёт Transaction(TON_WITHDRAW, -gold)). Идемпотентность через `Idempotency-Key` обязателен.
* **W7-021** Endpoint `POST /api/v1/admin/withdrawals/{id}/approve` — admin-only. Меняет статус PENDING_APPROVAL → APPROVED + ставит approved_at. Enqueue arq job `send_withdrawal(withdrawal_id)`.
* **W7-022** Arq job `send_withdrawal(withdrawal_id)` — читает WithdrawalRequest, signs TON tx через HD derived key, sends, обновляет `tx_hash` + `sent_at` + status=SENT. При network error → status=FAILED + error message (manual retry через admin endpoint).
* **W7-023** Endpoint `GET /api/v1/me/wallet/transactions` — paginated history с фильтром по type (TON_DEPOSIT/TON_WITHDRAW). Возвращает `[{id, type, amount, balance_after, ts, ton_tx_hash | null, withdrawal_status | null}]`.
* **W7-024** Bot `/wallet` команда (aiogram): отвечает `/me/wallet` info + `/me/wallet/transactions` last 5. Простой fmt текстом.
* **W7-025** Tests: withdraw debit + UPSERT withdrawal, balance check on withdraw, idempotency, admin approval flow, send_withdrawal job mock TON SDK.

## День 4 (Чт ~8ч) — Frontend wallet screen

* **W7-030** `frontend/src/api/wallet.ts` — `getWallet()`, `requestWithdraw(amount, address, idemKey)`, `getWalletTransactions(offset, limit)`.
* **W7-031** `frontend/src/screens/Wallet.tsx` — экран с двумя tab'ами: **Deposit** (показывает address + QR-кнопка copy) и **Withdraw** (форма amount + destination + "Запросить вывод" button + список pending withdrawals).
* **W7-032** QR-генерация через библиотеку `qrcode` (npm), inline SVG.
* **W7-033** TonConnect placeholder button — пока заглушка "Coming soon", чтобы UI был готов под Phase 8 интеграцию.
* **W7-034** Wire в City.tsx — "Кошелёк" button становится active (вместо `coming_soon`).
* **W7-035** I18n keys: `wallet.deposit_title`, `wallet.withdraw_title`, `wallet.copy_address`, `wallet.amount_ton`, `wallet.destination`, `wallet.submit_withdraw`, `wallet.pending`, `wallet.approved`, `wallet.sent`, `wallet.failed`, `wallet.min_amount`, `wallet.max_amount`, `wallet.invalid_address`. RU + EN.

## День 5 (Пт ~8ч) — Reliability + reconciliation

* **W7-040** Cron `reconcile_wallet_balances` (every 5 min, offset от существующих cron'ов): сверка `Wallet.last_seen_seqno` против актуального TON HTTP API; если listener завис, log CRITICAL.
* **W7-041** Cron `retry_failed_withdrawals` (every 30 min) — для каждого FAILED, если age < 24h И error != "insufficient_master_balance" → reset to APPROVED, re-enqueue send_withdrawal. Limit 3 retries (track в WithdrawalRequest.retry_count).
* **W7-042** Sentry breadcrumbs для wallet ops: deposit_detected, withdraw_requested, withdraw_approved, withdraw_sent, withdraw_failed.
* **W7-043** Metrics counters: `ton_deposit_total{}`, `ton_withdraw_total{status}`, `ton_listener_polls_total{}`, `ton_listener_errors_total{kind}`. Wire в существующий `metrics.py`.
* **W7-044** Hard rate limits через slowapi: POST /me/wallet/withdraw → 5 per 24h per profile. Manual override через admin (W8).
* **W7-045** Master-balance monitoring: cron `check_hot_wallet_balance` — если balance HD-master < 50 TON → CRITICAL log + Sentry alert (нечем платить withdrawals).

## День 6 (Сб ~8ч) — Security hardening

* **W7-050** **Audit endpoint** `GET /api/v1/admin/wallet/audit` — admin-only — возвращает `{total_deposits_ton, total_withdraws_ton, hot_wallet_balance_ton, pending_withdrawals_count, recent_anomalies}`. Anomaly = withdraw amount > 90th percentile of last 100 withdraws ИЛИ deposit < 0.1 TON (dust attack).
* **W7-051** **Withdrawal address blacklist** — таблица `wallet_blacklist (address, reason, added_at, added_by)` + check в /me/wallet/withdraw → 403 если destination в blacklist.
* **W7-052** **Rate limit per address**: `POST /me/wallet/withdraw` → max 3 withdrawals per destination_address per 24h (защита от sweep при compromised account).
* **W7-053** **HMAC rotation runbook** — `docs/SECURITY.md` секция про smooth rotation `INTERNAL_HMAC_LISTENER_TO_API` (dual-key window 24h).
* **W7-054** **Penetration test checklist** в `docs/SECURITY.md` — список ручных проверок перед mainnet: replay deposit, withdraw to own address loop, integer overflow на amount, race на approve+send.

## День 7 (Вс ~6ч) — Testnet E2E + W8 plan

* **W7-060** Testnet E2E smoke: новый профиль → /me/wallet → копировать address → отправить 1 testnet TON через @testgiverbot → wait 60s → /me/wallet/transactions показывает deposit → balance.gold кредитнут → request withdraw 0.5 TON → admin approve → tx отправлена → balance уменьшен корректно.
* **W7-061** Bug fixes из W7-060.
* **W7-062** Performance: TON-listener latency p99 < 30s от detect до credit.
* **W7-063** WEEK-8-PLAN.md outline: Phase 8 mainnet deploy + STON.fi liquidity + TonConnect + closed beta launch.

## Acceptance criteria недели

- ✅ Custodial HD wallet работает на testnet
- ✅ Deposit detection + atomic gold credit
- ✅ Withdrawal request → admin approve → testnet TX отправлена
- ✅ Frontend Wallet screen полностью функционален
- ✅ Backend tests: ≥360 (было 331 + ~30 на wallet/withdraw flows)
- ✅ Master mnemonic backup procedure задокументирована
- ✅ Все wallet endpoints rate-limited + audit-logged

## Риски

| Риск | Митигация |
|---|---|
| HD-master mnemonic утекает (env, git history, log) | `.env` в .gitignore (есть), `chmod 600`, никогда не log'ируем mnemonic. Master backup офлайн на бумаге + 2-of-3 sealed envelopes на доверенных людей. |
| TON-listener double-credit одного deposit (race на restart) | `Transaction.ref->>'tx_hash'` UNIQUE INDEX + INSERT-ON-CONFLICT с `assert rowcount > 0` для идемпотентности. |
| User указывает destination = exchange address без memo → потеря средств | Frontend warning "Адреса бирж требуют MEMO — не поддерживается"; admin approval — last line of defense. |
| Withdrawal-spam DoS опустошает hot wallet за минуты | Per-profile rate limit (5/24h, W7-044), per-address limit (3/24h, W7-052), max 100 TON / withdraw, hot wallet balance alert (W7-045). |
| Listener зависает (network drop) → deposits не credit'ятся часами | reconcile_wallet_balances cron детектит drift между Wallet.last_seen_seqno и actual API; если delta > N blocks → CRITICAL Sentry. |
| Race между withdraw debit и concurrent dungeon entry — баланс уходит в minus | `with_for_update()` lock на Balance row уже есть в /enter; добавить same в withdraw handler. CHECK gold ≥ 0 на DB-уровне (надо проверить — если нет, добавить в migration). |
| Testnet ≠ mainnet — баг проявится только под реальной нагрузкой | W8 — closed beta с whitelisted адресов на mainnet перед public launch. |

## Дополнительные заметки

- В W7 **не подключаемся к real TON Foundation grant** — заявка отдельно после mainnet smoke (Phase 8).
- Не используем TonConnect в первой итерации — простой "введи адрес" UX для withdraw.
- Не делаем mint/burn своего jetton — gold↔TON по fix-курсу (`TON_TO_GOLD_RATE` в config). Курс reviewable раз в день admin'ом.
- **Reset перед W8 mainnet:** все testnet withdrawals → SENT в логи + cleanup, hot wallet drain to test pool, повторный smoke на staging mainnet (если бюджет позволит).

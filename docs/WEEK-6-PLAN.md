# Week 6 — Outline

Версия: 0.1 (создано 2026-04-30)

Цель: **полный playable dungeon с прогрессией** — multi-floor advance + boss-encounter в финале + persistent campaign-progress + post-run reward summary.

W6 строится поверх W5 (single-floor combat + drops + finalize). К концу недели один dungeon-run = пройти N этажей подряд → убить босса → вернуться с лучшим лутом → видеть прогресс кампании в City.

## Что готово к старту W6

- ✅ DungeonRoom + WorldState + mob spawn (W5 Day 1)
- ✅ AI FSM (idle / chase / attack) + A* pathfinding (W5 Day 2)
- ✅ Combat damage / skills / cooldowns / status effects (W5 Day 3)
- ✅ Drops + materialize_item via HMAC finalize callback + escrow auto-claim (W5 Day 4)
- ✅ Frontend hotbar + tap-to-cast + damage numbers + death screen (W5 Day 5)
- ✅ Loot icons + long-press menu + compare tooltip + new-item badge (W5 Day 6)
- ✅ DB готова: `dungeon_runs.current_floor`, `Dungeon.floors_count`, `Dungeon.config` JSONB, `campaign_progress`

## Что НЕ делается в W6

- TON / wallet (Phase 7)
- PvP / market (postMVP)
- Real LPC sprites / Tiled JSON (assets-blocked)
- Production deploy (отдельный трек)
- Other classes (Mage / Ranger — postMVP)
- Loot crafting / salvage rewards (W7+ candidate)

---

## День 1 (Пн ~8ч) — Multi-floor server logic

* **W6-001** `DungeonRoom` читает `dungeon.config['floors']` (list of FloorConfig: `{walls, mob_pack_ids, spawn_points}`) при `onCreate` и сохраняет полный план run'а в room state. Source-of-truth — Dungeon.config JSONB; фронт ничего не знает про следующий floor пока не advance'нул.
* **W6-002** `room.send('next_floor')` от player'а после clearing текущего → server валидирует "все мобы мертвы" → инкремент `current_floor` в DungeonRun + transition в state + спавн нового encounter'а из FloorConfig.
* **W6-003** Per-floor `RunEncounter` row пишется при transition (а не один на run); combat_summary v1 расширяется per-floor accumulator'ом в `CombatLog`.
* **W6-004** Auto-checkpoint `last_checkpoint_at = now()` при transition — даёт `cleanup_expired_runs` корректно сейвить прогресс.
* **W6-005** Tests: 3-floor dungeon — enter / clear-floor-1 / advance / clear-floor-2 / advance / boss-clear / finalize → DB inspect: 3 RunEncounter rows + correct accumulated gold/xp.

## День 2 (Вт ~8ч) — Boss encounter

* **W6-010** New mob category `BOSS` в `mobs.py` (Python + TS mirror): hp ×8, damage ×2, custom telegraph window перед AOE (slow signal, 1s charge → AOE strike).
* **W6-011** Boss-only AI hooks: `enrage_threshold` (HP < 30% → +50% attack speed); `summon_adds` ability (раз в 20s спавнит 2 minion'а — re-uses existing spawn_encounter).
* **W6-012** Final-floor flag в FloorConfig: `{is_boss_floor: true, boss_id: 'crypt_lich'}` → DungeonRoom спавнит только boss instance + arena geometry.
* **W6-013** Drops для boss: гарантированный rare+ + 2× gold (через `drops.py` boss-multiplier параметр в `KillRewards`).
* **W6-014** Boss death = run COMPLETED triggered explicitly (не дожидаемся room dispose); `room.disconnect()` после finalize callback.
* **W6-015** Tests: TDD на boss damage table + AI enrage transition + summon trigger; integration test full boss kill → run.status COMPLETED + drop verification.

## День 3 (Ср ~8ч) — Campaign progression

* **W6-020** Mapping `dungeon_id → (act, location)`: `Dungeon` таблица расширяется `act INT`, `location INT` колонками (NULL для tutorial); миграция `0009_dungeon_campaign_meta.py` (manual).
* **W6-021** При finalize COMPLETED: UPSERT в `campaign_progress` (hero_id, act, location); первый успех проставляет `first_completed_at`, последующие инкрементят `completion_count` + обновляют `best_clear_time_s`.
* **W6-022** GET `/me/campaign` endpoint — возвращает `[{act, location, completion_count, best_clear_time_s, is_locked}]`. Locked-логика: location N+1 разлочена если location N completion_count ≥ 1.
* **W6-023** Frontend Campaign screen (`screens/Campaign.tsx`): grid 5 acts × 10 locations с состояниями (locked / available / completed / mastered) — заменяет текущий direct-jump в Playground.
* **W6-024** Frontend: Playground `dungeonItems` фильтруется по unlocked locations (locked dungeons показывает greyed + tooltip "complete prev location").
* **W6-025** I18n: act names (`act.1.name = "Crypt of Forgotten Kings"`), location names (`location.1.1.name = "Burial Chamber"`) — RU + EN.

## День 4 (Чт ~8ч) — Post-run summary + UX polish

* **W6-030** Finalize response payload: вместо тонкого `{status: 'completed'}` отдать `RunSummaryDTO {gold_earned, xp_earned, items: [ItemDTO], floors_cleared, duration_s, boss_killed: bool}`.
* **W6-031** Frontend `RunSummaryScreen.tsx` — full-screen overlay при completed/abandoned: список лута с rarity colors + numbers + кнопка "Continue → City".
* **W6-032** Death screen v2 — показать summary партиал (что успели собрать в escrow перед смертью) + revive option (W7 placeholder, button disabled).
* **W6-033** "Floor cleared" toast/animation между advance'ами (1.5s overlay "Floor 2 / 5").
* **W6-034** XP bar анимация на City hero summary при возврате — interpolated from old → new XP, "level up!" sparkle если перешёл порог.
* **W6-035** I18n: все summary keys + level-up message + floor-clear messages.

## День 5 (Пт ~8ч) — W5 follow-ups + drop polish

* **W6-040** Pass last-known mob position через `onMobRemove` в realtime.ts (W5 Day 6 follow-up; уже есть workaround через mobPositionsRef в Playground).
* **W6-041** Loot icon click → backend `POST /runs/{id}/pickup/{mob_kill_idx}` для escrow-claim в реальном времени (вместо batch на finalize). Сейчас pickup чисто visual; превратить в real handle. Альтернатива: оставить как есть и закрыть как "out of scope".
* **W6-042** CSS pass: hotbar / damage-numbers / death-screen / loot-icons / longpress-menu / compare-tooltip / nav-badge — все BEM-классы из W5 без стилей. Либо single `playground.css`+`combat.css`+`inventory-ext.css`, либо inline под уже существующий styles/index.css.
* **W6-043** Hotbar `playSfx('skill_cast')` per-skill дифференциация (cleave / shield_bash / whirlwind / charge — каждый свой sfx id, реальные пакеты позже).
* **W6-044** Mob death: gore-particle placeholder в Pixi (8 короткоживущих circle'ов).
* **W6-045** Knight idle/walk-cycle через простую sprite-sheet sub-rect анимацию (если есть placeholder spritesheet) — иначе skip и keep circle.

## День 6 (Сб ~6ч) — Reliability + telemetry

* **W6-050** Структурированный лог finalize event (already partial; extend with floor-by-floor breakdown + boss flag).
* **W6-051** Sentry breadcrumb на каждый floor advance + boss summon + critical death — для voodoo bug reports.
* **W6-052** Metric counter (Prometheus-ready): `dungeon_completed_total{dungeon_id, difficulty}`, `dungeon_abandoned_total`, `boss_killed_total`. Хранить in-process; expose через `/metrics` endpoint (W7 переедет в Prometheus).
* **W6-053** Replay-запрос: `GET /admin/runs/{id}/encounters` (admin-only) возвращает `RunEncounter` JSON для воспроизведения. Поверх существующей admin-auth.
* **W6-054** Cleanup_expired_runs учитывает `current_floor > 0` — при ABANDON отдаём 50% items в escrow (RUN-LIFECYCLE.md §6 политика, W5 deferred).

## День 7 (Вс ~6ч) — E2E + W7 plan

* **W6-060** End-to-end: enter Crypt Normal → clear floor 1 → advance → clear floor 2 → boss kill → finalize → check campaign_progress UPSERT + RunSummary correct + new item in inventory + level-up animation visible.
* **W6-061** Performance: 60 FPS при boss + 4 minion'а + AOE telegraph + damage numbers spam — profile Pixi ticker, оптимизировать text-pool если нужно.
* **W6-062** Bug fixes из E2E.
* **W6-063** WEEK-7-PLAN.md: класс Mage (вторая playable class) ИЛИ wallet/TON foundation — выбрать на основе MVP-priorities review.

## Acceptance criteria недели

- ✅ Multi-floor dungeon: 3-5 этажей в Crypt Normal с advance между ними
- ✅ Boss-floor работает (Crypt Lich, hp ~600, gear-check)
- ✅ Campaign screen показывает прогресс по 5 actам × 10 locations с lock-логикой
- ✅ RunSummary с лутом / xp / gold показывается после run'а
- ✅ Backend tests: ≥320 (было 286 + ~30 на multi-floor + boss + campaign)
- ✅ Realtime tests: ≥130 (было 120 + ~10 boss AI)
- ✅ E2E playable: новый игрок проходит первый act'а тутурьела до первого боса

## Риски

| Риск | Митигация |
|---|---|
| Boss balance: либо oneshot-killable либо unkillable за 5 минут | Табличный TDD damage-table + manual playtest 30 минут перед merge'ем; стандарт = ~90s boss fight на equipped-Knight ровного уровня |
| Multi-floor state дрейф при network drop между floor'ами | Auto-checkpoint W6-004 + cleanup_expired_runs корректно подхватит; reconnect к существующей room.run_id (не новый /enter) |
| Campaign UI grid 50 cells на mobile в TG WebApp — viewport mess | Compact horizontal-scroll act-by-act (5 vertical strips), не 5×10 grid |
| Replay/admin endpoint показывает PII | Admin-only middleware + redact profile_id → hash в response (already standard pattern) |
| Visual loot icon ≠ actual rarity (server roll) → user confused | Либо синхронизировать rarity hint от server'а до finalize (extra packet), либо честный disclaimer в UI ("preview, real reward at finish") |

## Открытые вопросы (требуют решения до старта дня)

1. **Floor transition trigger**: автоматический (когда последний моб убит) ИЛИ player'у надо тапнуть exit-portal? Player-controlled даёт breathing room, autotrigger даёт flow.
2. **Boss death без full-clear**: если бос умер а minion'ы живы — run COMPLETED или ждём clear minion'ов? Diablo-style: бос = win, minion'ы despawn.
3. **Pickup-on-tap (W6-041)** — closing W5 visual mock или скоупим в W7? Решение: skip, оставить как visual-only.
4. **Campaign locking**: completion_count ≥ 1 unlock'ит next location ИЛИ нужен min hero_level ИЛИ "key item"-system? Простейшее = completion_count, выбираем для MVP.

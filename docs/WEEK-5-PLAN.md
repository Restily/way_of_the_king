# Week 5 — Outline

Версия: 0.1 (создано 2026-04-29)
Цель: **первый полный playable loop** — войти в данж → бить мобов → собрать лут → выйти → надеть → снова войти сильнее.

W5 — это первый week когда **combat-формулы из W4 (pure functions) запускаются в Colyseus DungeonRoom**, а **drops материализуются в `item` table через `loot_db.materialize_item`** при kill моба.

## Что готово к старту W5

- ✅ §6 + §8 миграции (item / dungeon_run / run_encounters / daily_dungeon_entries)
- ✅ Combat pure functions: damage / cooldowns / skills (Knight 4 active) / status / drops
- ✅ AI FSM: idle → chase → attack → return; A* pathfinding; spawn_encounter
- ✅ Inventory backend (GET / equip / unequip)
- ✅ Hero combat-stats с equipped items + GET /me/combat-stats
- ✅ Colyseus DungeonRoom + WorldState + ws_token JWT + server-side collision (W3-fix)
- ✅ Frontend client prediction + dev-overlay (W3-043/044)
- ✅ /health/ready extended + structlog request duration (W3-052/053)
- ✅ Reconciliation cron + cleanup_expired_runs (W3-050/051)
- ✅ Combat log дизайн (`combat_log.py`) — серилизация в `run_encounters.combat_summary` JSONB

## Что НЕ делается в W5

- TON / wallet (Phase 7)
- PvP / маркет (постMVP)
- Real LPC sprites / Tiled JSON loader (assets-blocked)
- Production deploy (отложено отдельным треком)
- Сложный AI (flee, ranged kiting и т.п. — Phase 6)

---

## День 1 (Пн ~8ч) — Mob entities в WorldState

* **W5-001** Расширить `WorldState` schema: `mobs: MapSchema<Mob>` (id, type, x, y, hp, maxHp, state, target_session_id?)
* **W5-002** Spawn-on-floor-start: при onJoin (или при advance to next floor) DungeonRoom вызывает `spawn_encounter(rng, dungeon.config, floor, encounter_idx, spawn_positions)` (через FastAPI `/internal` GET endpoint OR pre-loaded в state)
* **W5-003** Mob HP/state в Colyseus — авто-broadcast через Schema diff
* **W5-004** Frontend: render mobs в Pixi (placeholder cubes разного цвета per mob type) с HP-bar над спрайтом
* **W5-005** Tests: Colyseus DungeonRoom с заспавненными мобами, multi-tick симуляция

## День 2 (Вт ~8ч) — AI FSM в realtime tick

* **W5-010** Colyseus tick вызывает `step_ai(mob, nearest_player, now_ms)` для каждого моба → применяет AIAction
* **W5-011** Mob movement через server tick (server-authoritative)
* **W5-012** Targeting: nearest player по позиции (для multi-player в комнате)
* **W5-013** A* pathfinding integration: при chase'е не в LoS — через `find_path()`, кешировать на N tick'ов
* **W5-014** Tests: integration test full encounter (player подходит → mob detect → chase → attack)

## День 3 (Ср ~10ч) — Combat: damage + skills

* **W5-020** Skill cast от player'а: client отправляет `room.send('cast', {skill_id, target_x, target_y})`
* **W5-021** Server: `skill_cast.resolve_cast` → list of hit mobs → `combat.compute_damage` для каждого → mob.hp -=
* **W5-022** Mob attack от FSM: при `AIAction kind=attack` → `compute_damage` против player.hp в state
* **W5-023** Status effects (stun/slow) применяются и тикают per server tick
* **W5-024** CooldownTracker per player + per mob — server enforces (client может отображать UI cooldowns локально)
* **W5-025** Tests: TDD на каждый Knight skill в realtime context

## День 4 (Чт ~10ч) — Drops + loot persistence + finalize

* **W5-030** Mob death: `on_mob_killed(rng, mob_def, hero_level, affix_pool, base_id, base_slot)` → `KillRewards`
* **W5-031** Loot pickup: при death моба auto-rolled item материализуется через `loot_db.materialize_item(escrow_run_id=run.id)`
* **W5-032** XP/gold accumulator в `dungeon_run.pending_gold` + `hero.xp += rewards.xp_gained`
* **W5-033** **HMAC callback** Colyseus → FastAPI `/internal/runs/{id}/finalize` с realистичным combat_summary (через `CombatLog.to_summary`)
* **W5-034** При finalize COMPLETED: `transaction(DUNGEON_REWARD)` + `daily_dungeon_entries` (уже работает); items в escrow_run переходят в inventory (auto-claim или wait for manual /claim — выбрать политику)
* **W5-035** Tests: full flow login → enter → kill 3 mobs → finalize COMPLETED → verify item rows + xp + gold

## День 5 (Пт ~10ч) — Frontend combat UX

* **W5-040** Skill hotbar (4 slots) с CD-визуализацией (radial mask)
* **W5-041** Tap target → cast (single-target skills) / tap on ground для AoE
* **W5-042** Damage numbers всплывающие от mob position (Pixi text)
* **W5-043** HP bar над heroes / mobs
* **W5-044** Death screen: hero died → return to City с reward summary (если успел собрать)
* **W5-045** I18n keys для skills/mobs

## День 6 (Сб ~8ч) — Inventory polish + drop UX

* **W5-050** При kill моба — visual loot drop в Pixi (icon на полу) до auto-pickup OR manual click
* **W5-051** Inventory bag прокачать: drag-and-drop OR long-press menu (compare + equip + salvage)
* **W5-052** Item compare tooltip (сравнение equipped vs inventory)
* **W5-053** "New item" badge над City Inventory button после возврата из data
* **W5-054** Sound effects placeholder (silent triggers — sound packs в W6+)

## День 7 (Вс ~6ч) — E2E + W6 plan

* **W5-060** End-to-end smoke: enter Crypt Normal → kill 5 mobs → settle → equip best drop → re-enter с буст stats
* **W5-061** Performance pass: 60 FPS при 5+ mobs + AoE skill effects
* **W5-062** Bug fixes
* **W5-063** WEEK-6-PLAN.md: campaign progression + multi-floor data + boss fights

## Acceptance criteria недели

- ✅ Knight в Crypt Normal убивает мобов через server-authoritative combat
- ✅ XP / gold / items начисляются после finalize
- ✅ Equip нового item меняет combat-stats и заметно усиливает следующий run
- ✅ Backend tests: ≥330 (было 282, +50 на realtime combat + drops integration)
- ✅ E2E playable loop работает на dev-стенде

## Риски

| Риск | Митигация |
|---|---|
| Combat balance в первом приближении убивает игрока за 3 удара / даёт 1HP-боссу | TDD с табличными ожиданиями, не доверяем ощущениям |
| AI pathfinding медленный при N>10 мобов одновременно | Кеш blocked-set по hash(walls); pathfind вызывается реже attack rate |
| Schema diff broadcast > 60Hz перегружает WS на mid-range Android | DungeonRoom 20Hz tick — Colyseus коалесцирует diffs автоматически; flag latency overlay (W3-044) |
| Server crash во время encounter → потеря loot escrow | Cleanup_expired_runs (W3-051) переводит в ABANDONED, политика "50% items в inventory" из RUN-LIFECYCLE.md §6 — реализуется в W5-034 |
| Lag → server reconcile snap слишком резкий | TELEPORT_THRESHOLD=30px уже в scene.ts, можно подкрутить |

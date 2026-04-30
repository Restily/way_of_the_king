# Week 4 — Тикеты

Версия: 0.1 (создано 2026-04-28)
Период: 7 дней, ~60 рабочих часов
Цель недели:
1. **Combat foundation (pure)** — damage formulas + crit + resistances + cooldowns как pure functions с TDD. Phase 4 в ROADMAP, но реализуем без realtime — чтобы не блокироваться на Colyseus.
2. **Mob entities + AI state machine** — 3 типа мобов (Skeleton Warrior/Archer, Zombie), FSM (idle→patrol→detect→chase→attack→return), pathfinding по grid через A*.
3. **Skill system (Knight 4 active)** — `cleave`, `shield_bash`, `whirlwind`, `charge` с cooldowns + cost + AoE/single-target distinction.
4. **Inventory endpoints** — `GET /inventory`, `POST /items/{id}/equip`, `POST /items/{id}/unequip` + frontend грид-экран.

Каждый тикет:
- **AC** / **Estimate** / **Dependencies** / **Status**

## Что готово к началу W4 (фундамент)

- ✅ §1-§8 + §11.2 миграции применены (profile/balance/hero/transaction/idempotency/items/affixes/dungeons + run_encounters/daily_dungeon_entries/campaign_progress)
- ✅ loot.py (PoE-style affix gen) + loot_db.py adapter
- ✅ Seed-данные: 10 base + 33 affixes + 6 dungeons
- ✅ Idempotency middleware + Arq cron worker + structlog JSON + Sentry request_id
- ✅ Pixi placeholder сцена с движением + collision + camera
- ✅ Stats formulas каркас ([wotk/game/stats.py](../backend/src/wotk/game/stats.py)) и leveling ([wotk/game/leveling.py](../backend/src/wotk/game/leveling.py))
- ✅ 156/156 тестов зелёные

## Что НЕ делается на 4-й неделе (защита скоупа)

- Colyseus realtime layer (Phase 3, W3 days 4-5 — отложено до появления prod-инфры или решения о реализации без prod)
- Real LPC sprites / Tiled JSON (нет assets — combat работает через placeholder shapes)
- Inventory UI с drag-and-drop (W4 — basic grid + click-to-equip)
- PvP / market / TON (постMVP)
- Full encounter spawning в realtime (combat механики purely server-side, без realtime broadcast в W4)

---

## День 1 (Пн) — Combat formulas (pure) (~8ч)

### W4-001 — Damage calculation pure function `TODO`
- `wotk/game/combat.py` — `compute_damage(attacker_stats, defender_stats, skill, rng) -> DamageResult`
- Учитывает: `attacker.atk * skill.dmg_multiplier`, mitigation `defender.def`, crit roll (`rng < attacker.crit_chance` → ×`attacker.crit_dmg`), resistance type-specific
- Возвращает `DamageResult{raw, mitigated, was_crit, was_dodged}`
- **AC:** ≥10 unit-тестов: zero-stats baseline, full-mitigation (defender.def >= raw), crit applied, dodge skips damage entirely
- **Estimate:** 2.5ч

### W4-002 — Resistance system + damage types `TODO`
- `class DamageType(IntEnum)`: PHYSICAL=0, FIRE=1, COLD=2, LIGHTNING=3, POISON=4
- Добавить в `DerivedStats`: `resist_phys/fire/cold/lightning/poison: int` (% reduction, capped at 75)
- compute_damage применяет resistance ПОСЛЕ defense mitigation (multiplicative)
- **AC:** unit-тесты: 0% resist = full damage, 50% = halved, 75% = quartered, >75% всё равно 75% (cap)
- **Estimate:** 1.5ч
- **Dependencies:** W4-001

### W4-003 — Cooldown / cost ticking system `TODO`
- `wotk/game/cooldowns.py` — `CooldownTracker` class с методами:
  - `try_cast(skill_id, current_time_ms) -> bool` (returns True если skill готов и сразу ставит на CD)
  - `remaining_ms(skill_id, current_time_ms) -> int`
  - `tick(now_ms)` — no-op (CD проверяется через delta), но nice for batching
- Mana cost validation отдельно — caller проверяет mana >= cost перед try_cast
- **AC:** ≥5 тестов: казт когда CD=0 → True, второй казт сразу → False, через CD → True снова
- **Estimate:** 2ч

### W4-004 — Knight skill definitions `TODO`
- `wotk/game/skills.py`:
  - `class SkillDef(frozen dataclass)`: id, name_key, mana_cost, cooldown_ms, dmg_multiplier, range, aoe_radius (0=single), animation_ms, damage_type
  - `KNIGHT_SKILLS: dict[str, SkillDef]`:
    - `cleave` (free CD 800ms, 1.2× dmg, 60° AoE 100px range, PHYS)
    - `shield_bash` (CD 6s, 1.5× dmg + stun 1s, single target 80px, PHYS)
    - `whirlwind` (mana 30, CD 12s, 0.8× dmg ×3 ticks, 360° AoE 120px, PHYS)
    - `charge` (mana 20, CD 8s, 2.0× dmg + dash 200px, single target, PHYS)
- **AC:** dict импортируется, все 4 ключа есть в default `hero.active_skills`
- **Estimate:** 1ч

### W4-005 — Combat tests covering all skills `TODO`
- `tests/test_combat.py` — табличные тесты: для каждого skill × (без crit / с crit / с resist) → expected damage в пределах ±10%
- Property-based test через `hypothesis`: для случайных stats invariant `damage >= 0` всегда
- **AC:** ≥15 тестов, ≥90% coverage `combat.py` + `cooldowns.py` + `skills.py`
- **Estimate:** 1ч
- **Dependencies:** W4-001..W4-004

---

## День 2 (Вт) — Mob entities + AI state machine (~10ч)

### W4-010 — `MobDef` registry (3 типа) `TODO`
- `wotk/game/mobs.py`:
  - `class MobDef(frozen)`: id, name_key, base_hp, base_atk, base_def, move_speed, detect_radius, attack_range, attack_cooldown_ms, xp_drop, gold_drop_range
  - `MOBS: dict[str, MobDef]`:
    - `skeleton_warrior` (HP 50, ATK 8, DEF 2, melee, range 30)
    - `skeleton_archer` (HP 35, ATK 12, DEF 1, ranged, range 200, slower attack)
    - `zombie` (HP 90, ATK 6, DEF 4, melee tank, slow move)
- **AC:** dict импортируется, ≥3 mob defs, все поля заполнены
- **Estimate:** 1ч

### W4-011 — AI state machine (FSM) `TODO`
- `wotk/game/ai.py`:
  - `class AIState(IntEnum)`: IDLE, PATROL, DETECT, CHASE, ATTACK, RETURN, DEAD
  - `class MobInstance`: position, hp, state, target_player_id, last_attack_at, spawn_position
  - `def step_ai(mob, world, now_ms) -> AIAction`:
    - IDLE → если player в detect_radius → DETECT
    - DETECT → CHASE
    - CHASE → если player в attack_range → ATTACK; если player вне 2× detect_radius → RETURN
    - ATTACK → если cooldown готов → выпустить attack action; CHASE если player ушёл
    - RETURN → дойти до spawn → IDLE
- `AIAction` — typed union: `Move(dx, dy) | Attack(target_id) | Idle()`
- Pure function — все state changes возвращаются caller'ом, не мутируют mob внутри (для testability)
- **AC:** ≥10 тестов с табличной FSM-проверкой: для каждой пары (current_state, world_condition) → expected next_state + action
- **Estimate:** 3ч
- **Dependencies:** W4-010

### W4-012 — Grid pathfinding (A*) `TODO`
- `wotk/game/pathfind.py`:
  - `def find_path(start: Vec2, goal: Vec2, walls: list[Rect], grid_size: int = 32) -> list[Vec2]`
  - Простая A* реализация по grid'у, heuristic = Manhattan distance
  - Walls конвертируются в blocked-cells
  - Возвращает список waypoint'ов (или пустой если path не найден)
- **AC:** unit-тесты: прямой путь без преград (Manhattan), путь вокруг колонны, недостижимая цель → []
- **Estimate:** 2.5ч

### W4-013 — Spawn system (encounter generation) `TODO`
- `wotk/game/spawn.py`:
  - `def spawn_encounter(rng, dungeon_config, floor, encounter_idx) -> list[MobInstance]`
  - Читает loot_table из dungeon.config, генерирует mob roster
  - Spawn positions из room layout (placeholder — равномерный grid)
- **AC:** detеrministic per (rng_seed, floor, idx); ≥3 mob по encounter; mob types из MOBS registry
- **Estimate:** 1.5ч
- **Dependencies:** W4-010

### W4-014 — AI integration test через mob+player loop `TODO`
- `tests/test_ai_integration.py`: симуляция 100 ticks
  - Spawn 1 zombie + 1 player в room
  - Player двигается к моба
  - Mob detects → chases → attacks → player HP падает
  - Если player отходит за 2× detect_radius → mob уходит в RETURN
- **AC:** end-to-end сценарий проходит, все state transitions ожидаемые
- **Estimate:** 2ч
- **Dependencies:** W4-011, W4-012

---

## День 3 (Ср) — Skill execution + status effects (~8ч)

### W4-020 — Skill cast resolution `TODO`
- `wotk/game/skill_cast.py` — `def resolve_cast(caster, skill, target_pos, world) -> CastResult`
- AoE: возвращает list[entity_id] в radius
- Single-target: возвращает [target_id] если в range
- За пределами range → CastResult(success=False, reason="out_of_range")
- **AC:** ≥10 тестов на каждый Knight skill: cleave hits 2 mobs in cone, whirlwind hits 5 in 360° circle, charge dashes player position
- **Estimate:** 3ч
- **Dependencies:** W4-001, W4-004

### W4-021 — Status effects system (stun, slow, poison) `TODO`
- `class StatusEffect`: type (STUN/SLOW/POISON/BURN), duration_ms, applied_at, magnitude
- `EntityState.statuses: list[StatusEffect]`
- `tick_statuses(entity, now_ms) -> ...` — обновляет cooldowns, удаляет expired
- shield_bash применяет STUN, специальные mob skills могут применять SLOW/POISON
- **AC:** ≥5 тестов: STUN блокирует ход, SLOW снижает move_speed на 50%, POISON наносит урон каждый tick
- **Estimate:** 2ч

### W4-022 — XP / loot drop on mob kill `TODO`
- `wotk/game/drops.py`:
  - `def on_mob_killed(mob_def, killer_hero_level, rng, dungeon_config) -> KillRewards`
  - Возвращает `{xp_gained, gold_gained, items: list[GeneratedItem]}` (через generate_item из loot.py + dungeon loot_table weights)
- Прямо здесь не пишет в БД — caller делает persistence (через loot_db.materialize_item)
- **AC:** ≥5 тестов; xp = mob.xp_drop × difficulty_mult; gold uniform от gold_drop_range; items соответствуют loot_table rarity weights
- **Estimate:** 2ч
- **Dependencies:** W4-010, [loot.py](../backend/src/wotk/game/loot.py)

### W4-023 — Combat events log `TODO`
- `wotk/game/combat_log.py` — append-only log событий боя (для анти-чита и дебага)
- `class CombatEvent`: tick, actor_id, action_type, target_id, damage, was_crit
- Сериализуется в `run_encounters.combat_summary` → JSONB при finalize
- **AC:** events накапливаются, серилизация в dict совпадает с `{v: 1, ...}` форматом DATABASE.md §8.3
- **Estimate:** 1ч

---

## День 4 (Чт) — Inventory backend (~10ч)

### W4-030 — `GET /api/v1/inventory` `TODO`
- Возвращает все `item` юзера (where owner=profile.id AND escrow_run_id IS NULL AND NOT is_in_market_escrow)
- Pagination через `?limit=50&offset=0` (default 50, max 200)
- Filter: `?slot=2&rarity_min=2`
- Response: `{items: [{id, base_id, base_kind, rarity, ilvl, affixes, equipped_on, equipped_slot, inventory_position}], total}`
- **AC:** возвращает только свои items, фильтры работают, сортировка by rarity DESC, ilvl DESC
- **Estimate:** 2ч
- **Dependencies:** §6 model

### W4-031 — `POST /api/v1/items/{id}/equip` `TODO`
- Body: `{slot: int}` (0..5, должен совпадать с item_base.slot)
- В транзакции (FOR UPDATE на item):
  1. Verify ownership: `item.owner_profile_id == profile.id`
  2. Item должен быть в inventory (`inventory_position IS NOT NULL`)
  3. Если в слоте уже что-то надето — снять (set equipped_on/slot=NULL, inventory_position=first_free)
  4. Set: equipped_on=hero.id, equipped_slot=slot, inventory_position=NULL
- **Idempotency** через middleware
- **AC:** equip из inventory работает; повторный equip того же item → no-op (idempotent на уровне FK constraint); equip в занятый слот → swap; equip в слот не подходящий по item_base.slot → 422
- **Estimate:** 3ч
- **Dependencies:** W4-030

### W4-032 — `POST /api/v1/items/{id}/unequip` `TODO`
- В транзакции: equipped_on=NULL, equipped_slot=NULL, inventory_position=first_free
- Если inventory full (все 48 слотов заняты) → 409 inventory_full
- **AC:** unequip работает; full inventory blocks; not-equipped item → 409
- **Estimate:** 1.5ч
- **Dependencies:** W4-030

### W4-033 — Helper `find_first_free_inventory_slot(profile_id)` `TODO`
- SQL query: `SELECT generate_series(0, 47) EXCEPT SELECT inventory_position FROM item WHERE owner_profile_id=$1 AND inventory_position IS NOT NULL ORDER BY 1 LIMIT 1`
- Используется в equip/unequip и при автоматической материализации лута
- **AC:** возвращает min unused position (0..47); NULL когда full
- **Estimate:** 1ч

### W4-034 — Tests для inventory endpoints `TODO`
- `tests/test_inventory_api.py`:
  - GET без auth → 401
  - GET с пустым inventory → []
  - Equip → GET показывает item с equipped_on
  - Equip wrong slot → 422
  - Equip when slot full → swap, second item ушёл в inventory
  - Unequip when full inventory → 409
- **AC:** ≥8 тестов
- **Estimate:** 2.5ч
- **Dependencies:** W4-030..033

---

## День 5 (Пт) — Inventory frontend (~10ч)

### W4-040 — Inventory React screen `TODO`
- `frontend/src/screens/Inventory.tsx`
- 6×8 grid (48 ячеек). Item рендерится по `inventory_position` индексу.
- Сверху панель equipped slots (6 ячеек: HELMET/CHEST/WEAPON/OFFHAND/BOOTS/RING)
- Click on inventory item → call equip API → optimistic update
- Click on equipped → unequip API
- **AC:** click work flow проходит, optimistic UI не glitches
- **Estimate:** 4ч
- **Dependencies:** W4-031, W4-032

### W4-041 — Item tooltip с snapshot affixes `TODO`
- Long-press / hover показывает tooltip с:
  - name (i18n из item_base.kind)
  - rarity color (COMMON gray → LEGENDARY orange)
  - base stats
  - affixes список из `item.affixes` JSONB: `T{t} +{value} {mod_type}` + roll quality (`{value}/{vmax} = {pct}%`)
- **AC:** tooltip читаем, snapshot fields отображены
- **Estimate:** 2ч

### W4-042 — Rarity color theme + animations `TODO`
- CSS classes `item--common/magic/rare/epic/legendary` с border colors
- Subtle glow animation для legendary (CSS keyframe)
- **AC:** все 5 rarities визуально различимы
- **Estimate:** 1ч

### W4-043 — Inventory link с City экрана `TODO`
- Кнопка "Inventory" в City теперь активная (была disabled)
- Route: 'city' | 'playground' | 'inventory'
- **AC:** flow City → Inventory → back to City работает
- **Estimate:** 1ч
- **Dependencies:** W4-040

### W4-044 — i18n keys для inventory + items `TODO`
- ru.json + en.json: `inventory.title`, `inventory.empty`, `item.<kind>.name` для seed'ed bases, `affix.<mod_type>.t<tier>` для seed'ed affixes
- **AC:** нет hardcoded strings в Inventory.tsx; ESLint i18next plugin clean
- **Estimate:** 2ч

---

## День 6 (Сб) — Bridge: combat + inventory (~8ч)

### W4-050 — Hero stats с учётом equipped items `TODO`
- `wotk/game/hero_stats.py` — `compute_hero_combat_stats(hero, equipped_items) -> DerivedStats`
- Сумма base_stats + ATK from weapon + DEF from armor + bonuses from affixes
- Учитывает affix mod_type (применение `flat_str` → str+value, `pct_atk` → atk × (1 + value/100))
- **AC:** unit-тесты: голый Knight vs Knight в epic gear — atk и def кратно выше; resistance каппится на 75%
- **Estimate:** 3ч
- **Dependencies:** W4-001, [stats.py](../backend/src/wotk/game/stats.py)

### W4-051 — `GET /api/v1/me/combat-stats` `TODO`
- Возвращает derived stats с учётом equipped (или базовых если ничего не надето)
- Response: `{hp, mana, atk, def, crit_chance, crit_dmg, attack_speed, move_speed, resist_phys, resist_fire, ...}`
- **AC:** меняется при equip/unequip без перезагрузки страницы
- **Estimate:** 1.5ч

### W4-052 — Show stats panel в City `TODO`
- В City экран добавить collapsible "Stats" panel со списком derived stats
- Auto-refresh после equip/unequip через invalidation in zustand store
- **AC:** stats обновляются в течение 200ms после equip
- **Estimate:** 2ч

### W4-053 — End-to-end: equip → stats change → ready for dungeon `TODO`
- Smoke test: login → create hero → seed 3 random items → equip всё → check stats panel показывает буст → ready (для будущего dungeon entry)
- **AC:** ручной + screenshot evidence
- **Estimate:** 1.5ч

---

## День 7 (Вс) — Polish + W5 plan (~6ч)

### W4-060 — Performance pass: combat math benchmark `TODO`
- Microbench: 1000 mob kills + 10000 damage calcs → должно укладываться в <100ms на dev машине
- Если slow — выделить hot spots через cProfile
- **AC:** benchmark номера задокументированы в комментарии у `compute_damage`
- **Estimate:** 1ч

### W4-061 — Bug fixes из ручного тестирования `TODO`
- Резерв на всё что нашлось при e2e сборке
- **Estimate:** 2ч

### W4-062 — Update WEEK-4-TICKETS статус + WEEK-5-PLAN.md outline `TODO`
- Создать `docs/WEEK-5-PLAN.md` с outline:
  - Phase 4 завершение: реальный dungeon entry → mob spawn → combat в Pixi → kill → loot pickup → finalize → equip
  - Phase 3 catch-up: Colyseus integration (если решим делать без prod)
  - Reconciliation cron, audit_events для combat anomalies
- **AC:** W5 план содержит ≥10 тикетов
- **Estimate:** 1.5ч

### W4-063 — Buffer `TODO`
1.5ч резерв.

---

## Итого по неделе

- Всего тикетов: **31** (тот же объём)
- Суммарная оценка: ~62 часа
- Critical path: W4-001 → W4-004 → W4-011 → W4-020 → W4-030 → W4-040 → W4-050 → W4-053
- **Parallel tracks**: combat-pure (день 1-3) + inventory-fullstack (день 4-5) + bridge (день 6) — независимы до bridge

## Acceptance criteria недели

- ✅ Combat formulas pure-functions с TDD coverage ≥90%
- ✅ 3 mob типа с FSM AI работают в integration тесте
- ✅ 4 Knight skills с cooldowns + cost валидацией
- ✅ Inventory grid в frontend с equip/unequip workflow
- ✅ Hero combat stats обновляются при equip изменении
- ✅ Backend tests: ≥200 (было 156, +50 на combat/AI/inventory)

## Что НЕ должно сломаться (regression-защита)

- W1-W3: все 156 предыдущих тестов остаются зелёными
- Idempotency middleware на /heroes остаётся работать
- Pixi placeholder сцена (Playground) не ломается

## Риски недели

| Риск | Митигация |
|---|---|
| Combat balancing — формулы дают перекошенный gameplay | В W4 фокус на correctness (тесты на инварианты), не на баланс. Tuning отдельной фазой. |
| AI FSM сложнее чем выглядит — углы edge cases | Pure functions + table-driven tests catch это; изоляция от realtime упрощает дебаг |
| Pathfinding A* медленный на больших картах | Cap grid_size=32, мapы ≤40×30 в MVP — search space ~1200 cells, A* справится |
| Inventory swap UX confusing | Optimistic update + undo button; explicit confirmation dialog для destructive actions (salvage в W5+) |
| Hero stats recompute при каждом equip → too many recomputes | Memoize на hash(equipped_items) ключ, recompute только при change |
| Affix snapshot vs current AffixDefinition divergence в формулах | Snapshot имеет vmin/vmax/tier — формула применяет по value (не lookup'ит снова), divergence не critical |

## Что готово к началу W5

- Полный gameplay loop без realtime: hero stats → combat decisions → mob kill → loot drop → inventory equip → stats boost
- Когда Colyseus integration придёт (W5 или позже) — combat/AI логика подключается без переписывания (pure functions + thin orchestration layer в realtime/)
- Inventory UI как референс для других list-based screens (skills, achievements, friends)

/**
 * DungeonRoom — комната одного dungeon_run (1 player в MVP, multi позже).
 *
 * Lifecycle:
 *  - onAuth: верифицируем ws_token JWT (HS256, тот же secret что у FastAPI).
 *  - onJoin: создаём Player в WorldState.
 *  - tick (20Hz): применяем inputs из последнего onMessage, broadcast diff.
 *  - onLeave: убираем player; если последний — room dispose'ится.
 *
 * onMessage("input", { x, y, seq }) — нормализованный input vector от клиента.
 * onMessage("cast", { skill_id, target_x, target_y }) — cast intent from client.
 * Сервер двигает player с фиксированной скоростью; client может делать
 * prediction локально и reconcile при schema diff.
 */

import { Client, Room } from '@colyseus/core';
import jwt from 'jsonwebtoken';

import { log as rootLog } from '../logger.js';
import { AIState, stepAi, type PlayerObservation } from '../game/ai.js';
import { spawnEncounter, type MobInstance, type Vec2 } from '../game/spawn.js';
import { MOBS } from '../game/mobs.js';
import { Mob, Player, WorldState } from '../schemas/WorldState.js';
import { computeDamage, DamageType } from '../game/combat.js';
import { CooldownTracker } from '../game/cooldowns.js';
import { KNIGHT_SKILLS } from '../game/skills.js';
import { resolveCast, type TargetCandidate } from '../game/skillCast.js';
import {
  StatusType,
  dotDamagePerSec,
  filterActive,
  isStunned,
  type StatusEffect,
} from '../game/statusEffects.js';
import { makeLcg } from '../game/rng.js';
import { CombatLog, CombatEventType } from '../game/combatLog.js';
import { onMobKilled, type ItemDropIntent } from '../game/drops.js';
import { finalizeRun, floorCleared } from '../internal/api.js';
import type { FloorConfig } from '../game/dungeonConfig.js';

const log = rootLog.child({ component: 'DungeonRoom' });

interface WsTokenClaims {
  sub: string;
  type: string;
  run_id: string;
  hero_id: number;
  dungeon_id: string;
  seed_hex: string;
  /** Per-floor configs embedded at /enter time (W6-001). */
  floors?: FloorConfig[];
  iat: number;
  exp: number;
}

interface InputMessage {
  x: number;
  y: number;
  seq?: number;
}

interface CastMessage {
  skill_id: string;
  target_x: number;
  target_y: number;
}

/** Скорость player'а в px/sec — sync с frontend (Player.ts). */
const PLAYER_SPEED_PX_S = 140;
/** Tick rate — 20Hz = 50ms. */
const TICK_INTERVAL_MS = 50;
/** Стартовая позиция player'а в комнате (placeholder). */
const SPAWN_X = 320;
const SPAWN_Y = 240;
/** Hitbox player'а — должен совпадать с frontend Player.HITBOX_HALF. */
const HITBOX_HALF = 11;
/** Mana regen per second (W5-021 spec: +5/sec). */
const MANA_REGEN_PER_SEC = 5;
/** Default hero defense (placeholder until equipped stats are wired in). */
const PLAYER_BASE_DEF = 10;
/** Placeholder attacker stats used for player casting (atk=20, weapon 5-10, crit 5%/150%). */
const PLAYER_ATTACKER = {
  atk: 20,
  critChancePct: 5,
  critDamagePct: 150,
  weaponMinDmg: 5,
  weaponMaxDmg: 10,
} as const;

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Placeholder room geometry — rooms 'arena' (40×30 tiles × 32 px) с
 * периметром-стенкой. В W5 геометрия будет передаваться из FastAPI в
 * /enter response (вместе с dungeon.config) или загружаться по run_id.
 */
const TILE = 32;
const ROOM_COLS = 40;
const ROOM_ROWS = 30;
const ROOM_WALLS: readonly Rect[] = Object.freeze([
  { x: 0, y: 0, w: ROOM_COLS * TILE, h: TILE },
  { x: 0, y: (ROOM_ROWS - 1) * TILE, w: ROOM_COLS * TILE, h: TILE },
  { x: 0, y: 0, w: TILE, h: ROOM_ROWS * TILE },
  { x: (ROOM_COLS - 1) * TILE, y: 0, w: TILE, h: ROOM_ROWS * TILE },
]);

function collidesAt(cx: number, cy: number): boolean {
  const px = cx - HITBOX_HALF;
  const py = cy - HITBOX_HALF;
  const pw = HITBOX_HALF * 2;
  const ph = HITBOX_HALF * 2;
  for (const w of ROOM_WALLS) {
    if (px < w.x + w.w && px + pw > w.x && py < w.y + w.h && py + ph > w.y) {
      return true;
    }
  }
  return false;
}

export class DungeonRoom extends Room<WorldState> {
  override maxClients = 4; // MVP — solo, но allow group в будущем

  private readonly inputs = new Map<string, InputMessage>();

  /**
   * Parallel FSM state for each mob, keyed by String(instanceId).
   * Schema (state.mobs) is for broadcast; this map holds runtime AI fields.
   */
  private readonly mobInstances = new Map<string, MobInstance>();

  /**
   * Stable per-session integer ID used internally by the AI FSM.
   * Opaque to clients — not broadcast.
   */
  private readonly playerIds = new Map<string, number>();
  /** Reverse map: internal numeric ID → sessionId for O(1) lookup on attack. */
  private readonly playerNumberToSessionId = new Map<number, string>();
  private nextPlayerId = 0;

  /** Per-player cooldown trackers. Init on onJoin, cleanup on onLeave. */
  private readonly playerCooldowns = new Map<string, CooldownTracker>();

  /** Per-player status effects (not in Schema — server-only for now). */
  private readonly playerStatuses = new Map<string, StatusEffect[]>();

  /** Shared room RNG — seeded from JWT seed_hex on first onJoin. */
  private rng: () => number = makeLcg(12345);
  private _rngSeeded = false;

  /**
   * Accumulated kill rewards — flushed to FastAPI on onDispose via /internal/finalize.
   * goldTotal and xpTotal are running sums; items accumulates drop intents.
   */
  private readonly pendingRewards: { xpTotal: number; goldTotal: number; items: ItemDropIntent[] } =
    { xpTotal: 0, goldTotal: 0, items: [] };

  /** Append-only combat log for anti-cheat audit. Serialized in onDispose. */
  private readonly combatLog = new CombatLog();

  /**
   * Current server tick counter. Incremented each tick call.
   * Used as stable tick value for CombatLog events.
   */
  private _tickCounter = 0;

  /**
   * run_id from the first authenticated client's JWT claims.
   * Set in onJoin; used in onDispose to call /internal/finalize.
   */
  private _runId: string | null = null;

  /**
   * Per-floor configurations from the ws_token JWT (W6-001).
   * Cached from auth.floors on first onJoin. Null until first client joins.
   */
  private _floorConfigs: FloorConfig[] | null = null;

  /**
   * 0-based index of the current floor (mirrors dungeon_run.current_floor).
   * Incremented when the player successfully advances via next_floor.
   */
  private _currentFloor = 0;

  /**
   * True while a floor-advance is in-flight (awaiting /floor-cleared callback).
   * Prevents concurrent next_floor requests.
   */
  private _floorAdvanceInProgress = false;

  /**
   * Overall room outcome, updated as game events occur:
   * - ABANDONED (default): no explicit outcome yet.
   * - COMPLETED: all mobs died and at least one player was alive.
   * - FAILED: all players died.
   */
  private _roomStatus: 'COMPLETED' | 'FAILED' | 'ABANDONED' = 'ABANDONED';

  override onCreate(): void {
    this.setState(new WorldState());

    const spawnPositions: Vec2[] = [
      { x: 640, y: 480 },
      { x: 800, y: 400 },
      { x: 500, y: 600 },
      { x: 900, y: 700 },
      { x: 700, y: 300 },
    ];

    const mobInstancesList = spawnEncounter(this.rng, {
      floor: 0,
      encounterIdx: 0,
      spawnPositions,
    });

    for (const mi of mobInstancesList) {
      const key = String(mi.instanceId);

      // Schema mob — auto-broadcast to clients
      const mob = new Mob();
      mob.id = mi.mobDef.id;
      mob.instance_id = mi.instanceId;
      mob.x = mi.position.x;
      mob.y = mi.position.y;
      mob.hp = mi.hp;
      mob.maxHp = mi.hp;
      mob.state = mi.state;
      this.state.mobs.set(key, mob);

      // Runtime AI state (not broadcast)
      this.mobInstances.set(key, mi);
    }

    this.onMessage<InputMessage>('input', (client, message) => {
      // Validate range — иначе клиент может отправить (1e9, 1e9) и телепортнуться
      const x = Math.max(-1, Math.min(1, Number(message.x) || 0));
      const y = Math.max(-1, Math.min(1, Number(message.y) || 0));
      this.inputs.set(client.sessionId, { x, y, seq: message.seq });
    });

    // ── W5-020: Player cast handler ──────────────────────────────────────────
    this.onMessage<CastMessage>('cast', (client, message) => {
      this._resolvePlayerCast(client, message);
    });

    // Echo-back ping для frontend dev-overlay (W3-044). Сервер отвечает
    // immediately, клиент considers half-RTT при desire (но обычно полный).
    this.onMessage<{ ts: number }>('ping', (client, message) => {
      client.send('pong', { ts: Number(message.ts) || 0 });
    });

    // ── W6-002: Floor advance handler ────────────────────────────────────────
    this.onMessage('next_floor', (client, _message) => {
      void this._handleNextFloor(client);
    });

    this.setSimulationInterval((deltaMs) => this.tick(deltaMs), TICK_INTERVAL_MS);
  }

  override async onAuth(client: Client, options: { token?: string }): Promise<WsTokenClaims> {
    const secret = process.env.JWT_SECRET ?? '';
    if (!secret) {
      log.error({ session_id: client.sessionId }, 'jwt_secret_not_configured');
      throw new Error('JWT_SECRET not configured');
    }

    const token = options.token ?? '';
    if (!token) {
      log.warn({ session_id: client.sessionId }, 'ws_auth_missing_token');
      throw new Error('missing ws_token');
    }

    let decoded: jwt.JwtPayload;
    try {
      decoded = jwt.verify(token, secret, {
        algorithms: ['HS256', 'HS384', 'HS512'],
      }) as jwt.JwtPayload;
    } catch (err) {
      log.warn(
        {
          session_id: client.sessionId,
          reason: err instanceof Error ? err.message : 'unknown',
        },
        'ws_auth_invalid_token',
      );
      throw new Error(
        `invalid ws_token: ${err instanceof Error ? err.message : 'unknown'}`,
      );
    }

    if (decoded.type !== 'ws') {
      log.warn(
        { session_id: client.sessionId, type: decoded.type },
        'ws_auth_wrong_type',
      );
      throw new Error(`wrong token type: ${decoded.type}`);
    }
    if (
      typeof decoded.sub !== 'string' ||
      typeof decoded.run_id !== 'string' ||
      typeof decoded.hero_id !== 'number'
    ) {
      log.warn({ session_id: client.sessionId }, 'ws_auth_missing_claims');
      throw new Error('ws_token missing required claims');
    }

    log.info(
      {
        session_id: client.sessionId,
        run_id: decoded.run_id,
        profile_id: decoded.sub,
        hero_id: decoded.hero_id,
      },
      'ws_auth_ok',
    );
    return decoded as WsTokenClaims;
  }

  override onJoin(client: Client, _options: unknown, auth: WsTokenClaims): void {
    // Cache run_id from the first joining client for use in onDispose.
    if (this._runId === null) {
      this._runId = auth.run_id;
    }
    // Cache floor configs from JWT claims (W6-001).
    if (this._floorConfigs === null && Array.isArray(auth.floors) && auth.floors.length > 0) {
      this._floorConfigs = auth.floors;
      log.info(
        { run_id: auth.run_id, floor_count: auth.floors.length },
        'ws_floor_configs_loaded',
      );
    }
    // Seed RNG from run.seed (deterministic per run). Take first 8 hex chars
    // = 32-bit int, sufficient for LCG period.
    if (!this._rngSeeded && typeof auth.seed_hex === 'string' && auth.seed_hex.length >= 8) {
      const seedInt = parseInt(auth.seed_hex.slice(0, 8), 16);
      if (Number.isFinite(seedInt) && seedInt > 0) {
        this.rng = makeLcg(seedInt);
        this._rngSeeded = true;
      }
    }

    const player = new Player();
    player.id = auth.sub;
    player.x = SPAWN_X;
    player.y = SPAWN_Y;
    player.hp = 100;
    player.maxHp = 100;
    player.mana = 50;
    player.maxMana = 50;
    this.state.players.set(client.sessionId, player);

    // Assign stable internal numeric ID for AI targeting
    const numId = ++this.nextPlayerId;
    this.playerIds.set(client.sessionId, numId);
    this.playerNumberToSessionId.set(numId, client.sessionId);

    // Init per-player cooldown tracker and status list
    this.playerCooldowns.set(client.sessionId, new CooldownTracker());
    this.playerStatuses.set(client.sessionId, []);

    log.info(
      {
        session_id: client.sessionId,
        run_id: auth.run_id,
        profile_id: auth.sub,
        room_id: this.roomId,
      },
      'ws_join',
    );
  }

  override onLeave(client: Client): void {
    const numId = this.playerIds.get(client.sessionId);
    if (numId !== undefined) {
      this.playerNumberToSessionId.delete(numId);
    }
    this.state.players.delete(client.sessionId);
    this.inputs.delete(client.sessionId);
    this.playerIds.delete(client.sessionId);
    this.playerCooldowns.delete(client.sessionId);
    this.playerStatuses.delete(client.sessionId);
    log.info(
      { session_id: client.sessionId, room_id: this.roomId },
      'ws_leave',
    );
  }

  /**
   * Lazy-init per-player CooldownTracker.
   *
   * Should not be needed in normal flow (tracker is init on onJoin) but
   * guards against race conditions and simplifies testing.
   */
  private getPlayerCooldowns(sid: string): CooldownTracker {
    let tracker = this.playerCooldowns.get(sid);
    if (!tracker) {
      tracker = new CooldownTracker();
      this.playerCooldowns.set(sid, tracker);
    }
    return tracker;
  }

  /**
   * Find the nearest alive player to a mob and return a PlayerObservation.
   *
   * Iterates all players in room state, computing squared distance to avoid
   * a sqrt per player. Returns null when no alive players are present.
   */
  private nearestPlayerTo(mob: MobInstance): PlayerObservation | null {
    let nearest: { sessionId: string; player: Player; distSq: number } | null = null;

    for (const [sid, p] of this.state.players.entries()) {
      if (p.hp <= 0) continue;
      const dx = p.x - mob.position.x;
      const dy = p.y - mob.position.y;
      const distSq = dx * dx + dy * dy;
      if (!nearest || distSq < nearest.distSq) {
        nearest = { sessionId: sid, player: p, distSq };
      }
    }

    if (!nearest) return null;

    return {
      playerId: this._sessionIdToNumber(nearest.sessionId),
      position: { x: nearest.player.x, y: nearest.player.y },
      isAlive: nearest.player.hp > 0,
    };
  }

  /**
   * Return the stable internal numeric ID for a session.
   *
   * Assigned on onJoin; if somehow missing (e.g. mock in tests) falls back to
   * a hash derived from the string so the AI still gets a stable number.
   */
  private _sessionIdToNumber(sessionId: string): number {
    const id = this.playerIds.get(sessionId);
    if (id !== undefined) return id;
    // Fallback: simple string hash (should not occur in production)
    let h = 0;
    for (let i = 0; i < sessionId.length; i++) {
      h = (Math.imul(31, h) + sessionId.charCodeAt(i)) | 0;
    }
    return Math.abs(h);
  }

  /**
   * W5-020/021: Resolve a player cast message.
   *
   * Validates skill_id, cooldown, mana; then calls resolveCast to determine
   * hit mobs; calls computeDamage per hit mob; applies HP changes. Applies
   * STUN on shield_bash hits.
   */
  private _resolvePlayerCast(client: Client, message: CastMessage): void {
    const sessionId = client.sessionId;
    const player = this.state.players.get(sessionId);
    if (!player) return;

    // Player must be alive
    if (player.hp <= 0) return;

    // Player must not be stunned
    const playerStatuses = this.playerStatuses.get(sessionId) ?? [];
    const nowMs = performance.now();
    if (isStunned(playerStatuses, nowMs)) return;

    // Validate skill_id
    const skillId = String(message.skill_id ?? '');
    const skill = KNIGHT_SKILLS[skillId];
    if (!skill) return;

    // Validate target coords
    const targetX = Number(message.target_x);
    const targetY = Number(message.target_y);
    if (!isFinite(targetX) || !isFinite(targetY)) return;

    // Cooldown check (W5-024)
    const tracker = this.getPlayerCooldowns(sessionId);
    const cdOk = tracker.tryCast(skillId, {
      currentTimeMs: nowMs,
      cooldownMs: skill.cooldownMs,
    });
    if (!cdOk) {
      client.send('cast_rejected', { reason: 'cooldown', skill_id: skillId });
      return;
    }

    // Mana check (W5-021)
    if (player.mana < skill.manaCost) {
      // Silently ignore (spec: "ignore cast silently")
      // Undo the CD registration so the player isn't penalised for failed cast
      tracker.reset(skillId);
      return;
    }
    player.mana = Math.max(0, player.mana - skill.manaCost);

    // Build candidate list from alive mobs
    const candidates: TargetCandidate[] = [];
    for (const [, mi] of this.mobInstances.entries()) {
      if (mi.hp > 0 && mi.state !== AIState.DEAD) {
        candidates.push({
          entityId: mi.instanceId,
          position: { x: mi.position.x, y: mi.position.y },
        });
      }
    }

    const castResult = resolveCast({
      casterPosition: { x: player.x, y: player.y },
      skill,
      targetPosition: { x: targetX, y: targetY },
      candidates,
    });

    if (!castResult.success) return;

    let damageTotalMitigated = 0;

    for (const entityId of castResult.hitEntities) {
      const key = String(entityId);
      const mi = this.mobInstances.get(key);
      const schemaMob = this.state.mobs.get(key);
      if (!mi || !schemaMob || mi.hp <= 0) continue;

      const result = computeDamage({
        attacker: PLAYER_ATTACKER,
        defender: {
          hp: mi.hp,
          def_: mi.mobDef.base_def,
        },
        skillMultiplier: skill.dmgMultiplier,
        damageType: skill.damageType,
        rng: this.rng,
      });

      mi.hp = Math.max(0, mi.hp - result.mitigated);
      schemaMob.hp = mi.hp;
      damageTotalMitigated += result.mitigated;

      // W5-023: shield_bash applies STUN 1000ms to hit mob
      if (skillId === 'shield_bash') {
        mi.statuses.push({
          statusType: StatusType.STUN,
          appliedAtMs: nowMs,
          durationMs: 1000,
          magnitude: 0,
        });
      }

      // Log the player attack event.
      this.combatLog.record({
        tick: this._tickCounter,
        eventType: CombatEventType.PLAYER_ATTACK,
        actorId: this._sessionIdToNumber(sessionId),
        targetId: mi.instanceId,
        damage: result.mitigated,
        wasCrit: result.wasCrit,
        extra: { skill_id: skillId },
      });

      // Mob death — W5-030: collect kill rewards.
      if (mi.hp <= 0) {
        mi.state = AIState.DEAD;
        schemaMob.state = AIState.DEAD;

        // W6-013: boss drops get bossMultiplier=2.0 and guaranteed rare+.
        const bossMultiplier = mi.mobDef.is_boss ? 2.0 : 1.0;
        const rewards = onMobKilled({ rng: this.rng, mobDef: mi.mobDef, bossMultiplier });
        this.pendingRewards.xpTotal += rewards.xpGained;
        this.pendingRewards.goldTotal += rewards.goldGained;
        this.pendingRewards.items.push(...rewards.items);

        // Log the kill event.
        this.combatLog.record({
          tick: this._tickCounter,
          eventType: CombatEventType.PLAYER_KILL_MOB,
          actorId: this._sessionIdToNumber(sessionId),
          targetId: mi.instanceId,
          extra: { mob_type: mi.mobDef.id },
        });

        log.info(
          {
            mob_instance_id: mi.instanceId,
            mob_type: mi.mobDef.id,
            xp_gained: rewards.xpGained,
            gold_gained: rewards.goldGained,
            items_rolled: rewards.items.length,
            is_boss: mi.mobDef.is_boss,
          },
          'mob_killed',
        );

        // W6-014: Boss death → run COMPLETED immediately; close room.
        if (mi.mobDef.is_boss) {
          const anyPlayerAlive = [...this.state.players.values()].some((p) => p.hp > 0);
          if (anyPlayerAlive) {
            this._roomStatus = 'COMPLETED';
            log.info(
              { run_id: this._runId, boss_id: mi.mobDef.id },
              'boss_killed_run_completed',
            );
            this.disconnect();
          }
          return; // Stop processing — room is shutting down
        }

        // Check if all mobs are dead → room status = COMPLETED (if player alive).
        const anyPlayerAlive = [...this.state.players.values()].some((p) => p.hp > 0);
        const anyMobAlive = [...this.mobInstances.values()].some(
          (m) => m.state !== AIState.DEAD && m.hp > 0,
        );
        if (!anyMobAlive && anyPlayerAlive) {
          this._roomStatus = 'COMPLETED';
          // W6-031: broadcast run_summary BEFORE clients disconnect.
          this._broadcastRunSummary('COMPLETED', this._currentFloor);
        }
      }
    }

    log.info(
      {
        session_id: sessionId,
        skill_id: skillId,
        hit_count: castResult.hitEntities.length,
        damage_total: damageTotalMitigated,
      },
      'player_cast_resolved',
    );
  }

  /**
   * W5-022: Apply mob attack damage to target player.
   *
   * Uses mob's base_atk as AttackerStats; player def_ is PLAYER_BASE_DEF.
   * Player hp is floored at 0. Sets player to dead (hp=0) — death UX is Day 5.
   */
  private _applyMobAttack(mobInst: MobInstance, targetPlayerId: number): void {
    const sessionId = this.playerNumberToSessionId.get(targetPlayerId);
    if (!sessionId) return;

    const player = this.state.players.get(sessionId);
    if (!player || player.hp <= 0) return;

    const result = computeDamage({
      attacker: {
        atk: mobInst.mobDef.base_atk,
      },
      defender: {
        hp: player.hp,
        def_: PLAYER_BASE_DEF,
      },
      skillMultiplier: 1.0,
      damageType: DamageType.PHYSICAL,
      rng: this.rng,
    });

    player.hp = Math.max(0, player.hp - result.mitigated);

    // Log the mob attack event.
    this.combatLog.record({
      tick: this._tickCounter,
      eventType: CombatEventType.MOB_ATTACK,
      actorId: mobInst.instanceId,
      targetId: this._sessionIdToNumber(sessionId),
      damage: result.mitigated,
      wasCrit: result.wasCrit,
    });

    log.debug(
      {
        mob_id: mobInst.instanceId,
        target_session: sessionId,
        damage: result.mitigated,
        was_crit: result.wasCrit,
        player_hp_remaining: player.hp,
      },
      'mob_attack_resolved',
    );

    if (player.hp <= 0) {
      // Log the player death event.
      this.combatLog.record({
        tick: this._tickCounter,
        eventType: CombatEventType.MOB_KILL_PLAYER,
        actorId: mobInst.instanceId,
        targetId: this._sessionIdToNumber(sessionId),
      });

      log.info({ session_id: sessionId, mob_id: mobInst.instanceId }, 'player_died');

      // Check if all players dead → room status = FAILED.
      const anyPlayerAlive = [...this.state.players.values()].some((p) => p.hp > 0);
      if (!anyPlayerAlive) {
        this._roomStatus = 'FAILED';
        // W6-031: broadcast run_summary BEFORE clients disconnect.
        this._broadcastRunSummary('FAILED', this._currentFloor);
      }
    }
  }

  /**
   * W6-012: Spawn the boss mob at the arena center position.
   *
   * Boss is spawned as a single MobInstance with runtime boss fields initialized.
   * Instance ID is deterministic: floor * 1000 + 999 (reserved for boss slot).
   *
   * @param bossId - mob_def ID from MOBS registry (e.g. "crypt_lich").
   * @param floor - Current floor index.
   * @param position - Spawn position (arena center or first spawn_point).
   */
  private _spawnBoss(bossId: string, floor: number, position: Vec2): void {
    const md = MOBS[bossId];
    if (!md) {
      log.error({ boss_id: bossId }, 'boss_mob_def_not_found');
      return;
    }
    const instanceId = floor * 1000 + 999;
    const mi: MobInstance = {
      instanceId,
      mobDef: md,
      position: { x: position.x, y: position.y },
      spawnPosition: { x: position.x, y: position.y },
      hp: md.base_hp, // Boss HP is not scaled by floor mult (already 600)
      state: 0, // AIState.IDLE
      statuses: [],
      enraged: false,
      chargeUntilMs: 0,
      lastSummonAtMs: 0,
    };

    const key = String(instanceId);
    const schemaMob = new Mob();
    schemaMob.id = md.id;
    schemaMob.instance_id = instanceId;
    schemaMob.x = mi.position.x;
    schemaMob.y = mi.position.y;
    schemaMob.hp = mi.hp;
    schemaMob.maxHp = mi.hp;
    schemaMob.state = mi.state;
    this.state.mobs.set(key, schemaMob);
    this.mobInstances.set(key, mi);

    log.info(
      { boss_id: bossId, instance_id: instanceId, floor, hp: mi.hp },
      'boss_spawned',
    );
  }

  /**
   * W6-031: Broadcast a lightweight run_summary message to all connected clients.
   *
   * Uses local pendingRewards (accumulated kill rewards since last floor-cleared)
   * as a best-effort approximation — the canonical source of truth remains the
   * GET /runs/{id}/summary endpoint. Must be called BEFORE clients disconnect.
   *
   * @param status - Terminal run status being broadcast.
   * @param floorsCleared - Number of floors cleared (current floor index).
   */
  private _broadcastRunSummary(
    status: 'COMPLETED' | 'FAILED' | 'ABANDONED',
    floorsCleared: number,
  ): void {
    if (!this._runId) return;
    const summary = {
      run_id: this._runId,
      status,
      gold_earned: this.pendingRewards.goldTotal,
      xp_earned: this.pendingRewards.xpTotal,
      items: this.pendingRewards.items.map((i) => ({
        id: 0, // Not yet materialized — placeholder
        base_kind: 'unknown',
        rarity: i.rarity,
        ilvl: 1,
      })),
      floors_cleared: floorsCleared,
      duration_s: 0, // Server will compute canonical value
      boss_killed: status === 'COMPLETED',
    };
    this.broadcast('run_summary', summary);
    log.info(
      { run_id: this._runId, status, floors_cleared: floorsCleared },
      'run_summary_broadcast',
    );
  }

  /**
   * Called by Colyseus when the room is being destroyed (all clients left or
   * explicit dispose). Fires /internal/runs/{id}/finalize as fire-and-forget.
   *
   * Status logic:
   * - COMPLETED if _roomStatus was set to COMPLETED (last mob died, player alive).
   * - FAILED if all players died.
   * - ABANDONED otherwise (no explicit outcome — clients disconnected early).
   *
   * If no run_id was ever captured (no client authenticated), no-op.
   */
  override onDispose(): void {
    if (!this._runId) {
      log.info({ room_id: this.roomId }, 'room_dispose_no_run_id_noop');
      return;
    }

    let heroHp = 0;
    let heroMana = 0;
    for (const p of this.state.players.values()) {
      if (p.hp > heroHp) {
        heroHp = p.hp;
        heroMana = p.mana;
      }
    }

    const runId = this._runId;
    log.info(
      {
        room_id: this.roomId,
        run_id: runId,
        status: this._roomStatus,
        gold_total: this.pendingRewards.goldTotal,
        xp_total: this.pendingRewards.xpTotal,
        items_count: this.pendingRewards.items.length,
      },
      'room_dispose_finalizing',
    );

    // Fire-and-forget: retry-loop (up to ~10s) cannot block Colyseus dispose,
    // иначе room shutdown зависает за timeout. Promise живёт в Node event loop.
    void finalizeRun({
      runId,
      status: this._roomStatus,
      heroState: { hp: Math.round(heroHp), mana: Math.round(heroMana) },
      goldEarned: this.pendingRewards.goldTotal,
      xpEarned: this.pendingRewards.xpTotal,
      itemsRolled: this.pendingRewards.items,
      combatSummary: this.combatLog.toSummary(),
    }).catch((err: unknown) => {
      log.error(
        {
          room_id: this.roomId,
          run_id: runId,
          error: err instanceof Error ? err.message : String(err),
        },
        'room_dispose_finalize_failed',
      );
    });
  }

  /**
   * W6-002: Handle 'next_floor' message from any client.
   *
   * Validates that all mobs are dead; if so:
   * 1. Flushes the current floor's CombatLog via flushFloor().
   * 2. Calls /internal/runs/{id}/floor-cleared to write RunEncounter,
   *    increment current_floor, and update last_checkpoint_at.
   * 3. Spawns the next floor encounter from _floorConfigs.
   * 4. Broadcasts 'floor_advanced' to all clients.
   * 5. If no more floors remain, sets _roomStatus = COMPLETED.
   *
   * On failure or invalid state: sends 'floor_advance_rejected' to the client.
   */
  private async _handleNextFloor(client: Client): Promise<void> {
    if (!this._runId) {
      client.send('floor_advance_rejected', { reason: 'no_run_id' });
      return;
    }

    // Guard against concurrent advance requests.
    if (this._floorAdvanceInProgress) {
      client.send('floor_advance_rejected', { reason: 'advance_in_progress' });
      return;
    }

    // Validate all mobs are dead.
    const anyMobAlive = [...this.mobInstances.values()].some(
      (m) => m.state !== AIState.DEAD && m.hp > 0,
    );
    if (anyMobAlive) {
      client.send('floor_advance_rejected', { reason: 'mobs_alive' });
      return;
    }

    const nextFloor = this._currentFloor + 1;
    const totalFloors = this._floorConfigs?.length ?? 0;
    const isLastFloor = totalFloors > 0 && nextFloor >= totalFloors;

    this._floorAdvanceInProgress = true;

    try {
      // Flush CombatLog for the completed floor (W6-003).
      const floorSummary = this.combatLog.flushFloor();

      // Notify FastAPI: write RunEncounter + increment current_floor + checkpoint.
      await floorCleared({
        runId: this._runId,
        floor: this._currentFloor,
        goldEarned: this.pendingRewards.goldTotal,
        xpEarned: this.pendingRewards.xpTotal,
        itemsRolled: this.pendingRewards.items,
        combatSummary: floorSummary,
        advanceToFloor: nextFloor,
      });

      // Reset per-floor reward accumulators.
      this.pendingRewards.goldTotal = 0;
      this.pendingRewards.xpTotal = 0;
      this.pendingRewards.items = [];

      // Advance local floor counter.
      this._currentFloor = nextFloor;

      if (isLastFloor) {
        // All floors cleared → treat as run complete; onDispose will finalize.
        this._roomStatus = 'COMPLETED';
        this.broadcast('floor_advanced', { floor: nextFloor, run_complete: true });
        // W6-031: broadcast run_summary after last floor before clients disconnect.
        this._broadcastRunSummary('COMPLETED', nextFloor);
        log.info(
          { run_id: this._runId, floor: nextFloor },
          'all_floors_cleared_run_complete',
        );
        return;
      }

      // Spawn next floor's mob encounter.
      const nextFloorConfig = this._floorConfigs?.[nextFloor];
      if (nextFloorConfig) {
        // Clear existing mobs from schema + runtime.
        this.state.mobs.clear();
        this.mobInstances.clear();

        const spawnPositions = nextFloorConfig.spawn_points.length > 0
          ? nextFloorConfig.spawn_points
          : [
              { x: 640, y: 480 },
              { x: 800, y: 400 },
              { x: 500, y: 600 },
            ];

        // W6-012: Boss floor — spawn only the boss at arena center.
        if (nextFloorConfig.is_boss_floor && nextFloorConfig.boss_id) {
          this._spawnBoss(nextFloorConfig.boss_id, nextFloor, spawnPositions[0] ?? { x: 640, y: 480 });
        } else {
          const mobPool = nextFloorConfig.mob_pack.length > 0
            ? nextFloorConfig.mob_pack
            : undefined; // falls back to DEFAULT_MOB_POOL in spawnEncounter

          const mobInstancesList = spawnEncounter(this.rng, {
            floor: nextFloor,
            encounterIdx: 0,
            spawnPositions,
            mobPool,
          });

          for (const mi of mobInstancesList) {
            const key = String(mi.instanceId);
            const mob = new Mob();
            mob.id = mi.mobDef.id;
            mob.instance_id = mi.instanceId;
            mob.x = mi.position.x;
            mob.y = mi.position.y;
            mob.hp = mi.hp;
            mob.maxHp = mi.hp;
            mob.state = mi.state;
            this.state.mobs.set(key, mob);
            this.mobInstances.set(key, mi);
          }
        }
      }

      // Reset room status for the new floor.
      this._roomStatus = 'ABANDONED';

      this.broadcast('floor_advanced', { floor: nextFloor, run_complete: false });
      log.info(
        { run_id: this._runId, floor: nextFloor, mobs_spawned: this.mobInstances.size },
        'floor_advanced',
      );
    } catch (err) {
      log.error(
        {
          run_id: this._runId,
          floor: this._currentFloor,
          error: err instanceof Error ? err.message : String(err),
        },
        'floor_advance_failed',
      );
      client.send('floor_advance_rejected', { reason: 'server_error' });
    } finally {
      this._floorAdvanceInProgress = false;
    }
  }

  /**
   * Server tick: apply queued inputs to player positions с collision,
   * mana regen, DoT ticks, AI FSM for every mob, and mob attack damage.
   *
   * Slide-along-wall: при коллизии пробуем move отдельно по X и по Y —
   * permits игроку плавно скользить вдоль стены вместо застревания.
   */
  private tick(deltaMs: number): void {
    const dt = deltaMs / 1000;
    const nowMs = performance.now();
    this._tickCounter++;

    // ── Player movement + mana regen + DoT ──────────────────────────────────
    for (const [sessionId, player] of this.state.players.entries()) {
      if (player.hp <= 0) continue;

      // Movement
      const input = this.inputs.get(sessionId);
      if (input) {
        const len = Math.hypot(input.x, input.y);
        if (len >= 0.01) {
          const nx = input.x / len;
          const ny = input.y / len;
          const distance = PLAYER_SPEED_PX_S * dt * Math.min(len, 1);
          const dx = nx * distance;
          const dy = ny * distance;

          if (!collidesAt(player.x + dx, player.y + dy)) {
            player.x += dx;
            player.y += dy;
          } else {
            if (!collidesAt(player.x + dx, player.y)) player.x += dx;
            if (!collidesAt(player.x, player.y + dy)) player.y += dy;
          }

          if (Math.abs(nx) > Math.abs(ny)) {
            player.facing = nx > 0 ? 'east' : 'west';
          } else {
            player.facing = ny > 0 ? 'south' : 'north';
          }
        }
      }

      // Mana regen (+5/sec)
      if (player.mana < player.maxMana) {
        player.mana = Math.min(player.maxMana, player.mana + MANA_REGEN_PER_SEC * dt);
      }

      // W5-023: DoT damage from player statuses
      const statuses = this.playerStatuses.get(sessionId);
      if (statuses && statuses.length > 0) {
        const dot = dotDamagePerSec(statuses, nowMs);
        if (dot > 0) {
          player.hp = Math.max(0, player.hp - dot * dt);
        }
        // Prune expired statuses
        const active = filterActive(statuses, nowMs);
        this.playerStatuses.set(sessionId, active);
      }
    }

    // ── Mob AI tick ─────────────────────────────────────────────────────────
    for (const [key, mobInst] of this.mobInstances.entries()) {
      const schemaMob = this.state.mobs.get(key);
      if (!schemaMob) continue;

      // Skip dead mobs — keep schema state as DEAD
      if (mobInst.state === AIState.DEAD || mobInst.hp <= 0) {
        schemaMob.state = AIState.DEAD;
        continue;
      }

      // W5-023: DoT damage on mob from status effects
      if (mobInst.statuses.length > 0) {
        const dot = dotDamagePerSec(mobInst.statuses, nowMs);
        if (dot > 0) {
          mobInst.hp = Math.max(0, mobInst.hp - dot * dt);
          schemaMob.hp = mobInst.hp;
          if (mobInst.hp <= 0) {
            mobInst.state = AIState.DEAD;
            schemaMob.state = AIState.DEAD;

            // Roll kill rewards for DoT kills too.
            const dotBossMultiplier = mobInst.mobDef.is_boss ? 2.0 : 1.0;
            const rewards = onMobKilled({
              rng: this.rng,
              mobDef: mobInst.mobDef,
              bossMultiplier: dotBossMultiplier,
            });
            this.pendingRewards.xpTotal += rewards.xpGained;
            this.pendingRewards.goldTotal += rewards.goldGained;
            this.pendingRewards.items.push(...rewards.items);

            this.combatLog.record({
              tick: this._tickCounter,
              eventType: CombatEventType.PLAYER_KILL_MOB,
              actorId: 0, // DoT — no specific actor tracked
              targetId: mobInst.instanceId,
              extra: { mob_type: mobInst.mobDef.id, source: 'dot' },
            });

            // W6-014: Boss death via DoT → run COMPLETED immediately.
            if (mobInst.mobDef.is_boss) {
              const anyPlayerAlive = [...this.state.players.values()].some((p) => p.hp > 0);
              if (anyPlayerAlive) {
                this._roomStatus = 'COMPLETED';
                log.info(
                  { run_id: this._runId, boss_id: mobInst.mobDef.id },
                  'boss_killed_dot_run_completed',
                );
                this.disconnect();
              }
              break; // Exit mob loop — room is shutting down
            }

            const anyPlayerAlive = [...this.state.players.values()].some((p) => p.hp > 0);
            const anyMobAlive = [...this.mobInstances.values()].some(
              (m) => m.state !== AIState.DEAD && m.hp > 0,
            );
            if (!anyMobAlive && anyPlayerAlive) {
              this._roomStatus = 'COMPLETED';
              // W6-031: broadcast run_summary for DoT-kill terminal state.
              this._broadcastRunSummary('COMPLETED', this._currentFloor);
            }

            continue;
          }
        }
        // Prune expired statuses
        mobInst.statuses = filterActive(mobInst.statuses, nowMs);
      }

      // W5-023: stun blocks mob AI action
      if (isStunned(mobInst.statuses, nowMs)) {
        // Stay in current state, just don't act
        continue;
      }

      // W6-011: Boss enrage check (apply once when HP falls below threshold).
      if (
        mobInst.mobDef.is_boss &&
        !mobInst.enraged &&
        mobInst.mobDef.enrage_hp_threshold_pct > 0
      ) {
        const hpPct = mobInst.hp / mobInst.mobDef.base_hp;
        if (hpPct < mobInst.mobDef.enrage_hp_threshold_pct) {
          mobInst.enraged = true;
          log.info(
            {
              mob_id: mobInst.instanceId,
              hp: mobInst.hp,
              hp_pct: hpPct.toFixed(2),
            },
            'boss_enraged',
          );
        }
      }

      const observation = this.nearestPlayerTo(mobInst);
      const action = stepAi(mobInst, observation, nowMs);

      // W6-011: Handle boss summon pack if returned by stepAi.
      if (action.summonPack && action.summonPack.length > 0) {
        mobInst.lastSummonAtMs = nowMs;
        // Spawn adds at offset positions from boss
        const offsetPositions: Vec2[] = [
          { x: mobInst.position.x - 80, y: mobInst.position.y },
          { x: mobInst.position.x + 80, y: mobInst.position.y },
        ];
        const adds = spawnEncounter(this.rng, {
          floor: this._currentFloor,
          encounterIdx: this._tickCounter,
          spawnPositions: offsetPositions,
          mobPool: action.summonPack,
        });
        for (const add of adds) {
          const addKey = String(add.instanceId);
          const addSchema = new Mob();
          addSchema.id = add.mobDef.id;
          addSchema.instance_id = add.instanceId;
          addSchema.x = add.position.x;
          addSchema.y = add.position.y;
          addSchema.hp = add.hp;
          addSchema.maxHp = add.hp;
          addSchema.state = add.state;
          this.state.mobs.set(addKey, addSchema);
          this.mobInstances.set(addKey, add);
        }
        log.info(
          { mob_id: mobInst.instanceId, adds_count: adds.length },
          'boss_summoned_adds',
        );
      }

      // Apply action
      switch (action.kind) {
        case 'move': {
          if (action.moveTo) {
            const tx = action.moveTo.x - mobInst.position.x;
            const ty = action.moveTo.y - mobInst.position.y;
            const dist = Math.hypot(tx, ty);
            if (dist > 0.5) {
              const step = mobInst.mobDef.move_speed_px_s * dt;
              const nx = tx / dist;
              const ny = ty / dist;
              const dx = nx * Math.min(step, dist);
              const dy = ny * Math.min(step, dist);

              // Slide-along-wall for mobs (same as player)
              if (!collidesAt(mobInst.position.x + dx, mobInst.position.y + dy)) {
                mobInst.position.x += dx;
                mobInst.position.y += dy;
              } else {
                if (!collidesAt(mobInst.position.x + dx, mobInst.position.y)) {
                  mobInst.position.x += dx;
                }
                if (!collidesAt(mobInst.position.x, mobInst.position.y + dy)) {
                  mobInst.position.y += dy;
                }
              }

              // Sync schema
              schemaMob.x = mobInst.position.x;
              schemaMob.y = mobInst.position.y;
            }
          }
          break;
        }

        case 'charge': {
          // W6-010: Boss starts telegraph (charge phase).
          // Record attack start time so CD applies from here.
          mobInst.lastAttackAtMs = nowMs;
          mobInst.chargeUntilMs = nowMs + mobInst.mobDef.telegraph_ms;
          mobInst.targetPlayerId = action.targetPlayerId;
          log.debug(
            {
              mob_id: mobInst.instanceId,
              charge_until_ms: mobInst.chargeUntilMs,
            },
            'boss_charge_start',
          );
          break;
        }

        case 'attack': {
          // W5-022: apply mob attack damage
          // For boss: this fires at end of BOSS_CHARGING (strike phase).
          // lastAttackAtMs was already set when the charge began.
          if (mobInst.mobDef.is_boss && mobInst.state === AIState.BOSS_CHARGING) {
            // Strike fires — clear charge state; CD already recorded at charge start.
            mobInst.chargeUntilMs = 0;
          } else {
            mobInst.lastAttackAtMs = nowMs;
          }
          mobInst.targetPlayerId = action.targetPlayerId;
          if (action.targetPlayerId !== undefined) {
            this._applyMobAttack(mobInst, action.targetPlayerId);
          }
          log.debug(
            { mob_id: mobInst.instanceId, target_player_id: action.targetPlayerId },
            'mob_attack_intent',
          );
          break;
        }

        case 'idle':
          // No movement
          break;
      }

      // Update FSM state on both runtime instance and broadcast schema
      mobInst.state = action.nextState;
      if (action.targetPlayerId !== undefined) {
        mobInst.targetPlayerId = action.targetPlayerId;
      }
      schemaMob.state = action.nextState;
    }
  }
}

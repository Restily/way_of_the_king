/**
 * Colyseus client wrapper для DungeonRoom.
 *
 * Подключается к комнате после успешного POST /dungeons/{id}/enter с
 * полученными ws_url + ws_token. Прокси над state-listeners — UI получает
 * callback'и при добавлении/удалении/обновлении player'ов в комнате.
 *
 * Client prediction для своего player'а реализован тонко: исходящий input
 * шлётся на сервер каждый input change; локальное render-position не ждёт
 * server confirmation (snappy UX). Reconciliation при server diff:
 *  - drift < TELEPORT_THRESHOLD: smooth lerp (вне scope этого модуля)
 *  - drift >= threshold: snap (server authoritative)
 */

import { Client, type Room } from 'colyseus.js';

export interface RemotePlayerSnapshot {
  sessionId: string;
  id: string;
  x: number;
  y: number;
  hp: number;
  maxHp: number;
  mana: number;
  maxMana: number;
  facing: string;
}

export interface MobSnapshot {
  instanceId: string;
  /** mob_def id ('skeleton_warrior', 'skeleton_archer', 'zombie'). */
  kind: string;
  x: number;
  y: number;
  hp: number;
  maxHp: number;
  /** AIState enum value — 0=IDLE. */
  state: number;
}

export interface RealtimeHandlers {
  /** Player добавлен в state (включая твоего собственного на onJoin). */
  onPlayerAdd?: (snapshot: RemotePlayerSnapshot) => void;
  /** Player обновлён (server pushed diff). */
  onPlayerUpdate?: (snapshot: RemotePlayerSnapshot) => void;
  /** Player ушёл из room. */
  onPlayerRemove?: (sessionId: string) => void;
  /** Mob появился в state (initial load + new spawns). */
  onMobAdd?: (m: MobSnapshot) => void;
  /** Mob обновлён (hp/position/state diff от сервера). */
  onMobUpdate?: (m: MobSnapshot) => void;
  /** Mob умер / удалён из room. */
  onMobRemove?: (instanceId: string) => void;
  /** Connection потерян (network drop / server kicked). */
  onLeave?: (code: number) => void;
}

export interface ConnectArgs {
  wsUrl: string;
  wsToken: string;
}

/** Скорость player'а — sync с realtime DungeonRoom. */
export const PLAYER_SPEED_PX_S = 140;

export interface RealtimeMetrics {
  /** Round-trip ping в мс (последний sample). */
  latencyMs: number;
  /** Количество inbound packets за последнюю секунду. */
  packetsPerSec: number;
  /** Количество outbound packets за последнюю секунду. */
  outboundPerSec: number;
}

const PING_INTERVAL_MS = 2000;

export class RealtimeConnection {
  private readonly client: Client;
  private room: Room | null = null;
  // Метрики для dev-overlay (W3-044). Не идут в state-listener — UI poll'ит
  // через getMetrics() со своей частотой, обычно раз в секунду.
  private latencyMs = 0;
  private inboundCount = 0;
  private outboundCount = 0;
  private lastSampleAt = Date.now();
  private inboundPerSec = 0;
  private outboundPerSec = 0;
  private pingTimer: ReturnType<typeof setInterval> | null = null;

  constructor(wsUrl: string) {
    this.client = new Client(wsUrl);
  }

  static async connect(
    args: ConnectArgs,
    handlers: RealtimeHandlers,
  ): Promise<RealtimeConnection> {
    const conn = new RealtimeConnection(args.wsUrl);
    await conn._join(args.wsToken, handlers);
    return conn;
  }

  private async _join(
    wsToken: string,
    handlers: RealtimeHandlers,
  ): Promise<void> {
    this.room = await this.client.joinOrCreate('dungeon', { token: wsToken });

    // Players MapSchema listeners.
    // Colyseus 0.16 schema callbacks API.
    this.room.state.players.onAdd((player: PlayerSchemaLike, sessionId: string) => {
      this._countInbound();
      handlers.onPlayerAdd?.(snapshotOf(sessionId, player));
      player.onChange?.(() => {
        this._countInbound();
        handlers.onPlayerUpdate?.(snapshotOf(sessionId, player));
      });
    });

    this.room.state.players.onRemove((_player: unknown, sessionId: string) => {
      this._countInbound();
      handlers.onPlayerRemove?.(sessionId);
    });

    // Mobs MapSchema listeners — mirrors players pattern above.
    this.room.state.mobs.onAdd((mob: MobSchemaLike, instanceId: string) => {
      this._countInbound();
      handlers.onMobAdd?.(mobSnapshotOf(instanceId, mob));
      mob.onChange?.(() => {
        this._countInbound();
        handlers.onMobUpdate?.(mobSnapshotOf(instanceId, mob));
      });
    });

    this.room.state.mobs.onRemove((_mob: unknown, instanceId: string) => {
      this._countInbound();
      handlers.onMobRemove?.(instanceId);
    });

    // pong message от сервера → ping latency. Server-side handler
    // отвечает на любое 'ping' немедленным 'pong' с echoed клиентским ts.
    this.room.onMessage('pong', (msg: { ts: number }) => {
      this._countInbound();
      const now = Date.now();
      this.latencyMs = Math.max(0, now - msg.ts);
    });

    this.room.onLeave((code) => {
      this._stopPing();
      handlers.onLeave?.(code);
    });

    this._startPing();
  }

  /**
   * Подписаться на произвольное Colyseus-сообщение от сервера (W6-031/033).
   *
   * Проксирует room.onMessage — должен вызываться после connect().
   * Если room ещё не создана — no-op (сообщение теряется).
   *
   * :param type: Имя сообщения (``"run_summary"`` | ``"floor_advanced"`` | ...).
   * :param callback: Handler получающий типизированный payload.
   */
  onMessage<T = unknown>(type: string, callback: (msg: T) => void): void {
    if (!this.room) return;
    this.room.onMessage(type, callback);
  }

  /** Шлёт нормализованный input vector серверу. */
  sendInput(x: number, y: number, seq?: number): void {
    if (!this.room) return;
    this.room.send('input', { x, y, seq });
    this._countOutbound();
  }

  /**
   * Шлёт каст скилла серверу (W5-020/041).
   *
   * Сервер всегда требует мировые target_x/target_y — для single-target
   * клиент передаёт world-position моба, для AoE — точку тапа.
   *
   * :param skillId: Canonical skill id ('cleave' | 'shield_bash' | ...).
   * :param target: Мировые координаты цели.
   */
  sendCast(skillId: string, target: { targetX: number; targetY: number }): void {
    if (!this.room) return;
    this.room.send('cast', {
      skill_id: skillId,
      target_x: target.targetX,
      target_y: target.targetY,
    });
    this._countOutbound();
  }

  get sessionId(): string {
    return this.room?.sessionId ?? '';
  }

  /**
   * Снять текущие метрики для dev-overlay.
   *
   * Calling this also rolls inbound/outbound rate window. Не вызывать
   * чаще чем раз в секунду — иначе rate'ы будут дёргаться.
   */
  getMetrics(): RealtimeMetrics {
    const now = Date.now();
    const elapsedSec = Math.max(0.001, (now - this.lastSampleAt) / 1000);
    if (elapsedSec >= 1) {
      this.inboundPerSec = Math.round(this.inboundCount / elapsedSec);
      this.outboundPerSec = Math.round(this.outboundCount / elapsedSec);
      this.inboundCount = 0;
      this.outboundCount = 0;
      this.lastSampleAt = now;
    }
    return {
      latencyMs: this.latencyMs,
      packetsPerSec: this.inboundPerSec,
      outboundPerSec: this.outboundPerSec,
    };
  }

  async leave(): Promise<void> {
    this._stopPing();
    await this.room?.leave();
    this.room = null;
  }

  private _startPing(): void {
    this.pingTimer = setInterval(() => {
      if (!this.room) return;
      this.room.send('ping', { ts: Date.now() });
      this._countOutbound();
    }, PING_INTERVAL_MS);
  }

  private _stopPing(): void {
    if (this.pingTimer !== null) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private _countInbound(): void {
    this.inboundCount += 1;
  }

  private _countOutbound(): void {
    this.outboundCount += 1;
  }
}

/** Минимальный shape player'а из Colyseus schema (без точного типа). */
interface PlayerSchemaLike {
  id: string;
  x: number;
  y: number;
  hp: number;
  maxHp: number;
  mana?: number;
  maxMana?: number;
  facing: string;
  onChange?: (cb: () => void) => void;
}

function snapshotOf(sessionId: string, p: PlayerSchemaLike): RemotePlayerSnapshot {
  return {
    sessionId,
    id: p.id,
    x: p.x,
    y: p.y,
    hp: p.hp,
    maxHp: p.maxHp,
    mana: p.mana ?? 0,
    maxMana: p.maxMana ?? 0,
    facing: p.facing,
  };
}

/** Минимальный shape моба из Colyseus schema (без точного типа). */
interface MobSchemaLike {
  id: string;
  instance_id: number;
  x: number;
  y: number;
  hp: number;
  maxHp: number;
  state: number;
  onChange?: (cb: () => void) => void;
}

function mobSnapshotOf(instanceId: string, m: MobSchemaLike): MobSnapshot {
  return {
    instanceId,
    kind: m.id,
    x: m.x,
    y: m.y,
    hp: m.hp,
    maxHp: m.maxHp,
    state: m.state,
  };
}

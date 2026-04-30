/**
 * WorldState schema — Colyseus авто-синхронизирует diffs клиенту.
 *
 * Player в MapSchema (key=session_id) — клиенты увидят появление/уход других
 * игроков автоматически. Отдельные fields (x/y/hp/facing) триггерят diff на
 * каждом изменении — оптимизация (delta encoding) делается Colyseus'ом.
 *
 * Mob в MapSchema (key=instance_id string) — аналогично для мобов.
 * Mob.id содержит mob_def id ('skeleton_warrior'); Mob.state = AIState enum value.
 */

import { MapSchema, Schema, type } from '@colyseus/schema';

export class Player extends Schema {
  @type('string') id = '';
  @type('number') x = 0;
  @type('number') y = 0;
  @type('number') hp = 100;
  @type('number') maxHp = 100;
  @type('number') mana = 50;
  @type('number') maxMana = 50;
  @type('string') facing = 'south'; // south/north/east/west
}

export class Mob extends Schema {
  /** mob_def id ('skeleton_warrior', 'skeleton_archer', 'zombie'). */
  @type('string') id = '';
  /** Matches MobInstance.instanceId; used as MapSchema key too. */
  @type('uint32') instance_id = 0;
  @type('number') x = 0;
  @type('number') y = 0;
  @type('number') hp = 0;
  @type('number') maxHp = 0;
  /** AIState enum value — 0=IDLE, 1=CHASE, 2=ATTACK, 3=RETURN. */
  @type('uint8') state = 0;
}

export class WorldState extends Schema {
  @type({ map: Player }) players = new MapSchema<Player>();
  @type({ map: Mob }) mobs = new MapSchema<Mob>();
  @type('number') currentFloor = 0;
}

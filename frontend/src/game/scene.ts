/**
 * Сборка Pixi-сцены: world container, рендер комнаты, player, ticker, camera follow.
 *
 * Не использует assets — все формы через PIXI.Graphics. Когда появятся
 * sprite packs / Tiled JSON — этот модуль будет переписан, но интерфейс
 * (createScene → setInput/resize/loadRoom/destroy) останется тем же.
 */

import { Application, Container, Graphics, Text, TextStyle, Ticker } from 'pixi.js';

import { playSfx } from '../audio/sfx';
import { Player } from './Player';
import { buildTestRoom, type Room, type RoomId } from './room';
import type { Vec2 } from './types';

/** Rarity-визуализация для лут-иконок на полу (только visual feedback). */
export type LootRarity = 0 | 1 | 2 | 3 | 4;

export interface SceneController {
  /** Установить вектор движения от внешнего источника (joystick / keyboard). */
  setInput(input: Vec2): void;
  /** Изменить размер canvas'а (поворот девайса, full-screen toggle). */
  resize(width: number, height: number): void;
  /** Сменить layout комнаты, переспавнить player на новой spawn. */
  loadRoom(id: RoomId): void;
  /** Добавить/обновить remote player (server-driven). */
  upsertRemotePlayer(sessionId: string, x: number, y: number): void;
  /** Удалить remote player'а (он покинул комнату). */
  removeRemotePlayer(sessionId: string): void;
  /** Добавить или обновить моба (server-driven, schema diff). */
  upsertMob(instanceId: string, kind: string, x: number, y: number, hp: number, maxHp: number): void;
  /** Убрать моба из сцены (смерть / despawn). */
  removeMob(instanceId: string): void;
  /**
   * Reconcile своего player'а к server-state.
   *
   * * drift < TELEPORT_THRESHOLD → smooth lerp за следующие frames (без skip)
   * * drift ≥ TELEPORT_THRESHOLD → snap (server authoritative, клиент уехал)
   *
   * Caller вызывает на каждом server diff player'а с его sessionId.
   */
  reconcileOwnPlayer(serverX: number, serverY: number): void;
  /** Текущая позиция своего player'а (для UI / debug). */
  getOwnPlayerPosition(): Vec2;
  /**
   * Заспавнить иконку лута на полу (W5-050).
   *
   * Иконка исчезает через `autoRemoveMs` мс или по тапу.
   * Это только visual feedback — реальный предмет создаётся сервером при finalize.
   *
   * :param x: Мировые координаты X.
   * :param y: Мировые координаты Y.
   * :param rarity: Визуальная редкость (0=common … 4=legendary).
   * :param autoRemoveMs: Время авто-исчезания в мс (по умолчанию 8000).
   * :returns: Уникальный id иконки для ручного removeLootIcon().
   */
  spawnLootIcon(x: number, y: number, rarity: LootRarity, autoRemoveMs?: number): string;
  /**
   * Убрать иконку лута по id (fade-out анимация).
   *
   * :param iconId: Id, возвращённый spawnLootIcon.
   */
  removeLootIcon(iconId: string): void;
  /**
   * Заспавнить всплывающее число урона над мобом (W5-042).
   *
   * Анимация: текст движется вверх ~40px за 600ms, alpha → 0, затем destroy.
   *
   * :param worldX: Мировые координаты X (центр моба).
   * :param worldY: Мировые координаты Y (центр моба).
   * :param value: Значение урона для отображения.
   */
  spawnDamageNumber(worldX: number, worldY: number, value: number): void;
  /**
   * Hit-test по экранным координатам — возвращает instanceId ближайшего моба
   * в радиусе HIT_RADIUS пикселей (экранные), или null если не нашли (W5-041).
   *
   * :param screenX: Экранная координата X (pointer event clientX).
   * :param screenY: Экранная координата Y (pointer event clientY).
   * :returns: instanceId моба или null.
   */
  hitTestMob(screenX: number, screenY: number): string | null;
  /**
   * Конвертировать экранные координаты в мировые (W5-041 AoE tap-to-cast).
   *
   * :param screenX: Экранная координата X.
   * :param screenY: Экранная координата Y.
   * :returns: Мировые координаты.
   */
  screenToWorld(screenX: number, screenY: number): Vec2;
  /**
   * Обновить HP своего player'а (W5-043).
   *
   * :param hp: Текущий HP.
   * :param maxHp: Максимальный HP.
   */
  updateOwnPlayerHp(hp: number, maxHp: number): void;
  /**
   * Получить текущую rendered-позицию моба (для loot-icon spawn после смерти).
   *
   * :param instanceId: Идентификатор моба.
   * :returns: Мировые координаты или ``null`` если моб не известен.
   */
  getMobPosition(instanceId: string): Vec2 | null;
  /**
   * Заспавнить gore-эффект частиц в точке смерти моба (W6-044).
   *
   * 8 кружков разлетаются в случайных направлениях с fade-out за ~400ms.
   *
   * :param worldX: Мировые координаты X (центр моба).
   * :param worldY: Мировые координаты Y (центр моба).
   */
  spawnDeathBurst(worldX: number, worldY: number): void;
  /** Полный teardown — снимает ticker, destroy'ит Application. Идемпотентно. */
  destroy(): void;
}

export interface CreateSceneArgs {
  canvasContainer: HTMLElement;
  width: number;
  height: number;
  initialRoom?: RoomId;
}

/** Цвета иконок лута по rarity (visual only, W5-050). */
const LOOT_COLORS: Record<number, number> = {
  0: 0xaaaaaa, // common — серый
  1: 0x5555ff, // magic — синий
  2: 0xffdd00, // rare — жёлтый
  3: 0xaa00ff, // epic — фиолетовый
  4: 0xff8800, // legendary — оранжевый
};

/** Fill colors per mob kind. Key '_default' is the fallback. */
const MOB_COLORS: Record<string, number> = {
  skeleton_warrior: 0xb0b0b0,
  skeleton_archer: 0xa0c8a0,
  zombie: 0x6c8a4a,
  _default: 0x808080,
};

/**
 * Кэшированные стили для damage-numbers — иначе TextStyle аллоцируется
 * на каждый удар (whirlwind по 5 мобам = 5 styles за тик).
 */
const DAMAGE_STYLE_NORMAL = new TextStyle({
  fontSize: 16,
  fontWeight: 'bold',
  fill: '#ffdd44',
  dropShadow: { color: '#000', blur: 3, distance: 1 },
});
const DAMAGE_STYLE_HIGH = new TextStyle({
  fontSize: 16,
  fontWeight: 'bold',
  fill: '#ff4444',
  dropShadow: { color: '#000', blur: 3, distance: 1 },
});

/** Цвет gore-частиц — тёмно-красный (W6-044). */
const DEATH_BURST_COLOR = 0xc23a3a;
/** Длительность анимации gore-burst в мс. */
const DEATH_BURST_DURATION_MS = 400;
/** Количество частиц на один burst. */
const DEATH_BURST_COUNT = 8;
/** Максимальная скорость частицы в px/мс мировых координат. */
const DEATH_BURST_SPEED = 0.12;

export async function createScene(args: CreateSceneArgs): Promise<SceneController> {
  const app = new Application();
  await app.init({
    width: args.width,
    height: args.height,
    background: 0x1a1614,
    antialias: true,
    autoDensity: true,
    resolution: window.devicePixelRatio || 1,
  });
  args.canvasContainer.appendChild(app.canvas);

  // Mutable viewport — обновляется через resize(), читается в tick.
  const viewport = { w: args.width, h: args.height };

  // Mutable room — пересоздаётся через loadRoom(). Player и worldGfx тоже
  // живут как mutable refs.
  const world = new Container();
  app.stage.addChild(world);

  let room: Room = buildTestRoom(args.initialRoom ?? 'default');
  let roomGfx: Container = renderRoomGfx(room);
  world.addChild(roomGfx);

  let player: Player = new Player(room.spawn);
  world.addChild(player.view);

  // Remote players (server-driven). Render как простые circles разного цвета —
  // collision/AI на сервере, у клиента только smooth lerp к target position.
  const remotes = new Map<string, { gfx: Graphics; targetX: number; targetY: number }>();

  // Mobs (server-driven). Container per mob: circle body + HP bar (bg + fg).
  // Lerp к target position аналогично remote players (12-frame catchup).
  const mobs = new Map<
    string,
    { container: Container; hpFg: Graphics; targetX: number; targetY: number; maxHp: number }
  >();

  // Damage numbers (W5-042). Всплывающие тексты урона в мировых координатах.
  // Каждая запись: text-объект + timestamp создания + стартовый Y.
  const damageNumbers: Array<{ text: Text; startY: number; createdAt: number }> = [];
  /** Длительность анимации числа урона в мс. */
  const DAMAGE_NUMBER_DURATION_MS = 650;
  /** Расстояние всплытия числа урона в px мировых координат. */
  const DAMAGE_NUMBER_RISE_PX = 44;

  // Gore-частицы (W6-044). Разлетаются при смерти моба, fade-out за ~400ms.
  // Каждая запись: Graphics-кружок + вектор скорости + timestamp создания.
  const deathBursts: Array<{
    gfx: Graphics;
    vx: number;
    vy: number;
    createdAt: number;
  }> = [];

  const spawnDamageNumber = (worldX: number, worldY: number, value: number): void => {
    const txt = new Text({
      text: String(value),
      style: value >= 50 ? DAMAGE_STYLE_HIGH : DAMAGE_STYLE_NORMAL,
    });
    txt.anchor.set(0.5, 1);
    txt.x = worldX;
    txt.y = worldY;
    world.addChild(txt);
    damageNumbers.push({ text: txt, startY: worldY, createdAt: performance.now() });
  };

  /** Заспавнить 8 gore-частиц разлёта в точке смерти моба (W6-044). */
  const spawnDeathBurst = (worldX: number, worldY: number): void => {
    const now = performance.now();
    for (let i = 0; i < DEATH_BURST_COUNT; i++) {
      const angle = (i / DEATH_BURST_COUNT) * Math.PI * 2;
      // Небольшая рандомизация радиуса — не идеально равномерный взрыв.
      const speed = DEATH_BURST_SPEED * (0.6 + Math.random() * 0.8);
      const gfx = new Graphics();
      gfx.circle(0, 0, 3).fill(DEATH_BURST_COLOR);
      gfx.x = worldX;
      gfx.y = worldY;
      world.addChild(gfx);
      deathBursts.push({
        gfx,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        createdAt: now,
      });
    }
  };

  // HP-бар своего player'а. Отрисован в world-координатах поверх спрайта.
  const ownHpBg = new Graphics();
  ownHpBg.rect(-14, -20, 28, 4).fill(0x4a1010);
  const ownHpFg = new Graphics();
  ownHpFg.rect(-14, -20, 28, 4).fill(0x40c040);
  world.addChild(ownHpBg);
  world.addChild(ownHpFg);

  // Текущий HP мобов — нужен для определения HP-decrease → spawn damage number.
  const mobHpPrev = new Map<string, number>();

  // Loot icons (W5-050). Визуальные иконки на полу после убийства моба.
  // Хранят alpha для fade-out анимации и таймер авто-исчезания.
  const lootIcons = new Map<
    string,
    { gfx: Graphics; fadeOutAt: number | null; fadingOut: boolean }
  >();
  let lootIconCounter = 0;

  // Client prediction state для своего player'а:
  //   * own player двигается локально (snappy UX)
  //   * server periodically diff'ит реальную позицию
  //   * при drift < TELEPORT_THRESHOLD — медленно стягиваем к server position
  //   * при drift ≥ threshold — snap (rubber-band, server authoritative)
  const TELEPORT_THRESHOLD = 30;
  // RECONCILE_RATE: доля drift'а компенсируемая за tick (0..1).
  // 0.18 ≈ 80% drift убирается за ~10 frames @ 60FPS = 167ms.
  const RECONCILE_RATE = 0.18;
  let reconcileTargetX: number | null = null;
  let reconcileTargetY: number | null = null;

  const input: Vec2 = { x: 0, y: 0 };

  const tick = (ticker: Ticker): void => {
    const dtSec = ticker.deltaMS / 1000;
    player.update(input, dtSec, room.walls);

    // Reconcile own player к server target (если есть).
    if (reconcileTargetX !== null && reconcileTargetY !== null) {
      const dx = reconcileTargetX - player.position.x;
      const dy = reconcileTargetY - player.position.y;
      player.position.x += dx * RECONCILE_RATE;
      player.position.y += dy * RECONCILE_RATE;
      player.view.position.set(player.position.x, player.position.y);
      // Когда стянулись достаточно близко — снимаем reconcile, иначе вечный
      // micro-tug приводит к jittery движению.
      if (Math.hypot(dx, dy) < 1) {
        reconcileTargetX = null;
        reconcileTargetY = null;
      }
    }

    // Remote players: smooth lerp к server target (12-frame catchup ≈ 200ms).
    for (const r of remotes.values()) {
      const dx = r.targetX - r.gfx.x;
      const dy = r.targetY - r.gfx.y;
      r.gfx.x += dx * Math.min(1, dtSec * 12);
      r.gfx.y += dy * Math.min(1, dtSec * 12);
    }

    // Mobs: same 12-frame lerp pattern as remote players.
    for (const m of mobs.values()) {
      const dx = m.targetX - m.container.x;
      const dy = m.targetY - m.container.y;
      m.container.x += dx * Math.min(1, dtSec * 12);
      m.container.y += dy * Math.min(1, dtSec * 12);
    }

    // Damage numbers: движение вверх + fade (W5-042).
    const now = performance.now();
    for (let i = damageNumbers.length - 1; i >= 0; i--) {
      const dn = damageNumbers[i];
      const elapsed = now - dn.createdAt;
      const progress = Math.min(1, elapsed / DAMAGE_NUMBER_DURATION_MS);
      dn.text.y = dn.startY - DAMAGE_NUMBER_RISE_PX * progress;
      dn.text.alpha = 1 - progress;
      if (progress >= 1) {
        world.removeChild(dn.text);
        dn.text.destroy();
        damageNumbers.splice(i, 1);
      }
    }

    // Gore-burst: радиальный разлёт частиц + fade (W6-044).
    for (let i = deathBursts.length - 1; i >= 0; i--) {
      const db = deathBursts[i];
      const elapsed = now - db.createdAt;
      const progress = Math.min(1, elapsed / DEATH_BURST_DURATION_MS);
      // Движение пропорционально elapsed (независимо от dtSec для точности).
      db.gfx.x += db.vx * ticker.deltaMS;
      db.gfx.y += db.vy * ticker.deltaMS;
      db.gfx.alpha = 1 - progress;
      if (progress >= 1) {
        world.removeChild(db.gfx);
        db.gfx.destroy();
        deathBursts.splice(i, 1);
      }
    }

    // Обновляем позицию HP-бара своего player'а вслед за спрайтом.
    ownHpBg.x = player.position.x;
    ownHpBg.y = player.position.y;
    ownHpFg.x = player.position.x;
    ownHpFg.y = player.position.y;

    // Loot icons: fade-out анимация и авто-удаление по таймеру (W5-050).
    for (const [iconId, icon] of lootIcons) {
      // Запускаем fade если пришло время авто-исчезания.
      if (icon.fadeOutAt !== null && now >= icon.fadeOutAt && !icon.fadingOut) {
        icon.fadingOut = true;
      }
      if (icon.fadingOut) {
        icon.gfx.alpha = Math.max(0, icon.gfx.alpha - dtSec * 2.5);
        if (icon.gfx.alpha <= 0) {
          world.removeChild(icon.gfx);
          icon.gfx.destroy();
          lootIcons.delete(iconId);
        }
      }
    }

    centerCameraOn(world, player.position, viewport.w, viewport.h, room);
  };
  app.ticker.add(tick);

  return {
    setInput(next: Vec2): void {
      // Change-detection: nipplejs/keyboard сэмплят при каждом event'е,
      // непрерывное удержание шлёт ~60+ событий/сек с одинаковым vector'ом.
      if (next.x === input.x && next.y === input.y) return;
      input.x = next.x;
      input.y = next.y;
    },
    resize(width: number, height: number): void {
      if (width === viewport.w && height === viewport.h) return;
      viewport.w = width;
      viewport.h = height;
      app.renderer.resize(width, height);
    },
    loadRoom(id: RoomId): void {
      world.removeChild(roomGfx);
      roomGfx.destroy({ children: true });
      world.removeChild(player.view);

      room = buildTestRoom(id);
      roomGfx = renderRoomGfx(room);
      // roomGfx ниже player'а в z-order — добавляем первым.
      world.addChildAt(roomGfx, 0);

      player = new Player(room.spawn);
      world.addChild(player.view);
    },
    upsertRemotePlayer(sessionId: string, x: number, y: number): void {
      let r = remotes.get(sessionId);
      if (!r) {
        const gfx = new Graphics();
        gfx.circle(0, 0, 12).fill(0xc23a3a).stroke({ width: 2, color: 0x6a1a1a });
        gfx.x = x;
        gfx.y = y;
        world.addChild(gfx);
        r = { gfx, targetX: x, targetY: y };
        remotes.set(sessionId, r);
      } else {
        r.targetX = x;
        r.targetY = y;
      }
    },
    removeRemotePlayer(sessionId: string): void {
      const r = remotes.get(sessionId);
      if (!r) return;
      world.removeChild(r.gfx);
      r.gfx.destroy();
      remotes.delete(sessionId);
    },
    upsertMob(instanceId: string, kind: string, x: number, y: number, hp: number, maxHp: number): void {
      const existing = mobs.get(instanceId);
      if (!existing) {
        // Build container: circle body + HP bar (bg rect + fg rect).
        const container = new Container();

        const body = new Graphics();
        const fillColor = MOB_COLORS[kind] ?? MOB_COLORS._default;
        body.circle(0, 0, 11).fill(fillColor);
        container.addChild(body);

        const hpBg = new Graphics();
        hpBg.rect(-12, -16, 24, 3).fill(0x4a1010);
        container.addChild(hpBg);

        const hpFg = new Graphics();
        const fgWidth = maxHp > 0 ? 24 * (hp / maxHp) : 0;
        hpFg.rect(-12, -16, fgWidth, 3).fill(0x40c040);
        container.addChild(hpFg);

        container.x = x;
        container.y = y;
        world.addChild(container);
        mobs.set(instanceId, { container, hpFg, targetX: x, targetY: y, maxHp });
        mobHpPrev.set(instanceId, hp);
      } else {
        const prevHp = mobHpPrev.get(instanceId) ?? hp;
        const damage = prevHp - hp;
        if (damage > 0) {
          spawnDamageNumber(
            existing.container.x,
            existing.container.y - 14,
            damage,
          );
        }
        mobHpPrev.set(instanceId, hp);

        existing.targetX = x;
        existing.targetY = y;
        existing.maxHp = maxHp;
        existing.hpFg.clear();
        const fgWidth = maxHp > 0 ? 24 * (hp / maxHp) : 0;
        existing.hpFg.rect(-12, -16, fgWidth, 3).fill(0x40c040);
      }
    },
    removeMob(instanceId: string): void {
      const m = mobs.get(instanceId);
      if (!m) return;
      world.removeChild(m.container);
      m.container.destroy(true);
      mobs.delete(instanceId);
    },
    reconcileOwnPlayer(serverX: number, serverY: number): void {
      const drift = Math.hypot(
        serverX - player.position.x,
        serverY - player.position.y,
      );
      if (drift >= TELEPORT_THRESHOLD) {
        // Snap (rubber-band): клиент ушёл слишком далеко — server authoritative.
        player.position.x = serverX;
        player.position.y = serverY;
        player.view.position.set(serverX, serverY);
        reconcileTargetX = null;
        reconcileTargetY = null;
      } else {
        // Smooth lerp за следующие frames — ставим target, tick подберёт.
        reconcileTargetX = serverX;
        reconcileTargetY = serverY;
      }
    },
    getOwnPlayerPosition(): Vec2 {
      return { x: player.position.x, y: player.position.y };
    },
    spawnLootIcon(x: number, y: number, rarity: LootRarity, autoRemoveMs = 8000): string {
      const iconId = `loot_${++lootIconCounter}`;
      const color = LOOT_COLORS[rarity] ?? LOOT_COLORS[0];

      const gfx = new Graphics();
      // Ромб = лут-иконка (отличается от round mob/player кружков).
      gfx.poly([0, -8, 8, 0, 0, 8, -8, 0]).fill(color).stroke({ width: 1.5, color: 0xffffff, alpha: 0.5 });
      gfx.x = x;
      gfx.y = y;
      gfx.alpha = 1;
      gfx.eventMode = 'static';
      gfx.cursor = 'pointer';
      gfx.on('pointertap', () => {
        // Тап → начать fade (W5-050 manual pickup visual).
        const icon = lootIcons.get(iconId);
        if (icon && !icon.fadingOut) {
          icon.fadingOut = true;
          playSfx('item_pickup');
        }
      });
      world.addChild(gfx);

      lootIcons.set(iconId, {
        gfx,
        fadeOutAt: performance.now() + autoRemoveMs,
        fadingOut: false,
      });

      playSfx('item_drop');
      return iconId;
    },
    removeLootIcon(iconId: string): void {
      const icon = lootIcons.get(iconId);
      if (icon && !icon.fadingOut) {
        icon.fadingOut = true;
      }
    },
    spawnDamageNumber,
    hitTestMob(screenX: number, screenY: number): string | null {
      // Конвертируем экранные coords → мировые, затем ищем ближайшего моба.
      const worldX = screenX - world.x;
      const worldY = screenY - world.y;
      /** Максимальный радиус попадания в экранных (= мировых) пикселях. */
      const HIT_RADIUS = 28;
      let closest: string | null = null;
      let closestDist = HIT_RADIUS;
      for (const [instanceId, m] of mobs) {
        const dist = Math.hypot(m.container.x - worldX, m.container.y - worldY);
        if (dist < closestDist) {
          closestDist = dist;
          closest = instanceId;
        }
      }
      return closest;
    },
    screenToWorld(screenX: number, screenY: number): Vec2 {
      return {
        x: screenX - world.x,
        y: screenY - world.y,
      };
    },
    updateOwnPlayerHp(hp: number, maxHp: number): void {
      ownHpFg.clear();
      const fgWidth = maxHp > 0 ? 28 * (hp / maxHp) : 0;
      ownHpFg.rect(-14, -20, fgWidth, 4).fill(hp / maxHp < 0.3 ? 0xe03030 : 0x40c040);
    },
    getMobPosition(instanceId: string): Vec2 | null {
      const m = mobs.get(instanceId);
      return m ? { x: m.container.x, y: m.container.y } : null;
    },
    spawnDeathBurst,
    destroy(): void {
      app.ticker.remove(tick);
      app.destroy(true, { children: true, texture: true });
    },
  };
}

/**
 * Рендер пола + grid + стен в одном Container — иначе loadRoom не сможет
 * атомарно убрать предыдущую комнату.
 */
function renderRoomGfx(room: Room): Container {
  const c = new Container();

  const floor = new Graphics();
  floor.rect(0, 0, room.width, room.height).fill(0x2c2419);
  c.addChild(floor);

  const grid = new Graphics();
  for (let x = room.tileSize; x < room.width; x += room.tileSize) {
    grid.moveTo(x, 0).lineTo(x, room.height);
  }
  for (let y = room.tileSize; y < room.height; y += room.tileSize) {
    grid.moveTo(0, y).lineTo(room.width, y);
  }
  grid.stroke({ width: 1, color: 0x352c20, alpha: 0.6 });
  c.addChild(grid);

  const walls = new Graphics();
  for (const w of room.walls) {
    walls.rect(w.x, w.y, w.w, w.h);
  }
  walls.fill(0x6b5840).stroke({ width: 1, color: 0x4a3d2c });
  c.addChild(walls);

  return c;
}

/**
 * Camera follow: сдвигает world так, чтобы player был в центре экрана.
 * Clamp по краям комнаты — если карта меньше viewport, центрируем.
 */
function centerCameraOn(
  world: Container,
  target: Vec2,
  viewW: number,
  viewH: number,
  room: Room,
): void {
  let x = viewW / 2 - target.x;
  let y = viewH / 2 - target.y;

  if (room.width <= viewW) {
    x = (viewW - room.width) / 2;
  } else {
    x = Math.max(viewW - room.width, Math.min(0, x));
  }
  if (room.height <= viewH) {
    y = (viewH - room.height) / 2;
  } else {
    y = Math.max(viewH - room.height, Math.min(0, y));
  }

  world.position.set(x, y);
}

/**
 * Playground — экран dungeon (offline test rooms или online через Colyseus).
 *
 * Mode-state определяет режим. Online режим включает обмен input/state с
 * Colyseus DungeonRoom; offline — чистая клиентская симуляция.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { type CampaignLocationInfo, getCampaign } from '../api/campaign';
import {
  type DungeonInfo,
  enterDungeon,
  fleeRun,
  listDungeons,
} from '../api/dungeons';
import type { RunSummaryDTO } from '../api/runs';
import { playSfx } from '../audio/sfx';
import { DeathScreen } from '../components/DeathScreen';
import { FloorClearedToast } from '../components/FloorClearedToast';
import { Hotbar, type HotbarSkill } from '../components/Hotbar';
import { Joystick } from '../components/Joystick';
import { RealtimeConnection } from '../game/realtime';
import { ROOMS, type RoomId } from '../game/room';
import { createScene, type SceneController } from '../game/scene';
import type { Vec2 } from '../game/types';
import { RunSummaryScreen } from './RunSummaryScreen';

/**
 * Knight skills для hotbar — id и cooldown_ms должны быть синхронны с
 * `realtime/src/game/skills.ts` (KNIGHT_SKILLS) и Python `wotk/game/skills.py`.
 * Используем 4 active skill'а в порядке отображения слева направо.
 */
const HOTBAR_SKILLS: HotbarSkill[] = [
  { id: 'cleave', cooldownMs: 800 },
  { id: 'shield_bash', cooldownMs: 6000 },
  { id: 'whirlwind', cooldownMs: 12000 },
  { id: 'charge', cooldownMs: 8000 },
];

/**
 * AoE-скиллы требуют ground-target (target_x/target_y), single-target — мобa.
 * Источник истины — KNIGHT_SKILLS.aoeRadiusPx > 0 ⇒ AoE.
 */
const AOE_SKILLS = new Set<string>(['cleave', 'whirlwind']);

export interface PlaygroundProps {
  onExit: () => void;
  /** Callback при успешном возврате из данжа — City покажет badge "new items". */
  onDungeonComplete?: () => void;
  /**
   * W6-024: данные для автоматического входа в данж (из экрана Campaign).
   * Если передан — Playground сразу переходит в online-режим с этим run'ом.
   */
  pendingEnter?: {
    runId: string;
    wsUrl: string;
    wsToken: string;
    dungeonId: string;
  };
  /** Callback вызываемый после потребления pendingEnter (чтобы App обнулил state). */
  onPendingEnterConsumed?: () => void;
  /**
   * W6-034: Callback вызываемый при возврате из данжа с xpGained > 0.
   * City использует это для анимации XP bar.
   */
  onReturnWithXp?: (xpGained: number) => void;
}

const ROOM_IDS = Object.keys(ROOMS) as RoomId[];

type Mode =
  | { kind: 'menu' }
  | { kind: 'offline'; room: RoomId }
  | {
      kind: 'online';
      runId: string;
      dungeon: DungeonInfo;
      wsUrl: string;
      wsToken: string;
    };

export function Playground({
  onExit,
  onDungeonComplete,
  pendingEnter,
  onPendingEnterConsumed,
  onReturnWithXp,
}: PlaygroundProps) {
  const { t } = useTranslation();
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const realtimeRef = useRef<RealtimeConnection | null>(null);
  const keyInputRef = useRef<Vec2>({ x: 0, y: 0 });
  const joyInputRef = useRef<Vec2>({ x: 0, y: 0 });
  const inputSeqRef = useRef(0);
  // Last sent (x,y) для дедупа sendInput — keyboard auto-repeat и nipplejs
  // move шлют 30-60 events/sec с одинаковым vector'ом.
  const lastSentRef = useRef<Vec2>({ x: 0, y: 0 });
  const [scene, setScene] = useState<SceneController | null>(null);
  const [mode, setMode] = useState<Mode>({ kind: 'menu' });
  const [dungeons, setDungeons] = useState<DungeonInfo[]>([]);
  // W6-024: список кампанийных локаций (разблокированные).
  const [campaignLocations, setCampaignLocations] = useState<CampaignLocationInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Hotbar UX state (W5-040..041): выбранный скилл + map id → endsAt timestamp.
  const [activeSkillId, setActiveSkillId] = useState<string | null>(null);
  const [cooldownEndsAt, setCooldownEndsAt] = useState<Map<string, number>>(
    () => new Map(),
  );
  // Death overlay (W5-044): показываем когда server diff'нул hp <= 0 для своего player'а.
  const [isDead, setIsDead] = useState(false);
  // W6-031: RunSummaryScreen — показываем когда server прислал run_summary WS-сообщение.
  const [runSummary, setRunSummary] = useState<RunSummaryDTO | null>(null);
  // W6-033: floor_advanced toast state.
  interface FloorToast { floor: number; total: number; key: number }
  const [floorToast, setFloorToast] = useState<FloorToast | null>(null);
  const floorToastKeyRef = useRef(0);

  // W6-024: загружаем unlocked кампанийные данжи + fallback на listDungeons.
  useEffect(() => {
    void (async () => {
      try {
        const [campaignResult, dungeonsResult] = await Promise.allSettled([
          getCampaign(),
          listDungeons(),
        ]);
        if (campaignResult.status === 'fulfilled') {
          setCampaignLocations(campaignResult.value.filter((l) => !l.is_locked));
        }
        if (dungeonsResult.status === 'fulfilled') {
          setDungeons(dungeonsResult.value.dungeons);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'list_failed');
      }
    })();
  }, []);

  // W6-024: если пришёл pendingEnter из Campaign — сразу входим в данж.
  useEffect(() => {
    if (!pendingEnter) return;
    // Ищем данж в загруженном списке для DungeonInfo; если не нашли — используем заглушку.
    const dungeon: DungeonInfo = dungeons.find((d) => d.id === pendingEnter.dungeonId) ?? {
      id: pendingEnter.dungeonId,
      name_key: `dungeon.${pendingEnter.dungeonId}.name`,
      theme: 0,
      difficulty: 0,
      min_level: 1,
      entry_cost_gold: 0,
      entry_cost_energy: 0,
      daily_limit: 0,
      floors_count: 5,
    };
    setMode({
      kind: 'online',
      runId: pendingEnter.runId,
      dungeon,
      wsUrl: pendingEnter.wsUrl,
      wsToken: pendingEnter.wsToken,
    });
    onPendingEnterConsumed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingEnter]);

  useEffect(() => {
    if (mode.kind === 'menu') return;
    const host = canvasHostRef.current;
    if (!host) return;
    let cancelled = false;
    let controller: SceneController | null = null;

    void (async () => {
      controller = await createScene({
        canvasContainer: host,
        width: window.innerWidth,
        height: window.innerHeight,
        initialRoom: mode.kind === 'offline' ? mode.room : 'arena',
      });
      if (cancelled) {
        controller.destroy();
        return;
      }
      setScene(controller);
    })();

    return () => {
      cancelled = true;
      controller?.destroy();
      setScene(null);
      // StrictMode double-mount cleanup: убираем всё что осталось.
      while (host.firstChild) host.removeChild(host.firstChild);
    };
  }, [mode.kind, mode.kind === 'offline' ? mode.room : null]);

  useEffect(() => {
    if (mode.kind !== 'online' || scene === null) return;
    const { wsUrl, wsToken } = mode;
    let cancelled = false;

    void (async () => {
      try {
        const conn = await RealtimeConnection.connect(
          { wsUrl, wsToken },
          {
            onPlayerAdd: (p) => {
              if (p.sessionId === conn.sessionId) {
                // Authoritative начальная позиция от сервера.
                scene.reconcileOwnPlayer(p.x, p.y);
                return;
              }
              scene.upsertRemotePlayer(p.sessionId, p.x, p.y);
            },
            onPlayerUpdate: (p) => {
              if (p.sessionId === conn.sessionId) {
                // Reconcile drift: client prediction двигает локально,
                // server diff'ит реальное положение → подтянуть/снапнуть.
                scene.reconcileOwnPlayer(p.x, p.y);
                // HP bar для своего player'а (W5-043) + death overlay (W5-044).
                scene.updateOwnPlayerHp(p.hp, p.maxHp);
                if (p.hp <= 0) {
                  setIsDead(true);
                }
                return;
              }
              scene.upsertRemotePlayer(p.sessionId, p.x, p.y);
            },
            onPlayerRemove: (sid) => {
              scene.removeRemotePlayer(sid);
            },
            onMobAdd: (m) => {
              scene.upsertMob(m.instanceId, m.kind, m.x, m.y, m.hp, m.maxHp);
            },
            onMobUpdate: (m) => {
              scene.upsertMob(m.instanceId, m.kind, m.x, m.y, m.hp, m.maxHp);
            },
            onMobRemove: (instanceId) => {
              const pos = scene.getMobPosition(instanceId);
              if (pos) {
                // W6-044: gore-burst ДО removeMob — позиция ещё доступна.
                scene.spawnDeathBurst(pos.x, pos.y);
                scene.spawnLootIcon(pos.x, pos.y, 0);
              }
              playSfx('mob_death');
              scene.removeMob(instanceId);
            },
            onLeave: () => {
              setError('connection_lost');
            },
          },
        );
        if (cancelled) {
          await conn.leave();
          return;
        }

        // W6-031: listen for run_summary broadcast (terminal state before disconnect).
        conn.onMessage('run_summary', (msg: RunSummaryDTO) => {
          setRunSummary(msg);
        });

        // W6-033: listen for floor_advanced broadcast.
        conn.onMessage('floor_advanced', (msg: { floor: number; run_complete: boolean }) => {
          const currentMode = mode;
          const total = currentMode.kind === 'online' ? currentMode.dungeon.floors_count : 0;
          floorToastKeyRef.current += 1;
          setFloorToast({ floor: msg.floor, total, key: floorToastKeyRef.current });
        });

        realtimeRef.current = conn;
      } catch (e) {
        setError(e instanceof Error ? e.message : 'connect_failed');
      }
    })();

    return () => {
      cancelled = true;
      void realtimeRef.current?.leave();
      realtimeRef.current = null;
    };
  }, [mode.kind === 'online' ? mode.runId : null, scene]);

  useEffect(() => {
    const downKeys = new Set<string>();
    const recompute = () => {
      let x = 0;
      let y = 0;
      if (downKeys.has('a') || downKeys.has('arrowleft')) x -= 1;
      if (downKeys.has('d') || downKeys.has('arrowright')) x += 1;
      if (downKeys.has('w') || downKeys.has('arrowup')) y -= 1;
      if (downKeys.has('s') || downKeys.has('arrowdown')) y += 1;
      keyInputRef.current = { x, y };
      pushInput();
    };
    const onDown = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (downKeys.has(k)) return;
      downKeys.add(k);
      recompute();
    };
    const onUp = (e: KeyboardEvent) => {
      downKeys.delete(e.key.toLowerCase());
      recompute();
    };
    window.addEventListener('keydown', onDown);
    window.addEventListener('keyup', onUp);
    return () => {
      window.removeEventListener('keydown', onDown);
      window.removeEventListener('keyup', onUp);
    };
  }, []);

  useEffect(() => {
    const onResize = () => {
      scene?.resize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener('resize', onResize);
    window.addEventListener('orientationchange', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('orientationchange', onResize);
    };
  }, [scene]);

  const pushInput = () => {
    const k = keyInputRef.current;
    const j = joyInputRef.current;
    const useJoy = j.x !== 0 || j.y !== 0;
    const v = useJoy ? j : k;
    scene?.setInput(v);
    // Network dedupe — не шлём дубликаты (auto-repeat / continuous joystick).
    if (
      realtimeRef.current &&
      (v.x !== lastSentRef.current.x || v.y !== lastSentRef.current.y)
    ) {
      lastSentRef.current = { x: v.x, y: v.y };
      realtimeRef.current.sendInput(v.x, v.y, ++inputSeqRef.current);
    }
  };

  const handleJoy = (v: Vec2) => {
    joyInputRef.current = v;
    pushInput();
  };

  /**
   * Резолв тапа по миру (W5-041): если выбран AoE-скилл — кастуем по
   * ground point; если single-target — ищем моба в радиусе hit-test'а.
   *
   * Не передаём hover-feedback; UX cycle: tap hotbar → "highlighted" →
   * tap мира → cast → активный скилл сбрасывается. Если скилл на CD —
   * cast блокируется на сервере (silent ignore — UI уже показывает radial mask).
   */
  const handleWorldTap = (e: React.PointerEvent<HTMLDivElement>) => {
    if (mode.kind !== 'online' || !scene || !realtimeRef.current || !activeSkillId) {
      return;
    }
    // Hotbar и joystick — это child'ы playground'а. Не реагируем на тапы по
    // ним (event bubbling от button'ов).
    const target = e.target as HTMLElement;
    if (target.closest('.playground__hotbar') || target.closest('.playground__joystick')) {
      return;
    }
    const skillDef = HOTBAR_SKILLS.find((s) => s.id === activeSkillId);
    if (!skillDef) {
      setActiveSkillId(null);
      return;
    }
    // Сервер всегда требует target_x/target_y. Для AoE используем тап-точку,
    // для single-target резолвим world-pos моба по hit-test'у (сервер сам
    // выберет ближайшую цель в радиусе скилла).
    let targetX: number;
    let targetY: number;
    if (AOE_SKILLS.has(activeSkillId)) {
      const world = scene.screenToWorld(e.clientX, e.clientY);
      targetX = world.x;
      targetY = world.y;
    } else {
      const mobId = scene.hitTestMob(e.clientX, e.clientY);
      if (mobId === null) {
        return; // Не сбрасываем active — даём шанс попасть со второй попытки.
      }
      const mobPos = scene.getMobPosition(mobId);
      if (mobPos === null) return;
      targetX = mobPos.x;
      targetY = mobPos.y;
    }
    realtimeRef.current.sendCast(activeSkillId, { targetX, targetY });
    // W6-043: раздельные id per-skill — будущая аудио-система найдёт нужный ассет по id.
    playSfx(`${activeSkillId}_cast` as Parameters<typeof playSfx>[0]);
    // Оптимистичный CD на клиенте — сервер всё равно enforce'ит, но UX feedback мгновенный.
    setCooldownEndsAt((prev) => {
      const next = new Map(prev);
      next.set(activeSkillId, Date.now() + skillDef.cooldownMs);
      return next;
    });
    setActiveSkillId(null);
  };

  /** Тап по слоту hotbar'а — выбор активного скилла (W5-040). */
  const handleSelectSkill = (id: string) => {
    setActiveSkillId((cur) => (cur === id ? null : id));
  };

  /** Возврат в City после смерти (W5-044). */
  const handleDeathReturn = () => {
    setIsDead(false);
    setRunSummary(null);
    setMode({ kind: 'menu' });
  };

  /** W6-031: Continue → City после RunSummaryScreen. */
  const handleRunSummaryContinue = useCallback(() => {
    const xp = runSummary?.xp_earned ?? 0;
    setRunSummary(null);
    setMode({ kind: 'menu' });
    onDungeonComplete?.();
    if (xp > 0) onReturnWithXp?.(xp);
    onExit();
  }, [runSummary, onDungeonComplete, onReturnWithXp, onExit]);

  /** W6-033: dismiss floor toast. */
  const handleFloorToastDismiss = useCallback(() => setFloorToast(null), []);

  const handleEnterOnline = async (dungeon: DungeonInfo) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const idem = crypto.randomUUID();
      const r = await enterDungeon(dungeon.id, idem);
      setMode({
        kind: 'online',
        runId: r.run_id,
        dungeon: r.dungeon,
        wsUrl: r.ws_url,
        wsToken: r.ws_token,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'enter_failed');
    } finally {
      setBusy(false);
    }
  };

  const handleFlee = async () => {
    if (mode.kind !== 'online' || busy) return;
    setBusy(true);
    try {
      await fleeRun(mode.runId);
      // После завершения данжа — сигнализируем City о новых предметах (W5-053).
      onDungeonComplete?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'flee_failed');
    } finally {
      setBusy(false);
      setMode({ kind: 'menu' });
    }
  };

  // W6-024: предпочитаем unlocked кампанийные данжи; fallback на listDungeons.
  const dungeonItems = useMemo(() => {
    // Если есть кампанийные локации — показываем их (unlocked only).
    if (campaignLocations.length > 0) {
      return campaignLocations.map((loc) => {
        const dungeon: DungeonInfo = dungeons.find((d) => d.id === loc.dungeon_id) ?? {
          id: loc.dungeon_id,
          name_key: loc.name_key,
          theme: 0,
          difficulty: 0,
          min_level: 1,
          entry_cost_gold: 0,
          entry_cost_energy: 0,
          daily_limit: 0,
          floors_count: 5,
        };
        return {
          key: loc.dungeon_id,
          label: t(loc.name_key, { defaultValue: loc.dungeon_id }),
          hint: t('playground.entry_cost', {
            gold: dungeon.entry_cost_gold,
            energy: dungeon.entry_cost_energy,
          }),
          onClick: () => void handleEnterOnline(dungeon),
        };
      });
    }
    // Fallback: показываем все данжи из listDungeons (старый behavior).
    return dungeons.map((d) => ({
      key: d.id,
      label: d.id,
      hint: t('playground.entry_cost', {
        gold: d.entry_cost_gold,
        energy: d.entry_cost_energy,
      }),
      onClick: () => void handleEnterOnline(d),
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignLocations, dungeons, busy, t]);

  const offlineItems = useMemo(
    () =>
      ROOM_IDS.map((id) => ({
        key: id,
        label: id,
        hint: t('playground.offline_hint'),
        onClick: () => setMode({ kind: 'offline', room: id }),
      })),
    [t],
  );

  if (mode.kind === 'menu') {
    return (
      <div className="screen playground-menu">
        <header className="screen__header">
          <button type="button" className="inventory__back" onClick={onExit}>
            {t('playground.exit')}
          </button>
          <h1 className="inventory__title">{t('playground.menu_title')}</h1>
        </header>
        {error && <p className="error">{error}</p>}

        <DungeonMenuList
          title={t('playground.online')}
          items={dungeonItems}
          empty={t('playground.no_dungeons')}
          disabled={busy}
        />
        <DungeonMenuList
          title={t('playground.offline')}
          items={offlineItems}
        />
      </div>
    );
  }

  return (
    <div className="playground" onPointerDown={handleWorldTap}>
      <div ref={canvasHostRef} className="playground__canvas" />
      <button
        type="button"
        className="playground__exit"
        onClick={() => {
          if (mode.kind === 'online') {
            void handleFlee();
          } else {
            setMode({ kind: 'menu' });
          }
        }}
      >
        {mode.kind === 'online' ? t('playground.flee') : t('playground.exit')}
      </button>
      <div className="playground__hint">{t('playground.hint')}</div>
      {error && <div className="playground__error">{error}</div>}
      {import.meta.env.DEV && mode.kind === 'online' && (
        <DevOverlay realtimeRef={realtimeRef} />
      )}
      {mode.kind === 'online' && (
        <Hotbar
          skills={HOTBAR_SKILLS}
          activeSkillId={activeSkillId}
          cooldownEndsAt={cooldownEndsAt}
          onSelect={handleSelectSkill}
        />
      )}
      <Joystick onInput={handleJoy} />
      {isDead && <DeathScreen onReturn={handleDeathReturn} summary={runSummary ?? undefined} />}
      {!isDead && runSummary && (
        <RunSummaryScreen summary={runSummary} onContinue={handleRunSummaryContinue} />
      )}
      {floorToast && (
        <FloorClearedToast
          key={floorToast.key}
          floor={floorToast.floor}
          total={floorToast.total}
          onDismiss={handleFloorToastDismiss}
        />
      )}
    </div>
  );
}

interface DevOverlayProps {
  realtimeRef: React.RefObject<RealtimeConnection | null>;
}

function DevOverlay({ realtimeRef }: DevOverlayProps) {
  const [m, setM] = useState({ latencyMs: 0, packetsPerSec: 0, outboundPerSec: 0 });
  useEffect(() => {
    const id = setInterval(() => {
      const conn = realtimeRef.current;
      if (conn) setM(conn.getMetrics());
    }, 1000);
    return () => clearInterval(id);
  }, [realtimeRef]);
  return (
    <div className="playground__dev-overlay" aria-label="dev metrics">
      <div>ping: {m.latencyMs}ms</div>
      <div>in: {m.packetsPerSec}/s</div>
      <div>out: {m.outboundPerSec}/s</div>
    </div>
  );
}

interface MenuItem {
  key: string;
  label: string;
  hint: string;
  onClick: () => void;
}

interface DungeonMenuListProps {
  title: string;
  items: MenuItem[];
  empty?: string;
  disabled?: boolean;
}

function DungeonMenuList({ title, items, empty, disabled }: DungeonMenuListProps) {
  return (
    <section>
      <h2 className="bag__title">{title}</h2>
      {items.length === 0 && empty ? (
        <p className="muted">{empty}</p>
      ) : (
        <div className="dungeon-list">
          {items.map((it) => (
            <button
              key={it.key}
              type="button"
              className="menu__button menu__button--active"
              disabled={disabled}
              onClick={it.onClick}
            >
              <span className="menu__label">{it.label}</span>
              <span className="menu__hint">{it.hint}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

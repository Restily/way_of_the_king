/**
 * Hotbar — 4 слота скиллов Knight'а с CD-визуализацией.
 *
 * Single shared RAF в parent'е драйвит canvas overlay'и всех слотов
 * (4 RAF на компонент = напрасная работа).
 */

import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';

export interface HotbarSkill {
  /** Canonical skill id (cleave / shield_bash / whirlwind / charge). */
  id: string;
  /** Cooldown в миллисекундах — нужен для рассчёта radial sweep. */
  cooldownMs: number;
}

export interface HotbarProps {
  skills: HotbarSkill[];
  activeSkillId: string | null;
  cooldownEndsAt: Map<string, number>;
  onSelect: (skillId: string) => void;
}

const SLOT_SIZE = 64;

/** Иконки скиллов (emoji placeholder — заменить на sprite когда появится art). */
const SKILL_ICONS: Record<string, string> = {
  cleave: '⚔️',
  shield_bash: '🛡️',
  whirlwind: '🌀',
  charge: '💨',
};

function clearMask(canvas: HTMLCanvasElement): void {
  const ctx = canvas.getContext('2d');
  ctx?.clearRect(0, 0, canvas.width, canvas.height);
}

/**
 * Рисует radial-маску кулдауна на <canvas>.
 *
 * Sweep идёт от 270° (12 часов) по часовой. Когда прогресс = 0 (CD только
 * начался) — полный круг затемнён; прогресс = 1 (CD закончился) — пусто.
 */
function drawCdMask(canvas: HTMLCanvasElement, progress: number): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  if (progress >= 1) return;

  const cx = width / 2;
  const cy = height / 2;
  const r = Math.min(cx, cy) - 2;

  ctx.save();
  ctx.globalAlpha = 0.65;
  ctx.fillStyle = '#000';
  ctx.beginPath();
  const startAngle = -Math.PI / 2;
  const sweepEnd = startAngle + 2 * Math.PI * (1 - progress);
  ctx.moveTo(cx, cy);
  ctx.arc(cx, cy, r, startAngle, sweepEnd, false);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

export function Hotbar({ skills, activeSkillId, cooldownEndsAt, onSelect }: HotbarProps) {
  const canvasRefs = useRef<Map<string, HTMLCanvasElement>>(new Map());

  // Single RAF loop для всех слотов. Стартуем когда есть active CD,
  // останавливаемся когда все CD истекли.
  useEffect(() => {
    let rafId: number | null = null;

    const tick = () => {
      const now = Date.now();
      let anyActive = false;
      for (const skill of skills) {
        const canvas = canvasRefs.current.get(skill.id);
        if (!canvas) continue;
        const endsAt = cooldownEndsAt.get(skill.id);
        if (!endsAt || endsAt <= now) {
          clearMask(canvas);
          continue;
        }
        const remaining = endsAt - now;
        drawCdMask(canvas, 1 - remaining / skill.cooldownMs);
        anyActive = true;
      }
      rafId = anyActive ? requestAnimationFrame(tick) : null;
    };

    // Запускаем если хотя бы один CD активен сейчас.
    const now = Date.now();
    const anyActive = skills.some((s) => {
      const endsAt = cooldownEndsAt.get(s.id);
      return endsAt !== undefined && endsAt > now;
    });
    if (anyActive) {
      rafId = requestAnimationFrame(tick);
    } else {
      // Очищаем маски на случай если только что закончился последний CD.
      for (const skill of skills) {
        const c = canvasRefs.current.get(skill.id);
        if (c) clearMask(c);
      }
    }

    return () => {
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, [cooldownEndsAt, skills]);

  return (
    <div className="playground__hotbar">
      {skills.map((skill) => (
        <HotbarSlot
          key={skill.id}
          skill={skill}
          isActive={activeSkillId === skill.id}
          isOnCd={(cooldownEndsAt.get(skill.id) ?? 0) > Date.now()}
          onSelect={onSelect}
          registerCanvas={(el) => {
            if (el) canvasRefs.current.set(skill.id, el);
            else canvasRefs.current.delete(skill.id);
          }}
        />
      ))}
    </div>
  );
}

interface HotbarSlotProps {
  skill: HotbarSkill;
  isActive: boolean;
  isOnCd: boolean;
  onSelect: (id: string) => void;
  registerCanvas: (el: HTMLCanvasElement | null) => void;
}

function HotbarSlot({ skill, isActive, isOnCd, onSelect, registerCanvas }: HotbarSlotProps) {
  const { t } = useTranslation();
  const label = t(`combat.skill.${skill.id}.name`, { defaultValue: skill.id });
  return (
    <button
      type="button"
      className={`playground__hotbar-slot${isActive ? ' playground__hotbar-slot--active' : ''}${isOnCd ? ' playground__hotbar-slot--cd' : ''}`}
      onClick={() => onSelect(skill.id)}
      aria-label={label}
    >
      <span className="playground__hotbar-icon">{SKILL_ICONS[skill.id] ?? '?'}</span>
      <span className="playground__hotbar-name">{label}</span>
      <canvas
        ref={registerCanvas}
        className="playground__hotbar-cd-canvas"
        width={SLOT_SIZE}
        height={SLOT_SIZE}
      />
    </button>
  );
}

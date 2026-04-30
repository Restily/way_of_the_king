/**
 * FloorClearedToast — краткий overlay при переходе на следующий этаж.
 *
 * Появляется на 1.5 секунды когда Colyseus DungeonRoom рассылает сообщение
 * ``floor_advanced``. Показывает «Floor N / Total» и исчезает автоматически.
 */

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

export interface FloorClearedToastProps {
  /** 1-based номер текущего этажа для отображения. */
  floor: number;
  /** Общее количество этажей в данже. */
  total: number;
  /** Callback вызываемый по истечению 1.5 секунды для авто-dismiss'а. */
  onDismiss: () => void;
}

/** Продолжительность toast'а в мс. */
const TOAST_DURATION_MS = 1500;

/**
 * Absolutely-positioned toast overlay «Floor N / Total» (W6-033).
 */
export function FloorClearedToast({ floor, total, onDismiss }: FloorClearedToastProps) {
  const { t } = useTranslation();

  useEffect(() => {
    const timer = setTimeout(onDismiss, TOAST_DURATION_MS);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div className="floor-cleared-toast" role="status" aria-live="polite">
      {t('floor_cleared.toast', { floor, total })}
    </div>
  );
}

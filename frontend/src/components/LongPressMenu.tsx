/**
 * LongPressMenu — контекстное меню для item'а в инвентаре (W5-051).
 *
 * Touch: 500ms long-press → открыть меню.
 * Desktop: правый клик → открыть меню.
 * Действия: Equip / Unequip / Compare / Cancel.
 */

import { useRef } from 'react';
import { useTranslation } from 'react-i18next';

export interface LongPressMenuAction {
  /** Идентификатор действия. */
  id: 'equip' | 'unequip' | 'compare' | 'cancel';
  /** Отображаемый label (i18n). */
  label: string;
}

export interface LongPressMenuState {
  /** Item id, для которого открыто меню. */
  itemId: number;
  /** Оснащён ли item в данный момент. */
  isEquipped: boolean;
}

interface LongPressMenuOverlayProps {
  state: LongPressMenuState;
  onAction: (action: LongPressMenuAction['id'], itemId: number) => void;
}

/**
 * Оверлей меню — рендерится поверх инвентаря.
 *
 * :param state: Текущее состояние (какой item выбран).
 * :param onAction: Callback с выбранным действием.
 */
export function LongPressMenuOverlay({ state, onAction }: LongPressMenuOverlayProps) {
  const { t } = useTranslation();

  const actions: LongPressMenuAction[] = [
    ...(state.isEquipped
      ? [{ id: 'unequip' as const, label: t('inventory.menu.unequip') }]
      : [{ id: 'equip' as const, label: t('inventory.menu.equip') }]),
    { id: 'compare', label: t('inventory.menu.compare') },
    { id: 'cancel', label: t('inventory.menu.cancel') },
  ];

  return (
    /* Полупрозрачный backdrop — клик вне меню = cancel. */
    <div
      className="inventory__longpress-backdrop"
      onPointerDown={() => onAction('cancel', state.itemId)}
    >
      <div
        className="inventory__longpress-menu"
        onPointerDown={(e) => e.stopPropagation()}
      >
        {actions.map((a) => (
          <button
            key={a.id}
            type="button"
            className={`inventory__longpress-item inventory__longpress-item--${a.id}`}
            onClick={() => onAction(a.id, state.itemId)}
          >
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export interface UseLongPressResult {
  /** Props для элемента, поддерживающего long-press и right-click. */
  handlers: {
    onTouchStart: React.TouchEventHandler;
    onTouchEnd: React.TouchEventHandler;
    onTouchMove: React.TouchEventHandler;
    onContextMenu: React.MouseEventHandler;
  };
}

/**
 * Хук для long-press (500ms) и right-click → callback.
 *
 * :param onLongPress: Вызывается при successful long-press / right-click.
 * :returns: handlers для передачи в JSX element.
 */
export function useLongPress(onLongPress: () => void): UseLongPressResult {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const movedRef = useRef(false);

  const clear = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  return {
    handlers: {
      onTouchStart: () => {
        movedRef.current = false;
        timerRef.current = setTimeout(() => {
          if (!movedRef.current) {
            onLongPress();
          }
        }, 500);
      },
      onTouchMove: () => {
        movedRef.current = true;
        clear();
      },
      onTouchEnd: () => {
        clear();
      },
      onContextMenu: (e) => {
        e.preventDefault();
        onLongPress();
      },
    },
  };
}

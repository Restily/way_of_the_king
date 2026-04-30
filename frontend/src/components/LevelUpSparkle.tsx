/**
 * LevelUpSparkle — анимированный overlay «Level Up!» при повышении уровня.
 *
 * Показывается на ~2 секунды в City после возврата из данжа когда hero.level
 * увеличился относительно предыдущего значения. Реализован как CSS-анимация
 * (fade in → hold → fade out).
 */

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

export interface LevelUpSparkleProps {
  /** Новый уровень героя (для отображения в subtitle). */
  newLevel: number;
  /** Callback вызываемый по истечению анимации (~2 секунды). */
  onDismiss: () => void;
}

/** Продолжительность overlay в мс (CSS animation matches this). */
const SPARKLE_DURATION_MS = 2000;

/**
 * CSS-animated level-up overlay (W6-034).
 */
export function LevelUpSparkle({ newLevel, onDismiss }: LevelUpSparkleProps) {
  const { t } = useTranslation();

  useEffect(() => {
    const timer = setTimeout(onDismiss, SPARKLE_DURATION_MS);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div className="level-up-sparkle" role="alert" aria-live="assertive">
      <div className="level-up-sparkle__content">
        <h2 className="level-up-sparkle__title">{t('level_up.title')}</h2>
        <p className="level-up-sparkle__subtitle">
          {t('level_up.subtitle', { level: newLevel })}
        </p>
      </div>
    </div>
  );
}

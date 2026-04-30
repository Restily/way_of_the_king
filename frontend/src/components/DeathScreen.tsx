/**
 * DeathScreen — overlay при смерти героя (W5-044, расширен в W6-032).
 *
 * Появляется когда hp своего player'а достигает 0. Если передан ``summary`` —
 * показывает частичные награды (gold/xp/items которые уже попали в escrow до
 * смерти). Кнопка Revive задизейблена (W7 placeholder). Если summary нет —
 * показывает оригинальный минималистичный вариант.
 *
 * :param props.onReturn: Callback при нажатии "Вернуться в город".
 * :param props.summary: Опциональный :class:`RunSummaryDTO` с частичными наградами.
 */

import { useTranslation } from 'react-i18next';

import type { RunSummaryDTO } from '../api/runs';

/** CSS-класс для rarity-цвета предмета (0=COMMON..4=LEGENDARY). */
const RARITY_CLASS: Record<number, string> = {
  0: 'rarity--common',
  1: 'rarity--magic',
  2: 'rarity--rare',
  3: 'rarity--epic',
  4: 'rarity--legendary',
};

export interface DeathScreenProps {
  onReturn: () => void;
  /** W6-032: опциональные частичные награды run'а (gold/xp в escrow до смерти). */
  summary?: RunSummaryDTO;
}

/**
 * Полноэкранный overlay смерти героя (W6-032 v2).
 */
export function DeathScreen({ onReturn, summary }: DeathScreenProps) {
  const { t } = useTranslation();

  return (
    <div className="playground__death-screen">
      <div className="playground__death-content">
        <h1 className="playground__death-title">{t('combat.death.title')}</h1>

        {summary ? (
          <>
            <dl className="run-summary__stats run-summary__stats--death">
              <div className="run-summary__stat-row">
                <dt>{t('run_summary.gold')}</dt>
                <dd className="run-summary__stat-value">{summary.gold_earned}</dd>
              </div>
              <div className="run-summary__stat-row">
                <dt>{t('run_summary.xp')}</dt>
                <dd className="run-summary__stat-value">{summary.xp_earned}</dd>
              </div>
            </dl>

            {summary.items.length > 0 && (
              <ul className="run-summary__item-list run-summary__item-list--death">
                {summary.items.map((item) => (
                  <li
                    key={item.id}
                    className={`run-summary__item ${RARITY_CLASS[item.rarity] ?? 'rarity--common'}`}
                  >
                    <span className="run-summary__item-kind">{item.base_kind}</span>
                  </li>
                ))}
              </ul>
            )}

            <button
              type="button"
              className="playground__death-revive"
              disabled
              title="Coming in W7"
            >
              Revive (soon)
            </button>
          </>
        ) : (
          <p className="playground__death-hint">{t('combat.death.hint')}</p>
        )}

        <button
          type="button"
          className="playground__death-return"
          onClick={onReturn}
        >
          {t('combat.death.return')}
        </button>
      </div>
    </div>
  );
}

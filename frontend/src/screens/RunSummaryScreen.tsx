/**
 * RunSummaryScreen — полноэкранный overlay с итогами run'а.
 *
 * Показывается когда Colyseus room рассылает сообщение ``run_summary`` перед
 * disconnect (boss killed / hero death / flee). Содержит: gold + xp earned,
 * список лута с rarity-цветами, количество пройденных этажей, продолжительность
 * и медаль boss_killed. Кнопка «Continue → City» закрывает overlay и
 * возвращает player'а в город.
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

function formatDuration(s: number): string {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

export interface RunSummaryScreenProps {
  summary: RunSummaryDTO;
  /** Callback при нажатии «Continue → City». */
  onContinue: () => void;
}

/**
 * Полноэкранный overlay итогов run'а (W6-031).
 */
export function RunSummaryScreen({ summary, onContinue }: RunSummaryScreenProps) {
  const { t } = useTranslation();

  return (
    <div className="run-summary__overlay">
      <div className="run-summary__panel">
        <h1 className="run-summary__title">{t('run_summary.title')}</h1>

        {summary.boss_killed && (
          <div className="run-summary__boss-medal" aria-label="Boss killed">
            {'⚔️'} {t('run_summary.boss_killed')}
          </div>
        )}

        <dl className="run-summary__stats">
          <div className="run-summary__stat-row">
            <dt>{t('run_summary.gold')}</dt>
            <dd className="run-summary__stat-value">{summary.gold_earned}</dd>
          </div>
          <div className="run-summary__stat-row">
            <dt>{t('run_summary.xp')}</dt>
            <dd className="run-summary__stat-value">{summary.xp_earned}</dd>
          </div>
          <div className="run-summary__stat-row">
            <dt>{t('run_summary.duration')}</dt>
            <dd className="run-summary__stat-value">{formatDuration(summary.duration_s)}</dd>
          </div>
        </dl>

        <section className="run-summary__loot">
          {summary.items.length === 0 ? (
            <p className="run-summary__empty-loot muted">{t('run_summary.empty_loot')}</p>
          ) : (
            <ul className="run-summary__item-list">
              {summary.items.map((item) => (
                <li
                  key={item.id}
                  className={`run-summary__item ${RARITY_CLASS[item.rarity] ?? 'rarity--common'}`}
                >
                  <span className="run-summary__item-kind">{item.base_kind}</span>
                  <span className="run-summary__item-ilvl">ilvl {item.ilvl}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <button
          type="button"
          className="run-summary__continue menu__button menu__button--active"
          onClick={onContinue}
        >
          {t('run_summary.continue')}
        </button>
      </div>
    </div>
  );
}

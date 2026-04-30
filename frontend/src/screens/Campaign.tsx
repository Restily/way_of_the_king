/**
 * Campaign — экран прогресса кампании (W6-023).
 *
 * Сетка 3 акта × 2 локации (MVP seeds). Каждая ячейка показывает:
 * - Название данжа (i18n через name_key)
 * - Состояние: locked / available / completed / mastered (≥5 clear'ов)
 * - Тап → вход в данж через существующий /enter flow (handleEnterOnline)
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { type CampaignLocationInfo, getCampaign } from '../api/campaign';
import { enterDungeon } from '../api/dungeons';

/** Количество clear'ов для статуса "mastered". */
const MASTERED_THRESHOLD = 5;

/** MVP: 3 акта × 2 локации. */
const ACTS = [1, 2, 3] as const;
const LOCATIONS = [1, 2] as const;

export interface CampaignProps {
  onExit: () => void;
  /** Callback при успешном старте данжа — переводит в Playground. */
  onEnterDungeon: (runId: string, wsUrl: string, wsToken: string, dungeonId: string) => void;
}

type CellState = 'locked' | 'available' | 'completed' | 'mastered';

function getCellState(info: CampaignLocationInfo): CellState {
  if (info.is_locked) return 'locked';
  if (info.completion_count === 0) return 'available';
  if (info.completion_count >= MASTERED_THRESHOLD) return 'mastered';
  return 'completed';
}

function formatTime(s: number | null): string {
  if (s === null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

export function Campaign({ onExit, onEnterDungeon }: CampaignProps) {
  const { t } = useTranslation();
  const [locations, setLocations] = useState<CampaignLocationInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        const data = await getCampaign();
        setLocations(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'load_failed');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Индекс для быстрого lookup'а по (act, location).
  const locIndex = new Map(
    locations.map((l) => [`${l.act}:${l.location}`, l]),
  );

  const handleEnter = async (info: CampaignLocationInfo) => {
    if (busy || info.is_locked) return;
    setBusy(true);
    setError(null);
    try {
      const idem = crypto.randomUUID();
      const r = await enterDungeon(info.dungeon_id, idem);
      onEnterDungeon(r.run_id, r.ws_url, r.ws_token, info.dungeon_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'enter_failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="screen campaign">
      <header className="screen__header">
        <button type="button" className="inventory__back" onClick={onExit}>
          {t('playground.exit')}
        </button>
        <h1 className="inventory__title">{t('city.campaign')}</h1>
      </header>

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">{t('welcome.loading')}</p>}

      {!loading && (
        <div className="campaign__grid">
          {ACTS.map((act) => (
            <section key={act} className="campaign__act">
              <h2 className="campaign__act-title">{t(`act.${act}.name`)}</h2>
              <div className="campaign__locations">
                {LOCATIONS.map((loc) => {
                  const info = locIndex.get(`${act}:${loc}`);
                  if (!info) return null;
                  const state = getCellState(info);
                  return (
                    <button
                      key={`${act}:${loc}`}
                      type="button"
                      className={`campaign__cell campaign__cell--${state}`}
                      disabled={state === 'locked' || busy}
                      onClick={() => void handleEnter(info)}
                      title={
                        state === 'locked' ? t('campaign.locked') : undefined
                      }
                    >
                      <span className="campaign__cell-name">
                        {t(info.name_key, { defaultValue: info.dungeon_id })}
                      </span>
                      <span className="campaign__cell-sub">
                        {t(`location.${act}.${loc}.name`)}
                      </span>
                      <span className="campaign__cell-state">
                        {state === 'locked' && t('campaign.locked')}
                        {state === 'available' && '—'}
                        {state === 'completed' && (
                          <>
                            {t('campaign.completed')} ×{info.completion_count}
                            {info.best_clear_time_s !== null && (
                              <> · {formatTime(info.best_clear_time_s)}</>
                            )}
                          </>
                        )}
                        {state === 'mastered' && (
                          <>
                            {t('campaign.mastered')} ×{info.completion_count}
                            {info.best_clear_time_s !== null && (
                              <> · {formatTime(info.best_clear_time_s)}</>
                            )}
                          </>
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

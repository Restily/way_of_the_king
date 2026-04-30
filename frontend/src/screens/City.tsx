import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { type CombatStats, getCombatStats } from '../api/inventory';
import type { BalanceInfo, HeroInfo } from '../api/me';
import { LevelUpSparkle } from '../components/LevelUpSparkle';
import { useAuthStore } from '../store/auth';

const COMING_SOON_ITEMS = ['city.wallet', 'city.settings'] as const;

/** XP needed to level up at a given level (simple linear formula: level * 100). */
function xpToNextLevel(level: number): number {
  return level * 100;
}

interface Props {
  hero: HeroInfo;
  balance: BalanceInfo;
  onEnterPlayground: () => void;
  onEnterInventory: () => void;
  /** W6-023: переход в экран кампании. */
  onEnterCampaign: () => void;
  /** W5-053: показать красную точку на кнопке Inventory (новые предметы из данжа). */
  hasNewItems?: boolean;
  /** W6-034: XP полученный в последнем данже — анимируем XP bar. */
  xpGained?: number;
  /** W6-034: Callback когда анимация XP bar завершена (App сбрасывает xpGained). */
  onXpAnimationComplete?: () => void;
}

export function City({
  hero,
  balance,
  onEnterPlayground,
  onEnterInventory,
  onEnterCampaign,
  hasNewItems = false,
  xpGained = 0,
  onXpAnimationComplete,
}: Props) {
  const { t } = useTranslation();
  const [stats, setStats] = useState<CombatStats | null>(null);
  const [statsExpanded, setStatsExpanded] = useState(false);
  const loadMe = useAuthStore((s) => s.loadMe);

  // W6-034: XP bar animation state.
  const xpTotal = xpToNextLevel(hero.level);
  const xpCurrent = hero.xp % xpTotal;
  const [displayedXpPct, setDisplayedXpPct] = useState(() =>
    Math.min(100, Math.round((xpCurrent / xpTotal) * 100))
  );
  const [showLevelUp, setShowLevelUp] = useState(false);
  const prevLevelRef = useRef(hero.level);

  // Animate XP bar when xpGained > 0 on mount / prop change.
  useEffect(() => {
    if (xpGained <= 0) return;
    // Animate from old xp to new over ~600ms via CSS transition on width.
    const newXpPct = Math.min(100, Math.round((xpCurrent / xpTotal) * 100));
    // Small delay to allow the CSS transition to play from old value.
    const id = setTimeout(() => {
      setDisplayedXpPct(newXpPct);
      // Check level-up.
      if (hero.level > prevLevelRef.current) {
        setShowLevelUp(true);
      }
      prevLevelRef.current = hero.level;
      onXpAnimationComplete?.();
    }, 50);
    return () => clearTimeout(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [xpGained]);

  // Refetch stats + me-data параллельно — после возврата из Inventory
  // (equip changed) или Playground (enter/flee changed balance).
  useEffect(() => {
    void (async () => {
      const [, statsResult] = await Promise.allSettled([
        loadMe(),
        getCombatStats(),
      ]);
      if (statsResult.status === 'fulfilled') {
        setStats(statsResult.value);
      }
    })();
  }, [loadMe]);

  return (
    <div className="screen">
      <header className="screen__header city__header">
        <div>
          <h1 className="city__name">{hero.name}</h1>
          <p className="muted">
            {t('city.hero_summary', {
              level: hero.level,
              gold: balance.gold,
            })}
          </p>
          {/* W6-034: XP bar с CSS transition. */}
          <div className="city__xp-bar" aria-label={`XP: ${xpCurrent}/${xpTotal}`}>
            <div
              className="city__xp-bar-fill"
              style={{ width: `${displayedXpPct}%`, transition: 'width 600ms ease-out' }}
            />
          </div>
        </div>
        <p className="city__energy">
          {t('energy.label', { current: balance.energy, cap: balance.energy_cap })}
        </p>
      </header>
      {showLevelUp && (
        <LevelUpSparkle
          newLevel={hero.level}
          onDismiss={() => setShowLevelUp(false)}
        />
      )}

      {stats && (
        <button
          type="button"
          className="stats-panel"
          onClick={() => setStatsExpanded((v) => !v)}
          aria-expanded={statsExpanded}
        >
          <header className="stats-panel__header">
            <span className="stats-panel__title">{t('city.stats')}</span>
            <span className="stats-panel__chevron">
              {statsExpanded ? '▾' : '▸'}
            </span>
          </header>
          {statsExpanded && (
            <dl className="stats-panel__list">
              <StatRow label="HP" value={stats.hp} />
              <StatRow label="Mana" value={stats.mana} />
              <StatRow label="ATK" value={stats.atk} />
              <StatRow label="DEF" value={stats.def_} />
              <StatRow
                label="Crit"
                value={`${stats.crit_chance_pct.toFixed(1)}% × ${stats.crit_damage_pct.toFixed(0)}%`}
              />
              <StatRow
                label="Resist 🔥/❄/⚡"
                value={`${stats.resist_fire_pct}/${stats.resist_cold_pct}/${stats.resist_lightning_pct}`}
              />
            </dl>
          )}
        </button>
      )}

      <nav className="menu">
        <MenuButton
          label={t('city.campaign')}
          hint={t('city.campaign_hint')}
          onClick={onEnterCampaign}
          active
        />
        <MenuButton
          label={t('city.playground')}
          hint={t('city.playground_hint')}
          onClick={onEnterPlayground}
          active
        />
        <MenuButton
          label={t('city.inventory')}
          hint={t('city.inventory_hint')}
          onClick={onEnterInventory}
          active
          badge={hasNewItems}
        />
        {COMING_SOON_ITEMS.map((labelKey) => (
          <MenuButton key={labelKey} label={t(labelKey)} hint={t('city.coming_soon')} />
        ))}
      </nav>
    </div>
  );
}

interface MenuButtonProps {
  label: string;
  hint: string;
  onClick?: () => void;
  active?: boolean;
  /** W5-053: показать красную точку badge (new items). */
  badge?: boolean;
}

function MenuButton({ label, hint, onClick, active, badge }: MenuButtonProps) {
  return (
    <button
      type="button"
      className={`menu__button${active ? ' menu__button--active' : ''}`}
      disabled={!active}
      onClick={onClick}
    >
      <span className="menu__label">
        {label}
        {badge && <span className="city__nav-badge" aria-label="new items" />}
      </span>
      <span className="menu__hint">{hint}</span>
    </button>
  );
}

function StatRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat-row">
      <dt className="stat-row__label">{label}</dt>
      <dd className="stat-row__value">{value}</dd>
    </div>
  );
}

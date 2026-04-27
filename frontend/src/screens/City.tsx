import { useTranslation } from 'react-i18next';

import type { BalanceInfo, HeroInfo } from '../api/me';

interface Props {
  hero: HeroInfo;
  balance: BalanceInfo;
}

export function City({ hero, balance }: Props) {
  const { t } = useTranslation();

  return (
    <div className="screen">
      <header className="screen__header city__header">
        <div>
          <h1 className="city__name">{hero.name}</h1>
          <p className="muted">
            {t('city.hero_summary', { level: hero.level, gold: Math.floor(balance.gold / 1000) })}
          </p>
        </div>
        <p className="city__energy">
          {t('energy.label', { current: balance.energy, cap: balance.energy_cap })}
        </p>
      </header>

      <nav className="menu">
        <MenuButton labelKey="city.campaign" />
        <MenuButton labelKey="city.inventory" />
        <MenuButton labelKey="city.wallet" />
        <MenuButton labelKey="city.settings" />
      </nav>
    </div>
  );
}

function MenuButton({ labelKey }: { labelKey: string }) {
  const { t } = useTranslation();
  return (
    <button type="button" className="menu__button" disabled>
      <span className="menu__label">{t(labelKey)}</span>
      <span className="menu__hint">{t('city.coming_soon')}</span>
    </button>
  );
}

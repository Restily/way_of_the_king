import { useTranslation } from 'react-i18next';

import type { BalanceInfo, HeroInfo } from '../api/me';

const MENU_ITEMS = [
  'city.campaign',
  'city.inventory',
  'city.wallet',
  'city.settings',
] as const;

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
            {t('city.hero_summary', {
              level: hero.level,
              gold: Math.floor(balance.gold / 1000),
            })}
          </p>
        </div>
        <p className="city__energy">
          {t('energy.label', { current: balance.energy, cap: balance.energy_cap })}
        </p>
      </header>

      <nav className="menu">
        {MENU_ITEMS.map((labelKey) => (
          <MenuButton key={labelKey} label={t(labelKey)} hint={t('city.coming_soon')} />
        ))}
      </nav>
    </div>
  );
}

interface MenuButtonProps {
  label: string;
  hint: string;
}

function MenuButton({ label, hint }: MenuButtonProps) {
  return (
    <button type="button" className="menu__button" disabled>
      <span className="menu__label">{label}</span>
      <span className="menu__hint">{hint}</span>
    </button>
  );
}

import { useTranslation } from 'react-i18next';

export function Loading() {
  const { t } = useTranslation();
  return (
    <div className="screen screen--centered">
      <h1 className="brand">{t('welcome.title')}</h1>
      <p className="muted">{t('welcome.loading')}</p>
    </div>
  );
}

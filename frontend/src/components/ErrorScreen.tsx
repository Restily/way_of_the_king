import { useTranslation } from 'react-i18next';

interface Props {
  errorCode: string | null;
  onRetry?: () => void;
}

export function ErrorScreen({ errorCode, onRetry }: Props) {
  const { t } = useTranslation();
  const messageKey = errorCode ? `errors.${errorCode}` : 'errors.generic';
  return (
    <div className="screen screen--centered">
      <h1 className="brand">{t('welcome.title')}</h1>
      <p className="error">{t(messageKey, { defaultValue: t('errors.generic') })}</p>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          {t('welcome.retry')}
        </button>
      )}
    </div>
  );
}

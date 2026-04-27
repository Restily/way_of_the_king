import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

import { ErrorScreen } from './components/ErrorScreen';
import { Loading } from './components/Loading';
import { CreateHero } from './screens/CreateHero';
import { City } from './screens/City';
import { useAuthStore } from './store/auth';

function normalizeLocale(locale: string): string {
  return locale.split('-')[0]?.toLowerCase() ?? locale;
}

export function App() {
  const { i18n } = useTranslation();
  const status = useAuthStore((s) => s.status);
  const errorCode = useAuthStore((s) => s.errorCode);
  const userLocale = useAuthStore((s) => s.user?.locale);
  const me = useAuthStore((s) => s.me);
  const meError = useAuthStore((s) => s.meError);
  const signIn = useAuthStore((s) => s.signIn);
  const loadMe = useAuthStore((s) => s.loadMe);

  useEffect(() => {
    void signIn();
  }, [signIn]);

  useEffect(() => {
    if (!userLocale) return;
    if (normalizeLocale(i18n.language) !== normalizeLocale(userLocale)) {
      void i18n.changeLanguage(userLocale);
    }
  }, [userLocale, i18n]);

  useEffect(() => {
    if (status === 'authenticated' && !me && !meError) {
      void loadMe();
    }
  }, [status, me, meError, loadMe]);

  if (status === 'idle' || status === 'loading') return <Loading />;

  if (status === 'error' || status === 'unauthenticated') {
    return <ErrorScreen errorCode={errorCode} onRetry={() => void signIn()} />;
  }

  if (meError) return <ErrorScreen errorCode={meError} onRetry={() => void loadMe()} />;
  if (!me) return <Loading />;
  if (!me.hero) return <CreateHero />;
  return <City hero={me.hero} balance={me.balance} />;
}

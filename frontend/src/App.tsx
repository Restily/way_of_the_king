import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ApiError } from './api/client';
import type { HeroCreated } from './api/heroes';
import { getMe, type MeResponse } from './api/me';
import { ErrorScreen } from './components/ErrorScreen';
import { Loading } from './components/Loading';
import { CreateHero } from './screens/CreateHero';
import { City } from './screens/City';
import { useAuthStore } from './store/auth';

export function App() {
  const { i18n } = useTranslation();
  const status = useAuthStore((s) => s.status);
  const errorCode = useAuthStore((s) => s.errorCode);
  const userLocale = useAuthStore((s) => s.user?.locale);
  const signIn = useAuthStore((s) => s.signIn);

  const [me, setMe] = useState<MeResponse | null>(null);
  const [meError, setMeError] = useState<string | null>(null);

  // Стартует auth flow при монтировании.
  useEffect(() => {
    void signIn();
  }, [signIn]);

  // Подтягивает локаль из user.locale, когда профиль загружен.
  useEffect(() => {
    if (userLocale && i18n.language !== userLocale) {
      void i18n.changeLanguage(userLocale);
    }
  }, [userLocale, i18n]);

  // После авторизации тянем /me.
  const loadMe = useCallback(async () => {
    setMeError(null);
    try {
      const data = await getMe();
      setMe(data);
    } catch (e) {
      const code =
        e instanceof ApiError ? e.detail : e instanceof Error ? e.message : 'generic';
      setMeError(code);
    }
  }, []);

  useEffect(() => {
    if (status === 'authenticated' && me === null && meError === null) {
      void loadMe();
    }
  }, [status, me, meError, loadMe]);

  const onHeroCreated = useCallback((hero: HeroCreated) => {
    setMe((prev) =>
      prev
        ? {
            ...prev,
            hero: {
              id: hero.id,
              hero_class: hero.hero_class,
              name: hero.name,
              level: hero.level,
              xp: hero.xp,
              unspent_points: hero.unspent_points as { stat: number; skill: number },
              base_stats: hero.base_stats as { str: number; dex: number; int: number },
            },
          }
        : prev,
    );
  }, []);

  if (status === 'idle' || status === 'loading') {
    return <Loading />;
  }

  if (status === 'error' || status === 'unauthenticated') {
    return <ErrorScreen errorCode={errorCode} onRetry={() => void signIn()} />;
  }

  // status === 'authenticated'
  if (meError) {
    return <ErrorScreen errorCode={meError} onRetry={() => void loadMe()} />;
  }

  if (me === null) {
    return <Loading />;
  }

  if (me.hero === null) {
    return <CreateHero onCreated={onHeroCreated} />;
  }

  return <City hero={me.hero} balance={me.balance} />;
}

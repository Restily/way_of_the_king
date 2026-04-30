import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ErrorScreen } from './components/ErrorScreen';
import { Loading } from './components/Loading';
import { Campaign } from './screens/Campaign';
import { CreateHero } from './screens/CreateHero';
import { City } from './screens/City';
import { Inventory } from './screens/Inventory';
import { Playground } from './screens/Playground';
import { useAuthStore } from './store/auth';

type Route = 'city' | 'playground' | 'inventory' | 'campaign';

/** Данные для входа в данж из экрана Campaign. */
interface PendingDungeonEnter {
  runId: string;
  wsUrl: string;
  wsToken: string;
  dungeonId: string;
}

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
  const [route, setRoute] = useState<Route>('city');
  // W5-053: badge "new items" на кнопке Inventory в City после возврата из данжа.
  const [hasNewItems, setHasNewItems] = useState(false);
  // W6-023: данные для автоматического входа в данж из экрана Campaign.
  const [pendingEnter, setPendingEnter] = useState<PendingDungeonEnter | null>(null);
  // W6-034: xpGained передаётся из Playground в City для анимации XP bar.
  const [pendingXpGained, setPendingXpGained] = useState(0);

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
  if (route === 'playground') {
    return (
      <Playground
        onExit={() => {
          setPendingEnter(null);
          setRoute('city');
        }}
        onDungeonComplete={() => setHasNewItems(true)}
        pendingEnter={pendingEnter ?? undefined}
        onPendingEnterConsumed={() => setPendingEnter(null)}
        onReturnWithXp={(xp) => setPendingXpGained(xp)}
      />
    );
  }
  if (route === 'inventory') {
    return (
      <Inventory
        onExit={() => {
          // Открытие инвентаря — сбрасываем badge (W5-053).
          setHasNewItems(false);
          setRoute('city');
        }}
      />
    );
  }
  if (route === 'campaign') {
    return (
      <Campaign
        onExit={() => setRoute('city')}
        onEnterDungeon={(runId, wsUrl, wsToken, dungeonId) => {
          setPendingEnter({ runId, wsUrl, wsToken, dungeonId });
          setRoute('playground');
        }}
      />
    );
  }
  return (
    <City
      hero={me.hero}
      balance={me.balance}
      onEnterPlayground={() => setRoute('playground')}
      onEnterInventory={() => setRoute('inventory')}
      onEnterCampaign={() => setRoute('campaign')}
      hasNewItems={hasNewItems}
      xpGained={pendingXpGained}
      onXpAnimationComplete={() => setPendingXpGained(0)}
    />
  );
}

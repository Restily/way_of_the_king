/**
 * Zustand auth + profile store.
 *
 * Owns: tokens, user summary, full /me response (profile + balance + hero).
 * Actions: signIn, refresh (deduplicated), loadMe, applyHero, signOut.
 */
import { create } from 'zustand';

import { type ProfileSummary, login as apiLogin, refresh as apiRefresh } from '../api/auth';
import { ApiError, configureClient } from '../api/client';
import { type HeroCreated } from '../api/heroes';
import { type MeResponse, getMe as apiGetMe } from '../api/me';
import { toErrorCode } from '../lib/errors';
import * as storage from '../lib/storage';
import { getInitData } from '../lib/telegram';

const REFRESH_KEY = 'refresh_token';

export type AuthStatus =
  | 'idle'
  | 'loading'
  | 'authenticated'
  | 'unauthenticated'
  | 'error';

interface AuthState {
  // Auth tokens + summary (from /login response)
  accessToken: string | null;
  refreshToken: string | null;
  user: ProfileSummary | null;
  status: AuthStatus;
  errorCode: string | null;

  // Profile + game state (from /me response)
  me: MeResponse | null;
  meError: string | null;

  signIn: () => Promise<void>;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
  loadMe: () => Promise<void>;
  applyHero: (hero: HeroCreated) => void;
}

/** Tries cached refresh token. Returns null on any failure (silent fallback). */
async function tryRefreshFromCache(): Promise<{ access: string; refresh: string } | null> {
  let cached: string | null = null;
  try {
    cached = await storage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
  if (!cached) return null;
  try {
    const result = await apiRefresh(cached);
    return { access: result.access_token, refresh: result.refresh_token };
  } catch {
    return null;
  }
}

/** Fire-and-forget storage write — не блокируем UI. */
function persistRefreshToken(token: string): void {
  void storage.setItem(REFRESH_KEY, token).catch(() => {
    /* CloudStorage недоступен — токен потеряется после перезапуска, не fatal */
  });
}

// Дедупликация одновременных refresh: если несколько 401-х fetch'ей упали
// параллельно (token expired in flight), они все ждут одну и ту же
// refresh-операцию вместо того чтобы насылать N запросов на /auth/refresh.
let refreshInFlight: Promise<void> | null = null;

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  refreshToken: null,
  user: null,
  status: 'idle',
  errorCode: null,
  me: null,
  meError: null,

  signIn: async () => {
    // Reentrancy guard: StrictMode mounts dvojnoy + retry-кнопка не должны
    // спавнить параллельные login'ы.
    if (get().status === 'loading') return;
    set({ status: 'loading', errorCode: null });

    const refreshed = await tryRefreshFromCache();
    if (refreshed) {
      set({
        accessToken: refreshed.access,
        refreshToken: refreshed.refresh,
        status: 'authenticated',
      });
      persistRefreshToken(refreshed.refresh);
      return;
    }

    const initData = getInitData();
    if (!initData) {
      set({ status: 'error', errorCode: 'no_init_data' });
      return;
    }

    try {
      const result = await apiLogin(initData);
      set({
        accessToken: result.access_token,
        refreshToken: result.refresh_token,
        user: result.user,
        status: 'authenticated',
      });
      persistRefreshToken(result.refresh_token);
    } catch (e) {
      set({ status: 'error', errorCode: toErrorCode(e, 'auth_failed') });
    }
  },

  refresh: async () => {
    if (refreshInFlight) {
      await refreshInFlight;
      return;
    }
    refreshInFlight = (async () => {
      const refreshToken = get().refreshToken;
      if (!refreshToken) {
        await get().signOut();
        return;
      }
      try {
        const result = await apiRefresh(refreshToken);
        set({
          accessToken: result.access_token,
          refreshToken: result.refresh_token,
        });
        persistRefreshToken(result.refresh_token);
      } catch {
        await get().signOut();
      }
    })();
    try {
      await refreshInFlight;
    } finally {
      refreshInFlight = null;
    }
  },

  signOut: async () => {
    try {
      await storage.removeItem(REFRESH_KEY);
    } catch {
      /* ignore */
    }
    set({
      accessToken: null,
      refreshToken: null,
      user: null,
      status: 'unauthenticated',
      errorCode: null,
      me: null,
      meError: null,
    });
  },

  loadMe: async () => {
    set({ meError: null });
    try {
      const me = await apiGetMe();
      set({ me });
    } catch (e) {
      set({ meError: toErrorCode(e) });
    }
  },

  applyHero: (hero: HeroCreated) => {
    const me = get().me;
    if (!me) return;
    // HeroCreated extends HeroInfo + active_skills.
    // Для MeResponse.hero нам нужен HeroInfo — берём всё кроме active_skills.
    const { active_skills: _ignored, ...heroInfo } = hero;
    set({ me: { ...me, hero: heroInfo } });
  },
}));

// Подключаем API-клиент к store: Authorization header + дедуплицированный
// refresh при 401. configureClient вызывается один раз на module load.
configureClient({
  getAccessToken: () => useAuthStore.getState().accessToken,
  onUnauthorized: async () => {
    await useAuthStore.getState().refresh();
  },
});

/**
 * Zustand auth store.
 *
 * Управляет жизненным циклом auth: try refresh from cached token,
 * fallback на login через Telegram initData, expose actions для UI.
 */
import { create } from 'zustand';

import { type ProfileSummary, login as apiLogin, refresh as apiRefresh } from '../api/auth';
import { ApiError, configureClient } from '../api/client';
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
  accessToken: string | null;
  refreshToken: string | null;
  user: ProfileSummary | null;
  status: AuthStatus;
  errorCode: string | null;

  signIn: () => Promise<void>;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  refreshToken: null,
  user: null,
  status: 'idle',
  errorCode: null,

  signIn: async () => {
    set({ status: 'loading', errorCode: null });

    // 1) Попробовать рефрешнуть закэшированный refresh_token
    try {
      const cached = await storage.getItem(REFRESH_KEY);
      if (cached) {
        try {
          const result = await apiRefresh(cached);
          set({
            accessToken: result.access_token,
            refreshToken: result.refresh_token,
            status: 'authenticated',
          });
          await storage.setItem(REFRESH_KEY, result.refresh_token);
          return;
        } catch {
          // Refresh не сработал → continue к свежему login
        }
      }
    } catch {
      // storage недоступен — fallback на login
    }

    // 2) Свежий login через Telegram initData
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
      try {
        await storage.setItem(REFRESH_KEY, result.refresh_token);
      } catch {
        // не фатально, токен будет потерян после перезапуска приложения
      }
    } catch (e) {
      const code =
        e instanceof ApiError ? e.detail : e instanceof Error ? e.message : 'auth_failed';
      set({ status: 'error', errorCode: code });
    }
  },

  refresh: async () => {
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
      await storage.setItem(REFRESH_KEY, result.refresh_token);
    } catch {
      await get().signOut();
    }
  },

  signOut: async () => {
    try {
      await storage.removeItem(REFRESH_KEY);
    } catch {
      // ignore
    }
    set({
      accessToken: null,
      refreshToken: null,
      user: null,
      status: 'unauthenticated',
      errorCode: null,
    });
  },
}));

// Подключаем API client к store для авто-Authorization header + auto-refresh on 401.
configureClient({
  getAccessToken: () => useAuthStore.getState().accessToken,
  onUnauthorized: async () => {
    await useAuthStore.getState().refresh();
  },
});

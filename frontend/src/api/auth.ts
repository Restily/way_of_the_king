/** Login и refresh эндпоинты. */
import { apiFetch } from './client';

export interface ProfileSummary {
  id: number;
  locale: string;
  telegram_username: string | null;
  is_admin: boolean;
  withdrawal_2fa_enabled: boolean;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  user: ProfileSummary;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
}

export function login(initData: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>('/api/v1/auth/login', {
    method: 'POST',
    auth: false,
    body: { init_data: initData },
  });
}

export function refresh(refreshToken: string): Promise<TokenPair> {
  return apiFetch<TokenPair>('/api/v1/auth/refresh', {
    method: 'POST',
    auth: false,
    retryOnUnauthorized: false,
    body: { refresh_token: refreshToken },
  });
}

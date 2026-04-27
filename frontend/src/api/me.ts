/** GET /api/v1/me. */
import { apiFetch } from './client';

export interface ProfileFull {
  id: number;
  locale: string;
  telegram_username: string | null;
  is_admin: boolean;
  withdrawal_2fa_enabled: boolean;
  created_at: string;
}

export interface BalanceInfo {
  gold: number;
  energy: number;
  energy_cap: number;
  energy_updated_at: string;
}

export interface HeroInfo {
  id: number;
  hero_class: number;
  name: string;
  level: number;
  xp: number;
  unspent_points: { stat: number; skill: number };
  base_stats: { str: number; dex: number; int: number };
}

export interface MeResponse {
  profile: ProfileFull;
  balance: BalanceInfo;
  hero: HeroInfo | null;
}

export function getMe(): Promise<MeResponse> {
  return apiFetch<MeResponse>('/api/v1/me');
}

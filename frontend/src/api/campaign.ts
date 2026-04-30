/** Campaign progress endpoint — GET /api/v1/me/campaign. */
import { apiFetch } from './client';

export interface CampaignLocationInfo {
  act: number;
  location: number;
  dungeon_id: string;
  name_key: string;
  completion_count: number;
  best_clear_time_s: number | null;
  is_locked: boolean;
}

/**
 * Получить список кампанийных локаций с прогрессом активного героя.
 *
 * Возвращает массив отсортированный по (act, location).
 * is_locked=true означает что нужно пройти предыдущий акт.
 */
export function getCampaign(): Promise<CampaignLocationInfo[]> {
  return apiFetch<CampaignLocationInfo[]>('/api/v1/me/campaign');
}

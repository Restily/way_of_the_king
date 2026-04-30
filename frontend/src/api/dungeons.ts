/** Dungeon list + enter + flee endpoints. */
import { apiFetch } from './client';

export interface DungeonInfo {
  id: string;
  name_key: string;
  theme: number;
  difficulty: number;
  min_level: number;
  entry_cost_gold: number;
  entry_cost_energy: number;
  daily_limit: number;
  floors_count: number;
}

export interface EnterResponse {
  run_id: string;
  ws_url: string;
  ws_token: string;
  dungeon: DungeonInfo;
}

export interface FleeResponse {
  run_id: string;
  pending_gold_returned: number;
  status: string;
}

export function listDungeons(): Promise<{ dungeons: DungeonInfo[] }> {
  return apiFetch<{ dungeons: DungeonInfo[] }>('/api/v1/dungeons');
}

export function enterDungeon(
  dungeonId: string,
  idempotencyKey: string,
): Promise<EnterResponse> {
  return apiFetch<EnterResponse>(
    `/api/v1/dungeons/${dungeonId}/enter`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
    },
  );
}

export function fleeRun(runId: string): Promise<FleeResponse> {
  return apiFetch<FleeResponse>(`/api/v1/runs/${runId}/flee`, {
    method: 'POST',
  });
}

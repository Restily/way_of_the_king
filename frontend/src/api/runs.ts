/**
 * Run summary endpoint — W6-030 fallback для клиентов потерявших WS run_summary.
 *
 * GET /api/v1/runs/{run_id}/summary возвращает RunSummaryDTO для terminal run'ов.
 * Используется как canonical источник данных после возврата из данжа.
 */
import { apiFetch } from './client';

/** Краткое описание материализованного предмета из run'а. */
export interface ItemSummaryDTO {
  id: number;
  base_kind: string;
  rarity: number;
  ilvl: number;
}

/** Полный итог run'а — возвращается сервером после завершения. */
export interface RunSummaryDTO {
  run_id: string;
  /** COMPLETED / FAILED / ABANDONED / FLED */
  status: string;
  gold_earned: number;
  xp_earned: number;
  items: ItemSummaryDTO[];
  floors_cleared: number;
  duration_s: number;
  boss_killed: boolean;
}

/**
 * Получить RunSummaryDTO для завершённого run'а.
 *
 * Fallback если WS-сообщение run_summary было потеряно (refresh / network drop).
 * Возвращает 409 если run ещё активен (не terminal).
 *
 * :param runId: UUID dungeon_run'а.
 * :returns: :class:`RunSummaryDTO`.
 */
export async function getRunSummary(runId: string): Promise<RunSummaryDTO> {
  return apiFetch<RunSummaryDTO>(`/api/v1/runs/${runId}/summary`);
}

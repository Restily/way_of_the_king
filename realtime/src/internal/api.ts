/**
 * Internal HTTP client for Colyseus → FastAPI callbacks.
 *
 * Handles the HMAC-SHA256 signing of request bodies using
 * `INTERNAL_HMAC_REALTIME_TO_API` secret. Uses native Node 22 `fetch`.
 * Retries with exponential backoff: 3 attempts with delays 500ms / 2000ms / 8000ms.
 *
 * Exported functions:
 * - {@link finalizeRun} — terminal callback at room dispose.
 * - {@link floorCleared} — per-floor callback when player advances to next floor.
 */

import { createHmac } from 'node:crypto';

import { log as rootLog } from '../logger.js';
import type { CombatSummary } from '../game/combatLog.js';
import type { ItemDropIntent } from '../game/drops.js';

const log = rootLog.child({ component: 'internal/api' });

/** Retry delays in milliseconds: 500ms, 2s, 8s. */
const RETRY_DELAYS_MS = [500, 2000, 8000];

/**
 * Arguments for {@link finalizeRun}.
 */
export interface FinalizeRunArgs {
  runId: string;
  status: 'COMPLETED' | 'FAILED' | 'ABANDONED';
  heroState: { hp: number; mana: number };
  goldEarned: number;
  xpEarned: number;
  itemsRolled: ItemDropIntent[];
  combatSummary: CombatSummary;
}

/**
 * Sign a raw request body with HMAC-SHA256 using the internal secret.
 *
 * @param body - Raw UTF-8 encoded request body string.
 * @param secret - HMAC secret from `INTERNAL_HMAC_REALTIME_TO_API` env var.
 * @returns Hex-encoded digest (64 chars).
 */
function signBody(body: string, secret: string): string {
  return createHmac('sha256', secret).update(body).digest('hex');
}

/**
 * Sleep for a given number of milliseconds.
 *
 * @param ms - Duration to sleep.
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * POST to FastAPI `/api/v1/internal/runs/{runId}/finalize` with HMAC signing.
 *
 * Retries up to 3 times with exponential backoff (500ms → 2s → 8s).
 * If all retries fail, throws an error — caller should log and continue room shutdown.
 *
 * @param args - Finalize payload.
 * @throws {Error} If all retry attempts fail.
 */
export async function finalizeRun(args: FinalizeRunArgs): Promise<void> {
  const secret = process.env.INTERNAL_HMAC_REALTIME_TO_API ?? '';
  if (!secret) {
    log.error({ run_id: args.runId }, 'internal_hmac_secret_not_configured');
    throw new Error('INTERNAL_HMAC_REALTIME_TO_API not configured');
  }

  const apiBaseUrl = process.env.API_BASE_URL ?? 'http://localhost:8000';
  const url = `${apiBaseUrl}/api/v1/internal/runs/${args.runId}/finalize`;

  const payload = {
    status: args.status,
    hero_state: args.heroState,
    gold_earned: args.goldEarned,
    xp_earned: args.xpEarned,
    items_rolled: args.itemsRolled.map((i) => ({ rarity: i.rarity })),
    combat_summary: args.combatSummary,
  };

  const body = JSON.stringify(payload);
  const sig = signBody(body, secret);

  let lastError: Error | null = null;

  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt > 0) {
      const delayMs = RETRY_DELAYS_MS[attempt - 1] ?? 8000;
      log.warn(
        { run_id: args.runId, attempt, delay_ms: delayMs },
        'internal_finalize_retry',
      );
      await sleep(delayMs);
    }

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Internal-Sig': sig,
        },
        body,
      });

      if (response.ok) {
        log.info({ run_id: args.runId, status: args.status }, 'internal_finalize_ok');
        return;
      }

      // Non-retryable: 409 = already finalized (idempotency), 422 = bad payload.
      if (response.status === 409 || response.status === 422) {
        const text = await response.text().catch(() => '');
        log.warn(
          { run_id: args.runId, http_status: response.status, body: text },
          'internal_finalize_non_retryable_error',
        );
        return; // Don't retry — treat as terminal.
      }

      lastError = new Error(`HTTP ${response.status} from finalize endpoint`);
      log.warn(
        { run_id: args.runId, http_status: response.status, attempt },
        'internal_finalize_http_error',
      );
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      log.warn(
        { run_id: args.runId, attempt, error: lastError.message },
        'internal_finalize_network_error',
      );
    }
  }

  throw lastError ?? new Error('internal_finalize_all_retries_failed');
}

/**
 * Arguments for {@link floorCleared}.
 */
export interface FloorClearedArgs {
  runId: string;
  /** 0-based floor index that was just cleared. */
  floor: number;
  goldEarned: number;
  xpEarned: number;
  itemsRolled: ItemDropIntent[];
  combatSummary: CombatSummary;
  /** Floor index to advance the run to (= floor + 1). */
  advanceToFloor: number;
}

/**
 * POST to FastAPI `/api/v1/internal/runs/{runId}/floor-cleared` with HMAC signing.
 *
 * Called by DungeonRoom when the player sends `next_floor` and all mobs are dead.
 * Writes a RunEncounter row for the completed floor, increments
 * `dungeon_run.current_floor`, and updates `last_checkpoint_at`.
 *
 * Retries up to 3 times with exponential backoff (500ms → 2s → 8s).
 * If all retries fail, throws an error — caller should log and reject the floor advance.
 *
 * @param args - Floor-cleared payload.
 * @throws {Error} If all retry attempts fail.
 */
export async function floorCleared(args: FloorClearedArgs): Promise<void> {
  const secret = process.env.INTERNAL_HMAC_REALTIME_TO_API ?? '';
  if (!secret) {
    log.error({ run_id: args.runId }, 'internal_hmac_secret_not_configured');
    throw new Error('INTERNAL_HMAC_REALTIME_TO_API not configured');
  }

  const apiBaseUrl = process.env.API_BASE_URL ?? 'http://localhost:8000';
  const url = `${apiBaseUrl}/api/v1/internal/runs/${args.runId}/floor-cleared`;

  const payload = {
    floor: args.floor,
    gold_earned: args.goldEarned,
    xp_earned: args.xpEarned,
    items_rolled: args.itemsRolled.map((i) => ({ rarity: i.rarity })),
    combat_summary: args.combatSummary,
    advance_to_floor: args.advanceToFloor,
  };

  const body = JSON.stringify(payload);
  const sig = signBody(body, secret);

  let lastError: Error | null = null;

  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt > 0) {
      const delayMs = RETRY_DELAYS_MS[attempt - 1] ?? 8000;
      log.warn(
        { run_id: args.runId, floor: args.floor, attempt, delay_ms: delayMs },
        'internal_floor_cleared_retry',
      );
      await sleep(delayMs);
    }

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Internal-Sig': sig,
        },
        body,
      });

      if (response.ok) {
        log.info(
          { run_id: args.runId, floor: args.floor, advance_to: args.advanceToFloor },
          'internal_floor_cleared_ok',
        );
        return;
      }

      // Non-retryable: 409 = already processed, 422 = bad payload.
      if (response.status === 409 || response.status === 422) {
        const text = await response.text().catch(() => '');
        log.warn(
          { run_id: args.runId, floor: args.floor, http_status: response.status, body: text },
          'internal_floor_cleared_non_retryable_error',
        );
        return;
      }

      lastError = new Error(`HTTP ${response.status} from floor-cleared endpoint`);
      log.warn(
        { run_id: args.runId, floor: args.floor, http_status: response.status, attempt },
        'internal_floor_cleared_http_error',
      );
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      log.warn(
        { run_id: args.runId, floor: args.floor, attempt, error: lastError.message },
        'internal_floor_cleared_network_error',
      );
    }
  }

  throw lastError ?? new Error('internal_floor_cleared_all_retries_failed');
}

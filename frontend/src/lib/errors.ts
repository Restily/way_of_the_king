/**
 * Centralized API error → i18n key mapping.
 *
 * Used by all screens that need to display backend errors. Instead of each
 * screen reimplementing the err.detail switch, here лежит whitelist
 * known codes + safe fallback.
 */
import { ApiError } from '../api/client';

const KNOWN_ERROR_CODES = new Set([
  'auth_failed',
  'balance_missing',
  'expired_token',
  'generic',
  'geo_blocked',
  'hero_already_exists',
  'invalid_init_data',
  'invalid_token',
  'name_too_short',
  'network',
  'no_init_data',
]);

/**
 * Convert any thrown value to a stable error code suitable for i18n lookup.
 *
 * - ApiError: detail.toLowerCase() if known, else status-based fallback.
 * - TypeError (fetch network failure): 'network'.
 * - Otherwise: 'generic'.
 */
export function toErrorCode(err: unknown, fallback = 'generic'): string {
  if (err instanceof ApiError) {
    const code = err.detail.toLowerCase();
    if (KNOWN_ERROR_CODES.has(code)) return code;
    if (err.status === 422) return 'name_too_short';
    return fallback;
  }
  if (err instanceof TypeError) {
    // fetch() throws TypeError on network failures (offline, DNS, CORS, …)
    return 'network';
  }
  return fallback;
}

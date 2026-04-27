/** Hero CRUD endpoints. */
import { apiFetch } from './client';
import type { HeroInfo } from './me';

export interface HeroCreated extends HeroInfo {
  active_skills: string[];
}

export function createHero(
  name: string,
  idempotencyKey: string,
): Promise<HeroCreated> {
  return apiFetch<HeroCreated>('/api/v1/heroes', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: { name },
  });
}

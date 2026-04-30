/**
 * SFX placeholder — W5-054.
 *
 * Все функции — заглушки. Реальные sound packs подключаются в W6+.
 * В DEV-режиме вызовы логируются в console.debug для верификации call-сайтов.
 *
 * W6-043: добавлены раздельные id для каждого скилла Knight'а, чтобы
 * будущая аудио-система могла различать ассеты по id без изменения call-сайтов.
 */

/** Идентификаторы звуковых эффектов. */
export type SfxId =
  | 'cleave'
  | 'cleave_cast'
  | 'shield_bash_cast'
  | 'whirlwind_cast'
  | 'charge_cast'
  | 'item_drop'
  | 'item_pickup'
  | 'mob_death'
  | 'player_hit'
  | 'skill_cast';

/**
 * Воспроизвести звуковой эффект.
 *
 * :param id: Идентификатор SFX.
 */
export function playSfx(id: SfxId): void {
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.debug('[sfx]', id);
  }
}

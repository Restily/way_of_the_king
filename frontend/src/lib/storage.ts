/**
 * Persistent storage wrapper.
 *
 * Telegram CloudStorage если доступен (синхронизируется между устройствами
 * одного юзера через Telegram-инфру). Fallback на localStorage в браузере / dev.
 */
import { type CloudStorage, getTelegramWebApp } from './telegram';

const FALLBACK_PREFIX = 'wotk_';

// Telegram WebApp = singleton за всю сессию, поэтому CloudStorage handle
// можно закэшировать и не дёргать `window.Telegram?.WebApp` каждый раз.
let cachedCloud: CloudStorage | null | undefined;

function cloud(): CloudStorage | null {
  if (cachedCloud === undefined) {
    cachedCloud = getTelegramWebApp()?.CloudStorage ?? null;
  }
  return cachedCloud;
}

export async function setItem(key: string, value: string): Promise<void> {
  const cs = cloud();
  if (cs) {
    return new Promise<void>((resolve, reject) => {
      cs.setItem(key, value, (err) => (err ? reject(err) : resolve()));
    });
  }
  localStorage.setItem(FALLBACK_PREFIX + key, value);
}

export async function getItem(key: string): Promise<string | null> {
  const cs = cloud();
  if (cs) {
    return new Promise<string | null>((resolve, reject) => {
      cs.getItem(key, (err, value) => (err ? reject(err) : resolve(value ?? null)));
    });
  }
  return localStorage.getItem(FALLBACK_PREFIX + key);
}

export async function removeItem(key: string): Promise<void> {
  const cs = cloud();
  if (cs) {
    return new Promise<void>((resolve, reject) => {
      cs.removeItem(key, (err) => (err ? reject(err) : resolve()));
    });
  }
  localStorage.removeItem(FALLBACK_PREFIX + key);
}

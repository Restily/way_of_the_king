/**
 * Persistent storage wrapper.
 *
 * Использует Telegram CloudStorage если доступен (синхронизируется между
 * устройствами одного юзера). Fallback на localStorage в браузере / dev.
 */
import { getTelegramWebApp } from './telegram';

const FALLBACK_PREFIX = 'wotk_';

export async function setItem(key: string, value: string): Promise<void> {
  const cloud = getTelegramWebApp()?.CloudStorage;
  if (cloud) {
    await new Promise<void>((resolve, reject) => {
      cloud.setItem(key, value, (err) => (err ? reject(err) : resolve()));
    });
    return;
  }
  localStorage.setItem(FALLBACK_PREFIX + key, value);
}

export async function getItem(key: string): Promise<string | null> {
  const cloud = getTelegramWebApp()?.CloudStorage;
  if (cloud) {
    return new Promise<string | null>((resolve, reject) => {
      cloud.getItem(key, (err, value) => {
        if (err) reject(err);
        else resolve(typeof value === 'string' ? value : null);
      });
    });
  }
  return localStorage.getItem(FALLBACK_PREFIX + key);
}

export async function removeItem(key: string): Promise<void> {
  const cloud = getTelegramWebApp()?.CloudStorage;
  if (cloud) {
    await new Promise<void>((resolve, reject) => {
      cloud.removeItem(key, (err) => (err ? reject(err) : resolve()));
    });
    return;
  }
  localStorage.removeItem(FALLBACK_PREFIX + key);
}

/**
 * Тонкая обёртка над window.Telegram.WebApp.
 *
 * @telegram-apps/sdk-react в скоупе MVP не используется — нативный SDK
 * через тег <script> в index.html достаточен и не тянет лишних 30KB.
 */

interface TelegramThemeParams {
  bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  secondary_bg_color?: string;
}

interface TelegramUser {
  id: number;
  language_code?: string;
  is_premium?: boolean;
  username?: string;
  first_name?: string;
}

type GetItemCallback = (err: Error | null, value: string | null) => void;
type WriteCallback = (err: Error | null, ok?: boolean) => void;

interface CloudStorage {
  setItem: (key: string, value: string, cb?: WriteCallback) => void;
  getItem: (key: string, cb: GetItemCallback) => void;
  removeItem: (key: string, cb?: WriteCallback) => void;
}

interface HapticFeedback {
  impactOccurred: (style: 'light' | 'medium' | 'heavy') => void;
  notificationOccurred: (type: 'error' | 'success' | 'warning') => void;
}

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: { user?: TelegramUser };
  ready: () => void;
  expand: () => void;
  themeParams: TelegramThemeParams;
  colorScheme: 'light' | 'dark';
  viewportHeight: number;
  viewportStableHeight: number;
  HapticFeedback?: HapticFeedback;
  CloudStorage?: CloudStorage;
}

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
  }
}

export type { CloudStorage, GetItemCallback, TelegramWebApp, WriteCallback };

export function getTelegramWebApp(): TelegramWebApp | undefined {
  return window.Telegram?.WebApp;
}

export function getInitData(): string {
  return getTelegramWebApp()?.initData ?? '';
}

export function getTelegramLanguageCode(): string | undefined {
  return getTelegramWebApp()?.initDataUnsafe?.user?.language_code;
}

export function readyTelegram(): void {
  const tg = getTelegramWebApp();
  if (!tg) return;
  tg.ready();
  tg.expand();
}

export function hapticImpact(style: 'light' | 'medium' | 'heavy' = 'light'): void {
  getTelegramWebApp()?.HapticFeedback?.impactOccurred(style);
}

export function hapticNotify(
  type: 'success' | 'error' | 'warning' = 'success',
): void {
  getTelegramWebApp()?.HapticFeedback?.notificationOccurred(type);
}

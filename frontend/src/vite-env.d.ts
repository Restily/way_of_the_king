/// <reference types="vite/client" />

interface Window {
  Telegram?: {
    WebApp: {
      initData: string;
      initDataUnsafe: Record<string, unknown>;
      ready: () => void;
      expand: () => void;
      themeParams: Record<string, string>;
      viewportHeight: number;
      viewportStableHeight: number;
      HapticFeedback?: {
        impactOccurred: (style: 'light' | 'medium' | 'heavy') => void;
      };
      CloudStorage?: {
        getItem: (key: string, callback: (err: Error | null, value: string) => void) => void;
        setItem: (key: string, value: string, callback?: (err: Error | null) => void) => void;
      };
    };
  };
}

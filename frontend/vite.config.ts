import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Разрешаем ngrok / cloudflared / loca.lt туннели для local Telegram
    // Mini App тестирования. В проде фронт отдаёт Caddy, не Vite dev server.
    allowedHosts: ['.ngrok-free.app', '.ngrok.app', '.trycloudflare.com', '.loca.lt'],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/game': {
        target: 'ws://localhost:2567',
        ws: true,
      },
    },
  },
  build: {
    target: 'es2022',
    // 'hidden' = sourcemap файл создаётся, но НЕ ссылается из bundle.
    // Можем загружать в Sentry для server-side decode, без публичного link'а.
    sourcemap: mode === 'production' ? 'hidden' : true,
    chunkSizeWarningLimit: 250,
    rollupOptions: {
      output: {
        // ВНИМАНИЕ: pixi/tonconnect должны импортироваться ТОЛЬКО внутри
        // lazy-loaded screens (React.lazy → import()), иначе они попадут
        // в основной bundle и убьют first paint.
        manualChunks: {
          pixi: ['pixi.js', '@pixi/tilemap'],
          react: ['react', 'react-dom'],
          i18n: ['i18next', 'react-i18next', 'i18next-browser-languagedetector'],
        },
      },
    },
  },
}));

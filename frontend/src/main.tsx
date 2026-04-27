import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import './i18n';
import './index.css';
import { readyTelegram } from './lib/telegram';

// Сообщаем Telegram что Mini App готов к показу + расширяем viewport.
// Безопасно вызывается даже вне Telegram (no-op).
readyTelegram();

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('Root element #root not found');

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

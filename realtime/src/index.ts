import { Server } from '@colyseus/core';
import { WebSocketTransport } from '@colyseus/ws-transport';
import { monitor } from '@colyseus/monitor';
import express from 'express';
import basicAuth from 'express-basic-auth';
import { createServer } from 'http';

import { log } from './logger.js';
import { DungeonRoom } from './rooms/DungeonRoom.js';

const APP_ENV = process.env.APP_ENV ?? 'production';
const PORT = Number(process.env.REALTIME_PORT ?? 2567);

const app = express();

// Скрываем Express identification.
app.disable('x-powered-by');

app.use(express.json({ limit: '64kb' }));

// Health endpoint — БЕЗ версии (не помогаем атакующим таргетить CVE).
app.get('/health', (_req, res) => {
  res.json({ status: 'ok' });
});

// Colyseus monitor — только в development и только за basic auth.
// Раскрывает структуру комнат, позволяет kill их → опасно публично.
if (APP_ENV === 'development') {
  const monitorPassword = process.env.COLYSEUS_MONITOR_PASSWORD;
  if (!monitorPassword || monitorPassword.length < 16) {
    log.warn(
      'COLYSEUS_MONITOR_PASSWORD is not set or too short — /colyseus disabled',
    );
  } else {
    app.use(
      '/colyseus',
      basicAuth({
        users: { admin: monitorPassword },
        challenge: true,
        realm: 'wotk-realtime-monitor',
      }),
      monitor(),
    );
    log.info('colyseus_monitor_enabled (auth required)');
  }
}

// Production-валидация HMAC секретов для callback'ов в FastAPI.
// Если в проде их нет — отказываемся стартовать.
if (APP_ENV !== 'development') {
  const realtimeToApi = process.env.INTERNAL_HMAC_REALTIME_TO_API ?? '';
  const apiToRealtime = process.env.INTERNAL_HMAC_API_TO_REALTIME ?? '';

  if (realtimeToApi.length < 32 || apiToRealtime.length < 32) {
    log.fatal(
      'INTERNAL_HMAC_* secrets must be set and >= 32 chars in non-development env',
    );
    process.exit(1);
  }
  if (realtimeToApi === apiToRealtime) {
    log.fatal(
      'INTERNAL_HMAC_REALTIME_TO_API and INTERNAL_HMAC_API_TO_REALTIME must be DIFFERENT',
    );
    process.exit(1);
  }
}

const httpServer = createServer(app);

const gameServer = new Server({
  transport: new WebSocketTransport({ server: httpServer }),
});

// Регистрация игровых комнат.
gameServer.define('dungeon', DungeonRoom);

// JWT_SECRET sanity-check на старте (DungeonRoom.onAuth требует его).
if (!process.env.JWT_SECRET) {
  if (APP_ENV !== 'development') {
    log.fatal('JWT_SECRET must be set in non-development env');
    process.exit(1);
  }
  log.warn('JWT_SECRET not set — DungeonRoom.onAuth will reject all connections');
}

httpServer.listen(PORT, () => {
  log.info({ port: PORT, env: APP_ENV }, 'realtime server listening');
});

const shutdown = async (signal: string) => {
  log.info({ signal }, 'shutdown initiated');
  await gameServer.gracefullyShutdown();
  process.exit(0);
};

process.on('SIGTERM', () => void shutdown('SIGTERM'));
process.on('SIGINT', () => void shutdown('SIGINT'));

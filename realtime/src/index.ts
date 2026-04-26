import { Server } from '@colyseus/core';
import { WebSocketTransport } from '@colyseus/ws-transport';
import { monitor } from '@colyseus/monitor';
import express from 'express';
import { createServer } from 'http';
import pino from 'pino';

const log = pino({
  transport: process.env.NODE_ENV === 'production'
    ? undefined
    : { target: 'pino-pretty' },
});

const PORT = Number(process.env.REALTIME_PORT ?? 2567);

const app = express();
app.use(express.json());

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: 'realtime', version: '0.1.0' });
});

// Colyseus monitor (только в dev и за внутренним доступом)
if (process.env.APP_ENV !== 'production') {
  app.use('/colyseus', monitor());
}

const httpServer = createServer(app);

const gameServer = new Server({
  transport: new WebSocketTransport({ server: httpServer }),
});

// Регистрация игровых комнат — заполнится в Phase 3 (Недели 5-7)
// gameServer.define('dungeon', DungeonRoom);

httpServer.listen(PORT, () => {
  log.info({ port: PORT }, 'realtime server listening');
});

process.on('SIGTERM', async () => {
  log.info('SIGTERM received, shutting down');
  await gameServer.gracefullyShutdown();
  process.exit(0);
});

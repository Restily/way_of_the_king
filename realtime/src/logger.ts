/**
 * Shared pino logger — наследуется через `.child()` в room/handler модулях.
 *
 * Конфигурируется один раз при импорте: redact чувствительных полей + JSON
 * формат в production, pino-pretty в development. Если каждый модуль создаёт
 * свой `pino()` — теряются redact-правила и появляется риск утечки секретов.
 */

import pino from 'pino';

const NODE_ENV = process.env.NODE_ENV ?? 'production';

export const log = pino({
  transport: NODE_ENV === 'production' ? undefined : { target: 'pino-pretty' },
  redact: {
    paths: [
      '*.token',
      '*.jwt',
      '*.password',
      '*.secret',
      '*.authorization',
      '*.mnemonic',
      '*.hot_wallet_mnemonic',
      '*.api_key',
      '*.ws_token',
      '*.init_data',
      '*.initData',
      '*.tfa_code',
      'req.headers.authorization',
      'req.headers.cookie',
    ],
    censor: '***REDACTED***',
  },
});

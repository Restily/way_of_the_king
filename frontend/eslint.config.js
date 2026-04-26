import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import i18nextPlugin from 'eslint-plugin-i18next';

export default [
  js.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: {
      'react-hooks': reactHooks,
      i18next: i18nextPlugin,
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // Запрет литералов в JSX — все строки через i18next
      'i18next/no-literal-string': ['warn', { markupOnly: true }],
    },
  },
  {
    ignores: ['dist/', 'node_modules/', '*.config.js', '*.config.ts'],
  },
];

import i18n from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { initReactI18next } from 'react-i18next';

import en from './en.json';
import ru from './ru.json';

/**
 * Активные локали. Расширяется по мере появления переводов.
 * Убедись что порядок имён совпадает с файлами в этой директории + регистрацией
 * в `resources` ниже.
 */
export const SUPPORTED_LOCALES = ['ru', 'en'] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      ru: { translation: ru },
      en: { translation: en },
    },
    fallbackLng: 'ru',
    supportedLngs: SUPPORTED_LOCALES,
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'wotk_locale',
    },
  });

export default i18n;

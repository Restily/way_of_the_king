import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { createHero } from '../api/heroes';
import { toErrorCode } from '../lib/errors';
import { hapticNotify } from '../lib/telegram';
import { useAuthStore } from '../store/auth';

export function CreateHero() {
  const { t } = useTranslation();
  const applyHero = useAuthStore((s) => s.applyHero);

  // Один и тот же ключ на форму — повторный submit с тем же payload
  // backend увидит как retry, не как два независимых create.
  const idempotencyKeyRef = useRef<string>(crypto.randomUUID());

  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  const trimmed = name.trim();
  const isValid = trimmed.length >= 3 && trimmed.length <= 20;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValid || submitting) return;
    setSubmitting(true);
    setErrorCode(null);
    try {
      const hero = await createHero(trimmed, idempotencyKeyRef.current);
      hapticNotify('success');
      applyHero(hero);
    } catch (err) {
      hapticNotify('error');
      setErrorCode(toErrorCode(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="screen">
      <header className="screen__header">
        <h1>{t('create_hero.title')}</h1>
        <p className="muted">{t('create_hero.subtitle')}</p>
      </header>

      <form className="form" onSubmit={submit}>
        <label className="form__field">
          <span className="form__label">{t('create_hero.name_label')}</span>
          <input
            type="text"
            className="form__input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('create_hero.name_placeholder')}
            minLength={3}
            maxLength={20}
            disabled={submitting}
          />
        </label>

        {errorCode && (
          <p className="error">
            {t(`errors.${errorCode}`, { defaultValue: t('errors.generic') })}
          </p>
        )}

        <button
          type="submit"
          className="btn btn--primary"
          disabled={!isValid || submitting}
        >
          {submitting ? t('create_hero.creating') : t('create_hero.create_button')}
        </button>
      </form>
    </div>
  );
}

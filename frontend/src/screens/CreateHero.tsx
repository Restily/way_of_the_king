import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { createHero } from '../api/heroes';
import { ApiError } from '../api/client';
import type { HeroCreated } from '../api/heroes';
import { hapticNotify } from '../lib/telegram';

interface Props {
  onCreated: (hero: HeroCreated) => void;
}

export function CreateHero({ onCreated }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  const isValid = name.trim().length >= 3 && name.trim().length <= 20;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValid || submitting) return;
    setSubmitting(true);
    setErrorCode(null);
    try {
      const hero = await createHero(name.trim());
      hapticNotify('success');
      onCreated(hero);
    } catch (err) {
      hapticNotify('error');
      if (err instanceof ApiError) {
        if (err.detail === 'HERO_ALREADY_EXISTS') {
          setErrorCode('hero_already_exists');
        } else if (err.status === 422) {
          setErrorCode('name_too_short');
        } else {
          setErrorCode('generic');
        }
      } else {
        setErrorCode('network');
      }
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
            autoFocus
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

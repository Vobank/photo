import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../../api/client'
import { useSystem } from '../../api/queries'
import { Button } from '../../components/Button'
import { Segmented } from '../../components/Segmented'
import { toast } from '../../components/toast'
import fieldStyles from '../../components/Field.module.css'
import { LANGUAGES, setLanguage } from '../../i18n'
import styles from './Page.module.css'

type Theme = 'system' | 'dark' | 'light'

function readTheme(): Theme {
  const t = document.documentElement.dataset.theme
  return t === 'dark' || t === 'light' ? t : 'system'
}

function applyTheme(theme: Theme) {
  try {
    if (theme === 'system') {
      delete document.documentElement.dataset.theme
      localStorage.removeItem('photo.theme')
    } else {
      document.documentElement.dataset.theme = theme
      localStorage.setItem('photo.theme', theme)
    }
  } catch {
    /* storage unavailable: theme still applies for this session */
  }
}

export default function SettingsView() {
  const { t, i18n } = useTranslation()
  const [theme, setTheme] = useState<Theme>(readTheme)
  const { data: system } = useSystem()

  return (
    <div className={styles.page}>
      <div className={styles.column}>
        <header className={styles.head}>
          <h1>{t('settings.title')}</h1>
        </header>

        <section className={styles.card}>
          <div className={styles.row}>
            <span>{t('settings.language')}</span>
            <select
              aria-label={t('settings.language')}
              className={fieldStyles.select}
              style={{ width: 240 }}
              value={i18n.resolvedLanguage ?? 'en'}
              onChange={(e) => {
                const lng = e.target.value
                void setLanguage(lng, { remember: true })
                // Saved on the server too, so phones and other browsers follow.
                api.setLanguage(lng).catch(() => undefined)
              }}
            >
              {LANGUAGES.map((l) => (
                <option key={l.id} value={l.id} lang={l.id}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.row}>
            <span>{t('settings.theme')}</span>
            <div>
              <Segmented
                label={t('settings.theme')}
                value={theme}
                options={(['system', 'dark', 'light'] as const).map((v) => ({ value: v, label: t(`settings.themes.${v}`) }))}
                onChange={(v) => {
                  setTheme(v)
                  applyTheme(v)
                }}
              />
            </div>
          </div>
        </section>

        <section className={styles.card}>
          <h2>{t('settings.engine')}</h2>
          <div className={styles.row}>
            <span className={styles.muted}>
              {system ? t(`engine.${system.engine.state}`) : '…'}
              {system?.engine.error ? ` — ${system.engine.error}` : ''}
            </span>
            <Button
              size="sm"
              onClick={() => {
                void api.restartEngine()
                toast(t('settings.restarting'))
              }}
            >
              {t('settings.restartEngine')}
            </Button>
          </div>
        </section>

        <section className={styles.card}>
          <h2>{t('settings.about')}</h2>
          <p className={styles.muted}>{t('settings.aboutBody', { version: system?.version ?? '' })}</p>
          <p className={styles.muted}>{t('settings.privacy')}</p>
        </section>
      </div>
    </div>
  )
}

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { api } from '../../api/client'
import { keys } from '../../api/queries'
import type { ModelInfo } from '../../api/types'
import { Button } from '../../components/Button'
import { toastError } from '../../components/toast'
import { apiErrorText } from '../../lib/errors'
import { formatBytes } from '../../lib/format'
import { useLive } from '../../state/live'
import styles from './Studio.module.css'

/** Shown instead of the canvas until at least one model is installed. */
export function Onboarding({ models }: { models: ModelInfo[] }) {
  const { t } = useTranslation()
  const first = models[0]
  return (
    <div className={styles.onboarding}>
      <div className={styles.onboardCard}>
        <h1>{t('onboarding.title')}</h1>
        <p>{t('onboarding.body')}</p>
        {first && <ModelInstallLine model={first} />}
        <p className={styles.dims}>{t('onboarding.later')}</p>
      </div>
    </div>
  )
}

export function ModelInstallLine({ model, showName = true }: { model: ModelInfo; showName?: boolean }) {
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const live = useLive((s) => s.installs[model.id])
  const install = live && !live.finished ? live : model.install
  const variant = model.variants.find((v) => v.recommended) ?? model.variants[0]

  const start = useMutation({
    mutationFn: () => api.installModel(model.id, variant.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.models }),
    onError: (e) => toastError(apiErrorText(t, e)),
  })

  const lastError = live?.finished && live.error && live.error !== 'cancelled' ? live.error : null
  const lng = i18n.language

  return (
    <div className={styles.modelLine}>
      <div style={{ flex: 1, minWidth: 0 }}>
        {showName ? <div>{model.name}</div> : null}
        <small>{variant.label}</small>
        {install ? (
          <>
            <small className="num">
              {formatBytes(install.done, lng)} / {formatBytes(install.total, lng)}
            </small>
            <div className={styles.bar} role="progressbar" aria-valuemin={0} aria-valuemax={install.total} aria-valuenow={install.done}>
              <span style={{ width: `${(install.done / Math.max(install.total, 1)) * 100}%` }} />
            </div>
          </>
        ) : (
          <small>
            {model.license} · {formatBytes(variant.download_bytes, lng)}
          </small>
        )}
        {lastError && <small style={{ color: 'var(--danger)' }}>{lastError}</small>}
      </div>
      {install ? (
        <Button variant="ghost" size="sm" onClick={() => void api.cancelInstall(model.id)}>
          {t('actions.cancel')}
        </Button>
      ) : (
        <Button variant="primary" onClick={() => start.mutate()} disabled={start.isPending}>
          {lastError ? t('actions.retry') : t('actions.download')}
        </Button>
      )}
    </div>
  )
}

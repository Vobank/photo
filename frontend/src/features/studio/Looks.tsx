import { useQuery } from '@tanstack/react-query'
import { useId } from 'react'
import { useTranslation } from 'react-i18next'

import type { ModelFeatures } from '../../api/types'
import { AUTO, useStudio } from '../../state/studio'
import styles from './Studio.module.css'

const useStyles = () =>
  useQuery({
    queryKey: ['styles'],
    queryFn: async () => (await fetch('/api/v1/styles').then((r) => r.json())) as { styles: { id: string }[] },
    staleTime: Infinity,
  })

/** Style presets and the two quality switches. */
export function Looks({ features }: { features: ModelFeatures | undefined }) {
  const { t } = useTranslation()
  const s = useStudio()
  const { data } = useStyles()
  const enhanceId = useId()
  const detailId = useId()
  // "auto" first: Photo reads the prompt and picks the look; then no style; then presets.
  const ids = [AUTO, null, ...(data?.styles.map((x) => x.id) ?? [])]

  return (
    <>
      <div className={styles.section}>
        <div className={styles.sectionTitle} id="style-label">
          {t('looks.style')}
        </div>
        <div className={styles.styles} role="radiogroup" aria-labelledby="style-label">
          {ids.map((id) => (
            <button
              key={id ?? 'none'}
              type="button"
              role="radio"
              aria-checked={s.style === id}
              className={styles.styleChip}
              onClick={() => s.set({ style: id })}
            >
              {t(`styles.${id ?? 'none'}`)}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.section}>
        <label className={styles.toggle} htmlFor={enhanceId}>
          <input id={enhanceId} type="checkbox" checked={s.enhance} onChange={(e) => s.set({ enhance: e.target.checked })} />
          <span>
            {t('looks.enhance')}
            <small>{t('looks.enhanceHint')}</small>
          </span>
        </label>
        <label className={styles.toggle} htmlFor={detailId} data-disabled={!features?.detail}>
          <input
            id={detailId}
            type="checkbox"
            checked={s.detail && !!features?.detail}
            disabled={!features?.detail}
            onChange={(e) => s.set({ detail: e.target.checked })}
          />
          <span>
            {t('looks.detail')}
            <small>{features?.detail ? t('looks.detailHint') : t('looks.detailUnavailable')}</small>
          </span>
        </label>
      </div>
    </>
  )
}

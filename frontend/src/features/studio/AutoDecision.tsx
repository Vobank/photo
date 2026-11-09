import { useTranslation } from 'react-i18next'

import { useModels } from '../../api/queries'
import type { Resolved } from '../../api/types'

/**
 * "Auto: Photo · FLUX.2 Klein 4B" — what automatic mode chose for this picture.
 * Hovering shows the English prompt the image model received, when one was written.
 */
export function AutoDecision({ resolved }: { resolved: Resolved | null | undefined }) {
  const { t } = useTranslation()
  const { data: models } = useModels()
  if (!resolved) return null
  const modelName = models?.find((m) => m.id === resolved.model)?.name ?? resolved.model
  const look = resolved.style ? t(`styles.${resolved.style}`) : t('styles.none')
  return (
    <span title={resolved.prompt ?? undefined} style={{ fontFamily: 'var(--font-sans)' }}>
      {t('studio.autoChose', { style: look, model: modelName })}
    </span>
  )
}

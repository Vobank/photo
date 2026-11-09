import type { TFunction } from 'i18next'

import { ApiError } from '../api/client'
import type { Job } from '../api/types'

/** A request error in the user's language; the server's English text is the fallback. */
export function apiErrorText(t: TFunction, err: unknown): string {
  if (err instanceof ApiError) return t(`errors.api.${err.code}`, { defaultValue: err.message })
  return t('errors.network')
}

/** Headline and optional technical detail for a failed job. */
export function jobErrorText(t: TFunction, job: Pick<Job, 'error' | 'error_code'>): { title: string; detail: string | null } {
  const code = job.error_code ?? 'engine_error'
  const title = t(`errors.job.${code}`, { defaultValue: t('errors.job.engine_error') })
  // Only raw engine errors carry information the headline does not.
  return { title, detail: code === 'engine_error' ? job.error : null }
}

import type { TFunction } from 'i18next'

import { api } from '../../api/client'
import { queryClient } from '../../api/queries'
import type { ImageInfo, ModelInfo } from '../../api/types'
import { toast, toastError } from '../../components/toast'
import { apiErrorText } from '../../lib/errors'
import { navigate } from '../../lib/router'
import { useLive } from '../../state/live'
import { randomSeed, useStudio } from '../../state/studio'

/** Add a gallery picture to the studio's references. */
export function addAsReference(image: ImageInfo, t: TFunction) {
  useStudio.getState().addInput({ id: image.id, kind: 'image', width: image.width, height: image.height }, 'references')
  navigate({ view: 'studio' })
  toast(t('looks.addedAsReference'))
}

/** One click: new pictures that keep this one's composition and colours. */
export async function moreLikeThis(image: ImageInfo, t: TFunction): Promise<void> {
  const models = queryClient.getQueryData<ModelInfo[]>(['models']) ?? (await api.models())
  const same = models.find((m) => m.id === image.model && m.installed && m.features.variation)
  const model = same ?? models.find((m) => m.installed && m.features.variation)
  if (!model) {
    toastError(t('errors.api.variation_unsupported'))
    return
  }
  const p = image.params
  try {
    const job = await api.createJob({
      ...p,
      model: model.id,
      references: [],
      variation_of: image.id,
      variation_strength: 0.45,
      seed: randomSeed(),
      batch_size: Math.max(p.batch_size, 2),
      // Keep the look; skip a second language-model rewrite of an already rewritten prompt.
      enhance: false,
      prompt: image.final_prompt ?? p.prompt,
    })
    useLive.getState().upsertJob(job)
    useStudio.getState().set({ selectedImageId: null })
    navigate({ view: 'studio' })
  } catch (e) {
    toastError(apiErrorText(t, e))
  }
}

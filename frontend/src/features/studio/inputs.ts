import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, thumbUrl, uploadThumbUrl } from '../../api/client'
import { toastError } from '../../components/toast'
import { apiErrorText } from '../../lib/errors'
import { type InputPicture, useStudio } from '../../state/studio'

export const pictureThumb = (p: InputPicture) => (p.kind === 'image' ? thumbUrl(p.id) : uploadThumbUrl(p.id))

/** Upload files (from a picker, a drop or the clipboard) and add them as inputs. */
export function useAddFiles() {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(0)
  const add = useCallback(async (files: Iterable<File>) => {
    const images = [...files].filter((f) => f.type.startsWith('image/'))
    for (const file of images) {
      setBusy((n) => n + 1)
      try {
        const up = await api.upload(file)
        useStudio.getState().addInput({ id: up.id, kind: 'upload', width: up.width, height: up.height })
      } catch (e) {
        toastError(apiErrorText(t, e))
      } finally {
        setBusy((n) => n - 1)
      }
    }
  }, [t])
  return { add, busy: busy > 0 }
}

/** Rewrites the prompt with the local language model so the user can read and edit it. */
export async function improvePrompt(onUndoable: (previous: string) => void): Promise<void> {
  const s = useStudio.getState()
  const previous = s.prompt
  const { prompt } = await api.enhancePrompt(previous, s.style, s.inputMode === 'references' && s.inputs.length > 0)
  useStudio.getState().set({ prompt })
  onUndoable(previous)
}

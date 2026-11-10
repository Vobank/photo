import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../../api/client'
import type { ImageInfo } from '../../api/types'
import { toastError } from '../../components/toast'
import { apiErrorText } from '../../lib/errors'
import { useEdit } from '../../state/edit'

/** Upload a picture from disk (picker, drop or paste) and start editing it. */
export function useOpenFiles() {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const open = useCallback(
    async (files: Iterable<File>) => {
      const file = [...files].find((f) => f.type.startsWith('image/'))
      if (!file) return
      setBusy(true)
      try {
        const up = await api.upload(file)
        useEdit.getState().open({ id: up.id, kind: 'upload', width: up.width, height: up.height })
      } catch (e) {
        toastError(apiErrorText(t, e))
      } finally {
        setBusy(false)
      }
    },
    [t],
  )
  return { open, busy }
}

/** Start editing a picture from the gallery. */
export const editImage = (image: Pick<ImageInfo, 'id' | 'width' | 'height'>) =>
  useEdit.getState().open({ id: image.id, kind: 'image', width: image.width, height: image.height })

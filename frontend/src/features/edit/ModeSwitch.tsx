import type { InfiniteData } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { keys, queryClient } from '../../api/queries'
import type { ImageInfo } from '../../api/types'
import { Segmented } from '../../components/Segmented'
import { useEdit } from '../../state/edit'
import { useStudio } from '../../state/studio'
import { editImage } from './openFiles'

/** The picture on the canvas right now: the selected one, else the newest. */
function currentImage(): ImageInfo | undefined {
  const pages = queryClient.getQueryData<InfiniteData<{ images: ImageInfo[] }>>(keys.images(false))
  const images = pages?.pages.flatMap((p) => p.images) ?? []
  const selected = useStudio.getState().selectedImageId
  return (selected ? images.find((i) => i.id === selected) : undefined) ?? images[0]
}

/** "Create | Edit" at the top of the studio's side panel. */
export function ModeSwitch() {
  const { t } = useTranslation()
  const active = useEdit((s) => s.active)
  return (
    <Segmented<'create' | 'edit'>
      label={t('edit.mode')}
      value={active ? 'edit' : 'create'}
      options={[
        { value: 'create', label: t('edit.modeCreate') },
        { value: 'edit', label: t('edit.modeEdit') },
      ]}
      onChange={(mode) => {
        const s = useEdit.getState()
        if (mode === 'create') return s.close()
        if (s.source) return s.set({ active: true })
        // Start with whatever picture the user was just looking at.
        const image = currentImage()
        if (image) editImage(image)
        else s.set({ active: true })
      }}
    />
  )
}

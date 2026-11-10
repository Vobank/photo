import { useEffect, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'

import { thumbUrl } from '../../api/client'
import { useImages } from '../../api/queries'
import { activeJobs, useLive } from '../../state/live'
import { useEdit } from '../../state/edit'
import { useStudio } from '../../state/studio'
import { editImage } from '../edit/openFiles'
import styles from './Studio.module.css'

export function Filmstrip() {
  const { t } = useTranslation()
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useImages()
  const images = useMemo(() => data?.pages.flatMap((p) => p.images) ?? [], [data])
  const pending = useLive(useShallow((s) => activeJobs(s.jobs)))
  const previews = useLive((s) => s.previews)
  const progress = useLive((s) => s.progress)
  const selectedId = useStudio((s) => s.selectedImageId)
  const select = (id: string | null) => useStudio.getState().set({ selectedImageId: id })
  const shownId = selectedId ?? (pending.length ? null : images[0]?.id ?? null)
  const listRef = useRef<HTMLDivElement>(null)

  // ← / → step through results when not typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
      if ((e.target as HTMLElement).closest('input, textarea, select, [role="radiogroup"]')) return
      const idx = images.findIndex((i) => i.id === shownId)
      const older = e.key === (document.documentElement.dir === 'rtl' ? 'ArrowLeft' : 'ArrowRight')
      const next = images[older ? idx + 1 : Math.max(0, idx - 1)]
      if (next) {
        e.preventDefault()
        select(next.id)
        listRef.current?.querySelector(`[data-id="${next.id}"]`)?.scrollIntoView({ inline: 'nearest' })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [images, shownId])

  const onScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    if (hasNextPage && !isFetchingNextPage && el.scrollLeft + el.clientWidth > el.scrollWidth - 400) {
      void fetchNextPage()
    }
  }

  if (!images.length && !pending.length) return null

  return (
    <div className={styles.filmstrip} ref={listRef} onScroll={onScroll} aria-label={t('studio.results')}>
      {pending
        .slice()
        .reverse()
        .map((job) => {
          const p = progress[job.id]
          return (
            <button
              key={job.id}
              type="button"
              className={`${styles.thumb} ${styles.pending}`}
              aria-current={selectedId === null}
              aria-label={t('studio.inProgress')}
              onClick={() => select(null)}
            >
              {previews[job.id] && <img src={previews[job.id]} alt="" />}
              {!previews[job.id] && <span>{job.status === 'queued' ? t('studio.queued') : '…'}</span>}
              {p && <span className={styles.pendingBar} style={{ width: `${(p.value / p.max) * 100}%` }} />}
            </button>
          )
        })}
      {images.map((img) => (
        <button
          key={img.id}
          data-id={img.id}
          type="button"
          className={styles.thumb}
          aria-current={img.id === shownId}
          aria-label={img.params.prompt}
          onClick={() => (useEdit.getState().active ? editImage(img) : select(img.id))}
        >
          <img src={thumbUrl(img.id)} alt="" loading="lazy" decoding="async" />
        </button>
      ))}
    </div>
  )
}

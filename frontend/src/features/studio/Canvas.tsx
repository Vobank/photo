import {
  ArrowCounterClockwise,
  Copy,
  DownloadSimple,
  Heart,
  ImageSquare,
  Plant,
  Shuffle,
  Trash,
  X,
} from '@phosphor-icons/react'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, downloadUrl, imageUrl } from '../../api/client'
import { patchCachedImage, useImages, useToggleFavorite } from '../../api/queries'
import type { ImageInfo, Job } from '../../api/types'
import { IconButton } from '../../components/Button'
import { toast, toastError } from '../../components/toast'
import { jobErrorText } from '../../lib/errors'
import { formatDuration } from '../../lib/format'
import { useLive } from '../../state/live'
import { useStudio } from '../../state/studio'
import { AutoDecision } from './AutoDecision'
import { moreLikeThis, addAsReference } from './pictureActions'
import styles from './Studio.module.css'

/** The job the canvas should follow: running first, then the oldest queued. */
function useFocusJob(): Job | null {
  return useLive((s) => {
    const jobs = Object.values(s.jobs)
    return (
      jobs.find((j) => j.status === 'running') ??
      jobs.filter((j) => j.status === 'queued').sort((a, b) => (a.id < b.id ? -1 : 1))[0] ??
      null
    )
  })
}

function useLatestJob(): Job | null {
  return useLive((s) => {
    let latest: Job | null = null
    for (const j of Object.values(s.jobs)) if (!latest || j.id > latest.id) latest = j
    return latest
  })
}

export function Canvas() {
  const { t } = useTranslation()
  const selectedId = useStudio((s) => s.selectedImageId)
  const { data } = useImages()
  const images = data?.pages.flatMap((p) => p.images) ?? []
  const focusJob = useFocusJob()
  const latestJob = useLatestJob()
  const [dismissedError, setDismissedError] = useState<string | null>(null)

  const selected = selectedId ? images.find((i) => i.id === selectedId) : undefined

  if (!selected && focusJob) return <LiveView job={focusJob} />

  if (
    !selected &&
    latestJob?.status === 'failed' &&
    latestJob.id !== dismissedError &&
    (!images[0] || latestJob.id > images[0].job_id)
  ) {
    return (
      <div className={styles.canvas}>
        <div className={styles.errorBox} role="alert">
          <p>{jobErrorText(t, latestJob).title}</p>
          {jobErrorText(t, latestJob).detail && <p>{jobErrorText(t, latestJob).detail}</p>}
        </div>
        <div className={styles.toolbar}>
          <IconButton label={t('actions.dismiss')} onClick={() => setDismissedError(latestJob.id)}>
            <X size={16} />
          </IconButton>
        </div>
      </div>
    )
  }

  const image = selected ?? images[0]
  if (!image) {
    return (
      <div className={styles.canvas}>
        <div className={styles.empty}>
          <strong>{t('studio.emptyTitle')}</strong>
          <span>{t('studio.emptyBody')}</span>
        </div>
      </div>
    )
  }
  return <ImageView image={image} />
}

function LiveView({ job }: { job: Job }) {
  const { t, i18n } = useTranslation()
  const preview = useLive((s) => s.previews[job.id])
  const progress = useLive((s) => s.progress[job.id])
  const ahead = useLive(
    (s) => Object.values(s.jobs).filter((j) => j.status === 'queued' && j.id < job.id).length,
  )
  const [now, setNow] = useState(() => performance.now())

  useEffect(() => {
    const id = setInterval(() => setNow(performance.now()), 200)
    return () => clearInterval(id)
  }, [])

  const { width, height } = job.params
  const frac = progress ? progress.value / progress.max : 0
  const elapsed = progress ? (now - progress.startedAt) / 1000 : 0

  return (
    <div className={styles.canvas} aria-busy="true">
      <div className={styles.progressLine}>
        <span style={{ width: `${frac * 100}%` }} />
      </div>
      {preview ? (
        <img
          className={styles.canvasImage}
          src={preview}
          alt=""
          style={{ aspectRatio: `${width} / ${height}`, width: `min(100%, ${width}px)`, imageRendering: 'auto' }}
        />
      ) : (
        <div
          className={styles.placeholder}
          style={{ aspectRatio: `${width} / ${height}`, width: `min(100%, ${width}px, calc((100dvh - 200px) * ${width / height}))` }}
        >
          {job.status === 'queued'
            ? ahead > 0
              ? t('studio.queuedAhead', { count: ahead })
              : t('studio.starting')
            : t('studio.loadingModel')}
        </div>
      )}
      <div className={`${styles.canvasMeta} num`}>
        {progress && (
          <span>
            {t('studio.step', { value: progress.value, max: progress.max })}
          </span>
        )}
        {progress && <span>{formatDuration(elapsed, i18n.language)}</span>}
        <span>
          {width} × {height}
        </span>
        <AutoDecision resolved={job.resolved} />
      </div>
      <div className={styles.toolbar}>
        <IconButton label={t('actions.cancel')} onClick={() => void api.cancelJob(job.id)}>
          <X size={16} />
        </IconButton>
      </div>
    </div>
  )
}

function ImageView({ image }: { image: ImageInfo }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const reuse = useStudio((s) => s.reuse)
  const favorite = useToggleFavorite()

  const copy = async () => {
    try {
      const blob = await (await fetch(imageUrl(image.id))).blob()
      await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })])
      toast(t('toast.copied'))
    } catch {
      toastError(t('errors.clipboard'))
    }
  }

  const remove = async () => {
    try {
      await api.deleteImage(image.id)
      patchCachedImage(qc, image.id, null)
      useStudio.getState().set({ selectedImageId: null })
      toast(t('toast.deleted'), {
        action: {
          label: t('actions.undo'),
          run: () =>
            void api.restoreImage(image.id).then(() => qc.invalidateQueries({ queryKey: ['images'] })),
        },
      })
    } catch {
      toastError(t('errors.network'))
    }
  }

  useCanvasShortcuts({
    f: () => favorite.mutate({ id: image.id, favorite: !image.favorite }),
    m: () => void moreLikeThis(image, t),
    Delete: () => void remove(),
  })

  return (
    <div className={styles.canvas}>
      <img
        key={image.id}
        className={styles.canvasImage}
        src={imageUrl(image.id)}
        width={image.width}
        height={image.height}
        alt={image.params.prompt}
        style={{ width: 'auto', height: 'auto' }}
      />
      <div className={`${styles.canvasMeta} num`}>
        <span>
          {image.width} × {image.height}
        </span>
        <span>
          {t('studio.seed')} {image.seed}
        </span>
        <AutoDecision resolved={image.resolved} />
      </div>
      <div className={styles.toolbar}>
        <IconButton
          label={image.favorite ? t('actions.unfavorite') : t('actions.favorite')}
          shortcut="F"
          active={image.favorite}
          onClick={() => favorite.mutate({ id: image.id, favorite: !image.favorite })}
        >
          <Heart size={16} weight={image.favorite ? 'fill' : 'regular'} />
        </IconButton>
        <IconButton label={t('actions.reuse')} onClick={() => reuse(image)}>
          <ArrowCounterClockwise size={16} />
        </IconButton>
        <IconButton label={t('actions.reuseSeed')} onClick={() => reuse(image, { withSeed: true })}>
          <Plant size={16} />
        </IconButton>
        <span className={styles.toolbarSep} />
        <IconButton label={t('looks.moreLikeThis')} shortcut="M" onClick={() => void moreLikeThis(image, t)}>
          <Shuffle size={16} />
        </IconButton>
        <IconButton label={t('looks.addAsReference')} onClick={() => addAsReference(image, t)}>
          <ImageSquare size={16} />
        </IconButton>
        <span className={styles.toolbarSep} />
        <IconButton label={t('actions.copy')} onClick={() => void copy()}>
          <Copy size={16} />
        </IconButton>
        <IconButton
          label={t('actions.download')}
          onClick={() => {
            location.href = downloadUrl(image.id)
          }}
        >
          <DownloadSimple size={16} />
        </IconButton>
        <span className={styles.toolbarSep} />
        <IconButton label={t('actions.delete')} shortcut="Del" onClick={() => void remove()}>
          <Trash size={16} />
        </IconButton>
      </div>
    </div>
  )
}

/** Single-key shortcuts that only fire when the user is not typing. */
function useCanvasShortcuts(map: Record<string, () => void>) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (el.closest('input, textarea, select, [contenteditable="true"]')) return
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const fn = map[e.key] ?? map[e.key.toLowerCase()]
      if (fn) {
        e.preventDefault()
        fn()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })
}

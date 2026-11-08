import * as Dialog from '@radix-ui/react-dialog'
import { CaretLeft, CaretRight, DownloadSimple, Heart, X } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { downloadUrl, imageUrl, thumbUrl } from '../../api/client'
import { useImage, useImages, useToggleFavorite } from '../../api/queries'
import type { ImageInfo } from '../../api/types'
import { IconButton } from '../../components/Button'
import { Segmented } from '../../components/Segmented'
import { formatRelative } from '../../lib/format'
import { navigate } from '../../lib/router'
import { useStudio } from '../../state/studio'
import styles from './Gallery.module.css'

export default function GalleryView({ imageId }: { imageId: string | null }) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState<'all' | 'favorites'>('all')
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isPending } = useImages(filter === 'favorites')
  const images = data?.pages.flatMap((p) => p.images) ?? []
  const sentinel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = sentinel.current
    if (!el) return
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) void fetchNextPage()
      },
      { rootMargin: '800px' },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  return (
    <div className={styles.gallery}>
      <header className={styles.header}>
        <h1>{t('gallery.title')}</h1>
        <div style={{ width: 220 }}>
          <Segmented
            label={t('gallery.filter')}
            value={filter}
            options={[
              { value: 'all', label: t('gallery.all') },
              { value: 'favorites', label: t('gallery.favorites') },
            ]}
            onChange={setFilter}
          />
        </div>
      </header>

      {!isPending && images.length === 0 ? (
        <div className={styles.empty}>
          {filter === 'favorites' ? t('gallery.noFavorites') : t('gallery.empty')}
        </div>
      ) : (
        <div className={styles.grid}>
          {images.map((img) => (
            <a
              key={img.id}
              href={`/gallery/${img.id}`}
              className={styles.tile}
              style={{ aspectRatio: `${img.width} / ${img.height}` }}
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.button !== 0) return
                e.preventDefault()
                navigate({ view: 'gallery', imageId: img.id })
              }}
            >
              <img src={thumbUrl(img.id)} alt={img.params.prompt} loading="lazy" decoding="async" />
              {img.favorite && <Heart className={styles.fav} size={14} weight="fill" aria-label={t('gallery.favorite')} />}
            </a>
          ))}
          <div ref={sentinel} aria-hidden />
        </div>
      )}

      <Viewer imageId={imageId} images={images} />
    </div>
  )
}

function Viewer({ imageId, images }: { imageId: string | null; images: ImageInfo[] }) {
  const { t, i18n } = useTranslation()
  const fromList = images.find((i) => i.id === imageId)
  const { data: fetched } = useImage(fromList ? null : imageId)
  const image = fromList ?? fetched
  const favorite = useToggleFavorite()
  const idx = images.findIndex((i) => i.id === imageId)
  const close = () => navigate({ view: 'gallery' })
  const go = (delta: number) => {
    const next = images[idx + delta]
    if (next) navigate({ view: 'gallery', imageId: next.id }, { replace: true })
  }

  return (
    <Dialog.Root open={!!imageId} onOpenChange={(open) => !open && close()}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={styles.viewer}
          aria-describedby={undefined}
          onKeyDown={(e) => {
            if (e.key === 'ArrowRight') go(1)
            if (e.key === 'ArrowLeft') go(-1)
          }}
        >
          <Dialog.Title className="visually-hidden">{t('gallery.viewer')}</Dialog.Title>
          {image && (
            <>
              <div className={styles.viewerStage}>
                <img src={imageUrl(image.id)} alt={image.params.prompt} width={image.width} height={image.height} />
                {idx > 0 && (
                  <button type="button" className={`${styles.nav} ${styles.prev}`} onClick={() => go(-1)} aria-label={t('actions.previous')}>
                    <CaretLeft size={20} />
                  </button>
                )}
                {idx >= 0 && idx < images.length - 1 && (
                  <button type="button" className={`${styles.nav} ${styles.next}`} onClick={() => go(1)} aria-label={t('actions.next')}>
                    <CaretRight size={20} />
                  </button>
                )}
              </div>
              <aside className={styles.details}>
                <div className={styles.detailsBar}>
                  <IconButton
                    label={image.favorite ? t('actions.unfavorite') : t('actions.favorite')}
                    active={image.favorite}
                    onClick={() => favorite.mutate({ id: image.id, favorite: !image.favorite })}
                  >
                    <Heart size={16} weight={image.favorite ? 'fill' : 'regular'} />
                  </IconButton>
                  <IconButton label={t('actions.download')} onClick={() => (location.href = downloadUrl(image.id))}>
                    <DownloadSimple size={16} />
                  </IconButton>
                  <span style={{ flex: 1 }} />
                  <Dialog.Close asChild>
                    <IconButton label={t('actions.close')}>
                      <X size={16} />
                    </IconButton>
                  </Dialog.Close>
                </div>
                <p className={styles.prompt}>{image.params.prompt}</p>
                <dl className={styles.meta}>
                  <dt>{t('studio.model')}</dt>
                  <dd>{image.model}</dd>
                  <dt>{t('studio.size')}</dt>
                  <dd className="num">
                    {image.width} × {image.height}
                  </dd>
                  <dt>{t('studio.seed')}</dt>
                  <dd className="num">{image.seed}</dd>
                  <dt>{t('studio.steps')}</dt>
                  <dd className="num">{image.steps}</dd>
                  <dt>{t('gallery.created')}</dt>
                  <dd>{formatRelative(image.created_at, i18n.language)}</dd>
                </dl>
                <button
                  type="button"
                  className={styles.reuse}
                  onClick={() => {
                    useStudio.getState().reuse(image, { withSeed: true })
                    navigate({ view: 'studio' })
                  }}
                >
                  {t('gallery.openInStudio')}
                </button>
              </aside>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

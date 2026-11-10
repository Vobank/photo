import {
  ArrowCounterClockwise,
  ArrowUUpLeft,
  Broom,
  Eraser,
  Eye,
  Lasso,
  PaintBrush,
  Rectangle,
  SelectionInverse,
  X,
} from '@phosphor-icons/react'
import { type PointerEvent as ReactPointerEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../../api/client'
import { IconButton } from '../../components/Button'
import { toastError } from '../../components/toast'
import { jobErrorText } from '../../lib/errors'
import { MaskController } from '../../lib/mask'
import { type Point, closesPolygon, distance, polygonArea, spanRect, toPicture } from '../../lib/maskGeometry'
import { type EditTool, useEdit } from '../../state/edit'
import { useLive } from '../../state/live'
import styles from './Edit.module.css'
import { sourceUrl } from './logic'

const CLOSE_TOLERANCE = 12 // screen px: clicking this close to the first point closes the lasso
const FREEHAND_STEP = 4 // screen px between freehand lasso points

interface Draft {
  rectStart: Point | null
  lasso: Point[]
  lassoDragged: number // points added while the button was held
  pressed: boolean
  brushLast: Point | null
  hover: Point | null
}

const emptyDraft = (): Draft => ({ rectStart: null, lasso: [], lassoDragged: 0, pressed: false, brushLast: null, hover: null })

function accentColor(): string {
  return getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#e2a03f'
}

/** The picture with its selection on top, and the tools to draw it. */
export function EditCanvas() {
  const { t } = useTranslation()
  const source = useEdit((s) => s.source)
  const history = useEdit((s) => s.history)
  const tool = useEdit((s) => s.tool)
  const brushSize = useEdit((s) => s.brushSize)
  const erase = useEdit((s) => s.erase)
  const pendingJobId = useEdit((s) => s.pendingJobId)
  const set = useEdit((s) => s.set)
  const job = useLive((s) => (pendingJobId ? s.jobs[pendingJobId] : undefined))
  const progress = useLive((s) => (pendingJobId ? s.progress[pendingJobId] : undefined))

  const stageRef = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<HTMLCanvasElement>(null)
  const tintRef = useRef<HTMLCanvasElement | null>(null)
  const draft = useRef<Draft>(emptyDraft())
  const [fit, setFit] = useState<{ width: number; height: number } | null>(null)
  const [comparing, setComparing] = useState(false)
  const [, setTick] = useState(0) // re-render toolbar (undo availability) after changes

  const mask = useMemo(
    () => (source ? new MaskController(source.width, source.height) : null),
    // A new picture (or a new version of it) starts with an empty selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [source?.id, source?.width, source?.height],
  )

  useEffect(() => {
    set({ mask, selected: 0 })
    draft.current = emptyDraft()
    return () => set({ mask: null })
  }, [mask, set])

  // Fit the picture into the stage, keeping its shape.
  useLayoutEffect(() => {
    const stage = stageRef.current
    if (!stage || !source) return
    const measure = () => {
      const pad = 48
      const w = stage.clientWidth - pad
      const h = stage.clientHeight - pad - 40
      const scale = Math.min(w / source.width, h / source.height)
      setFit({ width: Math.max(1, Math.floor(source.width * scale)), height: Math.max(1, Math.floor(source.height * scale)) })
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(stage)
    return () => ro.disconnect()
  }, [source])

  const render = useCallback(() => {
    const canvas = overlayRef.current
    if (!canvas || !mask || !fit || !source) return
    const dpr = window.devicePixelRatio || 1
    const W = Math.round(fit.width * dpr)
    const H = Math.round(fit.height * dpr)
    if (canvas.width !== W || canvas.height !== H) {
      canvas.width = W
      canvas.height = H
    }
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const accent = accentColor()
    ctx.clearRect(0, 0, W, H)

    // Selection: the mask tinted with the accent colour.
    const tint = (tintRef.current ??= document.createElement('canvas'))
    tint.width = W
    tint.height = H
    const tctx = tint.getContext('2d')
    if (tctx) {
      tctx.drawImage(mask.canvas, 0, 0, W, H)
      tctx.globalCompositeOperation = 'source-in'
      tctx.fillStyle = accent
      tctx.fillRect(0, 0, W, H)
      ctx.globalAlpha = 0.5
      ctx.drawImage(tint, 0, 0)
      ctx.globalAlpha = 1
    }

    // Work in progress.
    const k = W / source.width // picture px → canvas px
    const d = draft.current
    ctx.lineWidth = 1.5 * dpr
    ctx.strokeStyle = accent
    ctx.fillStyle = accent + '40'
    if (d.rectStart && d.hover) {
      const r = spanRect(d.rectStart, d.hover)
      ctx.setLineDash([6 * dpr, 4 * dpr])
      ctx.fillRect(r.left * k, r.top * k, r.width * k, r.height * k)
      ctx.strokeRect(r.left * k, r.top * k, r.width * k, r.height * k)
      ctx.setLineDash([])
    }
    if (d.lasso.length) {
      ctx.beginPath()
      ctx.moveTo(d.lasso[0].x * k, d.lasso[0].y * k)
      for (const p of d.lasso.slice(1)) ctx.lineTo(p.x * k, p.y * k)
      if (d.hover) ctx.lineTo(d.hover.x * k, d.hover.y * k)
      ctx.stroke()
      for (const [i, p] of d.lasso.entries()) {
        if (d.lassoDragged > 0 && i > 0) break // freehand: only the start point
        ctx.beginPath()
        ctx.arc(p.x * k, p.y * k, (i === 0 ? 5 : 3) * dpr, 0, Math.PI * 2)
        ctx.fillStyle = i === 0 ? accent : '#fff'
        ctx.fill()
      }
    }
    if (tool === 'brush' && d.hover) {
      const r = (brushSize / 2) * dpr
      ctx.beginPath()
      ctx.arc(d.hover.x * k, d.hover.y * k, r, 0, Math.PI * 2)
      ctx.strokeStyle = 'rgba(0,0,0,.6)'
      ctx.lineWidth = 3 * dpr
      ctx.stroke()
      ctx.strokeStyle = '#fff'
      ctx.lineWidth = 1.5 * dpr
      ctx.stroke()
    }
  }, [mask, fit, source, tool, brushSize])

  useEffect(() => {
    render()
    if (!mask) return
    return mask.subscribe(() => requestAnimationFrame(render))
  }, [mask, render])

  const updateSelected = useCallback(() => {
    if (mask) set({ selected: mask.coverage() })
    setTick((n) => n + 1)
  }, [mask, set])

  // ---- pointer -----------------------------------------------------------------------

  // Still busy after success until the result is loaded as the new version.
  const busy = !!job && (job.status === 'queued' || job.status === 'running' || job.status === 'succeeded')

  const toPoint = (e: { clientX: number; clientY: number }): Point | null => {
    const canvas = overlayRef.current
    if (!canvas || !source) return null
    const r = canvas.getBoundingClientRect()
    return toPicture(e.clientX, e.clientY, { left: r.left, top: r.top, width: r.width, height: r.height }, source)
  }
  const screenScale = () => (fit && source ? fit.width / source.width : 1)
  const isErasing = (e: { altKey: boolean }) => erase !== e.altKey

  const commitLasso = useCallback(
    (eraseNow: boolean) => {
      const d = draft.current
      if (mask && d.lasso.length >= 3 && polygonArea(d.lasso) > 4) {
        mask.checkpoint()
        mask.polygon(d.lasso, eraseNow)
        updateSelected()
      }
      d.lasso = []
      d.lassoDragged = 0
      render()
    },
    [mask, render, updateSelected],
  )

  const onPointerDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    if (busy || e.button !== 0 || !mask) return
    const p = toPoint(e)
    if (!p) return
    e.currentTarget.setPointerCapture(e.pointerId)
    const d = draft.current
    d.pressed = true
    d.hover = p
    if (tool === 'rect') d.rectStart = p
    if (tool === 'brush') {
      mask.checkpoint()
      const size = brushSize / screenScale()
      mask.stroke(p, p, size, isErasing(e))
      d.brushLast = p
    }
    if (tool === 'lasso') {
      if (closesPolygon(d.lasso, p, CLOSE_TOLERANCE, screenScale())) {
        commitLasso(isErasing(e))
        d.pressed = false
        return
      }
      d.lasso.push(p)
      d.lassoDragged = 0
    }
    render()
  }

  const onPointerMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const p = toPoint(e)
    if (!p || !mask) return
    const d = draft.current
    d.hover = p
    if (d.pressed && tool === 'brush' && d.brushLast) {
      mask.stroke(d.brushLast, p, brushSize / screenScale(), isErasing(e))
      d.brushLast = p
      return // the mask change triggers a render
    }
    if (d.pressed && tool === 'lasso' && d.lasso.length) {
      if (distance(d.lasso[d.lasso.length - 1], p) * screenScale() >= FREEHAND_STEP) {
        d.lasso.push(p)
        d.lassoDragged += 1
      }
    }
    render()
  }

  const onPointerUp = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const d = draft.current
    if (!d.pressed || !mask) return
    d.pressed = false
    const p = toPoint(e) ?? d.hover
    if (tool === 'rect' && d.rectStart && p) {
      const r = spanRect(d.rectStart, p)
      if (r.width * screenScale() > 3 && r.height * screenScale() > 3) {
        mask.checkpoint()
        mask.rect(r, isErasing(e))
        updateSelected()
      }
      d.rectStart = null
    }
    if (tool === 'brush') {
      d.brushLast = null
      updateSelected()
    }
    // Drawn with the button held: a freehand lasso closes on release.
    if (tool === 'lasso' && d.lassoDragged > 8) commitLasso(isErasing(e))
    render()
  }

  const onLeave = () => {
    draft.current.hover = null
    render()
  }

  // ---- keyboard ----------------------------------------------------------------------

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input, textarea, select, [contenteditable="true"]')) return
      if (!mask) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        mask.undo()
        updateSelected()
        return
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const tools: Record<string, EditTool> = { b: 'brush', r: 'rect', l: 'lasso' }
      const key = e.key.toLowerCase()
      if (tools[key]) set({ tool: tools[key] })
      else if (key === 'x') set({ erase: !useEdit.getState().erase })
      else if (e.key === '[') set({ brushSize: Math.max(4, Math.round(useEdit.getState().brushSize / 1.25)) })
      else if (e.key === ']') set({ brushSize: Math.min(300, Math.round(useEdit.getState().brushSize * 1.25)) })
      else if (e.key === 'Enter' && draft.current.lasso.length) commitLasso(useEdit.getState().erase)
      else if (e.key === 'Escape') {
        draft.current = emptyDraft()
        render()
      } else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mask, set, commitLasso, render, updateSelected])

  // ---- finished edits become the next version ------------------------------------------

  const status = job?.status
  useEffect(() => {
    if (!job || !status) return
    if (status === 'succeeded' && job.image_ids.length) {
      const id = job.image_ids[0]
      void api
        .image(id)
        .then((info) => useEdit.getState().advance({ id, kind: 'image', width: info.width, height: info.height }))
        // The result is in the gallery either way; never leave the editor stuck as busy.
        .catch(() => set({ pendingJobId: null }))
    } else if (status === 'failed') {
      const { title } = jobErrorText(t, job)
      toastError(title)
      set({ pendingJobId: null })
    } else if (status === 'cancelled') {
      set({ pendingJobId: null })
    }
    // Only react to the status changing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  if (!source) return null
  const previous = history[history.length - 1]
  const shown = comparing && previous ? previous : source
  const frac = progress ? progress.value / progress.max : 0

  return (
    <div className={styles.stage} ref={stageRef}>
      <div className={styles.tools} role="toolbar" aria-label={t('edit.tools')}>
        <IconButton label={t('edit.brush')} shortcut="B" active={tool === 'brush'} onClick={() => set({ tool: 'brush' })}>
          <PaintBrush size={16} />
        </IconButton>
        <IconButton label={t('edit.rect')} shortcut="R" active={tool === 'rect'} onClick={() => set({ tool: 'rect' })}>
          <Rectangle size={16} />
        </IconButton>
        <IconButton label={t('edit.lasso')} shortcut="L" active={tool === 'lasso'} onClick={() => set({ tool: 'lasso' })}>
          <Lasso size={16} />
        </IconButton>
        <span className={styles.sep} />
        <IconButton label={t('edit.erase')} shortcut="X" active={erase} onClick={() => set({ erase: !erase })}>
          <Eraser size={16} />
        </IconButton>
        {tool === 'brush' && (
          <label className={styles.size}>
            <span className="visually-hidden">{t('edit.brushSize')}</span>
            <input
              type="range"
              min={4}
              max={300}
              value={brushSize}
              onChange={(e) => set({ brushSize: Number(e.target.value) })}
              aria-label={t('edit.brushSize')}
            />
            <span className="num">{brushSize}</span>
          </label>
        )}
        <span className={styles.sep} />
        <IconButton
          label={t('edit.undo')}
          shortcut="Ctrl+Z"
          disabled={!mask?.canUndo}
          onClick={() => {
            mask?.undo()
            updateSelected()
          }}
        >
          <ArrowCounterClockwise size={16} />
        </IconButton>
        <IconButton
          label={t('edit.invert')}
          onClick={() => {
            mask?.checkpoint()
            mask?.invert()
            updateSelected()
          }}
        >
          <SelectionInverse size={16} />
        </IconButton>
        <IconButton
          label={t('edit.clear')}
          onClick={() => {
            mask?.checkpoint()
            mask?.clear()
            updateSelected()
          }}
        >
          <Broom size={16} />
        </IconButton>
      </div>

      <div className={styles.versionTools}>
        {previous && (
          <>
            <IconButton
              label={t('edit.compare')}
              active={comparing}
              onPointerDown={() => setComparing(true)}
              onPointerUp={() => setComparing(false)}
              onPointerLeave={() => setComparing(false)}
            >
              <Eye size={16} />
            </IconButton>
            <IconButton label={t('edit.stepBack')} onClick={() => useEdit.getState().back()}>
              <ArrowUUpLeft size={16} />
            </IconButton>
          </>
        )}
        <IconButton label={t('edit.close')} onClick={() => useEdit.getState().close()}>
          <X size={16} />
        </IconButton>
      </div>

      {fit && (
        <div className={styles.frame} style={{ width: fit.width, height: fit.height }} data-busy={busy}>
          <img src={sourceUrl(shown)} alt="" draggable={false} className={styles.picture} />
          <canvas
            ref={overlayRef}
            className={styles.overlay}
            data-tool={tool}
            hidden={comparing}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onPointerLeave={onLeave}
            onDoubleClick={() => tool === 'lasso' && commitLasso(erase)}
          />
          {busy && (
            <div className={styles.busy} aria-live="polite">
              <div className={styles.busyBar}>
                <span style={{ width: `${Math.max(frac, 0.04) * 100}%` }} />
              </div>
              {t('edit.working')}
            </div>
          )}
        </div>
      )}

      <p className={styles.hint}>{comparing ? t('edit.comparing') : t(`edit.hint.${tool}`)}</p>
    </div>
  )
}

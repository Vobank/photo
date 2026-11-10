import type { Point, Rect } from './maskGeometry'

/** Longest side of the mask bitmap; the server scales it to the picture exactly. */
const MAX_SIDE = 4096
const UNDO_LIMIT = 40

/**
 * The selection as a bitmap at (up to) picture resolution: opaque white = selected.
 * Every change is undoable. Drawing happens in picture coordinates; ``scale`` maps
 * them onto the bitmap when the picture is larger than MAX_SIDE.
 */
export class MaskController {
  readonly canvas: HTMLCanvasElement
  readonly scale: number
  private readonly ctx: CanvasRenderingContext2D
  private undoStack: ImageData[] = []
  private listeners = new Set<() => void>()

  constructor(width: number, height: number) {
    this.scale = Math.min(1, MAX_SIDE / Math.max(width, height))
    this.canvas = document.createElement('canvas')
    this.canvas.width = Math.max(1, Math.round(width * this.scale))
    this.canvas.height = Math.max(1, Math.round(height * this.scale))
    const ctx = this.canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) throw new Error('Canvas is not available')
    this.ctx = ctx
  }

  subscribe(fn: () => void): () => void {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  private changed() {
    this.listeners.forEach((fn) => fn())
  }

  /** Call before a user action so it can be undone as one step. */
  checkpoint() {
    this.undoStack.push(this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height))
    if (this.undoStack.length > UNDO_LIMIT) this.undoStack.shift()
  }

  get canUndo() {
    return this.undoStack.length > 0
  }

  undo() {
    const prev = this.undoStack.pop()
    if (!prev) return
    this.ctx.putImageData(prev, 0, 0)
    this.changed()
  }

  private paint(erase: boolean, draw: (ctx: CanvasRenderingContext2D) => void) {
    const ctx = this.ctx
    ctx.save()
    ctx.scale(this.scale, this.scale)
    ctx.globalCompositeOperation = erase ? 'destination-out' : 'source-over'
    ctx.fillStyle = '#fff'
    ctx.strokeStyle = '#fff'
    draw(ctx)
    ctx.restore()
    this.changed()
  }

  rect(r: Rect, erase = false) {
    this.paint(erase, (ctx) => ctx.fillRect(r.left, r.top, r.width, r.height))
  }

  polygon(points: Point[], erase = false) {
    if (points.length < 3) return
    this.paint(erase, (ctx) => {
      ctx.beginPath()
      ctx.moveTo(points[0].x, points[0].y)
      for (const p of points.slice(1)) ctx.lineTo(p.x, p.y)
      ctx.closePath()
      ctx.fill()
    })
  }

  /** A brush segment; call repeatedly while dragging (after one checkpoint). */
  stroke(from: Point, to: Point, size: number, erase = false) {
    this.paint(erase, (ctx) => {
      ctx.lineWidth = size
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      ctx.beginPath()
      ctx.moveTo(from.x, from.y)
      ctx.lineTo(to.x, to.y)
      ctx.stroke()
    })
  }

  clear() {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
    this.changed()
  }

  invert() {
    const img = this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height)
    const d = img.data
    for (let i = 0; i < d.length; i += 4) {
      const on = d[i + 3] < 128
      d[i] = d[i + 1] = d[i + 2] = 255
      d[i + 3] = on ? 255 : 0
    }
    this.ctx.putImageData(img, 0, 0)
    this.changed()
  }

  /** Share of the picture that is selected, 0..1 (sampled, fast enough per stroke). */
  coverage(): number {
    const sample = document.createElement('canvas')
    sample.width = 96
    sample.height = Math.max(1, Math.round((96 * this.canvas.height) / this.canvas.width))
    const sctx = sample.getContext('2d')
    if (!sctx) return 0
    sctx.drawImage(this.canvas, 0, 0, sample.width, sample.height)
    const d = sctx.getImageData(0, 0, sample.width, sample.height).data
    let on = 0
    for (let i = 3; i < d.length; i += 4) if (d[i] >= 128) on++
    return on / (sample.width * sample.height)
  }

  /** Black-and-white PNG for the server (white = selected). */
  async toPng(): Promise<Blob> {
    const out = document.createElement('canvas')
    out.width = this.canvas.width
    out.height = this.canvas.height
    const octx = out.getContext('2d')
    if (!octx) throw new Error('Canvas is not available')
    octx.fillStyle = '#000'
    octx.fillRect(0, 0, out.width, out.height)
    octx.drawImage(this.canvas, 0, 0)
    return new Promise((resolve, reject) =>
      out.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not encode the selection'))), 'image/png'),
    )
  }
}

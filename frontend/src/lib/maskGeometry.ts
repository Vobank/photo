/** Pure geometry for the selection tools (unit-tested; no canvas needed). */

export interface Point {
  x: number
  y: number
}

export interface Rect {
  left: number
  top: number
  width: number
  height: number
}

/** Screen position → picture pixel, clamped to the picture. */
export function toPicture(clientX: number, clientY: number, shown: Rect, natural: { width: number; height: number }): Point {
  const x = ((clientX - shown.left) / shown.width) * natural.width
  const y = ((clientY - shown.top) / shown.height) * natural.height
  return { x: Math.min(natural.width, Math.max(0, x)), y: Math.min(natural.height, Math.max(0, y)) }
}

/** Rectangle spanned by two corners, in any drag direction. */
export function spanRect(a: Point, b: Point): Rect {
  return { left: Math.min(a.x, b.x), top: Math.min(a.y, b.y), width: Math.abs(b.x - a.x), height: Math.abs(b.y - a.y) }
}

export const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y)

/** A lasso closes when the pointer comes back near its first point (in screen pixels). */
export function closesPolygon(points: Point[], pointer: Point, screenTolerance: number, scale: number): boolean {
  return points.length >= 3 && distance(points[0], pointer) * scale <= screenTolerance
}

/** Area of a polygon; tiny or degenerate lassos are ignored instead of filled. */
export function polygonArea(points: Point[]): number {
  let sum = 0
  for (let i = 0; i < points.length; i++) {
    const a = points[i]
    const b = points[(i + 1) % points.length]
    sum += a.x * b.y - b.x * a.y
  }
  return Math.abs(sum) / 2
}

/** Points along a stroke closer than ``minStep`` to the previous kept point are dropped. */
export function thin(points: Point[], minStep: number): Point[] {
  const out: Point[] = []
  for (const p of points) if (!out.length || distance(out[out.length - 1], p) >= minStep) out.push(p)
  return out
}

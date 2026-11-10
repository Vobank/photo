import { describe, expect, it } from 'vitest'

import { missingForApply } from '../features/edit/logic'
import { closesPolygon, polygonArea, spanRect, thin, toPicture } from './maskGeometry'

describe('selection geometry', () => {
  const shown = { left: 100, top: 50, width: 400, height: 300 }
  const natural = { width: 2000, height: 1500 }

  it('maps screen points to picture pixels and clamps them', () => {
    expect(toPicture(100, 50, shown, natural)).toEqual({ x: 0, y: 0 })
    expect(toPicture(300, 200, shown, natural)).toEqual({ x: 1000, y: 750 })
    expect(toPicture(9999, -5, shown, natural)).toEqual({ x: 2000, y: 0 })
  })

  it('spans a rectangle in any drag direction', () => {
    expect(spanRect({ x: 50, y: 80 }, { x: 10, y: 20 })).toEqual({ left: 10, top: 20, width: 40, height: 60 })
  })

  it('closes a lasso only near its first point and with enough points', () => {
    const pts = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
    ]
    // scale 0.2: 50 picture px = 10 screen px
    expect(closesPolygon(pts, { x: 50, y: 0 }, 12, 0.2)).toBe(true)
    expect(closesPolygon(pts, { x: 100, y: 0 }, 12, 0.2)).toBe(false)
    expect(closesPolygon(pts.slice(0, 2), { x: 0, y: 0 }, 12, 0.2)).toBe(false)
  })

  it('measures polygon area regardless of winding', () => {
    const square = [
      { x: 0, y: 0 },
      { x: 10, y: 0 },
      { x: 10, y: 10 },
      { x: 0, y: 10 },
    ]
    expect(polygonArea(square)).toBe(100)
    expect(polygonArea([...square].reverse())).toBe(100)
  })

  it('thins dense strokes', () => {
    const dense = Array.from({ length: 50 }, (_, i) => ({ x: i, y: 0 }))
    expect(thin(dense, 10).map((p) => p.x)).toEqual([0, 10, 20, 30, 40])
  })
})

describe('edit panel readiness', () => {
  const base = { action: 'edit' as const, prompt: '', selected: 0, hasSource: true }

  it('needs a picture first', () => {
    expect(missingForApply({ ...base, hasSource: false, prompt: 'x' })).toBe('source')
  })

  it('needs words to change, and a selection to hide', () => {
    expect(missingForApply(base)).toBe('prompt')
    expect(missingForApply({ ...base, prompt: 'make it winter' })).toBeNull()
    expect(missingForApply({ ...base, action: 'hide' })).toBe('selection')
    expect(missingForApply({ ...base, action: 'hide', selected: 0.1 })).toBeNull()
  })

  it('removes either a selection or a named thing', () => {
    expect(missingForApply({ ...base, action: 'remove' })).toBe('selection')
    expect(missingForApply({ ...base, action: 'remove', prompt: 'the boat' })).toBeNull()
    expect(missingForApply({ ...base, action: 'remove', selected: 0.05 })).toBeNull()
  })
})

import { describe, expect, it } from 'vitest'

import { ASPECTS, SIZES, dimensionsFor } from './dimensions'

describe('dimensionsFor', () => {
  it('always yields valid model dimensions', () => {
    for (const a of ASPECTS) {
      for (const s of SIZES) {
        const { width, height } = dimensionsFor(a.id, s.id)
        expect(width % 16, `${a.id} ${s.id}`).toBe(0)
        expect(height % 16, `${a.id} ${s.id}`).toBe(0)
        expect(width).toBeGreaterThanOrEqual(256)
        expect(height).toBeLessThanOrEqual(2048)
        expect(width * height).toBeLessThanOrEqual(2048 * 2048)
      }
    }
  })

  it('keeps the requested shape and size', () => {
    expect(dimensionsFor('1:1', 'm')).toEqual({ width: 1024, height: 1024 })
    const wide = dimensionsFor('16:9', 'm')
    expect(wide.width / wide.height).toBeCloseTo(16 / 9, 1)
    expect(wide.width * wide.height).toBeGreaterThan(0.95 * 1024 * 1024)
  })

  it('grows monotonically with size', () => {
    const areas = SIZES.map((s) => {
      const d = dimensionsFor('3:2', s.id)
      return d.width * d.height
    })
    expect([...areas].sort((a, b) => a - b)).toEqual(areas)
  })
})

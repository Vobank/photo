/**
 * Output size presets. Users pick a shape and a size; we compute dimensions that are
 * multiples of 16 (what latent-space models need) and stay within the server's limits.
 */

export const ASPECTS = [
  { id: '1:1', w: 1, h: 1 },
  { id: '4:5', w: 4, h: 5 },
  { id: '3:4', w: 3, h: 4 },
  { id: '2:3', w: 2, h: 3 },
  { id: '9:16', w: 9, h: 16 },
  { id: '5:4', w: 5, h: 4 },
  { id: '4:3', w: 4, h: 3 },
  { id: '3:2', w: 3, h: 2 },
  { id: '16:9', w: 16, h: 9 },
  { id: '21:9', w: 21, h: 9 },
] as const

export type AspectId = (typeof ASPECTS)[number]['id']

/** Target pixel counts, in megapixels. */
export const SIZES = [
  { id: 's', mp: 0.6 },
  { id: 'm', mp: 1.0 },
  { id: 'l', mp: 1.6 },
  { id: 'xl', mp: 2.4 },
] as const

export type SizeId = (typeof SIZES)[number]['id']

const MIN = 256
const MAX = 2048
const MAX_PIXELS = 2048 * 2048

const snap = (v: number) => Math.max(MIN, Math.min(MAX, Math.round(v / 16) * 16))

export function dimensionsFor(aspect: AspectId, size: SizeId): { width: number; height: number } {
  const a = ASPECTS.find((x) => x.id === aspect) ?? ASPECTS[0]
  const s = SIZES.find((x) => x.id === size) ?? SIZES[1]
  const pixels = s.mp * 1024 * 1024
  const ratio = a.w / a.h
  let width = snap(Math.sqrt(pixels * ratio))
  let height = snap(width / ratio)
  while (width * height > MAX_PIXELS) {
    width = snap(width - 16)
    height = snap(width / ratio)
  }
  return { width, height }
}

export const megapixels = (w: number, h: number) => (w * h) / 1_000_000

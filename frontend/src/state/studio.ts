import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { GenerateParams, ImageInfo } from '../api/types'
import { ASPECTS, type AspectId, type SizeId, dimensionsFor } from '../lib/dimensions'

export const MAX_SEED = 2 ** 53 - 1
/** Model and style value meaning "let Photo decide from the prompt". */
export const AUTO = 'auto'
export const MAX_REFERENCES = 4

/** A picture used as input: from the gallery or uploaded from disk. */
export interface InputPicture {
  id: string
  kind: 'image' | 'upload'
  width: number
  height: number
}

/** "references": the result follows these pictures. "variation": start from one picture. */
export type InputMode = 'references' | 'variation'

interface StudioState {
  prompt: string
  negativePrompt: string
  model: string | null
  aspect: AspectId
  size: SizeId
  batch: number
  seedLocked: boolean
  seed: number
  steps: number | null // null = model default
  cfg: number | null
  advancedOpen: boolean

  style: string | null
  enhance: boolean
  detail: boolean
  inputMode: InputMode
  inputs: InputPicture[]
  /** 0.05 = stay very close to the source, 0.95 = barely related. */
  variationStrength: number

  /** Image shown on the canvas; null means "follow the newest result". */
  selectedImageId: string | null

  set: (patch: Partial<StudioData>) => void
  randomizeSeed: () => void
  reuse: (image: ImageInfo, opts?: { withSeed?: boolean }) => void
  addInput: (picture: InputPicture, mode?: InputMode) => void
  removeInput: (id: string) => void
  toParams: () => GenerateParams | null
}

type StudioData = Omit<StudioState, 'set' | 'toParams' | 'reuse' | 'randomizeSeed' | 'addInput' | 'removeInput'>

export const randomSeed = () => Math.floor(Math.random() * MAX_SEED)

/** The preset shape closest to a picture's own proportions. */
export function closestAspect(width: number, height: number): AspectId {
  const r = width / height
  let best: AspectId = ASPECTS[0].id
  let bestDiff = Infinity
  for (const a of ASPECTS) {
    const diff = Math.abs(Math.log(a.w / a.h / r))
    if (diff < bestDiff) {
      bestDiff = diff
      best = a.id
    }
  }
  return best
}

export const useStudio = create<StudioState>()(
  persist(
    (set, get) => ({
      prompt: '',
      negativePrompt: '',
      model: AUTO,
      aspect: '1:1',
      // ~2.4 MP: native high resolution is the biggest single quality gain (docs/realism.md).
      size: 'xl',
      batch: 1,
      seedLocked: false,
      seed: randomSeed(),
      steps: null,
      cfg: null,
      advancedOpen: false,
      style: AUTO,
      enhance: false,
      detail: false,
      inputMode: 'references',
      inputs: [],
      variationStrength: 0.5,
      selectedImageId: null,

      set: (patch) => set(patch),
      randomizeSeed: () => set({ seed: randomSeed() }),

      addInput: (picture, mode) => {
        const s = get()
        const nextMode = mode ?? s.inputMode
        if (nextMode === 'variation') {
          // One source; the output takes its shape.
          set({ inputMode: 'variation', inputs: [picture], aspect: closestAspect(picture.width, picture.height) })
          return
        }
        const kept = (s.inputMode === 'references' ? s.inputs : []).filter((p) => p.id !== picture.id)
        set({ inputMode: 'references', inputs: [...kept, picture].slice(-MAX_REFERENCES) })
      },

      removeInput: (id) => set((s) => ({ inputs: s.inputs.filter((p) => p.id !== id) })),

      reuse: (image, opts = {}) => {
        const p = image.params
        set({
          prompt: p.prompt,
          negativePrompt: p.negative_prompt ?? '',
          model: p.model,
          steps: p.steps ?? null,
          cfg: p.cfg ?? null,
          batch: p.batch_size,
          style: p.style ?? null,
          enhance: p.enhance ?? false,
          detail: p.detail ?? false,
          ...(opts.withSeed ? { seed: image.seed, seedLocked: true } : {}),
          ...matchDimensions(p.width, p.height),
        })
      },

      toParams: () => {
        const s = get()
        if (!s.model || !s.prompt.trim()) return null
        const { width, height } = dimensionsFor(s.aspect, s.size)
        const ids = s.inputs.map((p) => p.id)
        return {
          kind: 'generate',
          model: s.model,
          prompt: s.prompt.trim(),
          negative_prompt: s.negativePrompt.trim(),
          width,
          height,
          batch_size: s.batch,
          seed: s.seedLocked ? s.seed : null,
          steps: s.steps,
          cfg: s.cfg,
          style: s.style,
          enhance: s.enhance,
          detail: s.detail,
          references: s.inputMode === 'references' ? ids : [],
          variation_of: s.inputMode === 'variation' ? (ids[0] ?? null) : null,
          variation_strength: s.variationStrength,
        }
      },
    }),
    {
      name: 'photo.studio',
      version: 4,
      partialize: ({ selectedImageId: _s, set: _set, ...rest }) => rest,
      // v1 had no looks or inputs: defaults fill them in.
      // v3 introduced automatic mode; earlier defaults (no style, first model) become auto.
      migrate: (persisted, version) => {
        const s = persisted as StudioState
        if (version < 3) return { ...s, model: AUTO, style: s.style ?? AUTO, steps: null, cfg: null, size: 'xl' as const }
        // v4 made XL the default; people still on the old default move up with it.
        if (version < 4 && s.size === 'm') return { ...s, size: 'xl' as const }
        return s
      },
    },
  ),
)

function matchDimensions(width: number, height: number): Partial<StudioData> {
  // Find the preset pair that reproduces these exact dimensions, if any.
  for (const a of ASPECTS) {
    for (const size of ['s', 'm', 'l', 'xl'] as const) {
      const d = dimensionsFor(a.id, size)
      if (d.width === width && d.height === height) return { aspect: a.id, size }
    }
  }
  return { aspect: closestAspect(width, height) }
}

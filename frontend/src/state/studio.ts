import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { GenerateParams, ImageInfo } from '../api/types'
import { type AspectId, type SizeId, dimensionsFor } from '../lib/dimensions'

export const MAX_SEED = 2 ** 53 - 1

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
  /** Image shown on the canvas; null means "follow the newest result". */
  selectedImageId: string | null

  set: (patch: Partial<Omit<StudioState, 'set' | 'toParams' | 'reuse' | 'randomizeSeed'>>) => void
  randomizeSeed: () => void
  reuse: (image: ImageInfo, opts?: { withSeed?: boolean }) => void
  toParams: () => GenerateParams | null
}

export const randomSeed = () => Math.floor(Math.random() * MAX_SEED)

export const useStudio = create<StudioState>()(
  persist(
    (set, get) => ({
      prompt: '',
      negativePrompt: '',
      model: null,
      aspect: '1:1',
      size: 'm',
      batch: 1,
      seedLocked: false,
      seed: randomSeed(),
      steps: null,
      cfg: null,
      advancedOpen: false,
      selectedImageId: null,

      set: (patch) => set(patch),
      randomizeSeed: () => set({ seed: randomSeed() }),

      reuse: (image, opts = {}) => {
        const p = image.params
        set({
          prompt: p.prompt,
          negativePrompt: p.negative_prompt ?? '',
          model: p.model,
          steps: p.steps ?? null,
          cfg: p.cfg ?? null,
          batch: p.batch_size,
          ...(opts.withSeed ? { seed: image.seed, seedLocked: true } : {}),
          ...matchDimensions(p.width, p.height),
        })
      },

      toParams: () => {
        const s = get()
        if (!s.model || !s.prompt.trim()) return null
        const { width, height } = dimensionsFor(s.aspect, s.size)
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
        }
      },
    }),
    {
      name: 'photo.studio',
      version: 1,
      partialize: ({ selectedImageId: _s, set: _set, ...rest }) => rest,
    },
  ),
)

function matchDimensions(width: number, height: number): Partial<StudioState> {
  // Find the preset pair that reproduces these exact dimensions, if any.
  for (const aspect of ['1:1', '4:5', '3:4', '2:3', '9:16', '5:4', '4:3', '3:2', '16:9', '21:9'] as const) {
    for (const size of ['s', 'm', 'l', 'xl'] as const) {
      const d = dimensionsFor(aspect, size)
      if (d.width === width && d.height === height) return { aspect, size }
    }
  }
  return {}
}

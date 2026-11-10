import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { MaskController } from '../lib/mask'

export type EditTool = 'rect' | 'lasso' | 'brush'
export type EditAction = 'edit' | 'remove' | 'hide'
export type HideMode = 'blur' | 'pixelate' | 'fill'

/** A picture being edited: a gallery image or an uploaded file. */
export interface EditSource {
  id: string
  kind: 'image' | 'upload'
  width: number
  height: number
}

interface EditState {
  active: boolean
  source: EditSource | null
  /** Earlier versions in this editing session, oldest first ("step back", compare). */
  history: EditSource[]
  tool: EditTool
  brushSize: number // screen pixels
  erase: boolean
  action: EditAction
  hideMode: HideMode
  /** Separate text per action, so "what to remove" never inherits an edit instruction. */
  prompts: { edit: string; remove: string }
  batch: number
  /** Live selection, owned by the edit canvas. */
  mask: MaskController | null
  selected: number // share of the picture selected, 0..1
  pendingJobId: string | null

  set: (patch: Partial<EditData>) => void
  setPrompt: (text: string) => void
  open: (source: EditSource) => void
  close: () => void
  /** A finished edit becomes the new source; the old one goes to history. */
  advance: (next: EditSource) => void
  back: () => void
}

type EditData = Omit<EditState, 'set' | 'setPrompt' | 'open' | 'close' | 'advance' | 'back'>

export const useEdit = create<EditState>()(
  persist(
    (set, get) => ({
      active: false,
      source: null,
      history: [],
      tool: 'brush',
      brushSize: 48,
      erase: false,
      action: 'edit',
      hideMode: 'blur',
      prompts: { edit: '', remove: '' },
      batch: 1,
      mask: null,
      selected: 0,
      pendingJobId: null,

      set: (patch) => set(patch),
      setPrompt: (text) => {
        const { action, prompts } = get()
        if (action !== 'hide') set({ prompts: { ...prompts, [action]: text } })
      },
      open: (source) => {
        const s = get()
        if (s.active && s.source?.id === source.id) return
        set({ active: true, source, history: [], selected: 0, erase: false, pendingJobId: null })
      },
      close: () => set({ active: false, pendingJobId: null }),
      advance: (next) => {
        const s = get()
        set({ source: next, history: s.source ? [...s.history, s.source].slice(-20) : s.history, selected: 0, pendingJobId: null })
      },
      back: () => {
        const s = get()
        const prev = s.history[s.history.length - 1]
        if (prev) set({ source: prev, history: s.history.slice(0, -1), selected: 0 })
      },
    }),
    {
      name: 'photo.edit',
      version: 1,
      // Only tool preferences survive a reload; the session itself does not.
      partialize: (s) => ({ tool: s.tool, brushSize: s.brushSize, action: s.action, hideMode: s.hideMode }),
    },
  ),
)

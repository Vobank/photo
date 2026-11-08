import { create } from 'zustand'

export interface Toast {
  id: number
  message: string
  tone: 'info' | 'error'
  action?: { label: string; run: () => void }
}

interface ToastState {
  toasts: Toast[]
  push: (t: Omit<Toast, 'id'>, timeoutMs?: number) => void
  dismiss: (id: number) => void
}

let nextId = 1

export const useToasts = create<ToastState>()((set, get) => ({
  toasts: [],
  push: (t, timeoutMs = 5000) => {
    const id = nextId++
    set((s) => ({ toasts: [...s.toasts.slice(-3), { ...t, id }] }))
    setTimeout(() => get().dismiss(id), timeoutMs)
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

export const toast = (message: string, extra: Partial<Omit<Toast, 'id' | 'message'>> = {}) =>
  useToasts.getState().push({ message, tone: 'info', ...extra })

export const toastError = (message: string) => useToasts.getState().push({ message, tone: 'error' }, 8000)

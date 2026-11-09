import { create } from 'zustand'

import type { EngineState, InstallState, Job, ServerEvent, SetupRun } from '../api/types'

interface Progress {
  value: number
  max: number
  startedAt: number
}

interface LiveState {
  connected: boolean
  engine: { state: EngineState; error: string | null } | null
  jobs: Record<string, Job>
  progress: Record<string, Progress>
  previews: Record<string, string> // jobId → object URL of latest step preview
  installs: Record<string, InstallState>
  setupRun: SetupRun | null
  setConnected: (connected: boolean) => void
  apply: (event: ServerEvent) => void
  setPreview: (jobId: string, blob: Blob) => void
  upsertJob: (job: Job) => void
}

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])

function dropPreview(previews: Record<string, string>, jobId: string): Record<string, string> {
  if (!(jobId in previews)) return previews
  URL.revokeObjectURL(previews[jobId])
  const next = { ...previews }
  delete next[jobId]
  return next
}

export const useLive = create<LiveState>()((set) => ({
  connected: false,
  engine: null,
  jobs: {},
  progress: {},
  previews: {},
  installs: {},
  setupRun: null,

  setConnected: (connected) => set({ connected }),

  upsertJob: (job) => set((s) => ({ jobs: { ...s.jobs, [job.id]: job } })),

  setPreview: (jobId, blob) =>
    set((s) => {
      const job = s.jobs[jobId]
      if (job && TERMINAL.has(job.status)) return s
      const old = s.previews[jobId]
      if (old) URL.revokeObjectURL(old)
      return { previews: { ...s.previews, [jobId]: URL.createObjectURL(blob) } }
    }),

  apply: (event) =>
    set((s) => {
      switch (event.type) {
        case 'hello': {
          if (event.mode === 'setup') return { setupRun: event.run }
          const jobs = { ...s.jobs }
          for (const j of event.jobs) jobs[j.id] = j
          return { engine: event.engine, jobs }
        }
        case 'job': {
          const job = event.job
          const patch: Partial<LiveState> = { jobs: { ...s.jobs, [job.id]: job } }
          if (TERMINAL.has(job.status)) {
            patch.previews = dropPreview(s.previews, job.id)
            const progress = { ...s.progress }
            delete progress[job.id]
            patch.progress = progress
          }
          return patch
        }
        case 'progress': {
          const prev = s.progress[event.job_id]
          return {
            progress: {
              ...s.progress,
              [event.job_id]: {
                value: event.value,
                max: event.max,
                startedAt: prev?.startedAt ?? performance.now(),
              },
            },
          }
        }
        case 'setup':
          return { setupRun: event.run }
        case 'engine':
          return { engine: { state: event.state, error: event.error } }
        case 'model_install': {
          const { type: _t, ...install } = event
          return { installs: { ...s.installs, [install.model_id]: install } }
        }
        default:
          return s
      }
    }),
}))

export const activeJobs = (jobs: Record<string, Job>): Job[] =>
  Object.values(jobs)
    .filter((j) => j.status === 'queued' || j.status === 'running')
    .sort((a, b) => (a.id < b.id ? -1 : 1))

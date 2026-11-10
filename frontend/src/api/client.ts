import type {
  ApiErrorBody,
  JobRequest,
  ImageInfo,
  InstallState,
  Job,
  FieldError,
  InstallConfig,
  ModelInfo,
  SetupPlan,
  SetupRun,
  SetupSystemInfo,
  SystemInfo,
  Upload,
} from './types'

const BASE = '/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fields: { field: string; message?: string; code?: string; detail?: string }[]

  constructor(status: number, body: ApiErrorBody | null) {
    super(body?.error.message ?? `Request failed (${status})`)
    this.status = status
    this.code = body?.error.code ?? `http_${status}`
    this.fields = body?.error.fields ?? []
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json', ...init.headers } : init?.headers,
  })
  if (!res.ok) {
    let body: ApiErrorBody | null = null
    try {
      body = (await res.json()) as ApiErrorBody
    } catch {
      /* non-JSON error page */
    }
    throw new ApiError(res.status, body)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

export const api = {
  system: () => request<SystemInfo | SetupSystemInfo>('/system'),
  setLanguage: (language: string) =>
    request<{ language: string }>('/preferences', { method: 'PUT', body: JSON.stringify({ language }) }),

  setup: {
    plan: () => request<SetupPlan>('/setup'),
    validate: (cfg: InstallConfig) => request<{ ok: boolean; errors: FieldError[] }>('/setup/validate', json(cfg)),
    start: (cfg: InstallConfig) => request<SetupRun>('/setup/start', json(cfg)),
    cancel: () => request<SetupRun>('/setup/cancel', { method: 'POST' }),
    finish: () => request<{ status: string }>('/setup/finish', { method: 'POST' }),
  },
  restartEngine: () => request<{ status: string }>('/system/engine/restart', { method: 'POST' }),

  models: () => request<{ models: ModelInfo[] }>('/models').then((r) => r.models),
  installModel: (id: string, variant?: string) =>
    request<InstallState>(`/models/${encodeURIComponent(id)}/install`, json({ variant })),
  cancelInstall: (id: string) =>
    request<void>(`/models/${encodeURIComponent(id)}/install`, { method: 'DELETE' }),

  createJob: (params: JobRequest) => request<Job>('/jobs', json(params)),
  enhancePrompt: (prompt: string, style: string | null, hasReferences: boolean) =>
    request<{ prompt: string }>('/prompt/enhance', json({ prompt, style, has_references: hasReferences })),
  upload: async (file: Blob): Promise<Upload> => {
    const form = new FormData()
    form.append('file', file, file instanceof File ? file.name : 'pasted.png')
    const res = await fetch(`${BASE}/uploads`, { method: 'POST', body: form })
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null))
    return (await res.json()) as Upload
  },
  jobs: (active = false) => request<{ jobs: Job[] }>(`/jobs?active=${active}`).then((r) => r.jobs),
  cancelJob: (id: string) => request<Job>(`/jobs/${id}/cancel`, { method: 'POST' }),

  images: (opts: { before?: string; favorites?: boolean; limit?: number } = {}) => {
    const q = new URLSearchParams()
    if (opts.before) q.set('before', opts.before)
    if (opts.favorites) q.set('favorites', 'true')
    q.set('limit', String(opts.limit ?? 60))
    return request<{ images: ImageInfo[]; next: string | null }>(`/images?${q}`)
  },
  image: (id: string) => request<ImageInfo>(`/images/${id}`),
  setFavorite: (id: string, favorite: boolean) =>
    request<ImageInfo>(`/images/${id}`, { method: 'PATCH', body: JSON.stringify({ favorite }) }),
  deleteImage: (id: string) => request<void>(`/images/${id}`, { method: 'DELETE' }),
  restoreImage: (id: string) => request<ImageInfo>(`/images/${id}/restore`, { method: 'POST' }),
}

export const imageUrl = (id: string) => `${BASE}/images/${id}/file`
export const thumbUrl = (id: string) => `${BASE}/images/${id}/thumb`
export const uploadThumbUrl = (id: string) => `${BASE}/uploads/${id}/thumb`
export const uploadFileUrl = (id: string) => `${BASE}/uploads/${id}/file`
export const downloadUrl = (id: string) => `${BASE}/images/${id}/file?download=true`

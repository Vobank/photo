import type {
  ApiErrorBody,
  GenerateParams,
  ImageInfo,
  InstallState,
  Job,
  ModelInfo,
  SystemInfo,
} from './types'

const BASE = '/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fields: { field: string; message: string }[]

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
  system: () => request<SystemInfo>('/system'),
  restartEngine: () => request<{ status: string }>('/system/engine/restart', { method: 'POST' }),

  models: () => request<{ models: ModelInfo[] }>('/models').then((r) => r.models),
  installModel: (id: string, variant?: string) =>
    request<InstallState>(`/models/${encodeURIComponent(id)}/install`, json({ variant })),
  cancelInstall: (id: string) =>
    request<void>(`/models/${encodeURIComponent(id)}/install`, { method: 'DELETE' }),

  createJob: (params: GenerateParams) => request<Job>('/jobs', json(params)),
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
export const downloadUrl = (id: string) => `${BASE}/images/${id}/file?download=true`

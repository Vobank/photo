// Mirrors backend/src/photo/schemas.py and the route payloads in api/routes.py.

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type EngineState = 'not_installed' | 'stopped' | 'starting' | 'ready' | 'crashed'

export interface GenerateParams {
  kind?: 'generate'
  model: string
  prompt: string
  negative_prompt?: string
  width: number
  height: number
  seed?: number | null
  batch_size: number
  steps?: number | null
  cfg?: number | null
}

export interface Job {
  id: string
  kind: string
  status: JobStatus
  params: GenerateParams
  model: string
  variant: string
  seed: number
  progress: number
  error: string | null
  created_at: number
  started_at: number | null
  finished_at: number | null
  image_ids: string[]
}

export interface ImageInfo {
  id: string
  job_id: string
  width: number
  height: number
  seed: number
  model: string
  favorite: boolean
  created_at: number
  params: GenerateParams
  steps: number | null
  cfg: number | null
}

export interface ModelVariant {
  id: string
  label: string
  fits_gpu: boolean
  recommended: boolean
  installed: boolean
  download_bytes: number
  total_bytes: number
}

export interface InstallState {
  model_id: string
  variant_id: string
  total: number
  done: number
  error: string | null
  finished: boolean
}

export interface ModelInfo {
  id: string
  name: string
  vendor: string
  description: string
  tasks: string[]
  license: string
  license_url: string
  commercial_use: boolean
  defaults: { steps: number; cfg: number; sampler: string; scheduler: string }
  installed: boolean
  variants: ModelVariant[]
  install: InstallState | null
}

export interface SystemInfo {
  version: string
  engine: { state: EngineState; error: string | null }
  gpu: {
    name: string
    vram_gb: number
    arch: string
    driver: string
    supported: boolean
  } | null
  models_dir: string
}

export interface ApiErrorBody {
  error: { code: string; message: string; fields?: { field: string; message: string }[] }
}

export type ServerEvent =
  | { type: 'hello'; version: string; engine: SystemInfo['engine']; jobs: Job[] }
  | { type: 'job'; job: Job }
  | { type: 'progress'; job_id: string; value: number; max: number }
  | { type: 'image'; image_id: string; job_id: string }
  | { type: 'image_deleted'; image_id: string }
  | { type: 'engine'; state: EngineState; error: string | null }
  | ({ type: 'model_install' } & InstallState)

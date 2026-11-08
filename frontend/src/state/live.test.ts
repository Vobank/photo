import { beforeEach, describe, expect, it } from 'vitest'

import type { Job } from '../api/types'
import { activeJobs, useLive } from './live'

const job = (id: string, status: Job['status']): Job => ({
  id,
  kind: 'generate',
  status,
  params: { model: 'm', prompt: 'p', width: 1024, height: 1024, batch_size: 1 },
  model: 'm',
  variant: 'v',
  seed: 1,
  progress: 0,
  error: null,
  created_at: 0,
  started_at: null,
  finished_at: null,
  image_ids: [],
})

beforeEach(() => useLive.setState({ jobs: {}, progress: {}, previews: {}, installs: {} }))

describe('live store', () => {
  it('tracks progress and clears it when the job finishes', () => {
    const { apply } = useLive.getState()
    apply({ type: 'job', job: job('a', 'running') })
    apply({ type: 'progress', job_id: 'a', value: 3, max: 8 })
    expect(useLive.getState().progress.a).toMatchObject({ value: 3, max: 8 })
    apply({ type: 'job', job: job('a', 'succeeded') })
    expect(useLive.getState().progress.a).toBeUndefined()
  })

  it('ignores previews that arrive after a job finished', () => {
    const { apply, setPreview } = useLive.getState()
    apply({ type: 'job', job: job('a', 'succeeded') })
    setPreview('a', new Blob(['x']))
    expect(useLive.getState().previews.a).toBeUndefined()
  })

  it('lists active jobs oldest first', () => {
    const { apply } = useLive.getState()
    apply({ type: 'hello', version: '1', engine: { state: 'ready', error: null }, jobs: [job('c', 'queued'), job('a', 'running'), job('b', 'failed')] })
    expect(activeJobs(useLive.getState().jobs).map((j) => j.id)).toEqual(['a', 'c'])
  })
})

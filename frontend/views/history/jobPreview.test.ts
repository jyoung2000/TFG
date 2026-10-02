import { describe, expect, it } from 'vitest'
import { jobPreview } from './jobPreview'
import type { JobOutput } from '../../types/jobs'

const out = (o: Partial<JobOutput>) => ({ kind: 'file', path: '', ...o }) as JobOutput

describe('jobPreview', () => {
  it('previews a finished LoRA run by its sample, not its .safetensors', () => {
    const job = { outputs: [out({ kind: 'file', path: 'raven.safetensors' }), out({ kind: 'image', path: 'sample_840.png' })], metrics: {} }
    expect(jobPreview(job)).toEqual({ source: 'sample_840.png', kind: 'image' })
  })
  it('previews a running training job by its latest sample', () => {
    expect(jobPreview({ outputs: [], metrics: { samples: ['s140.png', 's280.png'] } })).toEqual({ source: 's280.png', kind: 'image' })
  })
  it('prefers a thumbnail and has nothing to show otherwise', () => {
    expect(jobPreview({ outputs: [out({ kind: 'video', path: 'a.mp4', thumb: 'a.jpg' })], metrics: {} }).source).toBe('a.jpg')
    expect(jobPreview({ outputs: [], metrics: {} })).toEqual({ source: '', kind: null })
  })
})

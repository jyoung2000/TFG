import { describe, expect, it } from 'vitest'
import { backgroundJobs, backgroundLabel } from './activityJobs'
import type { Job } from '../types/jobs'

const job = (o: Partial<Job>) => ({ id: 'j', kind: 'training', status: 'running', progress: 0, phase: '', title: '', outputs: [], metrics: {}, ...o }) as Job

describe('activity jobs', () => {
  it('shows a running LoRA training job, not image renders the queue already shows', () => {
    const jobs = [job({ id: 't', kind: 'training', progress: 12.4 }), job({ id: 'i', kind: 'image_gen' }), job({ id: 'd', kind: 'download', status: 'complete' })]
    expect(backgroundJobs(jobs).map(j => j.id)).toEqual(['t'])
    expect(backgroundLabel(backgroundJobs(jobs))).toBe('Training 12%')
  })
  it('counts the rest', () => {
    expect(backgroundLabel([job({ progress: 50 }), job({ kind: 'download', progress: 10 })])).toBe('Training 50% +1')
    expect(backgroundLabel([])).toBe('')
  })
})
